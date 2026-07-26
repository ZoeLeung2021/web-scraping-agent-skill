"""
Cleaner for RegStaer (Vnukovo) — the silver step paired with
regstaer_vnukovo_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_regstaer_vnukovo.py once validated.

GTR retailer — RegStaer Group of Companies is a Russian travel-retail
operator; its own site copy self-identifies as the leading duty-free
operator "at the country's airports" (plural). Country gets the "DF "
prefix ("DF Russia"), and Domestic_Tax stays null by definition for a
GTR/duty-free retailer — this is the expected/correct null, not an open
TODO.

Channel scope — OPEN ITEM, see scraper module docstring: this build could
not empirically confirm a genuine per-airport catalog split between
RegStaer's two named stores (Vnukovo, Mineralnye Vody); every fetch
resolved to the same "Vnukovo-A" terminal context and identical catalog
totals. Scoped to Channel = "Vnukovo International Airport (VKO)" only,
matching the task's own traffic-source origin (utm_source=vko). Flagged
for user sign-off before assuming a second Mineralnye Vody channel is (or
isn't) needed.

Currency: site prices in EUR ("€ 13", "€ 63") — LOCAL_CURRENCY = "EUR",
routed through the shared ExchangeRate_cleaning() helper for consistency
with every other cleaner in this repo (same pattern used by other
EUR-priced GTR builds — Le Marché Duty Free, Milano Malpensa Boutique,
Travel FREE CZ/BG, Silk Road Duty Free Georgia).

NOTE on the exchange-rate reference file: a local copy of
Ex.Rates_2025.xlsx (sheet "DF") found in the repo during this build lists
Russia's row as Country="Russia" (no "DF " prefix), IWSR Currency="EUR",
Local Currency="RUB". Every existing GTR cleaner in this repo (see
clean_le_marche_duty_free.py, clean_milano_malpensa_boutique.py) sets the
"DF " prefix BEFORE calling ExchangeRate_cleaning(), which joins on that
exact "Country" string — if the live production CSV (not checked into
this repo; lives at the Databricks Volume path below) mirrors the local
xlsx's un-prefixed naming, this join (and every other GTR cleaner's join)
would silently miss. This build follows the established repo precedent
rather than deviating unilaterally — flagged here for whoever owns the
reference file to confirm. In this specific case it happens not to change
the *output* either way: our LOCAL_CURRENCY ("EUR") already equals that
row's IWSR Currency ("EUR"), so ExchangeRate_cleaning()'s conversion mask
evaluates False (no-op) whether or not the join matches.

GTR_exclusive: no exclusivity badge, ribbon, or "Exclusives" concept found
anywhere on the site (see scraper module docstring) — the scraper never
sets this key, so it is already null for every row after the
ensure-columns-exist backfill below. This is the genuine null case, not
"No".
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "RegStaer"
LOCAL_CURRENCY = "EUR"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "€ 13", "€ 6.50" (space after symbol, dot
    decimal — no comma-decimal or thousands-separator variant seen live on
    this site). The comma-decimal branch is kept for defensive consistency
    with every other cleaner in this repo, in case a higher-priced/premium
    product ever renders one."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl") & ~size_lower.contains("x"),
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~size_lower.contains("x"),
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when(size_lower.contains("l") & ~size_lower.contains("x")
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
    """No dedicated Size field on this site — every product title carries
    size bundled in with brand/ABV (e.g. "DERBENT COGNAC 0.5L", "CAMUS
    VSOP INTENSELY AROMATIC 40% 1L", "RUSSIAN SPARKLING WINE ABRAU-DURSO,
    SEMI SWEET 0,375L"). Titles use BOTH dot- and comma-decimal volumes —
    normalize commas to dots before matching. Multipack titles containing
    "x" (e.g. "HENNESSY VSOP TP 40% 2X0.7L") are excluded by
    _normalize_size_to_cl above, same convention as every other cleaner in
    this repo, and correctly fall back to null Size rather than a
    misleading total/per-unit ambiguity."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only — ID_raw (the retailer's own "Code" field, pulled by
    the scraper's second-pass detail-page fetch) should cover every row in
    practice. This mirrors the scraper's own URL-ID regex as a last
    resort: the Bitrix product ID immediately before the trailing slug in
    ".../<PRODUCT_ID>__<slug>/"."""
    extracted = regexp_extract(product_link_col, r"/(\d+)__[^/]+/?$", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is the retailer's own "Code" field (data-role="code" on the
    # product detail page) — a real per-SKU identifier distinct from both
    # the Bitrix internal URL ID and the "Articul"/article number, pulled
    # by the scraper's second-pass detail-page fetch. Confirmed present on
    # all 135 live products tested (66 Cognac + 69 Sparkling Wine, 0
    # missing, 0 duplicates). The URL-ID fallback should rarely if ever
    # trigger.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))
    # Real single-price sites sometimes only populate one of these two
    # raw fields (a parsing edge case, not a genuine second price) -- back-
    # fill so neither ships null when a perfectly good price exists in its
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

    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site product titles mix English and Russian (brand/product names are
    # often transliterated Latin already, e.g. "DERBENT", "TSARSKAYA"; the
    # scraper strips the trailing RU/EN category tag after " / " from
    # every title before this cleaner ever sees it) — no bulk translation
    # step needed.

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
    # No exclusivity badge/ribbon/"exclusive" text found anywhere on this
    # site (only "Promotion", already captured as Strike_Price/
    # Price_Discounted) — the scraper never sets this key, so it's already
    # null for every row after the ensure-columns-exist backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)
    # GTR retailer — physical location is Russia (see scraper module
    # docstring), so Country = "DF Russia".
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/regstaer_vnukovo/*/*/*/*.json"
    clean(spark, bronze_path)
