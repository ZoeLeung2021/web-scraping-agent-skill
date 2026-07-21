"""
Scraper for DM Diplomat Duty Free (South Korea) — https://www.dmddf.com

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/dm_diplomat_duty_free_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: site name is literally "DM Diplomat Duty Free"
    (`dmddf` = DM Diplomat Duty Free), a duty-free operation serving the
    diplomatic community in Korea (`"addressCountry": "KR"` in the page's
    embedded schema.org JSON-LD). Market = "GTR", Country = "DF South Korea".
    Single shop, no multi-location split found. Channel fixed 2026-07-21
    to "South Korea Diplomatic Services" (was "N/A") — GTR_Pricing's real
    diplomatic-shop convention is "<Region> Diplomatic Services" (Peter
    Justesen/Denmark uses "Europe Diplomatic Services"); user chose
    country-specific naming over broad-region for this project's
    diplomatic builds. See feedback_channel_naming_airports memory.
  - Platform is imweb (a Korean website-builder/e-commerce CMS,
    `cdn.imweb.me`), not WooCommerce/Shopify.
  - Alcohol taxonomy: top-level "LIQUOR" nav item, with these 13 real
    subcategory pages found via the site's own nav (confirmed live, each
    fetched and checked independently — counts genuinely vary per
    subcategory, from 1 to 24 items, ruling out a shared display cap):
    SINGLEMALT_WHISKY, BLENDED_WHISKY, wine_red, wine_white, wine_rose,
    cognac, gin, vodka, champagne, rum, beer, korean_liquor,
    chinese_liquor. The combined "LIQUOR_HOME" landing page is a curated
    "best of" showcase (repeats the same few products across several
    carousel sections) — NOT a full listing, so this scraper loops the 13
    real subcategory pages instead, not the LIQUOR_HOME page.
  - Each product card is `<div class="shop-item _shop_item"
    data-product-properties="{&quot;idx&quot;:866,&quot;code&quot;:...,
    &quot;name&quot;:...,&quot;original_price&quot;:38,&quot;price&quot;:27,
    &quot;image_url&quot;:...}">` — a clean structured JSON attribute per
    card, parsed directly here rather than the visible DOM price/title
    spans (more reliable, same lesson as Attenza Duty Free's raw-data
    JSON this session). `idx` is the numeric product ID (also usable to
    build the product URL as `/<category>/?idx=<idx>`); `code` is an
    internal product code; `original_price`/`price` are already plain
    numbers (no currency symbol to strip) — confirmed the visible price
    spans show `$` (USD) throughout, so these numeric fields are USD.
  - Size is NOT a separate field anywhere. Spirits/whisky product names
    often embed it directly (e.g. "JACK DANIELS GENTLEMAN JACK 1L"), but
    wine product names checked (e.g. "Kvareli", "Otskhanuri Sapere") do
    not include any size at all — left for the cleaner's regex fallback
    to extract when present, null otherwise (no guessing).
  - No age-verification gate and no cookie-consent banner block this
    site's product listing pages — only internal login-state cookie logic
    was found, not a user-facing modal.
  - No GTR-exclusive badge/ribbon/"exclusive" text found anywhere in the
    product card markup or its JSON — left out of every row so the
    cleaner emits a true null for the whole column. A "NEW"/"ON SALE"
    badge exists (`.prod_icon.sale`) but that's an ordinary promotional
    flag, not an exclusivity signal.
  - No genuine "N items"/"Showing X of Y" total count exists anywhere on
    these subcategory pages — get_expected_item_count() returns None.
    Confirmed via a live scroll test that these pages render every
    matching product in one shot (stable count across 8+ scroll attempts,
    no infinite-scroll growth) — no pagination mechanism needed at all.
"""

import html
import json
import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import io

RETAILER_SLUG = "dm_diplomat_duty_free"
BASE_URL = "https://www.dmddf.com"

# Single shop, no location split found.
LOCATIONS = {
    "South Korea": ["South Korea Diplomatic Services"],
}

# 13 real alcohol subcategory slugs confirmed via the site's own nav — see
# module docstring for why the combined LIQUOR_HOME page isn't used instead.
CATEGORIES = [
    "SINGLEMALT_WHISKY", "BLENDED_WHISKY",
    "wine_red", "wine_white", "wine_rose",
    "cognac", "gin", "vodka", "champagne", "rum", "beer",
    "korean_liquor", "chinese_liquor",
]


class DMDiplomatDutyFreeScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/{self.category}"

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

    def get_expected_item_count(self):
        """No genuine per-category total count exists anywhere on this
        site — see module docstring. Returns None."""
        return None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="shop-item")

        for card in cards:
            product_dict = {}
            try:
                raw_props = card.get("data-product-properties")
                props = json.loads(html.unescape(raw_props)) if raw_props else {}
            except (TypeError, json.JSONDecodeError):
                props = {}

            idx = props.get("idx")
            product_dict["ID_raw"] = str(idx) if idx is not None else props.get("code")
            product_dict["Brandline"] = props.get("name")
            product_dict["Brand"] = None
            product_dict["Product_link"] = (
                f"{BASE_URL}/{self.category}/?idx={idx}" if idx is not None else None
            )

            original_price = props.get("original_price")
            price = props.get("price")
            product_dict["Strike Price"] = str(original_price) if original_price is not None else None
            product_dict["Price Discounted"] = str(price) if price is not None else product_dict["Strike Price"]

            # No GTR-exclusive concept found anywhere on this site — see
            # module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
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

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category in CATEGORIES:
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category}")
                scraper = DMDiplomatDutyFreeScraper(channel, category)
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
                        print(f"  -> {category}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category}: {e}")

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
