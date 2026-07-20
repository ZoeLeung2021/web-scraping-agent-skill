"""
Scraper for Gonsalves Liquors Ltd. — http://www.gonsalvesliquors.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/gonsalves_liquors_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

GENUINELY DIFFERENT SHAPE FROM EVERY OTHER SCRAPER IN THIS PROJECT: this
retailer does not publish an HTML product catalog at all. `prices.php` is
a static, ~20-year-old hand-coded HTML page (Dreamweaver-era markup,
`MM_preloadImages`/`MM_swapImage` nav-rollover JS, table-based layout) that
does nothing but link out to two PDFs:
  - download/GLL_Price_List_VAT.pdf  -- the REAL, current price list
    ("2026 PRICE LIST", dated 23/04/2026 in its own footer). This is the
    only file this scraper parses.
  - download/the-exclusive-coll.pdf  -- a marketing brochure ("The
    Exclusive Collection") with tasting notes and food-pairing text for
    ~20 luxury wines. CONFIRMED it carries NO prices anywhere in its 21
    pages (checked live, page 1-4 dumped and read) -- out of scope for a
    pricing scraper, not fetched/parsed here.

COMPANY / MARKET (confirmed live via company.php and contact.php):
  "Gonsalves Liquors Ltd." — founded 1970, Kingstown, SAINT VINCENT AND
  THE GRENADINES (Eastern Caribbean). Per contact.php the company runs
  TWO locations: a "CORPORATE HEADQUARTERS" wholesale/retail outlet on
  Melville St, Kingstown, AND a "DUTY FREE SHOP" at E.T. Joshua Airport.
  BUT the only price list this site publishes is explicitly headed
  "Prices quoted are VAT inclusive" (verbatim, page 1 of the PDF) — VAT-
  inclusive pricing is definitionally the wholesale/retail (Kingstown)
  price list, not the duty-free airport shop's (which would be VAT/tax-
  exempt and is not published anywhere on this site). So:
    Market = "Domestic" (no "DF " Country prefix)
    Country = "Saint Vincent and the Grenadines"
    Currency = "XCD" (Eastern Caribbean Dollar — the PDF's own "EC. $"
      column header; ISO 4217 code XCD)
    Channel = "N/A" (single published price list, no location/channel
      split — the airport duty-free shop has no separate published list
      to scrape)

FETCH METHOD — deliberately requests/urllib, NOT Selenium, unlike every
other scraper in this project: live-tested `curl` against both
prices.php and the PDF download URL and got clean HTTP/1.1 200 responses
immediately, zero JS challenge, zero Cloudflare/bot-wall, zero cookie
gate — confirmed by fetching the exact same content a real browser would
see. Standing up headless Chrome to click a static `<a href=...pdf>`
link that a plain GET already resolves would add real failure surface
(browser crashes, driver version skew, headless PDF-viewer redirects)
for zero benefit. If this site ever grows bot protection, switch to the
same undetected_chromedriver pattern as every other scraper (see
kings_suriname_scraper.py) and use `driver.get()` on the PDF URL, saving
the response bytes the same way.

PDF PARSING — pdfplumber, NOT PyMuPDF/fitz, NOT the naive
`page.extract_table()`: tested both live against the real 23-page PDF.
  - `extract_table()` was tried first and is GARBAGE on this document —
    it merges multiple product rows into single ragged table cells and
    mis-orders columns (confirmed: same 2 lines of text produced a
    6-column, half-empty mangled row via extract_table() vs. a clean
    single text line via extract_text()). Not used.
  - PyMuPDF's `get_text()` breaks every product's name/qty/price onto
    SEPARATE lines (one word-cluster per line) because the source PDF
    uses independently-positioned text runs for each column — unusable
    for line-based regex without extra reconstruction.
  - pdfplumber's `extract_text()` reconstructs each visual row as ONE
    text line (it groups words by y-position first) — e.g. "Jack Daniels
    12 x 75cl 862.50 86.25" comes back as a single clean line, ready for
    a `name / qty x size / case_price / bottle_price` regex. This is the
    only method used below.

REAL DOCUMENT STRUCTURE, confirmed by reading extracted text AND
rendering multiple pages to PNG for visual cross-check (pages 1-2, 3-5,
8-9, 11-22 all visually inspected against their extracted text):
  - Each product line is "<Name> <qty> x <size><unit> <case_price>
    <bottle_price>" — <case_price> is the price for a full case (the
    <qty> shown), <bottle_price> is the same product's single-bottle
    price. There is NO discount/strike-through concept anywhere in this
    document — the "* Wholesale prices offered on purchases of 3 bottles
    and more of the same item *" note describes a bulk-purchase price
    tier, not a promotional markdown on a specific SKU. Strike_Price and
    Price_Discounted are therefore set to the SAME value (the per-bottle
    price) — same convention used by every other single-price retailer
    in this project (e.g. kings_suriname). The case price/qty are kept
    in the bronze JSON as informational-only extra fields (Case_Price_raw,
    Case_Qty_raw) for audit purposes but are NOT part of the 17-column
    Silver schema and are dropped by the cleaner.
  - Category context comes from tilde-bounded section headers, e.g.
    "~ AMERICAN WHISKEY ~", sometimes prefixed "New ~ ZUCCARDI ~" (the
    regex below tolerates the optional "New " prefix — an earlier draft
    of this parser missed that and silently mis-attributed several wine
    producer sections to the wrong category; fixed and re-verified).
    Category state PERSISTS across page boundaries (a real early bug:
    resetting it per-page produced `None` categories for the first rows
    of nearly every page until that page's own header line appeared).
  - KNOWN, ACCEPTED DATA GAPS (documented, not silently dropped):
    1. ~8 alcohol product rows across the whole 23-page document give
       ONLY a "qty x size case_price bottle_price" line with NO text
       product name at all, because the source PDF renders that
       product's brand purely as a logo IMAGE (e.g. "Dewars White
       Label", plain "Beefeater", plain "Bombay Sapphire" — confirmed by
       rendering the page to PNG: a real brand logo sits directly above/
       beside these specific price rows with no text equivalent in the
       PDF's text layer). These rows are SKIPPED — there is no reliable
       way to assign a Brand/Brandline to a row whose only source is a
       raster image, and OCR-ing a logo image reliably enough to trust
       for a Brand field was judged not worth the fragility (no
       tesseract binary available in this project's WSL test env either
       — checked, not installed). ~8 rows out of ~750 (~1%).
    2. A handful of lines (5 confirmed: "Absolut Citron/Kurant", "Raynal
       VSOP...Superior", "Partager Rouge...", a Peppoli Chianti line, one
       on the water/mixer page) extract as garbled, character-
       interleaved text (e.g. "AAbbssoolluutt CKiutrraonnt 1122 xx
       11LLtt..."). Rendered to PNG and visually confirmed each one is a
       SINGLE, normal-looking row on the actual page — this is a stale/
       duplicate hidden text object left behind in the PDF's text layer
       (almost certainly an old price edited-over without deleting the
       old text run underneath, or a bold-text double-render artifact),
       not a real second product. Cross-checked: in every case the SAME
       product/price ALSO exists elsewhere in the document as a normal,
       cleanly-extracted line (e.g. "Absolut Citron 12 x 1Lt 735.00
       73.50" appears correctly elsewhere) — so this parser deliberately
       does NOT try to de-interleave/recover these lines, since doing so
       risks fabricating a phantom duplicate row. They simply fail the
       row regex and are dropped — confirmed harmless, not a real data
       loss.
  - ALCOHOL-ONLY FILTER: this single PDF mixes real spirits/wine/beer/
    sake/baijiu with a handful of non-alcohol sections: COFFEE (Illy
    capsules), OLIVE OIL (Zuccardi), SYRUP (cocktail syrups), water/
    mixer brands (Evian, Perrier Sparkling, San Pellegrino, Mountain Top,
    Angostura Bitters, Zing Zang cocktail mixes) sitting in an unheaded
    section, EPIC PRODUCTS (bar accessories — muddlers, ice buckets,
    corkscrews, wine bucket, etc.), and a Cuban cigar list. Filtering:
      - Category-keyword exclusion: "coffee", "olive oil", "syrup",
        "epic products", "cigar", "mixer" (substring match on the
        current section header).
      - EPIC PRODUCTS and the Cuban cigar list ALSO never match the row
        regex at all (both use a single bare price, e.g. "Cork Lift
        26.97", with no "qty x size" token) — confirmed live, so they're
        excluded twice over, structurally.
      - Name-keyword exclusion for the water/mixer brands specifically
        (their section has a blank/logo-only header with no text of its
        own, so category-keyword filtering can't catch them): "evian",
        "san pellegrino sparkling", "perrier sparkling", "mountain top
        natural spring", "angostura", "zing zang". Deliberately did NOT
        use a bare "cazadores" keyword (meant for a Cuban cigar brand) —
        it collided with and wrongly excluded "Cazadores Blanco", a real
        tequila; caught and fixed during testing. Deliberately did NOT
        use a bare "perrier" keyword either — it collided with
        "Perrier-Jouët Grand Brut" champagne; fixed to
        "perrier sparkling" (the water brand's full name).
      - BEATBOX PARTY PUNCH (a real ~11% ABV boxed cocktail brand) and
        XXL (a Moldovan flavoured-vodka brand, confirmed alcohol pricing
        pattern: 12x75cl case/bottle pricing matching every other spirit
        on the list) are INCLUDED as alcohol.
  - Live full-document parse result (see build report for the full
    breakdown): 766 lines matched the product-row regex; 750 kept as
    alcohol after filtering; 16 correctly excluded as non-alcohol
    (including one real bug caught during testing: a "San Pellegrino
    Sparkling Natural / Mineral Water" caption wraps across two PDF text
    lines, so "Mineral Water <qty x size> <price> <price>" alone matches
    the product regex with no "san pellegrino"/"sparkling" text on that
    same line for the other keyword checks to catch - fixed by adding a
    dedicated "mineral water" keyword); 12 orphan (nameless) rows and
    ~211 header/label/garbled-duplicate lines correctly fell through to
    no match.
"""

import io
import json
import re
import time
from datetime import datetime, timezone

import requests
import pdfplumber
from databricks.sdk import WorkspaceClient

RETAILER_SLUG = "gonsalves_liquors"
BASE_URL = "http://www.gonsalvesliquors.com"
PRICES_PAGE_URL = f"{BASE_URL}/prices.php"
# Confirmed live fallback in case the href in prices.php's markup ever
# changes but the file path doesn't (unlikely on a site this static).
FALLBACK_PDF_URL = f"{BASE_URL}/download/GLL_Price_List_VAT.pdf"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Single published price list, single location context - see module
# docstring for why the airport duty-free shop isn't (and can't be)
# scraped separately.
LOCATIONS = {
    "Saint Vincent and the Grenadines": ["N/A"],
}

CATEGORY_RE = re.compile(r"^(?:New\s+)?~\s*(.+?)\s*~", re.IGNORECASE)
NAMED_ROW_RE = re.compile(
    r"^(?P<isnew>New\s+)?(?P<name>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>[A-Za-z]+)\s+"
    r"(?P<case>[\d,]+\.\d{2})\s+"
    r"(?P<bottle>[\d,]+\.\d{2})\s*$"
)
ORPHAN_ROW_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*x\s*[\d.]+\s*[A-Za-z]+\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s*$"
)
SKIP_LINE_PATTERNS = [
    re.compile(r"Prices subject to change", re.IGNORECASE),
    re.compile(r"^Page \d+"),
    re.compile(r"^\d{2}/\d{2}/\d{4}"),
    re.compile(r"^QTY/SIZE"),
    re.compile(r"^CASE\s*$"),
    re.compile(r"^BOTTLE\s*$"),
    re.compile(r"^EC\.\s*\$"),
    re.compile(r"Wholesale prices offered"),
    re.compile(r"Prices quoted are VAT"),
    re.compile(r"^\d{4} PRICE LIST"),
    re.compile(r"Wines are stored"),
    re.compile(r"largest selection"),
    re.compile(r"GONSALVES LIQUORS"),
    re.compile(r"Cor\. Middle"),
    re.compile(r"P\. O\. Box"),
    re.compile(r"^Tel:"),
    re.compile(r"^Email:"),
    re.compile(r"^Website:"),
    re.compile(r"Vintages may vary"),
]

# Section-header keyword exclusions - see module docstring.
NON_ALCOHOL_CATEGORY_KEYWORDS = [
    "coffee", "olive oil", "syrup", "epic products", "cigar", "mixer",
]
# Per-row name-keyword exclusions for the header-less water/mixer section
# - see module docstring for why "cazadores" and bare "perrier" are
# deliberately NOT in this list.
NON_ALCOHOL_NAME_KEYWORDS = [
    "evian", "san pellegrino sparkling", "perrier sparkling",
    "mountain top natural spring", "angostura", "zing zang",
    # "Mineral Water" catches a real, confirmed leak found during
    # testing: the source PDF wraps "San Pellegrino Sparkling Natural /
    # Mineral Water" across two lines, so pdfplumber's line-based text
    # extraction puts "San Pellegrino Sparkling Natural" on its own
    # (price-less, harmlessly dropped) line and "Mineral Water <qty x
    # size> <price> <price>" on the next - which DOES match the product
    # row regex with "Mineral Water" read as the product name, and
    # neither "san pellegrino" nor "sparkling" appear anywhere on that
    # specific line for the category/name keyword filters above to
    # catch. No real alcohol product on this list is packaged/cased as
    # bare "Mineral Water", so this is safe.
    "mineral water",
]


def _is_alcohol(category: str, name: str) -> bool:
    cat_l = (category or "").lower()
    name_l = name.lower()
    if any(k in cat_l for k in NON_ALCOHOL_CATEGORY_KEYWORDS):
        return False
    if any(k in name_l for k in NON_ALCOHOL_NAME_KEYWORDS):
        return False
    return True


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


class GonsalvesLiquorsScraper:
    def __init__(self, location, channel):
        self.location = location
        self.channel = channel
        self.product_dicts = []
        self._pdf_url_cache = None
        self.expected_count = None  # no independent site-side total to
        # cross-check against on a static PDF price list - unlike every
        # HTML-catalog retailer in this project, there's no "X results"
        # counter anywhere on this site. Row count is validated instead
        # by the manual page-by-page visual cross-check documented in
        # the module docstring and build report.

    def find_pdf_url(self) -> str:
        """GET the real prices.php page and pull the price-list PDF href
        out of it, falling back to the confirmed-live hardcoded path if
        the markup ever changes shape."""
        try:
            resp = requests.get(
                PRICES_PAGE_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            match = re.search(
                r'href="(download/[^"]*Price_List[^"]*\.pdf)"',
                resp.text,
                re.IGNORECASE,
            )
            if match:
                return f"{BASE_URL}/{match.group(1)}"
        except requests.RequestException:
            pass
        return FALLBACK_PDF_URL

    def fetch_pdf_bytes(self) -> bytes:
        pdf_url = self.find_pdf_url()
        self._pdf_url_cache = pdf_url
        resp = requests.get(pdf_url, headers={"User-Agent": USER_AGENT}, timeout=60)
        resp.raise_for_status()
        return resp.content

    def parse_pdf(self, pdf_bytes: bytes):
        current_category = None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if any(p.search(line) for p in SKIP_LINE_PATTERNS):
                        continue
                    cat_match = CATEGORY_RE.match(line)
                    if cat_match:
                        current_category = cat_match.group(1).strip()
                        continue
                    m = NAMED_ROW_RE.match(line)
                    if not m:
                        # Either an orphan (logo-only brand, no text name)
                        # or a genuinely non-product line (sub-header,
                        # country-of-origin label, garbled duplicate-text
                        # artifact, single-price cigar/bar-accessory line)
                        # - see module docstring. Neither is recoverable
                        # here; both are deliberately dropped.
                        continue
                    d = m.groupdict()
                    name = d["name"].strip()
                    if not _is_alcohol(current_category, name):
                        continue

                    size_token = f"{d['size']}{d['unit']}"
                    brandline = f"{name} {size_token}"
                    product_dict = {
                        "Product_link": self._pdf_url_cache,
                        "ID_raw": _slugify(brandline),
                        "Brand": None,
                        "Brandline": brandline,
                        "Strike Price": d["bottle"],
                        "Price Discounted": d["bottle"],
                        "Category": current_category,
                        "Case_Qty_raw": d["qty"],
                        "Case_Price_raw": d["case"],
                        "Is_New_raw": bool(d["isnew"]),
                    }
                    self.product_dicts.append(product_dict)
        self._disambiguate_duplicate_ids()

    def _disambiguate_duplicate_ids(self):
        """Real, confirmed edge case: a handful of distinct products across
        this document share an identical name+size slug because their
        brand is ONLY shown as a logo image next to a generic text label
        (e.g. Kahlua's "Original 12 x 1Lt" and Malibu's "Original 12 x
        1Lt" are two different rums/liqueurs at two different prices -
        confirmed live on page 6 - but both extract as the bare text
        "Original" with no brand name recoverable from the PDF's text
        layer). Also a few identical varietal names repeat across
        different wine-producer sections with no producer name in the
        line itself (e.g. "Pinot Grigio 2023 75cl" under three different
        producers). Verified live (see build report): every one of these
        collisions is between rows with DIFFERENT prices, i.e. genuinely
        different products, not the same row parsed twice - so this
        disambiguates rather than drops. Confirmed no exact-duplicate
        (same slug AND same price) rows exist in this document."""
        seen_counts = {}
        for product_dict in self.product_dicts:
            base_id = product_dict["ID_raw"]
            seen_counts[base_id] = seen_counts.get(base_id, 0) + 1
            if seen_counts[base_id] > 1:
                product_dict["ID_raw"] = f"{base_id}-{seen_counts[base_id]}"

    def run_all(self):
        pdf_bytes = self.fetch_pdf_bytes()
        self.parse_pdf(pdf_bytes)


def upload_to_databricks(data: list, volume_path: str) -> None:
    print(f"Uploading {len(data)} records to Databricks Volume: {volume_path}")
    w = WorkspaceClient()
    json_data = json.dumps(data)
    file_like_object = io.BytesIO(json_data.encode("utf-8"))
    w.files.upload(volume_path, contents=file_like_object, overwrite=True)
    print("Upload successful!")


if __name__ == "__main__":
    all_data = []
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            print(f"Scraping {RETAILER_SLUG}: {country} / {channel}")
            scraper = GonsalvesLiquorsScraper(country, channel)
            try:
                scraper.run_all()
                for item in scraper.product_dicts:
                    item["Country"] = country
                    item["Channel"] = channel
                    item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                all_data.extend(scraper.product_dicts)
                scraped_count = len(scraper.product_dicts)
                total_scraped += scraped_count
                print(f"  -> scraped {scraped_count} alcohol rows from the PDF price list")
            except Exception as e:
                print(f"FAILURE scraping {country}/{channel}: {e}")

    print(f"TOTAL: scraped {total_scraped}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
