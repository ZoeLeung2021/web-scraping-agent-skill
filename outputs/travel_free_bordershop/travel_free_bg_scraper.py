"""
Scraper for Travel FREE Bordershop — Bulgaria (https://travel-free.bg/).

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/travel_free_bg_scraper.py
once validated.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - Platform is OpenCart. Product container: <div class="product-layout">,
    containing a hidden <input class="product-id_<N>"> (stable numeric ID)
    and a <div class="product-thumb"> with the actual card content.
  - Alcohol categories: /spirtni-napitki (spirits), /vino (wine), /bira
    (beer) — confirmed live, no non-alcohol mixing found.
  - Prices are shown as combined "€X.XX / Y.YYлв." text — EUR is always
    present alongside BGN, no currency-switcher interaction needed; the
    cleaner extracts just the EUR portion.
  - Discount pricing is real and confirmed: <span class="price-old"> (only
    present when on sale) + <span class="price-regular"> (always present —
    the current/selling price whether or not there's a discount).
  - Language switch is a simple URL prefix, not a click interaction:
    prepend /en/ right after the domain, e.g.
    https://travel-free.bg/en/spirtni-napitki. Confirmed via the site's own
    EN language link (https://travel-free.bg/en/shops-information).
  - Pagination is a plain ?page=N query param (confirmed via
    <link rel="next" href=".../spirtni-napitki?page=2">).
  - The site has a "Смяна на магазин" (change shop) mechanism
    (?route=common/store&stores_id=N) for 3 of its physical shops. TESTED
    LIVE: switching stores_id (0, 1, 2) produced byte-identical prices and
    catalog for the same product — this is a pickup-location selector, not
    a per-shop pricing mechanism. Per explicit instruction, production runs
    still set stores_id and re-scrape once per real location (not just
    replicate one scrape) since the mechanism genuinely exists here, even
    though the output is expected to be identical across locations — unlike
    Czech Republic/Croatia, where no such per-location mechanism exists at
    all, so those two just replicate a single scrape instead.
  - No GTR-exclusive badge/ribbon/"Exclusives" category was found on this
    site during inspection — GTR_exclusive is left as None for every row
    (true null per the schema's three-way convention), not "".

UNCONFIRMED / best effort: only 3 of Bulgaria's ~8 physical border shops
have an associated stores_id in the online "change shop" mechanism (Kulata,
Kalotina, and a third labelled "KPV" in the site's own image folder names —
verify the full name for "KPV" before relying on it). The other ~5 physical
shops aren't represented in the online switcher at all, so they're not
included as Channel values here.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "travel_free_bg"
BASE_URL = "https://travel-free.bg"

CATEGORIES = {
    "Spirits": "/en/spirtni-napitki",
    "Wine": "/en/vino",
    "Beer": "/en/bira",
}

# Confirmed via the site's own store-switcher — only these 3 of ~8 physical
# shops have an associated stores_id. See module docstring re: "KPV".
LOCATIONS = {
    "Kulata": 0,
    "Kalotina": 1,
    "KPV": 2,
}


class TravelFreeBGScraper:
    def __init__(self, category_path, stores_id):
        self.category_path = category_path
        self.stores_id = stores_id
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        sep = "&" if "?" in self.category_path else "?"
        self.url = f"{BASE_URL}{self.category_path}" + (f"{sep}page={page}" if page > 1 else "")

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
        self.driver.set_page_load_timeout(30)
        # Set the active shop for this session before browsing the
        # category — confirmed not to change pricing/catalog, but the
        # production script still does this per real location on request.
        store_switch_url = (
            f"{BASE_URL}/index.php?route=common/store&stores_id={self.stores_id}"
            f"&language=en&return_url=%2F"
        )
        self.driver.get(store_switch_url)
        time.sleep(1)
        self.get_url(page=1)
        self.driver.get(self.url)
        time.sleep(3)

    def get_expected_item_count(self):
        """Reads the "Showing 1 to 20 of <N> (<M> Pages)" total this
        storefront displays (English, since the scraper browses via the
        /en/ prefix — the Bulgarian-language phrasing is "Показва ... от
        <N> ..." if ever needed). Used only to validate scrape coverage."""
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        text = soup.get_text()
        match = re.search(r"(?:of|от)\s+(\d+)\s*\(", text)
        return int(match.group(1)) if match else None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="product-layout")

        for card in cards:
            item = {}
            try:
                id_input = card.find("input", class_=re.compile(r"^product-id_\d+$"))
                item["ID_raw"] = id_input["class"][0].split("_")[-1] if id_input else None
            except Exception:
                item["ID_raw"] = None
            try:
                link_el = card.find("h4").find("a")
                item["Product_link"] = link_el["href"]
                item["Brandline"] = link_el.get_text(strip=True)
            except Exception:
                item["Product_link"] = None
                item["Brandline"] = None
            item["Brand"] = None  # not exposed separately on this site
            item["Size"] = None  # not exposed separately; cleaner falls back to Brandline text
            try:
                old_price_el = card.find("span", class_="price-old")
                item["Strike Price"] = old_price_el.get_text(strip=True) if old_price_el else None
            except Exception:
                item["Strike Price"] = None
            try:
                regular_price_el = card.find("span", class_="price-regular")
                item["Price Discounted"] = regular_price_el.get_text(strip=True) if regular_price_el else None
            except Exception:
                item["Price Discounted"] = None
            item["GTR_exclusive"] = None  # no exclusivity signal found anywhere on this site

            self.product_dicts.append(item)

        return len(cards)

    def run_all(self):
        try:
            self.open_website()
            self.expected_count = self.get_expected_item_count()

            page = 1
            while True:
                if page > 1:
                    self.get_url(page=page)
                    self.driver.get(self.url)
                    time.sleep(2)
                found = self.get_main()
                if found == 0:
                    break
                page += 1
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
    # Production: real per-location scrape (sets stores_id and re-visits
    # the catalog fresh for each of the 3 known shops), per explicit
    # instruction — even though this was empirically confirmed to return
    # identical data every time (see module docstring). For a quick local
    # test, it's fine to comment out entries in LOCATIONS to check just one.
    all_data = []
    total_expected = 0
    total_scraped = 0

    for location, stores_id in LOCATIONS.items():
        for category_name, category_path in CATEGORIES.items():
            print(f"Scraping {RETAILER_SLUG}: {location} (stores_id={stores_id}) / {category_name}")
            scraper = TravelFreeBGScraper(category_path, stores_id)
            try:
                scraper.run_all()
                scraped_at = datetime.now(timezone.utc).isoformat()
                for item in scraper.product_dicts:
                    item["Country"] = "Bulgaria"
                    item["Channel"] = location
                    item["Scraped_At"] = scraped_at
                all_data.extend(scraper.product_dicts)
                scraped_count = len(scraper.product_dicts)
                total_scraped += scraped_count
                if scraper.expected_count is not None:
                    total_expected += scraper.expected_count
                    flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH"
                    print(f"  -> {category_name}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                else:
                    print(f"  -> {category_name}: scraped {scraped_count} / site total unknown")
            except Exception as e:
                print(f"FAILURE scraping {location}/{category_name}: {e}")

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
