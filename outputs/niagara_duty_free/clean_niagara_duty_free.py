"""
Cleaner for Niagara Duty Free — the silver step paired with
niagara_duty_free_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_niagara_duty_free.py once validated.

GTR retailer — Country gets the "DF " prefix (see scraper module
docstring: a real land-border duty-free shop on the Canadian side of
the Rainbow Bridge, Niagara Falls, ON, confirmed via the site's own
"Can I shop duty free? Yes" FAQ copy), Domestic_Tax stays null by
definition (not a TODO — GTR retailers don't get a Domestic_Tax value).

Currency: the site's own selling currency is CAD (the physical shop is
in Canada; the USD figure shown alongside every price is a same-
transaction currency conversion for American shoppers, not a second
retailer or a discount) — LOCAL_CURRENCY = "CAD", converted to the IWSR
reporting currency via the shared ExchangeRate_cleaning() helper, same
as every other cleaner in this repo.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "Niagara Duty Free"
LOCAL_CURRENCY = "CAD"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Scraper captures the raw CAD price text as-is, e.g. "$32.00" or
    "$11,995.00" (Louis XIII Cognac, a real thousands-comma price on this
    site) — strip the currency symbol and any thousands comma, keep the
    decimal point. No European comma-decimal formatting exists on this
    site (US/CAD "$X,XXX.XX" convention throughout), but the
    is_european_decimal branch is kept for consistency with every other
    cleaner's shared helper shape."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    """Standard cl/ml/l handling, same convention as Calle/Fleggaard.
    Multipack notations extracted upstream by _extract_size_from_text
    (e.g. "24 x 355mL" -> captures just the trailing "355mL" token, i.e.
    the real per-can/per-bottle size, not the pack total) already arrive
    here without an "x" in them, so no special multipack exclusion is
    needed — confirmed against real samples from this site (beer
    12/24/30-packs, icewine 3x200mL/4x200mL/6x200mL multi-bottle sets)."""
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl") & ~size_lower.contains("x"),
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~size_lower.contains("x"),
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when((size_lower.contains("liter") | size_lower.contains("l"))
              & ~size_lower.contains("x") & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
              regexp_replace(size_lower, "liter|l", "").cast(DoubleType()) * 100)
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
    """Fallback for the (very common, on this site) case where Size
    wasn't captured as a dedicated field — every Wine item and a handful
    of Liqueurs (e.g. "Drambuie", "Luxardo Sambuca") have no size at all
    in the title and correctly end up null here; most Alcohol/Beer/
    Icewine titles bundle it in parens, e.g. "Crown Royal Deluxe (1L)",
    "Alexander Keith's Cans (24 x 355mL)", "Peller Cab/Franc (50mL)"."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|liter|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only — ID_raw from the scraper's modal_<N> data attribute
    should cover every row; this mirrors the "#modal_<N>" anchor the
    scraper appends to Product_link in case ID_raw is ever missing."""
    extracted = regexp_extract(product_link_col, r"#modal_(\d+)$", 1)
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

    # ID_raw is the numeric modal ID pulled from the card's
    # data-bs-target attribute by the scraper — confirmed disjoint
    # across every leaf category (see scraper module docstring), so the
    # Product_link fallback should rarely if ever trigger.
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

    # Site is English-only (en-ca) — no ai_translate step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # GTR retailer — physical shop is in Canada (see scraper module
    # docstring), so Country = "DF Canada".
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # No exclusivity badge, ribbon, or "Exclusive" text found anywhere on
    # this site (including the currently-empty /specials page) — the
    # scraper never sets this key, so it's already null for every row
    # after the ensure-columns-exist backfill above.

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/niagara_duty_free/*/*/*/*.json"
    clean(spark, bronze_path)
