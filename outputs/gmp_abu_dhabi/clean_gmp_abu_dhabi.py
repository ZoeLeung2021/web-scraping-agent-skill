"""
Cleaner for GMP (Abu Dhabi alcohol home-delivery retailer) — the silver
step paired with gmp_abu_dhabi_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_gmp_abu_dhabi.py once validated.

Domestic retailer — Country is "Abu Dhabi" (user's explicit call — GMP
serves Abu Dhabi/Al Ain specifically, not nationwide UAE; read per-row
from the bronze JSON, no "DF " prefix since that's GTR-only) and read
directly from the bronze data tagged by the scraper's LOCATIONS dict.

Domestic_Tax: user confirmed the researched 30% Abu Dhabi municipality
tax on retail alcohol purchases (see gmp_abu_dhabi_scraper.py's module
docstring for full sourcing — Abu Dhabi kept this rate throughout, unlike
Dubai which suspended its own 30% tax Jan 2023-Dec 2024 before
reinstating it Jan 2025; a single "UAE" figure would have been wrong).
Applied as a flat "30%" string across every row — the site doesn't expose
a category-specific rate difference to model instead.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "GMP"
LOCAL_CURRENCY = "AED"

# User-confirmed: 30% flat Abu Dhabi municipality alcohol tax — see module
# docstring for sourcing.
DOMESTIC_TAX = "30%"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "AED2,900.00" or "AED49.00" — strip the
    currency code and thousands comma, keep the decimal point."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    # thousands-comma + dot-decimal (e.g. "2,900.00") vs a bare
    # comma-decimal (not seen on this site, but handled defensively same
    # as every other cleaner in this repo)
    is_thousands_comma = cleaned.rlike(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_thousands_comma, regexp_replace(cleaned, ",", "").cast(DoubleType()))
        .when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl") & ~size_lower.contains("x"),
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~size_lower.contains("x"),
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when((size_lower.contains("ltr") | size_lower.contains("l"))
              & ~size_lower.contains("x") & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
              regexp_replace(size_lower, "ltr|l", "").cast(DoubleType()) * 100)
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
    size in parentheses at the end (e.g. "Absolut Blue Vodka (75CL)",
    "AMG Carbon Vodka (1Ltr)", "Malayali Beer Power 7.5% Cans (50CL)").
    Extended for "Ltr" spelled out in addition to the usual cl/ml/l."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|ltr|l)\b)", 1)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is the retailer's own SKU (e.g. "SV0022") pulled directly
    # from the add-to-cart button's data attribute, or from the GTM
    # tracking JSON for WooCommerce "variable" products that don't render
    # a simple add-to-cart SKU on the listing page — see scraper
    # docstring. Falls back to the full Product_link only if genuinely
    # absent (shouldn't happen in practice per testing: 0 null IDs across
    # all 6 categories, 516 rows).
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(col("Product_link")),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # No dedicated Size field — always falls back to the title regex.
    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is English-only by default — no translation step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer — Country is read per-row from the bronze JSON
    # ("Abu Dhabi", tagged by the scraper's LOCATIONS dict), no "DF "
    # prefix (that prefix is GTR-only per the schema).
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    # User-confirmed flat 30% Abu Dhabi municipality tax — see module
    # docstring for sourcing.
    df = df.withColumn("Domestic_Tax", lit(DOMESTIC_TAX))
    # No exclusivity badge, ribbon, or "exclusive"/"members only" text
    # found anywhere on this site — the scraper never sets this key, so
    # it's already null for every row after the ensure-columns-exist
    # backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw")

    # Some rows are WooCommerce "variable" products (multi-pack/case
    # options) whose per-listing price is genuinely unresolvable without
    # visiting the product detail page — these correctly land in the DLQ
    # on the price-null condition, not a mapping bug. See scraper
    # docstring (confirmed 6-11 such rows per larger category in testing).
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/gmp_abu_dhabi/*/*/*/*.json"
    clean(spark, bronze_path)
