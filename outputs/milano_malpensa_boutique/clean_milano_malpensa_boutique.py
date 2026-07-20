"""
Cleaner for Milano Malpensa Boutique — the silver step paired with
milano_malpensa_boutique_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_milano_malpensa_boutique.py once validated.

GTR retailer — Milano Malpensa Boutique is S.E.A. S.p.A.'s (the airport
operator for Milan Malpensa/Linate, P.IVA 00826040156) own "book online,
pick up at Malpensa Terminal 1 on departure day" duty-free storefront.
Confirmed live via the site's own copy: "YOUR DUTY-FREE SHOPPING
DESTINATION!", repeated "duty-free" language, a flight-detail widget that
gates the reserve/checkout flow but NOT the listing/detail prices
themselves (every price renders with no flight info entered) — see the
scraper's module docstring for the full write-up. Country gets the "DF "
prefix (Country = "Italy" from the scraper -> "DF Italy" here),
Domestic_Tax stays null by definition (GTR/duty-free, not domestic) — that
is the expected/correct null, not an open TODO.

Currency: site prices in EUR ("€ 46,50" etc.) — LOCAL_CURRENCY = "EUR",
still routed through the shared ExchangeRate_cleaning() helper for
consistency with every other EUR-priced GTR cleaner in this repo (Le
Marché Duty Free, Travel FREE CZ/BG, Silk Road Duty Free Georgia,
Diplomatic Shop Serbia, Aircafe Uzbekistan).

GTR_exclusive: real per-product concept on this site, but the raw signal
captured by the scraper is the literal matched keyword text ("Travel
Exclusive", "Travel Retail Exclusive", "TRX", "GTR" — blank "" if none),
NOT a value that always contains the substring "exclusive" (e.g. "TRX"
and "GTR" don't). So unlike the generic template's default
`.contains("exclusive")` check, this cleaner maps any non-blank raw value
to "Yes" and blank "" to "No" instead.

Known, confirmed site-side quirk (not a scraper bug — see scraper
docstring): each category's H1 header badge count is consistently HIGHER
than the number of distinct SKUs actually reachable via full pagination
(e.g. Whiskey header said 183, live re-validation on 2026-07-20 found only
114 real SKUs across 5 exhausted pages, 0 duplicates). Most likely a
BigCommerce category-metadata field that includes delisted/out-of-
visibility products. This does not create bad rows in the silver
pipeline — it just means the per-category row counts will legitimately be
lower than the site's own displayed header count. Flagged for visibility,
not something to "fix" here.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "Milano Malpensa Boutique"
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
    """Site prices are e.g. "€ 46,50" (space after symbol, comma decimal),
    with the occasional dot-thousands premium bottle (e.g. "€ 1.234,56").
    Strip everything but digits/dot/comma, then disambiguate the two
    European formats before falling back to a plain-numeric cast."""
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
    """Fallback only — the scraper's own second-pass detail-page fetch
    ("Size: 1L" text) is the primary source and should cover the large
    majority of rows. This regex over Brandline is a safety net for the
    rare product where that second pass didn't find a match."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only — ID_raw (the numeric SKU baked into both the RSC
    JSON and the URL, e.g. "3454983" in ".../american-oak-3454983/") should
    cover every row in practice."""
    extracted = regexp_extract(product_link_col, r"-(\d+)/?$", 1)
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

    # ID_raw is the BigCommerce SKU pulled straight from the RSC product
    # JSON (and mirrored in the URL slug) by the scraper — the site's own
    # stable per-SKU identifier.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # Size comes from the scraper's second-pass detail-page fetch ("Size:
    # 1L" text) when present; falls back to extracting it from Brandline
    # text otherwise.
    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is already served in English via the /en/ path — no
    # ai_translate step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # GTR retailer — single airport (Malpensa Terminal 1, Italy).
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))

    # GTR_exclusive: real per-product concept, but the raw signal is the
    # literal matched keyword ("Travel Exclusive", "TRX", "GTR", ... or
    # blank "" if none) rather than text that always contains the
    # substring "exclusive" — map any non-blank raw value to "Yes" instead
    # of the generic template's `.contains("exclusive")` check. The
    # scraper always sets a real string (never Python None) for this site,
    # so the "does the site have this concept at all" check below is
    # expected to always resolve True here.
    site_has_exclusivity_concept = df.filter(col("GTR_exclusive").isNotNull()).limit(1).count() > 0
    if site_has_exclusivity_concept:
        df = df.withColumn(
            "GTR_exclusive",
            when(col("GTR_exclusive") != "", lit("Yes")).otherwise(lit("No")),
        )
    else:
        df = df.withColumn("GTR_exclusive", lit(None).cast(StringType()))

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/milano_malpensa_boutique/*/*/*/*.json"
    clean(spark, bronze_path)
