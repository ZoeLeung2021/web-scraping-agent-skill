"""
Cleaner for Siêu Thị Rượu Ngoại (Vietnam) — the silver step paired with
sieuthiruoungoai_scraper.py.

DEPLOY TARGET: copy this file to
GTR_Pricing/silver_scripts/clean_sieuthiruoungoai.py once validated.

Domestic retailer — Country is "Vietnam" (plain name, no "DF " prefix —
see scraper module docstring: no duty-free/traveler language anywhere on
the site, ordinary wholesale/retail liquor business with a showroom in
Ho Chi Minh City and nationwide delivery).

Domestic_Tax: Vietnam's Special Consumption Tax (Thuế tiêu thụ đặc biệt)
on alcohol under Law No. 66/2025/QH15, effective 2026-01-01, is an
ad-valorem rate string (no FX conversion — VND already matches the
site's own currency):
  - Spirits/wine/beer >= 20% ABV: "65%"
  - Spirits/wine/beer < 20% ABV: "35%"
User-approved research; see project memory (project_sieuthiruoungoai /
Domestic_Tax follow-up) for the sign-off.

Applied per the site's own 14 scraped Category values (see CATEGORIES in
the scraper module):
  - Reliably >=20% ABV categories mapped straight to "65%": Cognac,
    Blended Scotch Whisky, Single Malt Whisky, Brandy, Vodka, Spirits,
    Chinese liquor, Vietnamese liquor.
  - Reliably table-strength categories mapped straight to "35%": Wine,
    Champagne.
  - "Gin-Tequila-Liqueur" mixes >=20% ABV gin/tequila with often-<20%
    ABV liqueurs — classified by scanning Brandline for liqueur-brand/
    generic-liqueur keywords (-> "35%"), defaulting to "65%" (gin/
    tequila, the category's namesake majority) otherwise.
  - "Miniatures", "Clearance", and "Rare/unique bottles" are real
    cross-cutting buckets mixing many underlying spirit/wine types (not
    one alcohol type) — classified by scanning Brandline for keywords
    of the ACTUAL underlying type (cognac/whisky/vodka/brandy/gin/
    tequila/rum/Chinese-liquor -> "65%"; wine/champagne/liqueur ->
    "35%"). Rows with no keyword match are left null (honest
    insufficient-data, not a guess) — real, expected for this category
    per a live scrape (see _tax_mixed_category / keyword lists below):
    ~44% of "Rare/unique bottles" rows are decorative zodiac-
    animal decanters whose title never states the underlying spirit at
    all, vs. ~90-100% coverage on Gin-Tequila-Liqueur/Miniatures/
    Clearance.
  - An explicit "<size>/<NN>%" ABV token in Brandline (seen on some
    Gin-Tequila-Liqueur listings, e.g. "700ml/38%"), when present, is
    used directly ahead of any keyword and overrides the category
    default/keyword result for these four Brandline-classified
    categories.

Known limitation (kept as specified, flagged rather than silently
"fixed"): the generic "liqueur" keyword is a heuristic, not a per-SKU
ABV lookup — a small number of real products branded with the word
"Liqueur"/"Rượu mùi" are actually >=20% ABV (e.g. "Ancho Reyes ...Chili
Liqueur" ~40% ABV, "Kinmen Royal Liqueur" kaoliang ~38%+ ABV) and get
classified "35%" by this rule when "65%" would be the true rate. Same
caveat in reverse does not appear in the sampled data (no observed <20%
ABV product without a liqueur-style keyword).
"""

import re

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_extract, regexp_replace, when, lit, to_timestamp, year, date_format, lower, row_number
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from delta.tables import DeltaTable

from ExRate_Cleaning_fx import ExchangeRate_cleaning

MARKET = "Domestic"
RETAILER = "Siêu Thị Rượu Ngoại"
LOCAL_CURRENCY = "VND"

# ---------------------------------------------------------------------------
# Domestic_Tax — Vietnam Special Consumption Tax on alcohol, Law No.
# 66/2025/QH15 (effective 2026-01-01): "65%" for spirits/wine/beer >=20%
# ABV, "35%" for <20% ABV. See module docstring for the full mapping and
# real-Brandline-sample validation notes.

CATEGORY_TAX_65 = {
    "Cognac", "Blended Scotch Whisky", "Single Malt Whisky", "Brandy",
    "Vodka", "Spirits", "Chinese liquor", "Vietnamese liquor",
}
CATEGORY_TAX_35 = {"Wine", "Champagne"}
CATEGORY_GIN_TEQUILA_LIQUEUR = "Gin-Tequila-Liqueur"
CATEGORY_MIXED = {"Miniatures", "Clearance", "Rare/unique bottles"}

# Liqueur-brand / generic-liqueur keywords — English/French liqueur brand
# names plus real-data additions found scraping live Gin-Tequila-Liqueur/
# Miniatures/Clearance/Rare-unique-bottles pages (vermouth/aperitivo
# brands, umeshu/plum-wine terms) that the originally-given illustrative
# list didn't cover. Known limitation: a handful of real products branded
# "Liqueur" are actually >=20% ABV (Ancho Reyes Chili Liqueur ~40%, Kinmen
# Royal Liqueur kaoliang ~38%+) and will be misclassified "35%" by this
# heuristic — flagged, not silently patched, since it's the exact
# brandline-keyword approach specified for this build.
LIQUEUR_KEYWORDS = [
    "baileys", "bailey's", "kahlua", "cointreau", "amaretto", "disaronno",
    "sambuca", "chartreuse", "grand marnier", "frangelico", "drambuie",
    "southern comfort", "midori", "curacao", "curaçao", "triple sec",
    "limoncello", "schnapps", "liqueur", "rượu mùi",
    "vermouth", "cinzano", "carpano", "noilly-prat", "noilly prat",
    "umeshu", "rượu mơ",
]
# Gin/tequila brand keywords — used only as documentation/consistency for
# the mixed categories below; Gin-Tequila-Liqueur itself defaults to 65%
# whenever no liqueur keyword hits, so it doesn't need these explicitly.
GIN_KEYWORDS = [
    "gin", "bombay", "beefeater", "hendrick", "tanqueray", "citadelle",
    "four pillars", "gunpowder",
]
TEQUILA_KEYWORDS = [
    "tequila", "patron", "patrón", "jose cuervo", "don julio", "1800",
    "gran centenario", "maestro dobel", "clase azul", "codigo", "código",
    "montelobos",
]
# Underlying-type keyword buckets for the three cross-cutting "mixed"
# categories (Miniatures, Clearance, Rare/unique bottles) — each real
# product there is actually one of these types, just not filed under its
# type category. Real-data additions beyond the illustrative list are
# noted inline; found scraping live sample pages of all three categories
# (and Gin-Tequila-Liqueur) via the WSL Selenium harness.
COGNAC_KEYWORDS = [
    "cognac", "hennessy", "remy martin", "rémy martin", "martell",
    "courvoisier", "camus", "otard", "meukow",
]
WHISKY_KEYWORDS = [
    "whisky", "whiskey", "scotch", "bourbon", "chivas", "jack daniel",
    "johnnie walker", "macallan", "glenfiddich", "ballantine", "jim beam",
    "jameson", "glenlivet", "dewar",
    "jw", "white horse", "crown royal", "john walker", "balvenie",
    "lagavulin", "royal salute", "nikka", "aberfeldy", "ardbeg",
    "glenmorangie", "highland park", "single malt", "haig", "bernheim",
    "westward",
]
VODKA_KEYWORDS = ["vodka", "smirnoff", "absolut", "grey goose", "belvedere", "ciroc"]
BRANDY_KEYWORDS = [
    "brandy", "armagnac", "st-remy", "st-rémy", "st rémy", "napoleon",
]
RUM_KEYWORDS = ["rum", "rượu rum", "captain morgan", "mount gay", "cachaca", "cachaça"]
CHINESE_LIQUOR_KEYWORDS = ["mao tai", "moutai", "baijiu", "guojiao"]
WINE_KEYWORDS = [
    "vang", "wine", "champagne", "prosecco", "sparkling", "rượu vang",
    "cabernet", "sauvignon", "merlot", "chardonnay", "pinot", "shiraz",
    "riesling", "malbec", "rose wine", "rosé",
]

# Short tokens that need a regex word boundary to avoid matching inside
# an unrelated word (e.g. bare "gin"/"rum"/"jw" as substrings).
_WORD_BOUNDARY_KEYWORDS = {"gin", "rum", "jw"}

# "<size>/<NN>%" explicit ABV token seen on some real Gin-Tequila-Liqueur
# listings (e.g. "GRAN CENTENARIO REPOSADO 700ml/38%",
# "X-RATED FUSION 750ml/17%") — highest-priority signal when present,
# ahead of any keyword, for the four Brandline-classified categories.
_ABV_REGEX = r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%"


def _kw_pattern(keywords):
    """Case-insensitive alternation regex for use with .rlike(); short
    ambiguous tokens get an explicit \\b word boundary."""
    parts = []
    for kw in keywords:
        escaped = re.escape(kw)
        if kw in _WORD_BOUNDARY_KEYWORDS:
            parts.append(rf"\b{escaped}\b")
        else:
            parts.append(escaped)
    return "(?i)(" + "|".join(parts) + ")"


def _explicit_abv(brandline_col):
    raw = regexp_extract(brandline_col, _ABV_REGEX, 1)
    normalized = regexp_replace(raw, ",", ".")
    return when(raw == "", lit(None).cast(DoubleType())).otherwise(normalized.cast(DoubleType()))


def _tax_gin_tequila_liqueur(brandline_col):
    abv = _explicit_abv(brandline_col)
    bl = lower(brandline_col)
    return (
        when(abv.isNotNull() & (abv >= 20), lit("65%"))
        .when(abv.isNotNull() & (abv < 20), lit("35%"))
        .when(brandline_col.isNotNull() & bl.rlike(_kw_pattern(LIQUEUR_KEYWORDS)), lit("35%"))
        # Default: gin/tequila are the category's namesake majority.
        .otherwise(lit("65%"))
    )


def _tax_mixed_category(brandline_col):
    abv = _explicit_abv(brandline_col)
    bl = lower(brandline_col)
    return (
        when(abv.isNotNull() & (abv >= 20), lit("65%"))
        .when(abv.isNotNull() & (abv < 20), lit("35%"))
        .when(bl.rlike(_kw_pattern(COGNAC_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(WHISKY_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(VODKA_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(BRANDY_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(GIN_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(TEQUILA_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(RUM_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(CHINESE_LIQUOR_KEYWORDS)), lit("65%"))
        .when(bl.rlike(_kw_pattern(WINE_KEYWORDS)), lit("35%"))
        .when(bl.rlike(_kw_pattern(LIQUEUR_KEYWORDS)), lit("35%"))
        # No underlying-type signal found in Brandline — honest
        # insufficient-data null, not a guess. Real and expected for a
        # meaningful share of these three cross-cutting categories (see
        # module docstring).
        .otherwise(lit(None).cast(StringType()))
    )


def _domestic_tax_expr(category_col, brandline_col):
    return (
        when(category_col.isin(*CATEGORY_TAX_65), lit("65%"))
        .when(category_col.isin(*CATEGORY_TAX_35), lit("35%"))
        .when(category_col == CATEGORY_GIN_TEQUILA_LIQUEUR, _tax_gin_tequila_liqueur(brandline_col))
        .when(category_col.isin(*CATEGORY_MIXED), _tax_mixed_category(brandline_col))
        .otherwise(lit(None).cast(StringType()))
    )


EXRATE_CSV_PATH = "/Volumes/selfservice_nonprod/gtr_web_scraping/ref_files/Ex.Rates_2025.csv"
SILVER_TABLE = "selfservice_nonprod.gtr_web_scraping.gtr_silver_master"

CHANNEL_LABELS = {}

FORMAT_COLUMNS = [
    "Year", "Month", "Market", "Retailer", "Country", "Channel", "ID",
    "Brand", "Brandline", "Size", "Domestic_Tax", "Price_Discounted",
    "Strike_Price", "Currency", "GTR_exclusive", "Product_link", "Scraped_At",
]


def _fix_price(price_col):
    """Site prices are e.g. "26.490.000 đ" or "370.000 đ" — VND, dot as
    thousands separator, no minor/decimal unit in practice (checked
    across hundreds of live listings, never a comma or fractional đồng
    figure). Strip everything but digits, which collapses the thousands
    dots away cleanly, then cast to double."""
    cleaned = regexp_replace(price_col, r"[^\d]", "")
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
    """No dedicated Size field on this site — listing-card titles
    inconsistently carry size (e.g. "CÎROC Pineapple 75cl", "Belvedere
    Vodka silver 1750ml" DO; "Vodka Smirnoff Red", "Kilchoman 14 Years
    Old" do NOT). Extracts a cl/ml/l token when present; left null
    otherwise per this repo's "honest insufficient data" convention
    rather than defaulting to a guessed size. A real per-product
    "Thể tích (ml)" field exists on product-detail pages but isn't
    scraped here (visiting ~3,300 individual PDPs was judged not worth
    the added runtime for this build)."""
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

    # ID_raw is the site's own internal numeric product id, pulled from
    # each card's "cart/add/<ID>/1" add-to-cart link (confirmed unique
    # and stable across every category tested — see scraper docstring).
    # A real minority of cards (price-on-request / "Liên hệ" listings,
    # and a handful of other cards with a real price but no cart button
    # at all — both confirmed live, not a scraper bug) have no such
    # link; ID falls back to Product_link so a genuinely priced row
    # still gets a usable, stable identifier instead of being dropped —
    # same fallback pattern used by GMP Abu Dhabi and Le Bon Macau in
    # this repo. Rows with neither a real ID_raw nor a price correctly
    # end up in the DLQ below regardless.
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

    # No dedicated Size field — always falls back to the title regex.
    df = df.withColumn("Size", _normalize_size_to_cl(_extract_size_from_text(col("Brandline"))))
    df = df.withColumn("Size", when(col("Size") == "", None).otherwise(col("Size")))

    # Site is Vietnamese-only; product titles are brand names/spirit
    # terms as-is (e.g. "Cognac Lheraud Petite Champagne 1979") — no
    # ai_translate step used.

    df = df.withColumn("Year", year(to_timestamp(col("Scraped_At"))))
    df = df.withColumn("Month", date_format(to_timestamp(col("Scraped_At")), "MMMM"))
    df = df.withColumn("Scraped_At", to_timestamp(col("Scraped_At")))
    df = df.withColumn("Market", lit(MARKET))
    df = df.withColumn("Retailer", lit(RETAILER))
    df = df.withColumn("Channel", _map_channel_label(col("Channel")))
    # Domestic retailer — Country is the plain name ("Vietnam"), no "DF "
    # prefix (that prefix is GTR-only per the schema).
    df = df.withColumn("Currency", lit(LOCAL_CURRENCY))
    # Domestic_Tax — Vietnam Special Consumption Tax, Law No. 66/2025/QH15.
    # Category is still present at this point (dropped further below,
    # after this and the ExRate step both need it/Brandline).
    df = df.withColumn("Domestic_Tax", _domestic_tax_expr(col("Category"), col("Brandline")))
    # No exclusivity badge, ribbon, or "độc quyền"/"exclusive" text found
    # anywhere on this site — the scraper never sets this key, so it's
    # already null for every row after the ensure-columns-exist backfill
    # above.

    pdf = df.toPandas()
    if not pdf.empty:
        pdf = ExchangeRate_cleaning(pdf, EXRATE_CSV_PATH, "Strike_Price", "Price_Discounted")
        df = spark.createDataFrame(pdf)

    df = df.drop("Strike Price", "Price Discounted", "ID_raw", "Category")

    # "Liên hệ" (price-on-request) and no-cart-button listings genuinely
    # have no resolvable price — these correctly land in the DLQ on the
    # price-null condition, not a mapping bug. See scraper docstring.
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
    bronze_path = "/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/sieuthiruoungoai/*/*/*/*.json"
    clean(spark, bronze_path)
