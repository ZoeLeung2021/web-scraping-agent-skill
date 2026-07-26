"""
Cleaner for Spirits & Wine (Latvia) -- the silver step paired with
spiritsandwine_latvia_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_spiritsandwine_latvia.py once validated.

Domestic retailer -- Market = "Domestic", plain "Latvia" Country (no
"DF " prefix, that's GTR-only). See scraper module docstring for why this
is a genuinely different, independently-operated business from SuperAlko
Latvia (already built in this project), not a shared-ownership platform.

Domestic_Tax is a REAL per-bottle calculation, reusing SuperAlko Latvia's
already-user-confirmed Latvian VID (Valsts ieņēmumu dienests) excise-duty
rates -- same country, same law, and independently re-confirmed live
against vid.gov.lv's own published 2025/2026 rate figures (the EUR 159 /
EUR 264 "intermediate products" bands quoted there match SuperAlko's
constants exactly). This is possible here because every product card
exposes real per-product ABV% AND Size directly (even more directly than
SuperAlko, which had to regex ABV out of the free-text title -- here it's
a clean structured "<Type>, <ABV>%, <Size>" field, see scraper docstring).

EXTENSION BEYOND SUPERALKO -- user-confirmed 2026-07-20 ("Approve as
proposed"), same standing as the core reused rates above:
SuperAlko only had 6 broad categories (strong-alcohol, wine, beer, cider,
long-drinkcocktail, liqueur), so its category->band mapping never had to
handle several Type categories this site actually has:
  - Portvīns / šerijs (port/sherry) and Vermuts / aperitīvs (vermouth/
    aperitif) are fortified/aromatised wines -- classified here as EU
    "intermediate products" (the same starpprodukti band SuperAlko used
    for cocktails), NOT under the flat wine rate, per the standard EU
    excise-directive definition of that category. This is a judgment
    call this build is making, not something the user has confirmed for
    THIS site specifically.
  - Dzirkstošais vīns / Šampanietis (sparkling wine/champagne) are taxed
    at the SAME flat per-product-volume wine rate as still wine -- per a
    2026-07-20 web search of Latvian excise-duty reporting ("for wine,
    which would include sparkling wine, the excise duty will rise..."),
    Latvia does not appear to split sparkling from still wine into a
    separate band the way some other EU countries do. Also not
    previously confirmed by the user for this specific site.
  - "Mini" is a genuinely MIXED Type category on this site (miniature
    wine/sparkling bottles AND miniature spirits like a 0.2L Cognac,
    confirmed live -- see scraper docstring) with no separate sub-type
    field to disambiguate by category name. Banded here per-product by
    measured ABV instead: >=22% ABV -> spirits pure-alcohol formula
    (nothing produced by fermentation alone reaches that ABV), otherwise
    -> flat wine rate. Every "Mini"/"Suvenīri" sample checked live fell
    cleanly on one side of that line (cognac/whisky minis at 33-45%,
    wine/sparkling minis at 11-12%) with nothing in the ambiguous
    15-22% fortified-wine range, but this is a heuristic, not a rate
    the user has explicitly signed off on for this site.
These three bullets reuse REAL, confirmed rate constants, applied to
categories/products SuperAlko's original sign-off never covered -- now
separately approved for this site.

Rates (EUR, from SuperAlko's user-confirmed VID bands, re-verified live
against vid.gov.lv 2025/2026 reporting where checked -- see above):
  - Wine: EUR 134 per 100L of product (flat, not ABV-banded)
  - Fermented beverages (raudzētie dzērieni, i.e. cider here): EUR 77/100L
    product at <=6% ABV, EUR 134/100L product above 6% ABV
  - Intermediate products (starpprodukti, i.e. port/sherry/vermouth/
    cocktails here): EUR 159/100L product at <=15% ABV, EUR 264/100L
    product 15-22% ABV
  - Spirits (stiprie alkoholiskie dzērieni): EUR 1,955 per 100L of PURE
    alcohol (rate * ABV% * volume)
  - Beer: max(9.80 * ABV%, 18.10) per 100L of product

Category is read from the bronze JSON (tagged there by the paired
scraper purely to pick the right tax formula) and dropped before the
final 17-column schema -- it isn't one of the shared columns.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, greatest
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "Spirits & Wine"
LOCAL_CURRENCY = "EUR"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

# Channel is already "N/A" from the scraper -- no slug-to-label mapping needed.
CHANNEL_LABELS = {}

# VID excise rates in EUR -- see module docstring for the source/sign-off
# status (reused from SuperAlko Latvia, re-verified live, but the mapping
# extension below is NOT yet user-confirmed for this specific site).
WINE_RATE_PER_100L_PRODUCT = 134.0
FERMENTED_LOW_RATE_PER_100L_PRODUCT = 77.0    # <=6% ABV
FERMENTED_HIGH_RATE_PER_100L_PRODUCT = 134.0  # >6% ABV
INTERMEDIATE_LOW_RATE_PER_100L_PRODUCT = 159.0   # <=15% ABV
INTERMEDIATE_HIGH_RATE_PER_100L_PRODUCT = 264.0  # 15-22% ABV
SPIRITS_RATE_PER_100L_PURE_ALCOHOL = 1955.0
BEER_RATE_PER_ABV_PER_100L = 9.80
BEER_MIN_RATE_PER_100L = 18.10

# Site's own Category slug (see scraper CATEGORIES dict) -> VID band.
# "spirits"/"beer"/"fermented"/"intermediate"/"wine" map straight to a
# formula; "mini" is resolved per-product by measured ABV instead (see
# _compute_domestic_tax).
SPIRITS_TAX_CATEGORY = "spirits"
BEER_TAX_CATEGORY = "beer"
FERMENTED_TAX_CATEGORY = "fermented"
INTERMEDIATE_TAX_CATEGORY = "intermediate"
WINE_TAX_CATEGORY = "wine"
MINI_TAX_CATEGORY = "mini"
MINI_SPIRITS_ABV_THRESHOLD = 22.0

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site renders plain "99.99 €"/"0.75 €" -- dot-decimal already, no
    thousands separator or Latvian comma-decimal seen anywhere (unlike
    SuperAlko). Still routed through the shared strip-and-cast helper for
    consistency and to defensively handle any stray comma."""
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
        .when(size_lower.contains("l") & ~size_lower.contains("x") & ~size_lower.contains("cl") & ~size_lower.contains("ml"),
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
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    extracted = regexp_extract(product_link_col, r"-(\d{3,})$", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def _extract_abv(abv_col, brandline_col):
    """ABV comes pre-extracted from the scraper's structured
    product-details field. Falls back to re-extracting from Brandline in
    case the bronze field is ever missing, using the same "NN%" pattern."""
    raw = when(abv_col.isNotNull() & (abv_col != ""), abv_col).otherwise(
        regexp_extract(brandline_col, r"(\d+(?:[.,]\d+)?)\s*%", 1)
    )
    return regexp_replace(raw, ",", ".").cast(DoubleType())


def _compute_domestic_tax(category_col, abv_col, size_cl_col):
    """Per-bottle Latvian VID excise duty in EUR. See module docstring for
    the category->band mapping and which parts of it are a reused,
    user-confirmed rate vs. an unconfirmed extension. Returns a
    DoubleType column; the caller casts/formats it to match the shared
    Domestic_Tax string column. Null Size or ABV where the formula needs
    them yields a null tax rather than a wrong number."""
    size_l = size_cl_col / 100.0
    pure_alcohol_l = size_l * (abv_col / 100.0)

    spirits_tax = pure_alcohol_l * (SPIRITS_RATE_PER_100L_PURE_ALCOHOL / 100.0)
    wine_tax = size_l * (WINE_RATE_PER_100L_PRODUCT / 100.0)
    fermented_tax = size_l * (
        when(abv_col > 6.0, FERMENTED_HIGH_RATE_PER_100L_PRODUCT)
        .otherwise(FERMENTED_LOW_RATE_PER_100L_PRODUCT)
    ) / 100.0
    intermediate_tax = size_l * (
        when(abv_col > 15.0, INTERMEDIATE_HIGH_RATE_PER_100L_PRODUCT)
        .otherwise(INTERMEDIATE_LOW_RATE_PER_100L_PRODUCT)
    ) / 100.0
    beer_tax = size_l * greatest(
        abv_col * BEER_RATE_PER_ABV_PER_100L, lit(BEER_MIN_RATE_PER_100L)
    ) / 100.0

    # "Mini" is a genuinely mixed wine/spirits Type category on this site
    # (see docstring) -- resolved per-product by measured ABV rather than
    # by category name: >=22% ABV can only be a distilled spirit (nothing
    # from fermentation alone reaches that), otherwise treat as wine.
    mini_tax = when(abv_col >= MINI_SPIRITS_ABV_THRESHOLD, spirits_tax).otherwise(wine_tax)

    return (
        when(category_col == SPIRITS_TAX_CATEGORY, spirits_tax)
        .when(category_col == BEER_TAX_CATEGORY, beer_tax)
        .when(category_col == FERMENTED_TAX_CATEGORY, fermented_tax)
        .when(category_col == INTERMEDIATE_TAX_CATEGORY, intermediate_tax)
        .when(category_col == WINE_TAX_CATEGORY, wine_tax)
        .when(category_col == MINI_TAX_CATEGORY, mini_tax)
        .otherwise(lit(None).cast(DoubleType()))
    )


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel", "ABV", "Category"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

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
    df = df.withColumn("Size_cl", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size_cl", when(col("Size_cl") == "", None).otherwise(col("Size_cl")))

    df = df.withColumn("ABV_pct", _extract_abv(col("ABV"), col("Brandline")))

    df = df.withColumn(
        "Domestic_Tax_num",
        _compute_domestic_tax(col("Category"), col("ABV_pct"), col("Size_cl")),
    )
    # Shared schema column is string/null (see references/schema.md) --
    # round to 2dp and cast, keeping the underlying number auditable.
    df = df.withColumn(
        "Domestic_Tax",
        col("Domestic_Tax_num").cast("decimal(10,2)").cast(StringType()),
    )

    # Site is Latvian-language by default with no per-product translation
    # needed for these fields (Type/ABV/Size are all parsed structurally,
    # not by matching Latvian label text) -- no ai_translate step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer -- plain Country, no "DF " prefix (GTR-only).
    df = df.withColumnRenamed("Size_cl", "Size")
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))

    # No GTR/travel-retail-exclusivity concept found anywhere on this site
    # (see scraper module docstring) -- the scraper never sets this key, so
    # it's already null for every row after the ensure-columns-exist
    # backfill above. Leave as true null, not "No".

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw", "ABV", "ABV_pct",
                  "Category", "Domestic_Tax_num")

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/spiritsandwine_latvia/*/*/*/*.json"
    clean(spark, bronze_path)
