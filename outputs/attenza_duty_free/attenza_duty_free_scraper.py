"""
Scraper for Attenza Duty Free — https://attenza.net/shop/licores/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/attenza_duty_free_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: "Attenza Duty Free" name, meta description "libre de
    impuestos" (tax-free) and "Reserva para recoger directamente en el
    aeropuerto" (reserve for airport pickup) — unambiguous. Market = "GTR",
    Country gets the "DF " prefix in the cleaner.
  - 3 locations total, confirmed exhaustive via the site's own location
    filter JSON (`{"field": "locations", "title": "Aeropuerto", "values":
    [...]}`) — id 6 = "Colombia - Bogotá", id 5 = "Ecuador - Quito", id 7 =
    "El Salvador" (no specific airport named for this one). Matches exactly
    the 3 URLs the user provided — this is the full list, not a subset.
  - Single alcohol category covers everything: "licores" (Spanish for
    "liquors/spirits", `levels=3vFXVDxmZ8PXJAuXZcuT` in the URL). Confirmed
    via the site's top nav (`/shop/accesorios/`, `/chocolates/`,
    `/electronica/`, `/licores/`, `/nacionales/`, `/perfumes/`,
    `/relojeria/` — no separate wine/beer/champagne top-level category
    exists). Wine, Champagne, Whisky, Vodka, Rum, Gin, Tequila, Brandy/
    Cognac etc. are all just `level2` sub-filters *within* "licores", not
    separate categories to loop over.
  - Each product card (`<article class="clkec-product-item js-product-<ID>">`)
    carries a hidden `<input name="raw-data" value="{...html-escaped JSON...}">`
    with a full structured product object — far more reliable than parsing
    the rendered DOM text (which has separate Brand/title/size/price spans
    that would need individual selectors and are prone to formatting
    quirks). This scraper parses that JSON directly. Confirmed fields used:
    `code` (SKU), `name`, `content` (size, e.g. "1000 ML"), `base_price`
    (pre-discount), `price` (current/selling), `brand.name`, and
    `flags.is_exclusive` (a real per-product boolean — see GTR_exclusive
    note below).
  - GTR_exclusive: the raw-data JSON's `flags.is_exclusive` boolean is a
    genuine, always-present per-product signal (confirmed via a live
    sample and corroborated by a real "Exclusivo" filter checkbox on the
    page) — this is the cleanest GTR_exclusive signal found on any retailer
    this session, no ribbon/badge-hunting needed. Maps directly to the
    schema's Yes/No convention.
  - Pagination: CONFIRMED BLOCKED/UNRESOLVED — every location's "licores"
    listing shows exactly 35 products, and nothing changes that: neither
    the `&page=2/3/4/5` URL param (identical product IDs returned every
    time), nor clicking the visible "Mostrar mas" ("Show more") button via
    plain JS `.click()`, real `ActionChains` mouse click, or a direct
    jQuery `.trigger('click')` call — the button has no click handler
    bound to it at all in the captured DOM. A `level2` subcategory filter
    query param also didn't change the result set. Per user's explicit
    decision (2026-07-15), this scraper treats 35 as the genuine per-
    location total and does NOT attempt further pagination — revisit if a
    later validation run suggests the real catalog is larger than what's
    captured here.
  - Also confirmed: Colombia (location 6) and Ecuador (location 5) return
    byte-identical 35-item product sets; El Salvador (location 7) only
    differs by 6 of 35 items from the other two. This may mean the
    `locations` filter itself isn't reliably applied server-side (rather
    than each country genuinely stocking near-identical inventory) — per
    user's explicit decision (2026-07-15), this scraper still loops and
    tags each location as a separate Country/Channel regardless (same
    precedent as Travel FREE Bulgaria's byte-identical locations earlier
    this session) — the pipeline stays architecturally correct even if
    today's snapshot happens to overlap heavily; production behavior may
    differ.
  - No age-verification gate found. A `#CookieModal` cookie-consent overlay
    exists but doesn't block `page_source` parsing (BeautifulSoup reads the
    full HTML regardless of visual overlay state) — dismissed anyway for
    cleanliness, not because it's functionally required.
  - Currency: scraped with `pc=US%24` (USD) fixed for all 3 locations,
    matching the URLs the user provided — this is a Duty Free chain that
    quotes all listed locations in USD by default, not local currency.
"""

import html
import json
import os
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient
import io

RETAILER_SLUG = "attenza_duty_free"
BASE_URL = "https://attenza.net"
LICORES_LEVEL_ID = "3vFXVDxmZ8PXJAuXZcuT"

# Confirmed exhaustive via the site's own "Aeropuerto" location filter —
# see module docstring. Value is the numeric location id used in the URL.
LOCATIONS = {
    "Colombia": ["6"],
    "Ecuador": ["5"],
    "El Salvador": ["7"],
}

# Single alcohol category covers the whole site — see module docstring.
CATEGORIES = ["licores"]


class AttenzaDutyFreeScraper:
    def __init__(self, location_id, category):
        self.location_id = location_id
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = (
            f"{BASE_URL}/shop/{self.category}/"
            f"?levels={LICORES_LEVEL_ID}&lang=es&pc=US%24&locations={self.location_id}&page=1"
        )

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.driver.set_page_load_timeout(60)
        self.get_url()
        try:
            self.driver.get(self.url)
        except Exception:
            pass
        time.sleep(6)

    def dismiss_cookie_modal(self):
        self.driver.find_element(By.ID, "CookieModalClose").click()

    def get_expected_item_count(self):
        """No genuine per-location/category total display found anywhere
        on this site — the pagination is broken/inert (see module
        docstring), so there's no "Showing X of Y" text to read either.
        Returns None; coverage confidence for this retailer comes only
        from confirming the card count matches across repeated fetches,
        not from an independent site-displayed total."""
        return None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("article", class_="clkec-product-item")

        for card in cards:
            product_dict = {}
            try:
                raw_input = card.find("input", attrs={"name": "raw-data"})
                raw_json = json.loads(html.unescape(raw_input["value"])) if raw_input else {}
            except (AttributeError, TypeError, KeyError, json.JSONDecodeError):
                raw_json = {}

            try:
                link_el = card.find("a", href=True)
                product_dict["Product_link"] = BASE_URL + link_el["href"] if link_el else None
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None

            product_dict["ID_raw"] = raw_json.get("code")
            product_dict["Brandline"] = raw_json.get("name")
            product_dict["Brand"] = (raw_json.get("brand") or {}).get("name")
            product_dict["Size"] = raw_json.get("content")

            base_price = raw_json.get("base_price")
            price = raw_json.get("price")
            product_dict["Strike Price"] = str(base_price) if base_price is not None else None
            product_dict["Price Discounted"] = str(price) if price is not None else (
                product_dict["Strike Price"]
            )

            # A genuine, always-present per-product boolean (see module
            # docstring) — set as a real string per row since the site
            # tracks this concept for every product, matching the schema's
            # three-way convention (the cleaner turns this into Yes/No).
            is_exclusive = (raw_json.get("flags") or {}).get("is_exclusive")
            product_dict["GTR_exclusive"] = "true" if is_exclusive else "false"

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            try:
                self.dismiss_cookie_modal()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
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

    for country, location_ids in LOCATIONS.items():
        for location_id in location_ids:
            for category in CATEGORIES:
                print(f"Scraping {RETAILER_SLUG}: {country} / location={location_id} / {category}")
                scraper = AttenzaDutyFreeScraper(location_id, category)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = location_id
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    if scraper.expected_count is not None:
                        total_expected += scraper.expected_count
                        flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH"
                        print(f"  -> {category}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{location_id}/{category}: {e}")

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
