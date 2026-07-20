"""
Cleaner for Licoreria Disenzo (Peru) - the silver step paired with
licoreria_disenzo_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_licoreria_disenzo.py once validated.

Domestic retailer (legal entity "Inversiones Javic S.A.C.", trading as
"Disenzo") - Country is the plain country name ("Peru"), no "DF " prefix.

Domestic_Tax - researched 2026-07-20, read directly from SUNAT's own
Nuevo Apendice IV (TUO de la Ley del IGV e ISC, consolidated by DL 1644,
pub. 13.9.2024; rates via RM 030-2024-EF/15, eff. 1.3.2024). Peru's ISC
uses a "greater of a flat soles-per-liter amount OR an ad-valorem %"
rule, tiered by an ABV *band* (0-6 deg=20%, >6-12 deg=25%, >12-20 deg=30%,
>20 deg=40%) - in practice the ad-valorem side almost always governs at
real retail price points, so this cleaner uses the ad-valorem % as an
ad-valorem STRING for most categories.

Two categories get a computed absolute PEN amount instead (pattern (b),
using each product's real Size):
  - Piscos: DS 104-2004-EF art. 2 explicitly excludes Pisco (HS
    2208.20.21.00) from the ad-valorem system entirely - it pays ONLY a
    flat S/2.48 per liter, confirmed against the named primary decree.
  - Cervezas Artesanales / Cervezas Industriales (beer): TENTATIVE, not
    fully confirmed - sources conflict on the exact current figure
    (DS 014-2024-EF staged increases to S/2.51, but DS 115-2024-EF
    appears to have repealed the second step, implying S/2.41 persisted;
    could not reconcile from secondary sources alone). Using S/2.41 as
    the more likely current figure per the repeal reading, flagged as
    unconfirmed rather than treated as solid.

Wine categories (Cabernet/Espumosos/Tintos/Rosados/Blancos/Naturales/
Dulces) assumed 12% ABV -> 6-12 deg band -> "25%" (Espumosos/sparkling is
boundary-sensitive against the 12-20 deg band depending on real ABV, not
independently re-checked here).

Spirit categories (Whiskys/Cognacs y Brandys/Rones/Ginebras/Vodkas/
Tequilas y Mezcales) assumed >20% ABV -> "40%".

Liqueur-type categories split by real-world typical ABV rather than
lumped together: Cremas de Licor (cream liqueurs, e.g. Baileys-style,
typically ~17% ABV) and Vermouths (a fortified wine, typically 15-18%
ABV) -> 12-20 deg band -> "30%"; Otros Licores/Macerados (more variable,
often higher-proof spirit-based liqueurs) -> assumed >20% -> "40%".

Sake (FutsuShu/Junmai): TENTATIVE "30%" (assumed 12-20 deg band, typical
real sake ABV 13-16%) - no established project convention existed for
sake before this build, flagged as an open question rather than a
confirmed answer.

RTD and Packs y Combos: DELIBERATELY LEFT NULL. RTD's real ABV varies
too widely (4.5-8%) to land in one band; Packs y Combos are mixed
bundles of different underlying products with no single applicable
rate - both would need per-product decomposition this scraper doesn't
do, so left honestly null rather than guessed.

See project_peru_tax_research.md for full sourcing detail.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "Licoreria Disenzo"
LOCAL_CURRENCY = "PEN"

# Domestic_Tax rate structure - see module docstring for sourcing.
_WINE_25PCT = {"Cabernet", "Espumosos", "Tintos", "Rosados", "Blancos", "Naturales", "Dulces"}
_SPIRIT_40PCT = {"Whiskys", "Cognacs y Brandys", "Rones", "Ginebras", "Vodkas", "Tequilas y Mezcales"}
_LIQUEUR_40PCT = {"Otros Licores", "Macerados"}
_LIQUEUR_30PCT = {"Cremas de Licor", "Vermouths"}
_SAKE_30PCT_TENTATIVE = {"FutsuShu", "Junmai"}
_PISCO_RATE_PER_CL = 2.48 / 100  # S/2.48 per liter
_BEER_RATE_PER_CL_TENTATIVE = 2.41 / 100  # S/2.41 per liter, unconfirmed - see docstring
_BEER_CATEGORIES = {"Cervezas Artesanales", "Cervezas Industriales"}

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "S/.28.00" or "S/.1,250.00" - Peruvian Sol,
    comma as thousands separator, DOT as the decimal separator (the
    opposite convention from several other retailers in this repo, e.g.
    Kings Suriname's dot-thousands/comma-decimal SRD format). Strip the
    currency symbol/whitespace and thousands commas, keep the decimal
    dot, then cast to double."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    cleaned = regexp_replace(cleaned, ",", "")
    return when(cleaned == "", lit(None).cast(DoubleType())).otherwise(cleaned.cast(DoubleType()))


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
    """No dedicated Size field on the listing card - every product title
    carries size at the end (e.g. "Vino Vina Albali Tempranillo Seleccion
    750 ml", "Cerveza ACDC Rock or Bust en lata 568 ml", "Ginebra MG
    Paradiso 700 ml"). A real "Tamano" (Size) spec field exists on each
    product's own detail page but wasn't scraped here - see scraper
    module docstring. Pack products (e.g. "Pack Chivas Regal 12 anos:
    700 ml + 200 ml") carry TWO sizes in the title; this regex takes the
    first match only, same known limitation as every other title-parsed
    Size field in this repo."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _domestic_tax(category_col, size_cl_col):
    """Peru ISC - see module docstring. Most categories get an
    ad-valorem % string; Pisco and Beer (tentative) get a computed
    absolute PEN amount from their real Size; RTD/Packs y Combos fall
    through to null."""
    pisco_amount = (size_cl_col * lit(_PISCO_RATE_PER_CL)).cast("decimal(10,2)").cast(StringType())
    beer_amount = (size_cl_col * lit(_BEER_RATE_PER_CL_TENTATIVE)).cast("decimal(10,2)").cast(StringType())

    result = lit(None).cast(StringType())
    result = when(category_col.isin(*_WINE_25PCT), lit("25%")).otherwise(result)
    result = when(category_col.isin(*_SPIRIT_40PCT), lit("40%")).otherwise(result)
    result = when(category_col.isin(*_LIQUEUR_40PCT), lit("40%")).otherwise(result)
    result = when(category_col.isin(*_LIQUEUR_30PCT), lit("30%")).otherwise(result)
    result = when(category_col.isin(*_SAKE_30PCT_TENTATIVE), lit("30%")).otherwise(result)
    result = when(category_col == "Piscos", pisco_amount).otherwise(result)
    result = when(category_col.isin(*_BEER_CATEGORIES), beer_amount).otherwise(result)
    # RTD / Packs y Combos (or anything unrecognized) fall through to
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

    # ID_raw is the retailer's own per-SKU code pulled from each card's
    # add-to-cart `data-product_sku` attribute (e.g. "VIN583", "CERV44") -
    # falls back to the WordPress internal numeric product id
    # (`data-product_id`/`data-pid`) only if a SKU is genuinely absent.
    # Falls back further to Product_link so a genuinely priced row still
    # gets a usable, stable identifier instead of being dropped, same
    # fallback pattern used by GMP Abu Dhabi/Le Bon Macau/sieuthiruoungoai.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(col("Product_link")),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # No dedicated Size field on the listing card - always falls back to
    # the title regex.
    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is Spanish-only; product titles are brand names/spirit terms
    # as-is (e.g. "Ginebra MG Paradiso", "Whisky Something Special") - no
    # ai_translate step used.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer - Country is the plain name ("Peru"), no "DF "
    # prefix (that prefix is GTR-only per the schema).
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", _domestic_tax(col("Category"), col("Size")))
    # No exclusivity badge, ribbon, or "exclusivo"/"exclusive" text found
    # anywhere on this site (only a generic "Oferta!" on-sale ribbon,
    # already captured via Strike_Price/Price_Discounted) - the scraper
    # never sets this key, so it's already null for every row after the
    # ensure-columns-exist backfill above.

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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/licoreria_disenzo/*/*/*/*.json"
    clean(spark, bronze_path)
