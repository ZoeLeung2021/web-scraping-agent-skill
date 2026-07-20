"""
Cleaner for King's (Suriname) — the silver step paired with
kings_suriname_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_kings_suriname.py once validated.

Domestic retailer — Country is the plain country name (no "DF " prefix).
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "King's"
LOCAL_CURRENCY = "SRD"

# Domestic_Tax — Suriname alcohol excise, researched and user-confirmed
# 2026-07-16. Primary source: WTO Trade Policy Review WT/TPR/S/391 (2019),
# para 3.35 (verbatim, confirmed via direct PDF fetch): "Applied specific
# duties are: USD 2 per litre of rum; between USD 3.30 and USD 8.25 per
# litre of spirits, depending on the alcoholic content; USD 0.12 per
# percentage of alcohol by volume per litre on wine and beer." A widely
# repeated "45%/30%/10% ad valorem" figure attributed to this same report
# was checked against the actual PDF text twice and could not be found —
# treated as a search-engine hallucination, not used.
#
# Denominated in USD (the tax law's native currency) while the site's own
# Currency is SRD — same currency-mismatch situation as Nepal's
# Domestic_Tax, so written as an explicit unit-suffixed rate STRING
# (pattern (c)) rather than an FX-converted absolute amount.
#
# Category-to-rate mapping (user-confirmed methodology: linear
# interpolation of the USD 3.30-8.25/L spirits band over an assumed
# 20%-50% ABV range, using this repo's standard ABV tiers — 40% standard
# spirits, 25% liqueur-type, 5% beer — plus a new ~12% tier for table
# wine and a ~20% tier for fortified port):
#   rum                                          -> 2.00 USD/L (flat)
#   beer                                          -> 0.12 * 5  = 0.60 USD/L
#   wines, champagne, sparkling                   -> 0.12 * 12 = 1.44 USD/L
#   port                                          -> 0.12 * 20 = 2.40 USD/L
#   whisky, malt-whisky, cognac, gin, jenever,
#   aguardente, tequila, vodka, spirit             -> 6.60 USD/L (40% ABV)
#   liqueur, bitter, vermouth, cocktail            -> 4.125 USD/L (25% ABV)
_DOMESTIC_TAX_BY_CATEGORY = {
    "rum": "2.00 USD/L",
    "beer": "0.60 USD/L",
    "wines": "1.44 USD/L",
    "champagne": "1.44 USD/L",
    "sparkling": "1.44 USD/L",
    "port": "2.40 USD/L",
    "whisky": "6.60 USD/L",
    "malt-whisky": "6.60 USD/L",
    "cognac": "6.60 USD/L",
    "gin": "6.60 USD/L",
    "jenever": "6.60 USD/L",
    "aguardente": "6.60 USD/L",
    "tequila": "6.60 USD/L",
    "vodka": "6.60 USD/L",
    "spirit": "6.60 USD/L",
    "liqueur": "4.125 USD/L",
    "bitter": "4.125 USD/L",
    "vermouth": "4.125 USD/L",
    "cocktail": "4.125 USD/L",
}

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "SRD\xa07.360,50" or "SRD\xa0477,30" — a
    non-breaking space after the currency code, European dot-thousands/
    comma-decimal format. Strip everything but digits/dot/comma first."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_dot_thousands_comma_decimal = cleaned.rlike(r"^\d{1,3}(\.\d{3})*,\d{2}$")
    is_plain_comma_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(
            is_dot_thousands_comma_decimal,
            regexp_replace(regexp_replace(cleaned, r"\.", ""), ",", ".").cast(DoubleType()),
        )
        .when(is_plain_comma_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
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
    size at the end (e.g. "100 PIPERS 75CL", "BALLANTINE'S 12 YO 1L",
    "CHIVAS REGAL 12 YO 1.75L"). Handles a decimal point already present
    in some sizes (e.g. "1.75L") without mangling it."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    extracted = regexp_extract(product_link_col, r"variation=([\w-]+)", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel", "Category"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is the "variation" query-param value pulled from the
    # product URL by the scraper (e.g. "11291-DO") — the site's own
    # stable per-SKU/variant identifier. Falls back to extracting it
    # from Product_link directly only if genuinely absent (shouldn't
    # happen per testing: 0 null IDs across 448 rows scraped).
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # No dedicated Size field — always falls back to the title regex.
    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site defaults to Dutch, but product titles are brand names/English
    # spirit terms as-is (e.g. "100 PIPERS," "BALLANTINE'S") — no
    # ai_translate step used.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer — Country is the plain name, no "DF " prefix.
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    domestic_tax = lit(None).cast(StringType())
    for _cat, _rate in _DOMESTIC_TAX_BY_CATEGORY.items():
        domestic_tax = when(col("Category") == _cat, lit(_rate)).otherwise(domestic_tax)
    df = df.withColumn("Domestic_Tax", domestic_tax)
    # No exclusivity badge, ribbon, or "exclusi*" text found anywhere on
    # this site — the scraper never sets this key, so it's already null
    # for every row after the ensure-columns-exist backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw")

    # A small number of rows are genuinely out-of-stock products whose
    # listing card doesn't render a price at all (confirmed live on
    # "JAMESON 1L" — the product detail page shows a real price, "SRD
    # 1.357,15," but the listing card's price span is empty while out of
    # stock) — these correctly land in the DLQ on the price-null
    # condition, not a mapping bug. See scraper docstring.
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/kings_suriname/*/*/*/*.json"
    clean(spark, bronze_path)
