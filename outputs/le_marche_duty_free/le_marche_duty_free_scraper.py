"""
Scraper for Le Marché Duty Free — https://www.lemarchereserveandcollect.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/le_marche_duty_free_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted and
reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source,
not a text-extraction proxy — every fact below was re-checked against the
actual live site):

  - GTR retailer. Le Marché Duty Free is the duty-free retail concession at
    the Eurotunnel Folkestone-Coquelles terminal in Coquelles, France —
    confirmed via the site's own About Us page ("Le Marché Duty Free... is
    a leading duty-free retail operator" ... "Whether you're embarking on a
    holiday or a business trip, Le Marché Duty Free ensures that your
    shopping experience is seamless and enjoyable") and corroborated by
    trade press (Moodie Davitt Report; dfnionline.com "Le Marché Duty Free
    opens Truck Shop at Eurotunnel Coquelles"). It's a joint-venture
    operator — Mumbai Travel Retail Private Limited (MTRPL), a JV between
    Adani Airport Holdings and Flemingo Travel Retail — running a single
    physical location that serves travellers/vehicles crossing the Channel
    Tunnel between France and the UK. Physical location is in France, so
    Market = "GTR", Country = "France" ("DF France" after the cleaner's GTR
    prefix). No flight/boarding-pass copy (it's a tunnel crossing, not an
    airport), but the operator explicitly self-identifies as duty-free and
    targets travellers, not local residents.
  - Platform: Microsoft Dynamics 365 Commerce storefront (confirmed via
    "_msdyn365" sign-in paths, "ms-product-search-result"/"msc-product"/
    "ms-refine-submenu" CSS classes, and product images served from
    images-eu-prod.cms.commerce.dynamics.com). Category pages use a
    "<slug>/<numericCategoryId>.c" URL and "?skip=N" offset pagination that
    was confirmed to be genuinely working (server-rendered, not a client-
    state trap like kings.sr) — skip=0 vs skip=30 returned zero overlapping
    product IDs, and a full paginate-to-the-end run on every category below
    landed exactly on the site's own displayed total with zero duplicate
    IDs.
  - Two URL path aliases exist ("lmdf-ecomm/<slug>/<id>.c", used in the
    original task URL and by this scraper, and "lmdf-truck-shop/<slug>/
    <id>.c", seen in the live nav) but were confirmed live to serve the
    IDENTICAL catalog — same category IDs, same "<Category> N products"
    header count, same product IDs on every page. This is not two separate
    channels/catalogs to scrape twice, just two site-path aliases for one
    online store. Only "lmdf-ecomm" is used here.
  - Single physical location (Coquelles, France) — no store/location
    selector or per-store price variation found anywhere on the site.
    Modeled as one location with a single "N/A" channel, same convention as
    Fleggaard/Calle bordershops.
  - 3 real top-level alcohol categories, found via product breadcrumbs and
    the site's own category headers (not assumed from the URL):
      - Spirits   (5637167079.c) — "Spirits 192 products"
      - Wines     (5637167080.c) — "Wines 188 products" (includes Champagne,
        Red, White, Rosé, Sparkling, Vermouth, Port, and Cider as
        sub-facets — Cider lives inside Wines on this site, not Beer)
      - Beer      (5637184326.c) — "Beer 18 products"
    "Beauty" (fragrances/cosmetics) and "Food" (snacks/confectionery) are
    separate top-level categories with zero alcohol overlap, confirmed via
    site search ("perfume" -> Beauty products only) — deliberately never
    scraped, so no extra non-alcohol filtering step is needed inside this
    scraper; the alcohol-only scope is enforced simply by which 3 top-level
    category IDs are looped.
  - NESTED/OVERLAPPING TAXONOMY TRAP CHECKED AND AVOIDED: each category's
    left-nav refiner ("Category") panel lists every sub-type TWICE with two
    different counts under two separate <li id="Category_N"> nodes that
    both link to the exact same refiner recordId (e.g. two "Gin" entries,
    "Gin(31)" and "Gin(1)", both pointing to
    refiners=[[5,"Gin",5637167088,2,"Gin","",0]] — the identical recordId
    5637167088). This is a genuine site-side refiner-panel rendering bug
    (duplicate facet-count entries for one category — confirmed the pairs
    sum to the page's own real total, e.g. Spirits: 174 primary + 18
    secondary = 192), not two distinct dimensions that should both be
    looped. Rather than loop any subcategory refiner at all (which would
    either double-count or require deduping against this rendering bug),
    this scraper simply paginates the parent category page itself end to
    end. Live validation: Spirits scraped 192/192 site total (0 duplicate
    IDs across 7 pages), Wines 188/188 (0 duplicates across 7 pages), Beer
    18/18 (0 duplicates, single page).
  - The "<N> Results for <query>" header shown elsewhere on this site
    (search results, and oddly also visible embedded in category page HTML)
    is unreliable — it showed the exact same stale "95 Results for..."
    string regardless of category or search query tested (Spirits page,
    "wine"/"champagne"/"perfume" searches all showed "95 Results for...").
    The per-category "<Category> N products" header used above (via
    get_expected_item_count) is the only trustworthy total on this site.
  - Product cards are `<li class="ms-product-search-result__item">`, each
    with exactly one `<a class="msc-product" href="/<url-slug>/<numericID>
    .p">` (ID = the run of digits immediately before ".p"), an
    `<h2 class="msc-product__title">` holding the full product name (brand
    + ABV% + size bundled into one string, e.g. "BAILEYS IRISH CREAM 17%
    1L", "CORONA EXTRA 4.5% CANS 24X0.33L") — there is no separate
    brand-only field, so Brandline carries the full title and Brand is left
    null, same convention as Fleggaard/GMP/Calle — and a single
    `<span class="msc-price__actual">€<price></span>`.
  - A `.msc-price__strikethrough` CSS class exists in the site's stylesheet
    but was confirmed EMPTY on every single product checked across all 3
    categories (398 products total, live full-pagination run) — no genuine
    per-product discount/before-price exists anywhere on this site.
    Strike_Price and Price_Discounted are therefore captured as the same
    raw listing price, same convention as Fleggaard/Calle.
  - A `.msc-product__offer` badge div is populated on a minority of
    products (~13%, 52/398 checked) but only ever with multi-buy bundle
    copy (e.g. "BUY 2 @ €44 - Ballantine", "BUY 4 FOR 3 - London Hill,
    Marlborough, Fjodor, King Robert") — never anything resembling
    "exclusive"/"GTR exclusive"/"duty-free exclusive", and there is no
    separate "Exclusives" nav category either. GTR_exclusive is therefore
    never set here (the null case — the site has no exclusivity concept at
    all — not the "No" case; see cleaner docstring for the three-way
    distinction).
  - No age-verification gate blocks page_source on any category, including
    Beer/Wines (checked specifically — page loads and renders product cards
    with no interstitial to dismiss).
  - Known data-quality quirk NOT specially handled: at least one Beer
    product ("BUDWEISER US CAN 792 CL") prints a pre-computed CASE total
    volume instead of the usual "<count>X<per-unit size>" multipack format
    (e.g. "24X0.355L") — the cleaner's size regex will read this as a
    (wrong) single-bottle size of 792cl rather than recognizing it as a
    24-pack, because it has no "x" marker to exclude it the way every other
    multipack title does. This is a single-title site quirk, not a
    systemic pattern — left as-is rather than special-cased.
"""

import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "le_marche_duty_free"
BASE_URL = "https://www.lemarchereserveandcollect.com"
SITE_PATH = "lmdf-ecomm"  # confirmed identical catalog to "lmdf-truck-shop" — see module docstring

# Single physical location (Eurotunnel Coquelles, France) — one unified
# online catalog, no store-specific price variation found. See module
# docstring.
LOCATIONS = {
    "France": ["N/A"],
}

# 3 real top-level alcohol categories confirmed live (slug -> numeric
# category recordId). Beauty/Food are separate non-alcohol top-level
# categories and are deliberately excluded by never being listed here.
CATEGORIES = {
    "spirits": "5637167079",
    "wines": "5637167080",
    "beer": "5637184326",
}

_TOTAL_RE = re.compile(r"(\d+)\s+products", re.IGNORECASE)
_PAGE_SIZE = 30
_MAX_PAGES = 20  # safety cap (600 products) — largest real category seen is 192


class LeMarcheDutyFreeScraper:
    def __init__(self, location, category_slug, category_id):
        self.location = location
        self.category_slug = category_slug
        self.category_id = category_id
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, skip=0):
        base = f"{BASE_URL}/{SITE_PATH}/{self.category_slug}/{self.category_id}.c"
        return base if skip == 0 else f"{base}?skip={skip}"

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
        self.driver.set_page_load_timeout(60)

    def _load(self, url):
        try:
            self.driver.get(url)
        except Exception:
            pass
        time.sleep(5)
        return BeautifulSoup(self.driver.page_source, "html.parser")

    def get_expected_item_count(self, soup):
        text = soup.get_text(" ", strip=True)
        match = _TOTAL_RE.search(text)
        return int(match.group(1)) if match else None

    def _extract_card(self, card):
        product_dict = {}
        try:
            link_el = card.find("a", class_="msc-product", href=True)
            href = link_el["href"] if link_el else None
            product_dict["Product_link"] = urljoin(BASE_URL, href) if href else None
            id_match = re.search(r"/(\d+)\.p", href or "")
            product_dict["ID_raw"] = id_match.group(1) if id_match else None
        except (AttributeError, TypeError):
            product_dict["Product_link"] = None
            product_dict["ID_raw"] = None

        try:
            title_el = card.find("h2", class_="msc-product__title")
            product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
            product_dict["Brand"] = None
        except (AttributeError, TypeError):
            product_dict["Brandline"] = None
            product_dict["Brand"] = None

        # No dedicated Size field on this site — Size is derived from the
        # Brandline title text in the cleaner (e.g. "...1L", "...75CL").
        product_dict["Size"] = None

        try:
            price_el = card.find("span", class_="msc-price__actual")
            price_text = price_el.get_text(strip=True) if price_el else None
            product_dict["Strike Price"] = price_text
            product_dict["Price Discounted"] = price_text
        except (AttributeError, TypeError):
            product_dict["Strike Price"] = None
            product_dict["Price Discounted"] = None

        # No GTR-exclusive badge/ribbon/"exclusive" text found anywhere on
        # this site — see module docstring. Deliberately not set here.

        return product_dict

    def get_main(self):
        soup = self._load(self.get_url(skip=0))
        self.expected_count = self.get_expected_item_count(soup)

        skip = 0
        for _page in range(_MAX_PAGES):
            if skip > 0:
                soup = self._load(self.get_url(skip=skip))
            cards = soup.find_all("li", class_="ms-product-search-result__item")
            if not cards:
                break
            for card in cards:
                self.product_dicts.append(self._extract_card(card))
            if len(cards) < _PAGE_SIZE:
                break
            if self.expected_count is not None and len(self.product_dicts) >= self.expected_count:
                break
            skip += _PAGE_SIZE

    def run_all(self):
        try:
            self.open_website()
            self.get_main()
        finally:
            try:
                if hasattr(self, "driver"):
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
    total_expected = 0
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_slug, category_id in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_slug}")
                scraper = LeMarcheDutyFreeScraper(channel, category_slug, category_id)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    if scraper.expected_count is not None:
                        total_expected += scraper.expected_count
                        flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH"
                        print(f"  -> {category_slug}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category_slug}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_slug}: {e}")

    if total_expected:
        print(f"TOTAL: scraped {total_scraped} / site says {total_expected}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
