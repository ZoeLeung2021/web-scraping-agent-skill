"""
Cleaner for King Power CN — the silver step paired with
kingpower_cn_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_kingpower_cn.py once validated.

GTR retailer — King Power is Thailand's major duty-free/travel-retail
operator; kingpower-cn.com is its Chinese-language-facing storefront for
pre-order + Thai-airport/downtown pickup ("离境订购" — departure pre-order).
Country gets the "DF " prefix ("DF Thailand"), and Domestic_Tax stays null
by definition for a GTR/duty-free retailer — this is the expected/correct
null, not an open TODO.

Channel — confirmed live (see scraper module docstring) that King Power's
pickup-airport switcher (Suvarnabhumi/Don Mueang/Chiang Mai/Phuket) does
NOT fork the catalog or prices at all: switching it and re-fetching cat=48
returned an identical 91-item listing, identical first-5 IDs, identical
first-5 prices. So there is genuinely one unified online catalog across
every King Power Thai pickup point (4 airports + 2 downtown stores). No
exact "kingpower"/"king_power" or "Suvarnabhumi" legacy Channel string was
found anywhere in GTR_Pricing (scrapers/, silver_scripts/, webscraping/,
kestra_flows/ all checked). User-confirmed 2026-07-23: Channel =
"Suvarnabhumi Airport (BKK)" — King Power's flagship Bangkok location,
following this project's standard airport-naming convention rather than
the combined-national-retailer alternative originally proposed.

Currency: site prices are in THB ("4250.00 THB") — the real Thailand
duty-free transaction currency (a second on-page CNY figure is only the
site's own live display-conversion estimate for Chinese shoppers, using
Alipay/UnionPay/WeChat rates — NOT captured by the scraper, and not used
here). LOCAL_CURRENCY = "THB", routed through the shared
ExchangeRate_cleaning() helper for consistency with every other cleaner in
this repo. Checked the live exchange-rate reference file
(GTR_Pricing/webscraping/Ex.Rates_2025.xlsx, sheet "DF") directly: its
Thailand row (Country="Thailand", plain/unprefixed, matching the join key
this function expects) already has IWSR Currency = "THB" = Local Currency,
i.e. THB already IS the IWSR reporting currency for the Thailand market —
so this call is expected to be a documented no-op on the numeric price
values (same category of exception as Singapore Changi skipping conversion
because SGD is already its reporting currency), while still correctly
carrying "THB" through. Kept in (rather than skipped) for consistency with
every other cleaner in this repo, same reasoning as clean_regstaer_vnukovo.py.

Language: product Brand/Brandline text comes back in Chinese (or mixed
Chinese/English, e.g. "MOUTAI/茅台", "轩尼诗X.O干邑白兰地1L") — confirmed live,
not assumed from the domain. kingpower-cn.com has NO in-page language
switcher (the header's "EN"/"TH" links are outbound links to the unrelated
kingpower.com domain, not an in-page translation of this site — see
scraper module docstring), so per SKILL.md step 4 this cleaner uses
Databricks' on-cluster `ai_translate()` for both Brand and Brandline,
applied AFTER Size has already been extracted from the raw Brandline text
(translating first could turn a recognizable "700ml"/"53度1000ML" into text
the size regex no longer matches).

GTR_exclusive: no exclusivity badge, ribbon, or "Exclusives" concept found
anywhere on the site (see scraper module docstring) — the scraper never
sets this key, so it is already null for every row after the
ensure-columns-exist backfill below. This is the genuine null case, not
"No". The only per-product badge concept found ("满1件8折" / "满1000减500"
quantity- and spend-based promo labels) is already captured via
Strike_Price/Price_Discounted, not a separate exclusivity signal.

Alcohol-only scope: the scraper already drops the two non-alcohol brands
that leak into the cat=48 "酒水" parent listing (THE COFFEE HOUSE / coffee,
and Gold Bird's Nest / 燕窝 non-alcoholic bird's-nest tonic drinks) at
scrape time — see that module's docstring for the live count check
(91 raw - 7 non-alcohol = 84 alcohol SKUs). Nothing further to filter here.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, regexp_extract, regexp_replace, when, lit, to_timestamp, year,
    date_format, lower, row_number, concat, expr,
)
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "King Power"
LOCAL_CURRENCY = "THB"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "4250.00 THB", "9500.00 THB" (dot decimal, no
    thousands separator seen live on this site — the comma-decimal branch
    is kept for defensive consistency with every other cleaner in this
    repo)."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    """Standard cl/ml/L normalization, extended to also treat "*" as a
    multipack marker (not just "x") — this site's titles bundle multipacks
    both ways, e.g. "700ml*2" and the reversed "2*1L". Real multipack
    titles are excluded here (fall back to null Size) rather than guessing
    a misleading total/per-unit figure, same convention as every other
    cleaner in this repo."""
    size_lower = lower(size_col)
    is_multipack = size_lower.contains("x") | size_lower.contains("*")
    return (
        when(size_lower.contains("cl") & ~is_multipack,
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~is_multipack,
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when(size_lower.contains("l") & ~is_multipack
              & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
              regexp_replace(size_lower, "l", "").cast(DoubleType()) * 100)
        .otherwise(lit(None).cast(DoubleType()))
    )


def _map_channel_label(channel_col):
    if not CHANNEL_LABELS:
        return channel_col
    mapped = channel_col
    for raw_value, label in CHANNEL_LABELS.items():
        mapped = when(channel_col == raw_value, lit(label)).otherwise(mapped)
    return mapped


def _extract_size_from_text(text_col):
    """No dedicated Size field on this site — every product title bundles
    size in with the (Chinese) product name, e.g. "三得利 响大师臻选威士忌700ml",
    "茅台（MOUTAI）贵州茅台酒 飞天 53度1000ML". The unit regex itself is
    language-agnostic (matches the trailing cl/ml/l token regardless of the
    surrounding script), so this runs BEFORE ai_translate() below — translating
    first could turn a matchable "700ml" into non-matching text."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only — ID_raw (the card's own data-common-id attribute,
    which also matches the numeric ID embedded in the product URL) should
    cover every row in practice. Mirrors the scraper's own URL shape
    (".../goods/<ID>") as a last resort."""
    extracted = regexp_extract(product_link_col, r"/goods/(\d+)", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def _extract_brand_before_slash(brand_col):
    """Brand strings on this site are either plain English ("SHUI JING
    FANG", "THE MACALLAN"), "ENGLISH/中文" ("JOHNNIE WALKER/尊尼获加" —
    English always comes first), or Chinese-only with no English at all
    ("云雾之湾" = Cloudy Bay, "唐培里侬" = Dom Pérignon). Take the part before
    the first "/" when present; ai_translate() below then acts as a safety
    net for whatever's left (a no-op on already-English text, a real
    translation for the Chinese-only brand names)."""
    return when(
        brand_col.contains("/"), regexp_extract(brand_col, r"^([^/]+)", 1)
    ).otherwise(brand_col)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is the card's own data-common-id attribute (numeric, and the
    # same value the product URL embeds) — a genuine stable per-SKU ID.
    # Confirmed 84/84 unique, 0 duplicates, 0 nulls on the live scrape test
    # for this build. The URL-ID fallback should rarely if ever trigger.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))
    # Real single-price sites sometimes only populate one of these two raw
    # fields (a parsing edge case, not a genuine second price) -- backfill
    # so neither ships null when a perfectly good price exists in its
    # sibling field. A genuine discount (both already populated) or a
    # genuinely priceless row (both null, correctly destined for the DLQ)
    # are both left untouched by this.
    df = df.withColumn(
        "Strike_Price",
        when(col("Strike_Price").isNull() & col("Price_Discounted").isNotNull(), col("Price_Discounted"))
        .otherwise(col("Strike_Price")),
    )
    df = df.withColumn(
        "Price_Discounted",
        when(col("Price_Discounted").isNull() & col("Strike_Price").isNotNull(), col("Strike_Price"))
        .otherwise(col("Price_Discounted")),
    )

    df = df.withColumn("Brand", _extract_brand_before_slash(col("Brand")))

    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is Chinese-only with no in-page English switcher (see module
    # docstring) — Databricks' on-cluster ai_translate runs AFTER Size has
    # already been extracted above, so a "700ml"/"53度1000ML" token can't be
    # mangled by translation before the size regex ever sees it.
    df = df.withColumn("Brand", expr("ai_translate(Brand, 'en')"))
    df = df.withColumn("Brandline", expr("ai_translate(Brandline, 'en')"))

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    # GTR/duty-free retailer — Domestic_Tax is null by definition (no
    # domestic tax applies to duty-free goods sold to travellers). This is
    # the expected, correct value here, not a pending TODO.
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # No exclusivity badge/ribbon/"Exclusives" concept found anywhere on
    # this site (only quantity-/spend-based promo labels, already captured
    # as Strike_Price/Price_Discounted) — the scraper never sets this key,
    # so it's already null for every row after the ensure-columns-exist
    # backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)
    # GTR retailer — physical/fulfillment location is Thailand (see scraper
    # module docstring), so Country = "DF Thailand". Applied AFTER
    # ExchangeRate_cleaning() above, never before — that function joins on
    # the plain "Country" name against the exchange-rate reference file,
    # which has no "DF "-prefixed rows.
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))

    df = df.drop("Strike Price", "Price Discounted", "ID_raw")

    bad_rows_cond = (col("ID").isNull()) | (col("ID") == "") | (col("Strike_Price").isNull() & col("Price_Discounted").isNull())
    df_dlq = df.filter(bad_rows_cond)
    df_clean = df.filter(~bad_rows_cond)

    dedup_window = Window.partitionBy("Product_link", "Channel", "Retailer", "ID", "Year", "Month").orderBy(col("Scraped_At").desc())
    df_clean = df_clean.withColumn("_rn", row_number().over(dedup_window)).filter(col("_rn") == 1).drop("_rn")

    try:
        if df_dlq.count() > 0:
            dlq_path = silver_table + "_dlq"
            df_dlq_str = df_dlq.select(*[col(c).cast(StringType()).alias(c) for c in df_dlq.columns])
            print(f"Writing {df_dlq.count()} bad rows to DLQ: {dlq_path}")
            df_dlq_str.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(dlq_path)
    except Exception as e:
        print(f"WARNING: DLQ write failed: {e}")

    final_df = df_clean.select(*[col(c) if c in df_clean.columns else lit(None).alias(c) for c in FORMAT_COLUMNS])

    if spark.catalog.tableExists(silver_table):
        target_table = DeltaTable.forName(spark, silver_table)
        merge_condition = (
            "target.Product_link = source.Product_link AND "
            "target.Channel = source.Channel AND "
            "target.Retailer = source.Retailer AND "
            "target.ID = source.ID AND "
            "target.Year = source.Year AND "
            "target.Month = source.Month"
        )
        target_table.alias("target").merge(final_df.alias("source"), merge_condition).whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()
    else:
        final_df.write.format("delta").saveAsTable(silver_table)


if __name__ == "__main__":
    spark = SparkSession.builder.appName(f"{RETAILER}_Silver_Transform").getOrCreate()
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/kingpower_cn/*/*/*/*.json"
    clean(spark, bronze_path)
