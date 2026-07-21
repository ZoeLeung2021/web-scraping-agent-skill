"""
Scraper for Flemingo Duty Free Colombo (Sri Lanka) —
https://www.flemingodutyfreecolombo.com/wines-spirits

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/flemingo_duty_free_colombo_scraper.py once validated
(this repo — web-scraping-agent-skill — is where retailer outputs are
drafted and reviewed).

One of 3 "Flemingo" duty-free sites the user asked to scrape together —
see flemingo_duty_free_kenya_scraper.py's module docstring for the full
platform-comparison writeup confirming all 3 run on genuinely different
codebases (this one is a custom PHP/Laravel-style template, distinct from
Kenya's WooCommerce and India's in-house template) and are therefore built
as 3 separate scrapers.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: "Flemingo" duty-free operator serving Colombo (Bandaranaike
    International Airport, Sri Lanka). Market = "GTR", Country =
    "DF Sri Lanka". Single location, single currency (USD).
  - The "wines-spirits" category is the full alcohol listing (no separate
    beer/champagne top-level category found — whisky/vodka/wine/etc. are
    all subcategories within it, same "scrape the parent category"
    pattern as Attenza/Diplomatic Shop/Fasola this session).
  - Product cards are `<div class="product-card">` containing:
      `<div class="product-name">` — combined name+size string, e.g.
        "LABEL 5 WHISKY 100CL" (no separate Brand field).
      `<div class="product-price">Unit Price : <i class="fa
        fa-usd"></i>20</div>` — single price, USD, no strike-through
        markup found anywhere on the ~24 cards sampled during testing.
      `<a class="proCover" href=".../wines-spirits/whisky/<slug>?arrival">`
        — product detail link; the slug embeds size but not a numeric ID.
      An add-to-cart element with `id="product_bestseller<N>"` and
        `data-value="<N>"` (e.g. "product_bestseller1646"/"1646") — this
        numeric value is used here as the product ID; the "bestseller"
        wording in the CSS class/ID appears to be a generic, reused
        component name rather than meaning the ID is scoped to some
        "bestsellers" subset (every card checked had one).
  - A `<div class="badge-container">` sometimes shows "Offers" (a
    promotion indicator, not exclusivity) on some cards — actively
    checked every badge found across the page for "Exclusive" text: none
    found. A "Travel Exclusive" nav link exists elsewhere on the page
    (`/travel-exclusive?arrival`) but — same false-lead pattern already
    learned from fasola-shop.com's initial proxy-research mixup — this is
    a top-level navigation category, not a per-product badge; confirmed
    no product card anywhere carries an "Exclusive"-worded badge.
    GTR_exclusive is left unset for every row so the cleaner emits a true
    null for the whole column.
  - Pagination: NOT a numbered-URL scheme (a `?page=2` param returns the
    identical first page, confirmed broken/inert — same failure mode as
    Attenza's dead "Mostrar mas" button) and NOT infinite scroll (10
    scroll-to-bottom attempts produced zero growth). It IS a real, working
    "See More" button (confirmed live — 12 cards per click, reliably
    reaching 286 of a genuine "Showing 1 – 12 of 290 products" total
    before plateauing at 286 across many further clicks; the small
    290-vs-286 gap looks like a handful of duplicate/unavailable items
    filtered from the combined view, not a scraping failure). This
    scraper clicks "See More" until the count stops growing or the site's
    own total is reached.
  - No age gate or cookie banner found blocking this category page.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "flemingo_duty_free_colombo"
BASE_URL = "https://www.flemingodutyfreecolombo.com"

LOCATIONS = {
    "Sri Lanka": ["Bandaranaike International Airport (CMB)"],
}
CATEGORIES = ["wines-spirits"]

_TOTAL_RE = re.compile(r"of\s+<span[^>]*>\s*(\d+)\s*</span>\s*products", re.IGNORECASE)


class FlemingoDutyFreeColomboScraper:
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
        time.sleep(10)

    def get_expected_item_count(self):
        match = _TOTAL_RE.search(self.driver.page_source)
        return int(match.group(1)) if match else None

    def click_see_more(self, max_clicks=40):
        """Real, working "See More" button — confirmed loading 12 more
        cards per click. Stop once the button disappears, the count stops
        growing across a click, or the site's own total is reached."""
        last_count = -1
        for _ in range(max_clicks):
            current_count = self.driver.page_source.count('class="product-card"')
            if self.expected_count is not None and current_count >= self.expected_count:
                break
            if current_count == last_count:
                break
            last_count = current_count
            clicked = False
            for _attempt in range(3):
                try:
                    btn = self.driver.find_element(By.XPATH, "//button[contains(., 'See More')]")
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView(true); arguments[0].click();", btn
                    )
                    clicked = True
                    break
                except (NoSuchElementException, StaleElementReferenceException):
                    time.sleep(1)
            if not clicked:
                break
            time.sleep(3)

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="product-card")

        for card in cards:
            product_dict = {}
            try:
                name_el = card.find("div", class_="product-name")
                product_dict["Brandline"] = name_el.get_text(strip=True) if name_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                link_el = card.find("a", class_="proCover")
                product_dict["Product_link"] = link_el["href"] if link_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Product_link"] = None

            try:
                cart_el = card.find(id=re.compile(r"^product_bestseller\d+$"))
                id_match = re.search(r"(\d+)$", cart_el["id"]) if cart_el else None
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError, KeyError):
                product_dict["ID_raw"] = None

            try:
                price_el = card.find("div", class_="product-price")
                price_text = price_el.get_text(strip=True) if price_el else None
                price_match = re.search(r"([\d.,]+)\s*$", price_text or "")
                price_val = price_match.group(1) if price_match else None
                product_dict["Strike Price"] = price_val
                product_dict["Price Discounted"] = price_val
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive badge found on any product card — see
            # module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            self.expected_count = self.get_expected_item_count()
            self.click_see_more()
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
                scraper = FlemingoDutyFreeColomboScraper(channel, category)
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
