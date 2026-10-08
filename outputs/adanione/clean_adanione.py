"""
Cleaner for Adanione (Mumbai airport duty free, Arrival store), the silver
step paired with adanione_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_adanione.py once validated.

GTR retailer. This is the duty-free pre-order storefront for Mumbai
International Airport (BOM), run on the Adani One app/site. Retailer =
"Adanione" (user-confirmed 2026-10-01). Country "India" from the scraper
becomes "DF India", applied AFTER the FX call (see below). Domestic_Tax is
null by definition (GTR).

Channel: "Mumbai International Airport (BOM)" (user-confirmed 2026-10-01).
Only the Arrival store is scraped, and Departure is out of scope, so the
Channel carries no store suffix.

Price_Discounted is the price shown on the listing card. For most SKUs that
is the pre-order price, which takes an extra 10% off the in-store discounted
price. The user confirmed this is the price to capture.

Currency: INR (prices shown as "₹3,26,700", Indian lakh grouping). The
scraper already strips them to plain digits. Converted via the shared
ExchangeRate_cleaning() like every other cleaner.

Brand: the scraper lands the site's internal brand slug ("royal-salute",
"jack-daniel-s"). About 1 in 6 slugs don't prefix the product name. Most are
harmless ("the-glenlivet" naming, apostrophes), but some are owner or
importer slugs ("moet-hennessy" on Ardbeg, "beam-suntory" on Yamazaki/Toki,
"gran-cru-club-private-limited" on Bordeaux wines) or typos ("avitation",
"longitute-77"). _resolve_brand() handles these in order:
  1. Find the slug's words inside the product name and use the name's own
     spelling ("jack-daniel-s" + "Jack Daniel's Tennessee 100cl" ->
     "Jack Daniel's").
  2. Explicit override for a known-bad slug (BRAND_SLUG_OVERRIDES).
  3. Known owner/importer slug: take the brand from the start of the name
     (NAME_PREFIX_BRANDS, else the first word after "The"/"Suntory").
  4. Otherwise title-case the slug.
Brandline is the product name with the brand words and the trailing size
removed. When nothing is left ("Cointreau 100cl"), it falls back to the
Brand itself. Bordeaux wines under the importer slug gran-cru-club-private-limited
(10 SKUs on 2026-10-01, names like "RD BORDEAUX CHATEAU BRANAIRE DUCRU 2014
75 CL") have no reliable brand in either field, so Brand is left null there.
The full name stays in Brandline.

GTR_exclusive: real per-product concept (API isExclusive). The scraper
emits "Exclusive" or "", so the template's .contains("exclusive") mapping to
Yes/No applies as-is.
"""

import re

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number, concat, udf
from pyspark.sql.types import StringType, DoubleType, StructType, StructField
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "GTR"
RETAILER = "Adanione"
LOCAL_CURRENCY = "INR"

EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {
    "arrival": "Mumbai International Airport (BOM)",
}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]

# Slugs that are misspelled or don't appear in the product name at all.
BRAND_SLUG_OVERRIDES = {
    "avitation": "Aviation",
    "longitute-77": "Longitude 77",
    "sheildaig": "Shieldaig",
    "lebenon": "Chateau Musar",
    "veuve-clicquot-ponsardin-vcp": "Veuve Clicquot",
    "j-b": "J&B",
    "pimm-s-no-1": "Pimm's",
    "fino-tequila": "Fino",
    "1800-tequila": "1800",
}

# Slugs that name the owner/importer/region rather than the brand, so the
# brand has to come from the product name instead.
OWNER_SLUGS = {
    "beam-suntory", "suntory-global-spirits", "pernod-ricard", "moet-hennessy",
    "remy-martin", "remy-cointreau", "glengoyne", "bordeaux", "rv", "mezcal",
}
# No reliable brand in either field (see module docstring) -> null Brand.
UNRESOLVABLE_SLUGS = {"gran-cru-club-private-limited"}

# Multi-word brands seen at the start of names under an owner slug.
NAME_PREFIX_BRANDS = ["Jim Beam", "Bodegas Chateau Siran", "Aime Arnoux", "400 Conejos"]
LEADING_NOISE = {"the", "suntory"}

_TRAILING_SIZE = re.compile(
    r"[\s,]*(?:\d+\s*x\s*)?\d+(?:\.\d+)?\s*(?:cl|ml|ltr|l)\b\.?\s*$", re.IGNORECASE
)


def _norm(token):
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _slug_words(slug):
    # "jack-daniel-s" -> ["jack", "daniels"] so it matches "Jack Daniel's".
    words = [w for w in slug.lower().split("-") if w]
    merged = []
    for w in words:
        if w == "s" and merged:
            merged[-1] += "s"
        else:
            merged.append(w)
    return merged


def _tidy_case(text):
    return text.title() if text.isupper() else text


def _strip_size(text):
    return _TRAILING_SIZE.sub("", text).strip(" ,-")


def _resolve_brand(slug, name):
    """Returns (Brand, Brandline). Pure Python so it can be unit-tested
    without Spark. See the module docstring for the resolution order."""
    name = (name or "").strip()
    slug = (slug or "").strip().lower()
    tokens = name.split()
    norms = [_norm(t) for t in tokens]

    if not slug or slug in UNRESOLVABLE_SLUGS:
        return None, _strip_size(name) or None

    # 1. Slug words found as a contiguous run in the name. Tokens that
    #    normalise to "" (like "&" in "Moet & Chandon") are skipped while
    #    matching but kept in the output span.
    want = _slug_words(slug)
    for start in range(len(tokens)):
        i, j = start, 0
        while i < len(tokens) and j < len(want):
            if norms[i] == "":
                i += 1
                continue
            # A trailing possessive "s" is tolerated, so slug "remy-martin"
            # matches "Remy Martin's".
            if norms[i] != want[j] and not (j == len(want) - 1 and norms[i] == want[j] + "s"):
                break
            i += 1
            j += 1
        if j == len(want) and norms[start] != "":
            brand = _tidy_case(" ".join(tokens[start:i]).strip(" ,"))
            rest = " ".join(tokens[:start] + tokens[i:])
            if start == 0 or all(n in LEADING_NOISE for n in norms[:start]):
                rest = " ".join(tokens[i:])
            return brand, _strip_size(rest) or brand

    # 2. Known-bad slug.
    if slug in BRAND_SLUG_OVERRIDES:
        brand = BRAND_SLUG_OVERRIDES[slug]
        rest = re.sub(re.escape(brand), " ", name, count=1, flags=re.IGNORECASE)
        return brand, _strip_size(" ".join(rest.split())) or brand

    # 3. Owner/importer slug: brand from the start of the name.
    if slug in OWNER_SLUGS:
        for prefix in NAME_PREFIX_BRANDS:
            if name.lower().startswith(prefix.lower()):
                return prefix, _strip_size(name[len(prefix):]) or prefix
        k = 0
        while k < len(tokens) - 1 and norms[k] in LEADING_NOISE:
            k += 1
        if tokens:
            brand = _tidy_case(tokens[k].strip(" ,"))
            return brand, _strip_size(" ".join(tokens[k + 1:])) or brand

    # 4. Fall back to the slug itself.
    brand = " ".join(w.capitalize() for w in slug.split("-"))
    return brand, _strip_size(name) or brand


_brand_schema = StructType([
    StructField("Brand", StringType()),
    StructField("Brandline", StringType()),
])
_resolve_brand_udf = udf(lambda slug, name: _resolve_brand(slug, name), _brand_schema)


def _fix_price(price_col):
    """The scraper already strips "₹" and the lakh-grouping commas
    ("₹3,26,700" -> "326700"). This just guards against any leftover
    symbol. INR has no decimal-comma format, so no European branch here."""
    return regexp_replace(price_col, r"[^\d.]", "").cast(DoubleType())


def _normalize_size_to_cl(size_col):
    """Raw sizes are the API's unitSize: "700 ml", "1 ltr", "1.75 ltr",
    "50 ml". Twin packs report total pack volume ("2 ltr" for 2x1L),
    matching the pack price. "ltr" is collapsed to "l" and spaces removed
    before the standard cl/ml/l conversion."""
    size_lower = regexp_replace(regexp_replace(lower(size_col), "ltr", "l"), r"\s+", "")
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
    """Fallback only. unitSize was populated on every SKU on 2026-10-01.
    Product names carry the size too ("..., 70CL", "100cl", "75 Cl")."""
    return regexp_extract(text_col, r"(?i)(\d+(?:\.\d+)?\s*(?:cl|ml|ltr|l)\b)", 1)


def _extract_id_from_link(product_link_col):
    """Fallback only. ID_raw is the link's last path segment, an
    alphanumeric SKU code like "02N03220", not a digit run, so the
    template's digits regex would truncate it. Take the last segment."""
    extracted = regexp_extract(product_link_col, r"/([^/?]+)/?(?:\?.*)?$", 1)
    return when(extracted != "", extracted).otherwise(product_link_col)


def clean(spark, bronze_path: str, silver_table: str = SILVER_TABLE):
    df = spark.read.json(bronze_path)

    dedup_cols = [c for c in df.columns if c != "Scraped_At"]
    # Among rows identical in every column except Scraped_At (i.e. a
    # reconfirmed-unchanged product across multiple bronze scrapes),
    # dropDuplicates() picks an arbitrary survivor -- in practice the
    # oldest, since Spark tends to process the date-partitioned bronze
    # glob in path order. Order by Scraped_At desc and take rank 1 so
    # the most recently confirmed timestamp survives instead.
    _content_window = Window.partitionBy(*dedup_cols).orderBy(col("Scraped_At").desc())
    df = df.withColumn("_content_rn", row_number().over(_content_window)).filter(col("_content_rn") == 1).drop("_content_rn")

    for c in ["Product_link", "ID_raw", "Brand", "Brandline", "Size",
              "Strike Price", "Price Discounted", "GTR_exclusive",
              "Country", "Channel"]:
        if c not in df.columns:
            df = df.withColumn(c, lit(None).cast(StringType()))

    # ID_raw = last path segment of the card's product link (e.g.
    # ".../p/ardmore-triplewood-100cl/02N03220" -> "02N03220"), which is
    # the site's own SKU code.
    df = df.withColumn(
        "ID",
        when(col("ID_raw").isNotNull() & (col("ID_raw") != ""), col("ID_raw"))
        .otherwise(_extract_id_from_link(col("Product_link"))),
    )

    df = df.withColumn("Strike_Price", _fix_price(col("Strike Price")))
    df = df.withColumn("Price_Discounted", _fix_price(col("Price Discounted")))
    # Backfill each price from the other when only one parsed, so a good
    # price never ships null. A genuine discount (both populated) or a
    # priceless row (both null, destined for the DLQ) is left untouched.
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

    # Size from the API's unitSize, falling back to the product name.
    # Computed BEFORE Brandline is trimmed below, which strips the size text.
    size_or_fallback = when(
        col("Size").isNotNull() & (col("Size") != ""), col("Size")
    ).otherwise(_extract_size_from_text(col("Brandline")))
    df = df.withColumn("Size", _normalize_size_to_cl(size_or_fallback))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Brand slug + product name -> real Brand and trimmed Brandline.
    df = df.withColumn("_bb", _resolve_brand_udf(col("Brand"), col("Brandline")))
    df = df.withColumn("Brand", col("_bb.Brand")).withColumn("Brandline", col("_bb.Brandline")).drop("_bb")

    # Site is in English, so no ai_translate step needed.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    df = df.withColumn("Domestic_Tax", lit(None).cast(StringType()))

    # GTR_exclusive: real per-product concept (API isExclusive). The
    # scraper emits "Exclusive" or "" (never None), so this always resolves
    # to the Yes/No branch for this site.
    site_has_exclusivity_concept = df.filter(col("GTR_exclusive").isNotNull()).limit(1).count() > 0
    if site_has_exclusivity_concept:
        df = df.withColumn(
            "GTR_exclusive",
            when(lower(col("GTR_exclusive")).contains("exclusive"), lit("Yes")).otherwise(lit("No")),
        )
    else:
        df = df.withColumn("GTR_exclusive", lit(None).cast(StringType()))

    # FX conversion joins on the plain Country name ("India"), so the "DF "
    # prefix must come AFTER this call, never before.
    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/adanione/*/*/*/*.json"
    clean(spark, bronze_path)
