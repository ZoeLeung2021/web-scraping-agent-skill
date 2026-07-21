"""
Scraper for Diplomatic Shop (Serbia) — https://diplomaticshop.rs/product-category/beverages/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/diplomatic_shop_serbia_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: the site's own header banner literally reads "DUTY FREE -
    DIPLOMATIC SHOP" and body copy says "We look forward to making your
    duty free experience first class!" — this is a duty-free operation
    serving the diplomatic community out of a single Belgrade location
    ("Our store is located in the port of Belgrade area in the city
    center."), not a normal domestic retailer despite selling in a single
    country. Market = "GTR", Country = "DF Serbia".
  - Single location — no multi-country/multi-branch split found or implied
    anywhere on the site. Channel fixed 2026-07-21 to "Serbia Diplomatic
    Services" (was "N/A") — GTR_Pricing's real diplomatic-shop convention
    is "<Region> Diplomatic Services" (Peter Justesen/Denmark uses
    "Europe Diplomatic Services"); user chose country-specific naming
    over broad-region for this project's diplomatic builds. See
    feedback_channel_naming_airports memory.
  - WordPress + WooCommerce (Woodmart theme). Top-level shop categories:
    beverages, cigarettes, cigars-cigarillos, luggage, perfumes,
    special-offer, sunglasses, watches — "beverages" is the sole alcohol
    category and its own subcategories (aperitif, brandy, champagne,
    cognac, gin, liquer, other, rum, sparkling-wine, tequila, vodka,
    whiskey, wines) are all alcohol types with no soft-drink overlap, so
    scraping the parent "beverages" category page (which already lists
    every subcategory's products combined) covers the full alcohol catalog
    without needing a separate loop per subcategory.
  - Age gate: a WordPress "Age Gate" plugin DOB form (day/month/year fields
    `#age-gate-d`/`#age-gate-m`/`#age-gate-y` + `button.age-gate__button`
    submit) appeared on the very first fetch of this session but did NOT
    appear on a later fetch of the same URL — likely cookie/session-based
    (the form has a checked "Remember me" checkbox). Dismissed
    defensively in try/except since it's inconsistent, same pattern as
    every other age-gated retailer in this repo.
  - Product cards: `<div class="wd-product ... product-grid-item product
    ... product_cat-beverages product_cat-<subcat> ... data-id="<ID>">`.
    The numeric `data-id` (also `data-product_id` on the add-to-cart link)
    is a reliable per-product ID; the add-to-cart link's `data-product_sku`
    attribute (e.g. "0466") is the retailer's own SKU, preferred when
    present. No separate Brand field exists — the `<h3 class="wd-entities-
    title"><a>` title text bundles brand, product name, ABV%, and size all
    into one string (e.g. "BEEFEATER DRY GIN 1L", "MOËT & CHANDON IMPÉRIAL
    BRUT 12% 75CL") — kept as Brandline only, same convention as other
    single-title-field retailers this session (Silk Road Duty Free,
    SuperAlko). Price is a single `<span class="price">` — no `<del>`/
    `<ins>` strike-through markup found anywhere on the category page, so
    there's no discount concept to capture; Strike_Price and
    Price_Discounted are the same raw value. Currency is EUR throughout
    (checked 14 separate price spans, all `€`).
  - Pagination: plain numbered pages, `/product-category/beverages/page/N/`
    — confirmed via real `<a class="page-numbers" href=".../page/2/">`
    links, no click/AJAX needed. The category page also shows a genuine,
    independent total via `<p class="woocommerce-result-count">Showing
    1–12 of 148 results</p>` — used here as `get_expected_item_count()`
    real coverage validation, not a guess.
  - GTR_exclusive: no badge/ribbon/"exclusive"/"onsale" markup found
    anywhere in the product card HTML — left unset for every row so the
    cleaner emits a true null for the whole column.
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

RETAILER_SLUG = "diplomatic_shop_serbia"
BASE_URL = "https://diplomaticshop.rs"

# Single physical/online shop, no location split found.
LOCATIONS = {
    "Serbia": ["Serbia Diplomatic Services"],
}

# "beverages" is the sole alcohol top-level category — see module docstring.
CATEGORIES = ["beverages"]

_RESULT_COUNT_RE = re.compile(r"of\s+(\d+)\s+results", re.IGNORECASE)


class DiplomaticShopSerbiaScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page == 1:
            return f"{BASE_URL}/product-category/{self.category}/"
        return f"{BASE_URL}/product-category/{self.category}/page/{page}/"

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
        try:
            self.driver.get(self.get_url(page=1))
        except Exception:
            pass
        time.sleep(5)

    def dismiss_age_gate(self):
        self.driver.find_element(By.ID, "age-gate-d").send_keys("01")
        self.driver.find_element(By.ID, "age-gate-m").send_keys("01")
        self.driver.find_element(By.ID, "age-gate-y").send_keys("1990")
        self.driver.find_element(By.CSS_SELECTOR, "button.age-gate__button").click()
        time.sleep(3)

    def get_expected_item_count(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        el = soup.find("p", class_="woocommerce-result-count")
        if not el:
            return None
        match = _RESULT_COUNT_RE.search(el.get_text())
        return int(match.group(1)) if match else None

    def get_total_pages(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        page_links = soup.select("ul.page-numbers a.page-numbers, ul.page-numbers span.page-numbers")
        numbers = [int(a.get_text(strip=True)) for a in page_links if a.get_text(strip=True).isdigit()]
        return max(numbers) if numbers else 1

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
                add_to_cart = card.find("a", class_="add_to_cart_button")
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
            try:
                self.dismiss_age_gate()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
            total_pages = self.get_total_pages()
            self.get_main()
            for page in range(2, total_pages + 1):
                try:
                    self.driver.get(self.get_url(page=page))
                except Exception:
                    pass
                time.sleep(3)
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
                scraper = DiplomaticShopSerbiaScraper(channel, category)
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
