"""
PySpark cleaner template — the "silver" step of the GTR_Pricing pipeline.
Reads a retailer's bronze JSON, standardizes it onto the shared 17-column
schema (see references/schema.md), converts currency via the shared FX
utility, and MERGEs into the shared gtr_silver_master Delta table.

Copy this into GTR_Pricing/silver_scripts/clean_<retailer>.py and fill in
the TODOs. Two real cleaners to compare against depending on shape:
  - clean_cloud9_laos.py    — single country/channel, both fixed literals
  - clean_dufry_europe.py   — many countries/channels, both read per-row
    from the bronze JSON (tagged there by the paired scraper) instead of
    being hardcoded — this template follows that pattern since it works
    for the single-location case too (every row just carries the same
    value), and is a smaller diff if the retailer later grows locations.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

# TODO: fill these in for the retailer being cleaned — see references/schema.md
# MARKET: "GTR" if "duty free"/"travel retail"/"bordershop" (or local-language
# equivalents) show up repeatedly across the site's own branding/copy. If the
# site never says either and you're not confident, STOP and ask the user to
# confirm before setting this — don't guess, it drives the Domestic_Tax
# decision below too.
MARKET = "TODO"          # "GTR" or "Domestic"
RETAILER = "TODO"
LOCAL_CURRENCY = "TODO"  # ISO code as it appears on the site, e.g. "LAK".
                          # If currency varies by Country/Channel (e.g. Dufry
                          # Europe), replace the single Currency withColumn
                          # below with a when/otherwise chain keyed on
                          # Country/Channel instead — see clean_dufry_europe.py.

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

# TODO: if this site's raw Channel is an airport/branch slug (e.g. "zurich"),
# map it to a human-readable label here, the way clean_dufry_europe.py does:
#   "zurich" -> "Zurich International Airport (ZRH)"
# Leave this dict empty (falls through to the raw value unchanged) for
# single-location retailers where Channel is already "N/A" or similarly final.
CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Strip currency symbols and handle both thousands-comma and
    European decimal-comma formats. TODO: adjust the symbol strip regex
    if this site uses a currency symbol other than what's already covered
    by [^\\d.,] (e.g. multi-character symbols)."""
    cleaned = regexp_replace(price_col, r"[^\d.,]", "")
    is_european_decimal = cleaned.rlike(r"^\d+,\d{2}$")
    return (
        when(is_european_decimal, regexp_replace(cleaned, ",", ".").cast(DoubleType()))
        .otherwise(regexp_replace(cleaned, ",", "").cast(DoubleType()))
    )


def _normalize_size_to_cl(size_col):
    """TODO: this default handles cl/ml/L suffixes; extend if this site uses
    a different unit or a combined size+pack format (e.g. "6 x 750ml")."""
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
    """Pulls a size-looking substring (e.g. "750ml", "70cl", "1L") out of
    free text such as Brandline/the product name — used when a site doesn't
    expose Size as its own field but the bottle size is embedded in the
    product title instead (e.g. "Johnnie Walker Black Label 750ml"). TODO:
    extend the unit list if this site uses something beyond cl/ml/l."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Falls back to pulling a numeric-ID-looking substring out of the
    product URL when the site doesn't expose an explicit SKU/product ID —
    several existing cleaners extract the ID this way (see webscraping's
    "Product ID (numeric digits extracted)" convention). Falls back to the
    full link if no digit run is found. TODO: adjust the regex if this
    site's ID is a non-numeric slug rather than a run of digits."""
    extracted = regexp_extract(product_link_col, r"(\d{4,})", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    # Volume anomaly detection (check_volume_anomaly from
    # volume_anomaly_detection.py) is available but optional — wire it in
    # here only if this retailer's row count is unpredictable enough to
    # warrant it. Not required for every new cleaner.

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    df = df.dropDuplicates(dedup_cols)

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # Prefer a retailer-native numeric SKU ID (ID_raw) if the site exposes
    # one — it survives a product URL changing. If it doesn't, don't just
    # fall back to the whole Product_link: pull the numeric-ID-looking part
    # out of the URL first (_extract_id_from_link), and only use the full
    # link as a last resort if no such substring exists.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))

    # If the site doesn't expose Size as its own field, the bottle size is
    # often embedded in Brandline/the product name instead — fall back to
    # extracting it from there before normalizing to cl.
    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # TODO: only needed if the scraper couldn't get this site into English
    # (no in-page language switcher, Chrome auto-translate didn't stick —
    # see scraper_template.py). Databricks' built-in ai_translate runs
    # on-cluster via a foundation model, no external package/network call
    # needed — see clean_hyundai_duty_free_korea.py for the reference.
    # Must run AFTER Size has already been extracted from Brandline above —
    # translating first could turn a recognizable "750ml"/"70cl" into
    # something the cl/ml/l regex in _extract_size_from_text no longer matches.
    # from pyspark.sql.functions import expr
    # df = df.withColumn("Brand", expr("ai_translate(Brand, 'en')"))
    # df = df.withColumn("Brandline", expr("ai_translate(Brandline, 'en')"))

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))

    # Country/Channel are read per-row from the bronze JSON (the paired
    # scraper tags every row with these, even for a single-location
    # retailer) rather than hardcoded here — this is what lets a retailer's
    # cleaner handle multiple countries/airports without special-casing.
    # GTR retailers get a "DF <Country>" prefix (e.g. "DF Czech Republic")
    # to distinguish duty-free pricing from a domestic entry for the same
    # country in the exchange-rate reference file — matches the convention
    # already used elsewhere in this pipeline (e.g. "DF Andorra"). Domestic
    # retailers keep the plain country name.
    if MARKET == "GTR":
        df = df.withColumn("Country", concat(lit("DF "), col("Country")))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))

    # TODO: if this site's prices are already in the reporting currency for
    # every row (single fixed currency), this literal is enough. If currency
    # varies by Country/Channel instead, replace it with a when/otherwise
    # chain — see clean_dufry_europe.py's Armenia-default/Zurich-CHF-override
    # pattern for the shape to copy.
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))

    # TODO: if MARKET == "Domestic", don't just leave this null by default —
    # look up that country's consumer alcohol excise/duty tax rate(s) (they
    # typically differ by beverage type: spirits/wine/beer usually have
    # different rates) and propose the figure(s) to the user for sign-off
    # before hardcoding a value here. For "GTR" retailers, null is correct
    # as-is — duty-free prices are pre-tax by definition.
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))

    # GTR_exclusive is three-way, not a boolean — see references/schema.md:
    # "Yes" if this product carries the site's own exclusivity tag, "No" if
    # the site tracks the concept but doesn't flag this particular SKU, and
    # true null if the whole site never mentions GTR-exclusivity anywhere
    # (no badge/ribbon, no "Exclusives" category). A retailer either tracks
    # this concept for every product or not at all, so tell the two cases
    # apart by whether ANY row ever got a real (non-null) raw value — the
    # scraper should set a real string (blank "" default) per row when the
    # site has the concept, and leave the field as Python None everywhere
    # when it doesn't (see scraper_template.py's GTR_exclusive TODO).
    # TODO: adjust the "exclusive" substring check if this site's raw signal
    # text doesn't literally contain that word (e.g. a bare "true"/"1" flag).
    site_has_exclusivity_concept = df.filter(col("GTR_exclusive").isNotNull()).limit(1).count() > 0
    if site_has_exclusivity_concept:
        df = df.withColumn(
            "GTR_exclusive",
            when(lower(col("GTR_exclusive")).contains("exclusive"), lit("Yes")).otherwise(lit("No")),
        )
    else:
        df = df.withColumn("GTR_exclusive", lit(None).cast(StringType()))

    # Convert local-currency prices into the IWSR reporting currency via the
    # shared FX lookup keyed by Country. Always use this shared utility —
    # don't write new conversion logic per retailer. Skip this call entirely
    # only if this site's prices are already in the reporting currency for
    # its market (e.g. Singapore Changi skips it because SGD already is the
    # reporting currency there) — document that exception here if it applies.
    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw")

    bad_rows_cond = (col("ID").isNull()) | (col("ID") == "") | (col("Strike_Price").isNull() & col("Price_Discounted").isNull())
    df_dlq = df.filter(bad_rows_cond)
    df_clean = df.filter(~bad_rows_cond)

    # Keep only the most recently scraped snapshot per merge key — multiple
    # bronze scrapes in the same reporting month would otherwise present as
    # multiple source rows matching one MERGE target key.
    dedup_window = Window.partitionBy("Product_link", "Channel", "Retailer", "ID", "Year", "Month").orderBy(col("Scraped_At").desc())
    df_clean = df_clean.withColumn("_rn", row_number().over(dedup_window)).filter(col("_rn") == 1).drop("_rn")

    try:
        if df_dlq.count() > 0:
            dlq_path = silver_table + "_dlq"
            # Cast to string so this shared, cross-site DLQ table's schema
            # can't fail Delta's mergeSchema on a type mismatch between sites.
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
    # TODO: set to this retailer's actual bronze path from the scraper.
    bronze_path = f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/TODO_retailer_slug/*/*/*/*.json"
    clean(spark, bronze_path)
