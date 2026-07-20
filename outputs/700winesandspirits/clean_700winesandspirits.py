"""
Cleaner for 700 Wines and Spirits (Bahamas) — the silver step paired with
700winesandspirits_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_700winesandspirits.py once validated.

Domestic retailer (legal entity "Commonwealth Brewery Ltd", a Heineken
subsidiary) — Country is the plain country name ("Bahamas"), no "DF "
prefix (see scraper module docstring: no duty-free/traveler language
anywhere on the site, ordinary e-commerce liquor retailer with home
delivery / in-store pickup for the general public).

Domestic_Tax — researched 2026-07-20, read directly from the primary
legal text: Excise Act No. 28 of 2023 (First Schedule) and the Excise
(Amendment) Act, 2025 (in force 1 July 2025, so current as of today).
  - Spirits (Whiskey, Vodka, Rum, Tequila, Gin, Liqueur, Brandy): a
    specific duty of USD/BSD 13.00 per IMPERIAL gallon (verbatim from the
    2025 Amendment Act, tariff codes 2208.2010-2208.9090 — replaced the
    old "$15.00 per proof gallon"). BSD is pegged 1:1 to USD, no FX step
    needed. Computed here as an absolute per-bottle amount (pattern (b))
    using each product's real Size (already normalized to cl): rate per
    cl = 13.00 / 454.609 (1 imperial gallon = 454.609 cl).
  - Ready To Drink: genuinely DIFFERENT treatment, confirmed in the same
    schedule — spirits-based coolers (HS 2208.9010) are taxed 35% ad
    valorem instead of the per-gallon specific rate.
  - Wine (all 17 real leaf categories - Red Blend, Malbec, Cabernet
    Sauvignon, Pinot Noir, Merlot, Kosher, Sangria, Moscato (Red),
    Zinfandel, Chardonnay, Pinot Grigio, Moscato (White), Riesling,
    Sauvignon Blanc, White Blend, Sparkling Wine, Rose): 50% ad valorem
    (HS 2204, confirmed for both still and sparkling wine). NOTE: the
    Excise Table separately lists "wine-based coolers" at 35% instead of
    50% - Sangria could arguably qualify as a wine-based cooler rather
    than plain wine, but this site's own Sangria products are sold as
    bottled wine-style products, not a canned RTD cooler format, so 50%
    is used here. Flagged as a minor judgment call, not re-confirmed
    against the site's actual Sangria product format beyond the category
    label.
  - Beer ("Beer" catch-all category): DELIBERATELY LEFT NULL. Two real
    gaps found during research, neither filled with a guess: (1) the
    imported-beer HS 2203 rate was found in one source as "10% + $10 BSD
    per imperial gallon" but the extraction was self-flagged as possibly
    garbled and could not be independently confirmed; (2) Commonwealth
    Brewery's own locally-produced beer (Kalik, local Heineken) faces a
    confirmed but differently-structured domestic-manufacturing excise
    (charged "when put up for retail sale"), with no current rate found
    (only a stale 2007 figure). This retailer's "Beer" category almost
    certainly mixes both imported and locally-produced beer with no way
    to distinguish them from the scraped data - left null rather than
    picking either rate incorrectly for an unknown mix.
See project_bahamas_tax_research.md for full sourcing detail.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "700 Wines and Spirits"
LOCAL_CURRENCY = "BSD"

# Domestic_Tax rate structure - see module docstring for sourcing.
# BSD is pegged 1:1 to USD, no FX step needed for the computed amount.
_SPIRIT_CATEGORIES = {"Whiskey", "Vodka", "Rum", "Tequila", "Gin", "Liqueur", "Brandy"}
_SPIRIT_RATE_PER_CL = 13.00 / 454.609  # $13.00 BSD per imperial gallon (454.609 cl)
_WINE_CATEGORIES = {
    "Red Blend", "Malbec", "Cabernet Sauvignon", "Pinot Noir", "Merlot",
    "Kosher", "Sangria", "Moscato (Red)", "Zinfandel", "Chardonnay",
    "Pinot Grigio", "Moscato (White)", "Riesling", "Sauvignon Blanc",
    "White Blend", "Sparkling Wine", "Rose",
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
    """Grid card prices are plain "$25.00"-style strings (Ecwid's default
    USD-style formatting; the Bahamian dollar is pegged 1:1 to USD and the
    site never shows a currency code) - strip the "$" and any stray
    thousands comma, keep the decimal dot."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    cleaned = regexp_replace(cleaned, ",", "")
    return when(cleaned == "", lit(None).cast(DoubleType())).otherwise(cleaned.cast(DoubleType()))


def _normalize_size_to_cl(size_col):
    size_lower = lower(size_col)
    return (
        when(size_lower.contains("cl") & ~size_lower.contains("x"),
             regexp_replace(size_lower, r"[^\d.]", "").cast(DoubleType()))
        .when(size_lower.contains("ml") & ~size_lower.contains("x"),
              regexp_replace(size_lower, r"[^\d.]", "").cast(DoubleType()) / 10)
        .when(size_lower.contains("l") & ~size_lower.contains("x")
              & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
              regexp_replace(size_lower, r"[^\d.]", "").cast(DoubleType()) * 100)
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
    """Fallback for the rare card whose title didn't carry a "•"-separated
    size (the scraper's dedicated Size field already covers the vast
    majority - see scraper docstring's "<Name> • <Size>" convention).
    Regex against the full Brandline text as a defensive backstop."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _domestic_tax(category_col, size_cl_col):
    """Bahamas excise — see module docstring. Spirits get a computed
    absolute BSD amount from the $13.00/imperial-gallon specific duty
    using real Size (cl); Ready To Drink and Wine get their own real ad
    valorem rates; Beer is deliberately left null (see docstring)."""
    spirit_amount = (size_cl_col * lit(_SPIRIT_RATE_PER_CL)).cast("decimal(10,2)").cast(StringType())
    result = lit(None).cast(StringType())
    result = when(category_col.isin(*_SPIRIT_CATEGORIES), spirit_amount).otherwise(result)
    result = when(category_col == "Ready To Drink", lit("35%")).otherwise(result)
    result = when(category_col.isin(*_WINE_CATEGORIES), lit("50%")).otherwise(result)
    # category_col == "Beer" (or anything unrecognized) falls through to
    # the initial null - deliberate, see docstring.
    return result


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel", "Category"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw is Ecwid's own numeric product id (as a string), read directly
    # from each grid card's `grid-product--id-<n>` CSS class - confirmed
    # unique per product across every category tested. Falls back to
    # Product_link so a genuinely priced row still gets a usable, stable
    # identifier instead of being dropped, same fallback pattern used by
    # GMP Abu Dhabi/Le Bon Macau/Licoreria Disenzo.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(col("Product_link")),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # Dedicated Size field is populated by the scraper for the vast
    # majority of cards (split on the title's "•" bullet - see scraper
    # docstring); falls back to a regex against Brandline for the rare
    # card without one.
    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is English-only - no translation step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer - Country is the plain name ("Bahamas"), no "DF "
    # prefix (that prefix is GTR-only per the schema).
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", _domestic_tax(col("Category"), col("Size")))
    # GTR_exclusive: no exclusivity badge/tag concept found anywhere on
    # this site (checked every category page, /featured-deals, and a live
    # PDP for "exclusiv*" - zero matches) - the scraper never sets this
    # key, so it's already null for every row after the ensure-columns-
    # exist backfill above. True null case, not invented.

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/700winesandspirits/*/*/*/*.json"
    clean(spark, bronze_path)
