"""
Cleaner for West Coast Duty Free — the silver step paired with
west_coast_duty_free_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_west_coast_duty_free.py once validated.

GTR retailer — Country gets the "DF " prefix (see scraper module
docstring: a real land-border duty-free shop on the Canadian side of the
Pacific Highway crossing, Surrey, BC, confirmed via the site's own "Duty
Free... items can be purchased when crossing national borders... for
export only" FAQ copy), Domestic_Tax stays null by definition (not a
TODO — GTR retailers don't get a Domestic_Tax value).

Currency: the site's own copy states prices are "in Canadian dollars"
and the physical shop is in BC, Canada — LOCAL_CURRENCY = "CAD",
converted to the IWSR reporting currency via the shared
ExchangeRate_cleaning() helper, same as every other cleaner in this repo.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "West Coast Duty Free"
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
    """Scraper captures the raw CAD price text as-is, e.g. "$30" or
    "$329.00" — strip the currency symbol and any thousands comma, keep
    the decimal point. No European comma-decimal formatting exists on
    this site (US/CAD "$X,XXX.XX" convention), but the
    is_european_decimal branch is kept for consistency with every other
    cleaner's shared helper shape."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    """Standard cl/ml/l handling, same convention as niagara_duty_free/
    Calle/Fleggaard. This site's titles use "litre"/"L"/"ml" tokens
    (e.g. "1.14 litre", "1L", "750ml") with no multipack notation at all
    (every liquor item here is a single bottle) — the "x" multipack guard
    is kept anyway for consistency with the shared helper shape."""
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl") & ~size_lower.contains("x"),
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~size_lower.contains("x"),
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when((size_lower.contains("litre") | size_lower.contains("liter") | size_lower.contains("l"))
              & ~size_lower.contains("x") & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
              regexp_replace(size_lower, "litres|litre|liters|liter|l", "").cast(DoubleType()) * 100)
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
    """Fallback for the case where Size wasn't captured as a dedicated
    field (it never is on this site — see scraper module docstring, every
    title bundles Brand + Size together, e.g. "Crown Royal 1.14 litre",
    "Don Julio Reposado 750ml", "Grey Goose 1 litre")."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|litres?|liters?|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only — ID_raw from the scraper's wp-image-<N> media
    attachment ID should cover every row; this mirrors the
    "#wp-image-<N>" anchor the scraper appends to Product_link in case
    ID_raw is ever missing."""
    extracted = regexp_extract(product_link_col, r"#wp-image-(\d+)$", 1)
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

    # ID_raw is the WordPress media attachment ID pulled from the item's
    # <img class="... wp-image-<N> ..."> by the scraper — the only stable
    # per-item identifier on this site (confirmed no other SKU/ID exists
    # anywhere), so the Product_link fallback should rarely if ever
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

    # Site is English-only (en-ca) — no ai_translate step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # No exclusivity badge, ribbon, or "Exclusive" SKU tag found anywhere
    # on this site (only generic marketing copy describing the whole
    # store, e.g. "exclusive duty-free prices") — the scraper never sets
    # this key, so it's already null for every row after the
    # ensure-columns-exist backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)
    # GTR retailer — physical shop is in Surrey, BC, Canada (see scraper
    # module docstring), so Country = "DF Canada".
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/west_coast_duty_free/*/*/*/*.json"
    clean(spark, bronze_path)
