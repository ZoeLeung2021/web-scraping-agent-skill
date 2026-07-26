"""
Cleaner for BorderShop (Puttgarden & Rostock, operated by Heinemann TRFB
GmbH) — the silver step paired with bordershop_heinemann_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_bordershop_heinemann.py once validated.

GTR retailer — Country gets the "DF " prefix (both shops are physically in
Germany, near the Puttgarden and Rostock ferry ports — see scraper module
docstring for the confirmed Heinemann TRFB GmbH / Calle / Fleggaard
land-border precedent this follows). Domestic_Tax stays null (GTR, not a
domestic retailer — this is expected, not a TODO).

GTR_exclusive here is a genuine Yes/No (never null) — the scraper reads a
real per-product `dimension3` "travel exclusive" tag (paired 1:1 with a
visible "Travel Edition" ribbon) straight from each card's embedded JSON,
unlike Calle/Fleggaard where no such concept exists on the site at all.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "BorderShop"
LOCAL_CURRENCY = "DKK"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

# Channel values are the raw location names the scraper sets ("Puttgarden",
# "Rostock") — no relabeling needed.
CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Prices come from each card's embedded JSON as plain decimal strings
    (e.g. "99.95") — no currency symbol to strip, but this still runs
    through the shared comma/European-decimal-safe helper for
    consistency, since a handful of product entries mix Danish
    comma-decimal formatting into otherwise-JSON-sourced fields."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    """The scraper's Size field is a single isolated size token (e.g.
    "1L", "0.7L", "0,33L", "1 l.") pulled either from the price box's
    per-unit reference line or a regex match against the product name —
    never a raw multipack string like "24 x 33 cl" (the regex only
    captures the trailing unit token, not the leading "24 x"), but the
    "x" guard is kept anyway for defense in depth. Danish comma-decimals
    are normalized to "." first."""
    size_norm = regexp_replace(lower(size_col), ",", ".")
    return (
        when(size_norm.contains("cl") & ~size_norm.contains("x"),
             regexp_replace(size_norm, "cl", "").cast(DoubleType()))
        .when(size_norm.contains("ml") & ~size_norm.contains("x"),
              regexp_replace(size_norm, "ml", "").cast(DoubleType()) / 10)
        .when((size_norm.contains("liter") | size_norm.contains("l"))
              & ~size_norm.contains("x") & ~size_norm.contains("cl") & ~size_norm.contains("ml"),
              regexp_replace(size_norm, "liter|l", "").cast(DoubleType()) * 100)
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
    """Fallback for the rare row where the scraper's own Size field is
    empty — titles bake size in too (e.g. "Bollinger ... 0.75L")."""
    normalized = regexp_replace(text_col, ",", ".")
    return regexp_extract(normalized, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|liter|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    extracted = regexp_extract(product_link_col, r"/p/0*(\d+)/", 1)
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

    # ID_raw is the clean numeric product id straight from each card's
    # embedded JSON (e.g. "630375") — the Product_link fallback (parsed
    # from the zero-padded /p/000000000000630375/ URL segment) should
    # rarely if ever trigger.
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

    # Site defaults to Danish (da) locale — product titles are brand
    # names/spirit names in Latin script as-is, no ai_translate step used.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))
    # GTR_exclusive already carries a real "Yes"/"No" from the scraper
    # (per-product `dimension3` "travel exclusive" tag) — passed through
    # as-is, no further mapping needed here.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)
    # GTR retailer — both shops are physically in Germany (see scraper
    # module docstring), so Country = "DF Germany", not "DF Denmark",
    # despite the da (Danish) customer-facing locale this was scraped
    # under.
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/bordershop_heinemann/*/*/*/*.json"
    clean(spark, bronze_path)
