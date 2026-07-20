"""
Cleaner for Gonsalves Liquors Ltd. (Saint Vincent and the Grenadines) —
the silver step paired with gonsalves_liquors_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_gonsalves_liquors.py once validated.

Domestic retailer — Country is the plain country name (no "DF " prefix).
See the scraper's module docstring for the full source-document analysis
(PDF price list, not an HTML catalog) — this cleaner only covers the
generic silver-schema mapping; the interesting/novel work for this build
is entirely in the scraper's PDF parsing.

Domestic_Tax — researched 2026-07-20, read directly from the First
Schedule of the Excise Tax Act, Cap. 430 (Act No. 16 of 2007, as amended
through SRO 2/2009) — customs.gov.vc/downloads/act-excise-tax-ch430.pdf.
Rates are SPECIFIC per-litre-of-PRODUCT amounts (not ABV/pure-alcohol-
based), so no assumed-ABV tier is needed here — a genuine advantage over
most other Domestic_Tax builds in this project. Confirmed a widely
search-summarized "WT/TPR/S/299"-attributed rate table does NOT actually
exist in that document (read in full) — same hallucination pattern
flagged on the Suriname build; not used.

Almost every alcoholic category on this schedule lands at the SAME rate,
EC$3.30/L (Wine 22.04, Vermouth 22.05, Brandy/Whiskey/Rum/Gin/Vodka/
Liqueurs/Tequila-other 2208.20-2208.909) — so this cleaner defaults every
row to that rate, with two confirmed exceptions: Beer/Stout (22.03) at
EC$0.55/L, and Cider/Perry/Mead (22.06) at EC$0.50/L (no cider products
found live on this catalog, kept defensively in case one is added later).
Computed as an absolute XCD amount (pattern (b)) using each product's
real Size — matches the site's own Currency (XCD), no FX step needed.

CAVEAT, user-acknowledged (2026-07-20, "use as-is, flagged"): this
schedule is a verified 2009 floor/baseline. A footnote in SVG's 2014 WTO
Trade Policy Review confirms further excise increases via SRO 18/2011,
SRO 2/2012, and SRO 2/2013 that could not be located online — today's
real rates may be somewhat higher than what's used here. Update if a
newer consolidated schedule surfaces. See project_svg_tax_research.md
for full sourcing detail.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "Gonsalves Liquors"
LOCAL_CURRENCY = "XCD"  # Eastern Caribbean Dollar - the PDF's own "EC. $"
# column header; ISO 4217 code XCD. Confirmed NOT the same as whatever
# this project's reporting currency is, so ExchangeRate_cleaning() below
# is required (not skipped).

# Domestic_Tax rate structure - see module docstring for sourcing.
_BEER_RATE_PER_CL = 0.55 / 100  # EC$0.55 per liter
_CIDER_RATE_PER_CL = 0.50 / 100  # EC$0.50 per liter
_DEFAULT_RATE_PER_CL = 3.30 / 100  # EC$3.30 per liter - covers wine,
# vermouth, and every spirit/liqueur category on this schedule

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Prices in the source PDF are plain US/UK-style numbers, e.g.
    "1,090.00" or "86.25" (comma thousands separator, dot decimal) - no
    currency symbol embedded (the scraper already strips the "EC. $"
    column header, it's not part of each row's price text). Much simpler
    than the European comma-decimal formats seen on other builds."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    cleaned = regexp_replace(cleaned, ",", "")
    return cleaned.cast(DoubleType())


def _extract_size_from_text(text_col):
    """Brandline is built by the scraper as "<name> <size><unit>", e.g.
    "Jack Daniels 75cl", "Grey Goose Citron 1Lt", "Balvenie 16 Yr French
    Cask Oak Pineau Cask 70cl" - always a trailing size token, always
    present (the scraper always appends it), unlike retailers where size
    has to be guessed out of a free-text title."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|lt|l)\b)", 1)


def _normalize_size_to_cl(size_col):
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl"),
             regexp_replace(size_lower, "cl", "").cast(DoubleType()))
        .when(size_lower.contains("ml"),
              regexp_replace(size_lower, "ml", "").cast(DoubleType()) / 10)
        .when(size_lower.contains("lt"),
              regexp_replace(size_lower, "lt", "").cast(DoubleType()) * 100)
        .when(size_lower.contains("l"),
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


def _domestic_tax(category_col, size_cl_col):
    """SVG excise - see module docstring. Beer/Stout and Cider/Perry/
    Mead get their own confirmed lower rates; every other alcoholic
    category on this schedule (wine, vermouth, all spirits/liqueurs)
    shares the same EC$3.30/L rate, used here as the default."""
    cat_upper = when(category_col.isNotNull(), category_col).otherwise(lit(""))
    is_beer = cat_upper.contains("BEER") | cat_upper.contains("STOUT")
    is_cider = cat_upper.contains("CIDER") | cat_upper.contains("PERRY") | cat_upper.contains("MEAD")
    rate_per_cl = (
        when(is_beer, lit(_BEER_RATE_PER_CL))
        .when(is_cider, lit(_CIDER_RATE_PER_CL))
        .otherwise(lit(_DEFAULT_RATE_PER_CL))
    )
    return (size_cl_col * rate_per_cl).cast("decimal(10,2)").cast(StringType())


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel", "Category", "Case_Qty_raw",
              "Case_Price_raw", "Is_New_raw"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is a slug the scraper derives from the product's name+size
    # (e.g. "jack-daniels-75cl") - see scraper docstring for the
    # collision-disambiguation pass it already runs (a numeric-2/-3
    # suffix on the rare rows whose brand is logo-only text, where two
    # genuinely different products would otherwise share a slug).
    # Confirmed live: 0 null IDs across 751 rows scraped.
    df = df.withColumn("ID", col("ID_raw"))

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer - Country is the plain name, no "DF " prefix.
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", _domestic_tax(col("Category"), col("Size")))
    # No exclusivity concept anywhere in a wholesale/retail price-list PDF
    # - the scraper never sets this key, so it's already null for every
    # row after the ensure-columns-exist backfill above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw", "Case_Qty_raw",
                 "Case_Price_raw", "Is_New_raw")

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/gonsalves_liquors/*/*/*/*.json"
    clean(spark, bronze_path)
