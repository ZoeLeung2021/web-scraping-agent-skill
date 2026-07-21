"""
Scraper for BorderShop (Puttgarden & Rostock) — https://www.bordershop.com/da

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/bordershop_heinemann_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real
page_source, not a proxied/stripped fetch — every fact below was checked
against the actual site):

  - Operator: the site's own legal-notice page
    (/da/puttgarden/juridisk-meddelelse) names the responsible entity as
    "Heinemann TRFB GmbH", Zur Westmole 1a, 23769 Puttgarden, Germany
    (Handelsregister Hamburg HRB 195428, VAT DE 27/343/00392) — a Gebr.
    Heinemann travel-retail subsidiary. "Scandlines" (the ferry operator
    whose ports these two shops sit at) only appears as a separate
    footer link to the ferry company's own site, and product-page
    <title> tags still carry the legacy brand string "... | Scandlines
    Border Shop" — but the live copyright footer reads "(c) 2026
    Heinemann TRFB GmbH", which is the current, authoritative source
    used here over any older assumption. Customer-facing brand:
    "BorderShop" / "SCA Shop".
  - GTR retailer: the toldregler-bordershop (customs-rules) page's own
    copy confirms genuine cross-border/land-border retail — "Som
    forbruger kan du frit importere varer koebt i et EU-land til Danmark
    til eget brug" ("As a consumer you may freely import goods bought in
    an EU country into Denmark for personal use") — the same excise-tax
    arbitrage pattern as Calle/Fleggaard (Danish/Swedish travelers buying
    at Germany's lower alcohol excise rates). Market = "GTR". Both shops
    are physically in Germany, so Country = "Germany" here, "DF Germany"
    after the cleaner's GTR prefix, matching the Calle/Fleggaard
    precedent.
  - Two genuinely different physical locations confirmed live under the
    SAME domain and the SAME platform: /da/puttgarden/... and
    /da/rostock/... (both render the identical SAP Commerce Cloud/Hybris
    storefront — same "TF-SCA-CC/Online" catalog id, same DOM, same
    hidden `pointOfService` form field flipping between "PUTTGARDEN" and
    "ROSTOCK"). They are NOT one unified catalog, though: a live
    same-category comparison found only 16/40 overlapping product IDs on
    spiritus/whisky page 1, and full-pagination totals differed
    substantially (whisky: 276 unique products @ Puttgarden vs. 136 @
    Rostock; dansk-oel: 48 @ Puttgarden vs. 30 @ Rostock). Modeled here as
    two Channels under one Country — same shape as Attenza's
    multi-location build, not Fleggaard's single unified catalog.
  - IMPORTANT: this is a genuinely different codebase from Calle/
    Fleggaard/Travel FREE Bordershop (all also "*bordershop*"-branded
    project builds) — those are a Tailwind/React storefront; this one is
    SAP Commerce Cloud/Hybris (`smartedit-catalog-version-uuid`,
    `/c/scacat_XXXX/` category codes, `/p/000000000000XXXXXX/` product
    codes). The shared "bordershop" naming pattern is coincidental, not
    evidence of a shared platform — confirmed independently, not assumed.
  - Real category taxonomy confirmed via the site's own mega-menu (seen
    verbatim on every page's nav dump) and verified live by hitting each
    URL directly:
      Oel -> Dansk Oel, Svensk Oel, Flere Oel
      Vin & Cider -> Vin -> Roedvin, Hvidvin, Rosevin ; (also, as Vin &
        Cider's direct children) Cider, Mousserende
      Spiritus -> Whisky, Gin, Vodka, Rom, Likoer, Flere Spiritus
    NESTED-TAXONOMY TRAP AVOIDED: "Vin" (scacat_5201) is an intermediate
    parent category that ALSO renders a full aggregate product grid on
    its own URL (confirmed live: 40 cards hitting it directly, the same
    products that live under its Roedvin/Hvidvin/Rosevin children) — it
    is deliberately NOT looped here, only its 3 leaf children are. The
    top-level Oel/Vin & Cider/Spiritus parents behave the same way and
    are also not looped. Only the 14 real leaf subcategories below are
    scraped — a single, non-overlapping category dimension (confirmed no
    product double-counted between sibling leaves). Non-alcohol
    categories (Vand/water, Mad & Nydelse/food, Husholdning/household,
    Diverse/beauty+toys, Tilbud/offers which cross-cuts both alcohol and
    non-alcohol) are excluded by simply never being in CATEGORIES below.
  - Each product card (`div.c-product-card.js-product-card`) embeds a
    clean structured-data blob in a child
    `<script class="js-wishlist-payload js-track-payload" type="application/json">`
    tag — {name, id, price, brand, category, metric1, dimension3, ...}.
    Used directly instead of parsing DOM text where possible:
      - id: clean numeric SKU (e.g. "630375") — matches the trailing
        digits of the product URL's `/p/000000000000630375/` segment
        with leading zeros stripped. Used as ID_raw.
      - brand: clean brand string (e.g. "The Famous Grouse") -> Brand.
      - name: full title incl. size/ABV (e.g. "The Famous Grouse Blended
        Scotch Whisky 40 % 1L") -> Brandline.
      - price: current charged price (e.g. "99.95") -> Price_Discounted.
      - metric1: the pre-discount reference price when the product is on
        sale (e.g. "109.95"); empty string when not discounted. Confirmed
        against a real live `<s>109,95 DKK</s>` strikethrough element
        rendered next to a "Foer" ("Before") label in the same card's
        price box — a genuine second price, not invented (checked a
        30-160 card live sample per category, with anywhere from ~7% to
        ~35% of cards actually discounted depending on category). Used as
        Strike_Price when non-empty, otherwise falls back to price (no
        active discount).
      - dimension3: promo/exclusivity tag(s), confirmed live values across
        a multi-category sample: "", "special offer", "travel exclusive",
        "travel exclusive_special offer", "travel exclusive_out of stock"
        (multiple tags joined with "_" when more than one applies). The
        "travel exclusive" token pairs 1:1 with a real visible ribbon
        reading "Travel Edition" on the same card (confirmed live on an
        Auchentoshan whisky gift-pack product) — a genuine, selectively-
        applied per-product travel-retail-exclusivity signal, not a
        guess. GTR_exclusive = "Yes" when dimension3 contains "travel
        exclusive", else "No" — the site has a real exclusivity concept
        and applies it to only some SKUs, so every row gets an explicit
        Yes/No here, never null (unlike Calle/Fleggaard where the concept
        doesn't exist anywhere on the site at all).
  - Size: primarily read from the price box's own per-unit reference line
    (`p.c-price-box__reference`, e.g. "(99,95 DKK / 1 l.)" -> "1 l.");
    falls back to a regex over the card's `name` field (product titles
    bake size in too, e.g. "...40 % 1L", "Kung Pilsner 24 x 33 cl") when
    the reference line is missing or unparseable. Raw string is passed
    through as-is; the cleaner does cl-normalization and (matching the
    Calle/Fleggaard convention) deliberately excludes "x"-multipack sizes
    (e.g. "24 x 33 cl") from conversion since total-vs-per-unit is
    ambiguous.
  - Pagination: real, working `?page=N` (0-indexed) URL-based server-side
    pagination — confirmed live by fetching pages 0-7 directly by URL (no
    click needed) on spiritus/whisky and finding zero duplicate product
    IDs across pages, with an empty page 7 marking the end (i.e. genuine
    per-page server rendering, NOT the client-state-only bug that hit
    kings.sr, where direct URL navigation silently re-served page 1).
    This scraper fetches each page directly by URL and stops at the first
    empty page.
  - No blocking age-verification gate found on any category checked,
    including oel/beer.
"""

import os
import re
import time
from datetime import datetime, timezone
import json

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import io

RETAILER_SLUG = "bordershop_heinemann"
BASE_URL = "https://www.bordershop.com"
LOCALE = "da"

# Two genuinely different physical shops/catalogs on the same platform —
# see module docstring. Both are in Germany.
LOCATIONS = {
    "Germany": ["Puttgarden", "Rostock"],
}

# Channel-naming per this project's standing convention (see
# feedback_channel_naming_airports memory): both are real Scandlines car-
# ferry terminal towns to Denmark/Sweden, not airports or road border
# crossings, so this uses the established "Ferry - <name>" format already
# in GTR_Pricing's Aelia_cleaner.py CHANNEL_MAP (e.g. "Ferry - Inishmore")
# rather than the raw location slug. Kept separate from `self.location`
# (used for URL-building below) since the raw slug is still needed there.
CHANNEL_DISPLAY_NAME = {
    "Puttgarden": "Ferry - Puttgarden",
    "Rostock": "Ferry - Rostock",
}

# (url_path, category_code) for the 14 real leaf alcohol categories.
# Deliberately excludes the "Vin" (scacat_5201) intermediate parent and the
# Oel/Vin & Cider/Spiritus top-level parents — see module docstring's
# nested-taxonomy-trap note.
CATEGORIES = [
    ("oel/dansk-oel", "scacat_5101"),
    ("oel/svensk-oel", "scacat_5102"),
    ("oel/flere-oel", "scacat_5103"),
    ("vin-og-cider/vin/roedvin", "scacat_5202"),
    ("vin-og-cider/vin/hvidvin", "scacat_5203"),
    ("vin-og-cider/vin/rosevin", "scacat_5204"),
    ("vin-og-cider/mousserende", "scacat_5205"),
    ("vin-og-cider/cider", "scacat_5206"),
    ("spiritus/gin", "scacat_5301"),
    ("spiritus/whisky", "scacat_5302"),
    ("spiritus/vodka", "scacat_5303"),
    ("spiritus/rom", "scacat_5304"),
    ("spiritus/likoer", "scacat_5305"),
    ("spiritus/flere-spiritus", "scacat_5306"),
]

_SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:liter|cl|ml|l)\b", re.IGNORECASE)
_REF_SIZE_RE = re.compile(r"/\s*([\d.,]+\s*(?:liter|cl|ml|l))\)", re.IGNORECASE)


class BordershopHeinemannScraper:
    def __init__(self, location, category):
        self.location = location  # "Puttgarden" or "Rostock"
        self.category_path, self.category_code = category
        self.product_dicts = []

    def _category_url(self, page):
        base = f"{BASE_URL}/{LOCALE}/{self.location.lower()}/{self.category_path}/c/{self.category_code}/"
        if page:
            return f"{base}?q=%3Arelevance&page={page}"
        return base

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.driver.set_page_load_timeout(45)

    def _get_with_retry(self, url, tries=3):
        for attempt in range(tries):
            try:
                self.driver.get(url)
                return True
            except Exception:
                time.sleep(3)
        return False

    def _extract_size(self, card_soup, name_text):
        ref = card_soup.find("p", class_=lambda c: c and "c-price-box__reference" in c)
        if ref:
            m = _REF_SIZE_RE.search(ref.get_text(" ", strip=True))
            if m:
                return m.group(1)
        m2 = _SIZE_RE.search(name_text or "")
        return m2.group(0) if m2 else None

    def _parse_cards(self, html):
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("div", class_=lambda c: c and "c-product-card" in c and "js-product-card" in c)
        results = []
        for card in cards:
            product_dict = {}
            link_el = card.find("a", href=True)
            href = link_el["href"] if link_el else None
            product_dict["Product_link"] = f"{BASE_URL}{href}" if href else None

            data = {}
            script_tag = card.find("script", class_=lambda c: c and "js-wishlist-payload" in c)
            if script_tag:
                try:
                    data = json.loads(script_tag.get_text(strip=True))
                except (json.JSONDecodeError, TypeError):
                    data = {}

            product_dict["ID_raw"] = data.get("id") or None
            product_dict["Brand"] = data.get("brand") or None
            product_dict["Brandline"] = data.get("name") or None

            price = data.get("price") or None
            metric1 = data.get("metric1") or None
            product_dict["Price Discounted"] = price
            product_dict["Strike Price"] = metric1 if metric1 else price

            dimension3 = (data.get("dimension3") or "").lower()
            product_dict["GTR_exclusive"] = "Yes" if "travel exclusive" in dimension3 else "No"

            try:
                product_dict["Size"] = self._extract_size(card, data.get("name"))
            except (AttributeError, TypeError):
                product_dict["Size"] = None

            results.append(product_dict)
        return results

    def run_all(self, max_pages=40):
        self.open_website()
        try:
            for page in range(max_pages):
                url = self._category_url(page)
                ok = self._get_with_retry(url)
                if not ok:
                    break
                time.sleep(4)
                page_items = self._parse_cards(self.driver.page_source)
                if not page_items:
                    break
                self.product_dicts.extend(page_items)
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass


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
            for category in CATEGORIES:
                cat_label = category[0]
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {cat_label}")
                scraper = BordershopHeinemannScraper(channel, category)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = CHANNEL_DISPLAY_NAME.get(channel, channel)
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    print(f"  -> {cat_label}: scraped {scraped_count}")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{cat_label}: {e}")

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
