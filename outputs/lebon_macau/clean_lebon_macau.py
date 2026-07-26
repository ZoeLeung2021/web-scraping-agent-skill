"""
Cleaner for Le Bon (Macau) — the silver step paired with
lebon_macau_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_lebon_macau.py once validated.

Domestic retailer — Country is the plain country name ("Macau"), no
"DF " prefix (see scraper module docstring: no duty-free/traveler
language anywhere on the site, ordinary e-commerce liquor retailer with
home delivery).

Domestic_Tax — researched and user-confirmed 2026-07-16. Macau's alcohol
consumption tax (Lei n.º 4/99/M, "Regulamento do Imposto de Consumo",
Group II; rates per Despacho 180/2010, confirmed via a direct fetch of
gov.mo PS-1331a and MdME's 2025 Macau tax guide) is a hard 30% ABV cliff-
edge, not a graduated band:
  - Below 30% ABV (beer, most wine, most liqueurs) -> exempt, 0%.
  - Rice wine -> exempt regardless of ABV (explicit carve-out).
  - 30% ABV or above (most spirits, some high-proof liqueurs/fortified
    wine) -> MOP 20.00 per litre of product (specific duty) PLUS a 10%
    ad valorem component on CIF import value.
The 10% CIF component is deliberately NOT included here — Le Bon's site
only exposes retail HKD price, and CIF import value is always lower than
retail, so mechanically applying 10% to retail would overstate the tax
(user-confirmed decision: specific-duty component only, flagged as a
known simplification rather than silently invented). MOP != HKD (this
site's Currency) and there's no FX step to piggyback on, so the taxed
tier is written as an explicit unit-suffixed rate STRING ("20.00 MOP/L"),
same pattern as Nepal's and King's Suriname's Domestic_Tax.

ABV is read directly from each product's real title text (e.g. "Ardbeg
Perpetuum 70cl | 47.4%") rather than an assumed tier — a genuine
improvement over most other Domestic_Tax builds in this repo, which lack
real per-product ABV. Products with no parseable ABV in the title are
left null (honest "insufficient data for this SKU", not defaulted to
either the exempt or taxed rate).
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "Le Bon"
LOCAL_CURRENCY = "HKD"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Shopify's REST JSON returns plain decimal-string prices, e.g.
    "470.00" — no currency code, no thousands separator, dot-decimal
    already. Still routed through the shared strip-and-cast helper for
    consistency and to defensively handle any stray comma."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
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


def _domestic_tax_from_title(brandline_col):
    """Macau consumption tax: 30% ABV cliff-edge (exempt below, "20.00
    MOP/L" specific duty at/above — see module docstring), with rice wine
    always exempt regardless of ABV. Real per-product ABV read from the
    title text (e.g. "47.4%"); products with no parseable ABV are left
    null rather than defaulted."""
    abv = regexp_extract(brandline_col, r"(\d+(?:\.\d+)?)\s*%", 1).cast(DoubleType())
    is_rice_wine = lower(brandline_col).contains("rice wine")
    return (
        when(is_rice_wine, lit("0%"))
        .when(abv.isNull(), lit(None).cast(StringType()))
        .when(abv >= 30, lit("20.00 MOP/L"))
        .otherwise(lit("0%"))
    )


def _extract_size_from_text(text_col):
    """Fallback for the ~951/959 single-variant products where the
    scraper's dedicated Size field is null — every product title carries
    size (e.g. "Ardbeg Perpetuum 70cl | 47.4%"). Confirmed via testing:
    955/959 titles contain a cl-size token; one real gap ("Hendrick's Gin
    | 41.4%" has no size anywhere on the site) will correctly stay null
    here, not a bug."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel", "Category"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is Shopify's own numeric variant id (as a string), built
    # directly by the scraper from the products.json response — confirmed
    # zero nulls and zero duplicates across all 967 live variants (unlike
    # the site's own `sku` field, which has 2 nulls and 3 reused
    # duplicates — see scraper docstring for why sku was rejected in
    # favor of the variant id).
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(col("Product_link")),
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

    # Dedicated Size field is only populated by the scraper for the 8
    # multi-variant products (e.g. "75cl"/"100cl"); everything else falls
    # back to the title regex against Brandline.
    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is English-only by default — no translation step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer — Country is the plain name ("Macau"), no "DF "
    # prefix (that prefix is GTR-only per the schema).
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", _domestic_tax_from_title(col("Brandline")))
    # GTR_exclusive: the scraper always sets a real "true"/"false" string
    # for every row — "Le Bon Exclusive" is a genuine per-product
    # collection/tag on this site (confirmed 307/959 products, verified
    # two independent ways — see scraper docstring), so this is never the
    # null/unset case.
    df = df.withColumn(
        "GTR_exclusive",
        when(lower(col("GTR_exclusive")) == "true", lit("Yes")).otherwise(lit("No")),
    )

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw", "Category")

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/lebon_macau/*/*/*/*.json"
    clean(spark, bronze_path)
