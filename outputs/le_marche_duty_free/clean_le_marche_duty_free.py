"""
Cleaner for Le Marché Duty Free (Eurotunnel Coquelles, France) — the silver
step paired with le_marche_duty_free_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_le_marche_duty_free.py once validated.

GTR retailer — Le Marché Duty Free operates the duty-free concession at the
Eurotunnel Folkestone-Coquelles terminal in Coquelles, France (a joint
venture between Adani Airport Holdings and Flemingo Travel Retail, via
Mumbai Travel Retail Private Limited). Country gets the "DF " prefix
(physical location is in France — see scraper module docstring), and
Domestic_Tax stays null by definition for a GTR/duty-free retailer (no
domestic tax applies to duty-free goods) — this is the expected/correct
null, not an open TODO.

Currency: site prices in EUR ("€17.95" etc.) — LOCAL_CURRENCY = "EUR",
still routed through the shared ExchangeRate_cleaning() helper for
consistency with every other cleaner in this repo (same pattern used by
other EUR-priced GTR builds — Travel FREE CZ/BG, Silk Road Duty Free
Georgia, Diplomatic Shop Serbia, Aircafe Uzbekistan).
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "Le Marché Duty Free"
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
    """Site prices are e.g. "€17.95" — strip the euro sign, keep the
    decimal point. No thousands separator seen on this site (prices top
    out around €330), but the comma-decimal branch is kept for defensive
    consistency with every other cleaner in this repo."""
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
    size bundled in with brand/ABV (e.g. "BAILEYS IRISH CREAM 17% 1L",
    "GOUDALE BLONDE 7.2% 6X0.25L", "CHATEAUNEUF DU PAPE TRADITION ROUGE
    75CL"). Multipack titles (containing "x", e.g. "24X0.355L") are
    excluded by _normalize_size_to_cl above, same convention as every other
    cleaner in this repo, and correctly fall back to null Size rather than a
    misleading per-case total. Known exception NOT special-cased: "BUDWEISER
    US CAN 792 CL" has no "x" marker despite being a 24-pack — see scraper
    module docstring."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    extracted = regexp_extract(product_link_col, r"/(\d+)\.p", 1)
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

    # ID_raw is the numeric product ID pulled from the end of the product
    # URL slug by the scraper (the digits immediately before ".p") —
    # reliable, confirmed present on all 398 live products tested. The
    # Product_link fallback (parsed the same way) should rarely if ever
    # trigger.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is English-only (Eurotunnel serves both French and British
    # travellers, but the storefront copy/product titles are all English)
    # — no translation step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # GTR retailer — physical location is Coquelles, France (see scraper
    # module docstring), so Country = "DF France".
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    # GTR/duty-free retailer — Domestic_Tax is null by definition (no
    # domestic tax applies to duty-free goods sold to travellers). This is
    # the expected, correct value here, not a pending TODO.
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # No exclusivity badge, ribbon, or "exclusive"/"GTR exclusive" text
    # found anywhere on this site (the only per-product badge text seen was
    # multi-buy bundle copy like "BUY 2 @ €44") — the scraper never sets
    # this key, so it's already null for every row after the
    # ensure-columns-exist backfill above.

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/le_marche_duty_free/*/*/*/*.json"
    clean(spark, bronze_path)
