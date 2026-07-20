"""
Scraper for SuperAlko (Latvia) — https://superalko.lv/shop

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/superalko_latvia_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - This is a Domestic retailer (superalko.lv is a plain Latvian online
    liquor shop, no "duty free"/"travel retail"/"bordershop" language
    anywhere) — Market = "Domestic" in the paired cleaner, not "GTR".
  - Single online catalog, one country, no per-branch/location split found
    — modeled as a single "N/A" channel like other single-catalog retailers
    (e.g. Cloud 9 Laos, Silk Road Duty Free).
  - Language switch is a plain link, not a dropdown/JS toggle:
    https://superalko.lv/locale/en (also /lv, /fi, /est, /rus). Visiting
    this URL once at the start of each session sets the site to English for
    the rest of that browser session/cookie lifetime.
  - Age gate: a modal with a single button <button id="ageBtn"> — clicking
    it dismisses the whole modal (age + an inert, already-hidden cookie
    section). No dropdown/DOB picker involved.
  - Alcohol categories confirmed via the site's own nav, scoped by
    ?category=<code>: strong-alcohol, wine, beer, cider, long-drinkcocktail,
    liqueur. Excluded (non-alcohol or non-category-specific): gift-ideas,
    non-alcoholic-beverages, food, and exclusive-drinks (a curated marketing
    subset that overlaps the categories above — including it would just
    duplicate products already scraped under their real category, not add
    new ones).
  - Product cards are <div class="item"> inside <div id="shop-content">.
    Each card exposes clean, hidden-input fields inside its add-to-cart
    form — far more reliable than the visibly-rendered (and mojibake-prone,
    e.g. "20.99â‚¬") price text:
      <input type="hidden" name="products_id" value="10595">
      <input type="hidden" name="products_price" id="products_price" value="20.99">
    No separate strike/original-price field was found anywhere on the site
    (grepped for "old_price"/"discount_price"/"special_price"-style
    fields — only cart-subtotal JS used "discount", not a per-product
    field) — Strike_Price and Price_Discounted are the same raw value here.
  - Product title (from the card's <h1><a>) is the only name field — there's
    no separate Brand field anywhere, e.g. "Macaronesian White 37,5% 70cl".
    Brand is left null and the full title becomes Brandline, same
    convention as Silk Road Duty Free (Georgia).
  - Size and ABV are both embedded directly in the product title/attribute
    list rather than as clean separate fields:
      - Size: each card's <ul class="info"> has an <li> pair of
        <span class="attribute-heading">Tilpums</span><span>0.7L</span> —
        rather than matching the Latvian heading text (which won't survive
        the English locale switch reliably), this scraper scans every
        <li>'s value span for one shaped like a volume (e.g. "0.7L") with a
        regex, independent of the heading label.
      - ABV: pulled straight out of the title text via regex (e.g. "37,5%"
        in "Macaronesian White 37,5% 70cl") — confirmed present on every
        product checked. Needed by the paired cleaner's Latvian excise-duty
        (VID) formula, which is banded by ABV%.
  - GTR_exclusive: actively checked for a real per-product exclusivity
    badge/ribbon (per the schema's "look properly" rule) — none found
    anywhere in the card markup. There IS a nav category called
    "Ekskluzīvi Dzērieni" ("Exclusive Drinks", ?category=exclusive-drinks),
    but that's a curated marketing subset (like "Wine" or "Beer" — a
    regular product category), not a per-SKU travel-retail-exclusive tag,
    and this schema field specifically means GTR/travel-retail exclusivity.
    SuperAlko has no such concept — left out of every row so the cleaner
    emits a true null for the whole column.
  - Pagination is scroll-triggered AJAX, not numbered pages: a hidden
    <a href="#" id="load_products"> sentinel gets auto-clicked by the page's
    own JS the moment it scrolls into the viewport (a `scroll` event
    listener checking getBoundingClientRect, see page source), which POSTs
    to /filterProducts and appends more .item cards to #shop-content.
    Confirmed a plain JS `window.scrollTo(0, document.body.scrollHeight)`
    reliably fires native `scroll` events in headless Chrome (same lesson
    learned on CDFG Hong Kong — see references/testing.md) so this is used
    instead of send_keys(Keys.END).
  - Expected item count: <input id="total_record" type="hidden" value="...">
    looks like a per-category total but is CONFIRMED NOT ONE — it returned
    the identical value (4783) for every one of the 6 alcohol categories
    checked, i.e. it's a fixed sitewide constant unaffected by the
    ?category= filter. get_expected_item_count() returns None rather than
    this misleading number; this site has no genuine independent
    per-category count anywhere on the page to validate coverage against.
    Coverage confidence instead comes from the scroll loop only stopping
    once the AJAX-loaded item count is stable across several consecutive
    scrolls (see paginate_or_scroll).
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "superalko_latvia"
BASE_URL = "https://superalko.lv"

# Single unified online catalog, no per-branch split found.
LOCATIONS = {
    "Latvia": ["N/A"],
}

# Alcohol-only category codes confirmed from the site's own nav — see
# module docstring for what was excluded and why.
CATEGORIES = [
    "strong-alcohol",
    "wine",
    "beer",
    "cider",
    "long-drinkcocktail",
    "liqueur",
]

_SIZE_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:m?[lL])\s*$")
_ABV_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


class SuperAlkoLatviaScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/shop?category={self.category}"

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

        # Set English locale first — confirmed a plain link-based switch,
        # sticks for the rest of this browser session.
        try:
            self.driver.get(f"{BASE_URL}/locale/en")
            time.sleep(2)
        except Exception:
            pass

        self.get_url()
        try:
            self.driver.get(self.url)
        except Exception:
            pass
        time.sleep(3)

    def dismiss_age_verification(self):
        self.driver.find_element(By.ID, "ageBtn").click()

    def get_expected_item_count(self):
        """CONFIRMED this site's #total_record hidden input is NOT a
        per-category count despite looking like one — it returned the
        identical value (4783) for every one of the 6 alcohol categories
        checked, so it's a fixed sitewide constant, not filtered by the
        ?category= param. Using it as a coverage check would always show a
        false MISMATCH. This site has no genuine independent per-category
        total anywhere on the page — return None so the caller correctly
        reports "site total unknown" instead of a misleading number."""
        return None

    def paginate_or_scroll(self, max_scrolls=300, stable_target=3):
        """Scroll-triggered AJAX load — the page's own JS auto-clicks the
        #load_products sentinel once it's in the viewport. Keep scrolling
        to the bottom until the card count stops growing across several
        consecutive checks (or we hit the site's own reported total)."""
        last_count = -1
        stable_checks = 0
        expected = self.expected_count
        for _ in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            count = len(soup.select("#shop-content > div.item"))
            if expected is not None and count >= expected:
                break
            if count == last_count:
                stable_checks += 1
                if stable_checks >= stable_target:
                    break
            else:
                stable_checks = 0
            last_count = count

    def _extract_size(self, card):
        for li in card.select("ul.info li"):
            spans = li.find_all("span")
            if len(spans) >= 2:
                value = spans[-1].get_text(strip=True)
                if _SIZE_RE.match(value):
                    return value
        return None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.select("#shop-content > div.item")

        for card in cards:
            product_dict = {}
            try:
                title_el = card.select_one("h1 a")
                title_text = title_el.get_text(strip=True) if title_el else None
                product_dict["Brandline"] = title_text
                product_dict["Brand"] = None
                product_dict["Product_link"] = title_el["href"] if title_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None
                product_dict["Product_link"] = None

            try:
                id_input = card.find("input", attrs={"name": "products_id"})
                product_dict["ID_raw"] = id_input["value"] if id_input else None
            except (AttributeError, TypeError, KeyError):
                product_dict["ID_raw"] = None

            try:
                price_input = card.find("input", attrs={"name": "products_price"})
                price_val = price_input["value"] if price_input else None
                product_dict["Strike Price"] = price_val
                product_dict["Price Discounted"] = price_val
            except (AttributeError, TypeError, KeyError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            try:
                product_dict["Size"] = self._extract_size(card)
            except (AttributeError, TypeError):
                product_dict["Size"] = None

            try:
                abv_match = _ABV_RE.search(product_dict["Brandline"] or "")
                product_dict["ABV"] = abv_match.group(1).replace(",", ".") if abv_match else None
            except (AttributeError, TypeError):
                product_dict["ABV"] = None

            # Category is needed by the paired cleaner to pick the right
            # Latvian VID excise-duty band — not part of the final 17-column
            # schema, dropped there after Domestic_Tax is computed.
            product_dict["Category"] = self.category

            # No GTR/travel-retail-exclusivity concept found anywhere on
            # this site — see module docstring. Deliberately not set here
            # so the cleaner emits a true null for the whole column.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            time.sleep(2)
            try:
                self.dismiss_age_verification()
                time.sleep(1)
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
            self.paginate_or_scroll()
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
                scraper = SuperAlkoLatviaScraper(channel, category)
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
