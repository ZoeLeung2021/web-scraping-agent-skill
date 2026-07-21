"""
Scraper for Silk Road Duty Free (Georgia) — https://dutyfree.ge/products/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/silk_road_duty_free_georgia_scraper.py once validated
(this repo — web-scraping-agent-skill — is where retailer outputs are
drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - This is a Squarespace commerce site. Product cards are
    <div class="product-list-item" data-product-id="...">, where
    data-product-id is Squarespace's own stable 24-char item ID — reliable,
    no need for the Product_link digit-extraction fallback here.
  - The alcohol categories are already isolated by URL: /products/spirits,
    /products/wine, /products/beer. The site's other categories
    (confectionery, tobacco, perfume, cosmetics, fashion, toys, accessories)
    are excluded — this pipeline scrapes alcohol pricing only.
  - Prices are shown in EUR (€) directly on the listing card, single price
    only — no strike-through/original-price markup was found anywhere in
    the Spirits category (69/69 products used the identical price
    container class, no "sale" modifier class on any of them). Strike_Price
    is left null for this site; revisit if a discounted item is ever found.
  - No age-verification gate and no cookie-consent banner were found on
    either the listing or a product detail page — simpler than most
    duty-free sites in this repo, nothing to dismiss.
  - The listing page loads products asynchronously and the count is
    genuinely flaky to a fixed sleep: one inspection got only 20/69 items
    after a wait, a later one got 69/69 with a similar wait. There's no
    real pagination or scroll-triggered loading involved — it's just a
    render-timing race. wait_for_all_products() below polls until the
    product-card count stops changing rather than trusting a fixed delay.
  - Size is NOT on the listing page. Each product's detail page has
    <div class="product-description hidden-down-md">35% 12/1L</div> (ABV%
    and pack/volume, e.g. "12/1L" = case of 12 x 1L). This scraper visits
    every product's detail page to capture that raw text as Size — the
    paired cleaner's existing size-from-text fallback already extracts the
    volume (e.g. "1L") from strings shaped like this.
  - The retailer operates three physical shops (Tbilisi, Batumi, Poti) but
    sells through one unified online catalog with no per-shop pricing or
    URLs visible — modeled as one combined scrape pass rather than three
    separate ones, consistent with how other single-catalog retailers in
    this repo (e.g. Cloud 9 Laos) are modeled. Channel is "Georgia Duty
    Free" (updated 2026-07-21 per this project's standing airport/channel
    naming rule — see feedback_channel_naming_airports memory), matching
    GTR_Pricing's real "<Country> Duty Free" convention used for other
    combined-channel/no-split national retailers (e.g.
    big_five_south_africa_scraper.py -> "South Africa Duty Free",
    romania_best_value_scraper.py -> "Romania Duty Free") — Poti is a
    seaport, not an airport, so the airport-specific IATA-code format
    doesn't apply here; this is a genuinely different, non-airport
    convention for combined multi-location retailers.
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

RETAILER_SLUG = "silk_road_duty_free_georgia"
BASE_URL = "https://dutyfree.ge"

# Single unified online catalog — no per-shop pricing/URL split found.
LOCATIONS = {
    "Georgia": ["Georgia Duty Free"],
}

# Already alcohol-only category URLs — no scoping needed beyond this list.
CATEGORIES = {
    "Spirits": "/products/spirits",
    "Wine": "/products/wine",
    "Beer": "/products/beer",
}


class SilkRoadDutyFreeGeorgiaScraper:
    def __init__(self, category_path):
        self.category_path = category_path
        self.product_dicts = []
        self.expected_count = None  # from get_expected_item_count(), for validation only

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
        self.driver.get(f"{BASE_URL}{self.category_path}")
        time.sleep(4)

    def wait_for_all_products(self, max_wait_seconds=25, poll_interval=1.5):
        """Confirmed live: the listing renders products asynchronously and
        a fixed sleep is unreliable (one check got 20/69, another got
        69/69 with similar waits). Poll until the card count stops
        changing across two consecutive checks instead of trusting a delay."""
        last_count = -1
        stable_checks = 0
        elapsed = 0.0
        while elapsed < max_wait_seconds:
            time.sleep(poll_interval)
            elapsed += poll_interval
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            count = len(soup.find_all("div", class_="product-list-item"))
            if count == last_count and count > 0:
                stable_checks += 1
                if stable_checks >= 2:
                    return
            else:
                stable_checks = 0
            last_count = count

    def get_expected_item_count(self):
        """Reads the "N Results" total the category page itself displays —
        confirmed present on this storefront. Used to validate scrape
        coverage; not part of the product data."""
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        result_count_el = soup.find("span", class_="product-list-result-count")
        if not result_count_el:
            return None
        match = re.search(r"(\d+)\s*Results?", result_count_el.get_text())
        return int(match.group(1)) if match else None

    def get_listing(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="product-list-item")

        for card in cards:
            item = {}
            try:
                item["ID_raw"] = card.get("data-product-id")
            except Exception:
                item["ID_raw"] = None
            try:
                link_el = card.find("a", class_="product-list-item-link")
                item["_href"] = link_el["href"]
                item["Product_link"] = BASE_URL + link_el["href"]
            except Exception:
                item["_href"] = None
                item["Product_link"] = None
            try:
                item["Brandline"] = card.find("div", class_="product-list-item-title").get_text(strip=True)
            except Exception:
                item["Brandline"] = None
            item["Brand"] = None  # not exposed anywhere on this site — see module docstring
            try:
                item["Price Discounted"] = card.find("div", class_="product-list-item-price").get_text(strip=True)
            except Exception:
                item["Price Discounted"] = None
            item["Strike Price"] = None  # no strike-through markup found on this site
            item["GTR_exclusive"] = None  # no exclusivity badge found on this site

            self.product_dicts.append(item)

        return len(cards)

    def fill_in_sizes(self):
        """Size lives only on each product's detail page — visit every one
        collected by get_listing() and merge the raw "35% 12/1L"-style
        description text in. Uses a fresh page load per product rather than
        a second browser session; the paired cleaner already knows how to
        pull a size out of free text like this."""
        for item in self.product_dicts:
            if not item.get("_href"):
                item["Size"] = None
                continue
            try:
                self.driver.get(BASE_URL + item["_href"])
                time.sleep(2)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                desc_el = soup.find("div", class_="product-description")
                item["Size"] = desc_el.get_text(strip=True) if desc_el else None
            except Exception:
                item["Size"] = None
            finally:
                item.pop("_href", None)

    def run_all(self):
        try:
            self.open_website()
            self.wait_for_all_products()
            self.expected_count = self.get_expected_item_count()
            self.get_listing()
            self.fill_in_sizes()
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
            for category_name, category_path in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_name}")
                scraper = SilkRoadDutyFreeGeorgiaScraper(category_path)
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
                        print(f"  -> {category_name}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category_name}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {category_name}: {e}")

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
