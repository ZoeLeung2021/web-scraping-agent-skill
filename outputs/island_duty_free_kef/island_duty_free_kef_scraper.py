"""
Scraper for Ísland Duty Free (Keflavik International Airport, Iceland) —
https://www.islanddutyfree.is/en/global/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/island_duty_free_kef_scraper.py
(this repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed; GTR_Pricing is where they actually run).

VALIDATED 2026-07-14: ran end-to-end against the live site in a real headless
Chrome test environment (see the skill's SKILL.md notes on testing). Result:
976/976 items scraped across all 4 categories, exact match against the
site's own displayed "N Item(s)" counts — Beer & Cider 35/35, Whisky
179/179, Other Spirits 397/397, Wine & Champagne 365/365. Only the final
Databricks upload step wasn't exercised for real (no local credentials);
everything up to that point is confirmed working, not guessed.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source —
not just a non-JS-rendering fetch):
  - This is a Heinemann-platform storefront ("Heinemann Shop" in the page
    <title>) — same pattern as heinemann_denmark_scraper.py /
    heinemann_norway_scraper.py: a "c-product-card" container per product
    with an embedded "js-wishlist-payload js-track-payload" JSON blob
    (name, id, price, brand, category, metric1, dimension1-3). No dedicated
    size field in that JSON, confirmed — Size is embedded in the product
    title/Brandline instead (e.g. "...40% 0.7L with 2 Glasses"), matching
    the fallback already built into cleaner_template.py.
  - Product ID: JSON "id" is a clean numeric string (e.g. "1706609") —
    reliable, no need for the Product_link digit-extraction fallback here.
  - Alcohol category URLs follow /en/global/beverages/<slug>/c/kefcat_<code>/
    (Beer & Cider, Whisky, Other Spirits, Wine & Champagne — Soft Drinks and
    every non-alcohol top-level category, e.g. Beauty/Tobacco/Food/Toys, are
    deliberately excluded; this pipeline scrapes alcohol pricing only)
  - Prices are shown in ISK, and each category page displays a "<N> Item(s)"
    total count — used as the ground truth to validate scrape coverage
    against (see get_expected_item_count() below)
  - Pagination is confirmed: displayed page N links to ?page=N-1 (page 1 has
    no query param) — get_url() below matches the real pagination markup
  - Age gate ("you must be at least 20 years old", Yes/No) is a modal
    overlay rendered in the DOM regardless of dismissal — product cards are
    NOT nested inside it and are present in page_source either way. The
    real "Yes" button is `button[data-maturity-confirm]`. Since this
    scraper paginates via driver.get(url) rather than clicking pagination
    links, the overlay can't intercept any clicks either way — dismissing
    it is precautionary, not load-bearing, for this implementation.
  - Cookie consent is Usercentrics (shadow-DOM), confirmed present, same as
    the other Heinemann-platform scrapers in this repo.
  - Default site language is English ("EN - English" in the language
    switcher) — no translation step needed.

CONFIRMED (corrected 2026-07-14): "dimension3" in the JSON payload does
carry GTR-exclusive info on this storefront — a Glenfiddich product was
found with `"dimension3": "travel exclusive"`, and it visibly carries a
`<span class="c-ribbon c-ribbon--edition">Travel Edition</span>` badge
overlaid on its product image in the same card (inside
`<ul class="c-product-card__ribbons">`, right after the media wrapper).
The two signals agree, so dimension3 is reliable here — the earlier
products checked during initial inspection just happened to be
non-exclusive (blank dimension3). The site also has a whole separate
"Exclusives" nav category (e.g. /en/global/exclusives/exclusive-beverages-
and-food/exclusive-whiskys/c/kefcat_12406/) that could be cross-referenced
as a second signal, but wasn't needed once the ribbon/dimension3 match
was found. See clean_island_duty_free_kef.py for how this raw
"travel exclusive" string gets mapped to the schema's "GTR Exclusive"
convention.
"""

import os
import json
import re
import time
import io
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient

RETAILER_SLUG = "island_duty_free_kef"
BASE_URL = "https://www.islanddutyfree.is"

LOCATIONS = {
    "Iceland": ["Keflavik International Airport (KEF)"],
}

# Alcohol-only categories confirmed from the live Beverages menu.
CATEGORIES = {
    "Beer & Cider": "/en/global/beverages/beer-cider/c/kefcat_5500/",
    "Whisky": "/en/global/beverages/whisky/c/kefcat_5150/",
    "Other Spirits": "/en/global/beverages/other-spirits/c/kefcat_5010/",
    "Wine & Champagne": "/en/global/beverages/wine-champagne/c/kefcat_1100/",
}


class IslandDutyFreeKEFScraper:
    def __init__(self, category_path):
        self.category_path = category_path
        self.product_dicts = []
        self.expected_count = None  # from get_expected_item_count(), for validation only

    def get_url(self, page=1):
        if page > 1:
            # Confirmed pattern from the live pagination links: the visible
            # page number N links to ?page=N-1.
            self.url = f"{BASE_URL}{self.category_path}?q=%3Arelevance&page={page - 1}"
        else:
            self.url = f"{BASE_URL}{self.category_path}"

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
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
        self.driver.set_page_load_timeout(30)
        self.get_url(page=1)
        self.driver.get(self.url)
        time.sleep(3)

    def accept_cookies(self):
        # Confirmed: this site loads Usercentrics (same shadow-DOM pattern
        # as the other Heinemann-operated storefronts in this pipeline).
        accept_all = self.driver.execute_script(
            """return document.querySelector('#usercentrics-root').shadowRoot.querySelector("button[data-testid='uc-accept-all-button']")"""
        )
        accept_all.click()

    def confirm_age_gate(self):
        # Confirmed real selector: <button data-maturity-confirm ...>Yes</button>
        self.driver.find_element(By.CSS_SELECTOR, "button[data-maturity-confirm]").click()

    def get_expected_item_count(self):
        """Reads the "<N> Item(s)" total the category page itself displays —
        confirmed present on this storefront. Used to validate scrape
        coverage; not part of the product data."""
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        text_line = soup.find("div", class_="c-text-line")
        if not text_line:
            return None
        match = re.search(r"(\d+)\s*Item\(s\)", text_line.get_text())
        return int(match.group(1)) if match else None

    def get_main(self):
        page_html = self.driver.page_source
        soup = BeautifulSoup(page_html, "html.parser")
        # Confirmed real container class on this storefront.
        products = soup.find_all("div", class_="c-product-card")

        for product in products:
            try:
                payload = json.loads(
                    product.find("script", class_="js-wishlist-payload js-track-payload").string.strip()
                )
            except Exception:
                payload = {}

            item = {}
            try:
                item["Product_link"] = BASE_URL + product.find("a")["href"]
            except Exception:
                item["Product_link"] = None
            try:
                item["ID_raw"] = payload.get("id")
            except Exception:
                item["ID_raw"] = None
            try:
                item["Brand"] = payload.get("brand")
            except Exception:
                item["Brand"] = None
            try:
                item["Brandline"] = payload.get("name")
            except Exception:
                item["Brandline"] = None
            try:
                # No dedicated size field expected on this JSON payload
                # (matches the other Heinemann storefronts) — the paired
                # cleaner backfills Size from Brandline text, see
                # cleaner_template.py's _extract_size_from_text().
                item["Size"] = payload.get("size")
            except Exception:
                item["Size"] = None
            try:
                item["Strike Price"] = payload.get("metric1")
            except Exception:
                item["Strike Price"] = None
            try:
                item["Price Discounted"] = payload.get("price")
            except Exception:
                item["Price Discounted"] = None
            try:
                # Confirmed real signal — see module docstring. Raw value is
                # e.g. "travel exclusive" (lowercase) when flagged, "" when
                # not — this site tracks the concept for every product, so
                # default to "" (not None) even when the key is absent, so a
                # parse hiccup can't get misread by the cleaner as "this
                # site has no exclusivity concept at all". The cleaner maps
                # this to the schema's "Yes"/"No" convention.
                item["GTR_exclusive"] = payload.get("dimension3", "")
            except Exception:
                item["GTR_exclusive"] = ""

            self.product_dicts.append(item)

        return len(products)

    def run_all(self):
        try:
            self.open_website()
            try:
                self.accept_cookies()
            except Exception:
                pass
            time.sleep(1)
            try:
                self.confirm_age_gate()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            time.sleep(1)
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
    all_data = []
    total_expected = 0
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_name, category_path in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_name}")
                scraper = IslandDutyFreeKEFScraper(category_path)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    expected = scraper.expected_count
                    total_scraped += scraped_count
                    if expected is not None:
                        total_expected += expected
                        flag = "OK" if scraped_count == expected else "MISMATCH"
                        print(f"  -> {category_name}: scraped {scraped_count} / site says {expected} [{flag}]")
                    else:
                        print(f"  -> {category_name}: scraped {scraped_count} / site total unknown (couldn't read item count)")
                except Exception as e:
                    print(f"FAILURE scraping {category_name}: {e}")

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
