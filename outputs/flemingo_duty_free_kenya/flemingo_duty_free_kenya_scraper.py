"""
Scraper for Flemingo Duty Free (Kenya) — https://flemingodutyfree.ke/alcohol/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/flemingo_duty_free_kenya_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

This is one of 3 "Flemingo" duty-free sites the user asked to scrape
together (India/godutyfree.in, Kenya/flemingodutyfree.ke, Sri Lanka/
flemingodutyfreecolombo.com). CONFIRMED via a live platform comparison
across all 3 that they run on genuinely different codebases — Kenya is
WordPress/WooCommerce (Woodmart theme), India is a custom in-house
template ("Go Duty Free" branding, no CMS markers found), Sri Lanka is a
custom PHP/Laravel-style template (leftover placeholder meta tags like
"Your Company Name"/"yourwebsite.com" found in its <head>). Per this
project's standing rule ("check the actual HTML/platform before assuming
sites can be combined; if genuinely different, keep them separate" —
confirmed necessary for Travel FREE Bordershop earlier this session too),
these are 3 separate scraper files, not one combined script.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: site title is "Alcohol - FLEMINGO DUTY FREE KENYA" — an
    airport duty-free operator. Market = "GTR", Country = "DF Kenya".
    Single location, no branch split found. Channel confirmed 2026-07-21
    via a live page-text check: the site references "TERMINAL 1B GATE 12"
    — Terminal 1B is part of Nairobi's Jomo Kenyatta International
    Airport, so Channel is set to "Nairobi Jomo Kenyatta International
    Airport (NBO)", matching this exact string already used in
    GTR_Pricing's Dufry_Africa_cleaner.py CHANNEL_MAP for the same
    airport.
  - Platform is WordPress + WooCommerce, Woodmart theme — the EXACT same
    theme already used by Diplomatic Shop (Serbia), built earlier this
    session. Product card markup is structurally identical:
    `<div class="wd-product ... product-grid-item product type-product
    post-<ID> ... product_cat-alcohol product_cat-<subcat> ...
    data-id="<ID>">`. Title from `h3.wd-entities-title a` (bundles
    brand+name+ABV%+size into one string, e.g. "100 Pipers Whisky 40% Nrf
    100 Cl" — no separate Brand field, same as Diplomatic Shop). Real SKU
    via the add-to-cart link's `data-product_sku` attribute (e.g.
    "02A05E25P001-00002"). Price via `span.price
    .woocommerce-Price-amount` — single price, no `<del>`/`<ins>`
    strike-through markup found anywhere. Currency is USD (`$`).
  - The "alcohol" category page shows exactly 12 products with NO
    pagination widget anywhere in the DOM (no `.woocommerce-result-count`,
    no `.page-numbers`, no "Load more" button) — confirmed this is a
    single-page category, not a truncated/capped view (WooCommerce omits
    pagination markup entirely when there's only one page, same reasoning
    already used for single-page retailers elsewhere in this repo, e.g.
    Silk Road Duty Free). No coverage-count text exists to validate
    against; confidence instead comes from there being no pagination
    control to follow.
  - No GTR-exclusive badge/ribbon/"exclusive" text found anywhere on the
    category page — left unset for every row so the cleaner emits a true
    null for the whole column.
  - No age gate or cookie banner found blocking this category page.
"""

import os
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "flemingo_duty_free_kenya"
BASE_URL = "https://flemingodutyfree.ke"

LOCATIONS = {
    "Kenya": ["Nairobi Jomo Kenyatta International Airport (NBO)"],
}
CATEGORIES = ["alcohol"]


class FlemingoDutyFreeKenyaScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/{self.category}/"

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
        time.sleep(5)

    def get_expected_item_count(self):
        """No genuine total-count display exists — this is a single-page
        category with no pagination widget at all (see module
        docstring). Returns None."""
        return None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="product-grid-item")

        for card in cards:
            product_dict = {}
            try:
                title_el = card.select_one("h3.wd-entities-title a")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Product_link"] = title_el["href"] if title_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Brandline"] = None
                product_dict["Product_link"] = None
            product_dict["Brand"] = None

            try:
                add_to_cart = card.find("a", class_="add-to-cart-loop") or card.find("a", class_="add_to_cart_button")
                sku = add_to_cart.get("data-product_sku") if add_to_cart else None
                pid = card.get("data-id") or (add_to_cart.get("data-product_id") if add_to_cart else None)
                product_dict["ID_raw"] = sku if sku else pid
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None

            try:
                price_el = card.select_one("span.price .woocommerce-Price-amount")
                price_text = price_el.get_text(strip=True) if price_el else None
                product_dict["Strike Price"] = price_text
                product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive badge/ribbon found anywhere on this site —
            # see module docstring. Deliberately not set here.

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
                scraper = FlemingoDutyFreeKenyaScraper(channel, category)
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
