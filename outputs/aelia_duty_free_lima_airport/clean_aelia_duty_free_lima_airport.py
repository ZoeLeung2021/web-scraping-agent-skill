"""
Cleaner for Aelia Duty Free at Lima's Jorge Chávez International Airport —
the silver step paired with aelia_duty_free_lima_airport_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_aelia_duty_free_lima_airport.py once
validated.

GTR retailer — the site's own homepage copy explicitly says "compras de
primera clase, libres de impuestos para viajeros de todo el mundo"
(duty-free shopping for travelers worldwide). Country gets the "DF " prefix
(physical location is Lima, Peru — see scraper module docstring), and
Domestic_Tax stays null by definition for a GTR/duty-free retailer (no
domestic tax applies to duty-free goods) — this is the expected/correct
null, not an open TODO.

RETAILER = "Lima Airport Partners (Aelia)" — user-confirmed 2026-07-21
after a real cross-site ID check. The data owner compared this site's
Hennessy XO (VTEX sku "1372") against Aelia Lyon's (aeliadutyfree.fr)
real Hennessy XO Magento product id ("71968") from their own GTR_Pricing
data — the two numbering systems are unrelated (small sequential VTEX
tenant-scoped skus here vs. large Magento catalog entity ids there), so
this site's IDs do NOT line up with the existing "Aelia" retailer used
for France/Romania/Ireland etc. in the production repo. Named
accordingly rather than as plain "Aelia", per the user's explicit
either/or instruction. The underlying two-entity nuance still applies:
the *platform*/marketplace itself ("marketplace.lima-airport.com") is
legally operated by Lima Airport Partners S.R.L. (LAP), and every
product card additionally says "Vendido por: Aelia Duty Free" (a
Lagardère Travel Retail brand) — this RETAILER value names both.

Currency: site prices in USD (confirmed via both the visible price-range
facet and every product's own schema.org offers.priceCurrency) —
LOCAL_CURRENCY = "USD", still routed through the shared
ExchangeRate_cleaning() helper for consistency with every other cleaner in
this repo (same pattern used by Attenza Duty Free, also USD-priced).

ID: no Magento-style `div.price-box.price-final_price[data-product-id]`
exists on this site (it's VTEX, not Magento — confirmed live, zero matches).
ID_raw is the schema.org `sku` field pulled from each product's JSON-LD on
the category listing page (unique, stable, confirmed against the site's own
embedded VTEX itemId for the same products) — see scraper module docstring
for the full investigation. The cross-site ID question above is now
resolved (does NOT line up with Aelia France/Romania/Ireland's IDs) —
this VTEX sku remains the correct, stable per-product identifier for
THIS site regardless of the RETAILER-naming outcome.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "Lima Airport Partners (Aelia)"
LOCAL_CURRENCY = "USD"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Prices are captured as plain numeric strings by the scraper (pulled
    straight from JSON-LD offers.price, e.g. "129", "79.00") — no currency
    symbol or thousands separator to strip, but the comma-decimal branch is
    kept for defensive consistency with every other cleaner in this repo."""
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
    """No dedicated Size field anywhere in the site's shelf-level JSON-LD —
    every Brandline carries the VTEX "nameComplete" spec string bundled
    with brand/ABV/size (e.g. "CHABOT XO SUPERIOR 70CL 40%", "METAXA 7*
    40% 1L", "MOUTAI DUFU LEGENDARY CHINA 37,5CL 53%"). The site mixes
    comma-decimal and dot-decimal size notation inconsistently across
    products (confirmed live — both "37,5CL" and "37.5 CL" forms seen for
    sibling Moutai products) — normalize comma to dot before the regex,
    same convention as every other title-parsed Size field in this repo."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    extracted = regexp_extract(product_link_col, r"/([\w-]+)/p$", 1)
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

    # ID_raw is the schema.org "sku" field pulled from each product's
    # JSON-LD on the category listing page — confirmed unique and stable
    # across all 17 live products tested (0 duplicates). The Product_link
    # fallback (parsed for a URL slug) should rarely if ever trigger.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is Spanish-only; product/brand names are proper nouns as-is
    # (e.g. "Chabot Armagnac XO Superior", "Metaxa 7 Stars") — no
    # translation step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # GTR retailer — physical location is Lima, Peru (see scraper module
    # docstring), so Country = "DF Peru".
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    # GTR/duty-free retailer — Domestic_Tax is null by definition (no
    # domestic tax applies to duty-free goods sold to travellers). This is
    # the expected, correct value here, not a pending TODO.
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # No exclusivity badge, ribbon, or "exclusivo"/"exclusive" text found
    # anywhere on this site (a full-page-text keyword scan for "exclusiv"
    # returned zero hits on both category pages and 2 PDPs checked in
    # detail) — the scraper never sets this key, so it's already null for
    # every row after the ensure-columns-exist backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/aelia_duty_free_lima_airport/*/*/*/*.json"
    clean(spark, bronze_path)
