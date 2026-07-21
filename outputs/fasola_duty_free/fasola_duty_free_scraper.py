"""
Scraper for Fa-So-La Duty Free (Narita Airport) — https://www.fasola-shop.com/en/goodsList.aspx?cat=120

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/fasola_duty_free_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: site title is "【Official】Fa-So-La Duty Free Pre-Order
    Site | Narita Airport" — an airport duty-free pre-order platform
    (order online, pick up post-security at Narita before departure), no
    ambiguity. Market = "GTR", Country = "DF Japan".
  - Single location (Narita Airport), single currency (JPY). Channel
    fixed 2026-07-21 per this project's standing airport-naming rule
    (see feedback_channel_naming_airports memory): was "N/A" -> "Tokyo
    Narita International Airport (NRT)", matching this exact string
    already used in GTR_Pricing's jal_duty_free_scraper.py and
    Japan_Duty_Free_scraper.py for the same airport.
  - `cat=120` is the master "Liquor" category and already lists every
    alcohol subcategory's products combined (Whisky, Wine, Champagne,
    Gin, Vodka, Sake, Shochu, Chinese liquor, etc. all appear together) —
    confirmed via a live fetch, same pattern as Attenza Duty Free's
    "licores" and Diplomatic Shop's "beverages": scrape the one parent
    category rather than looping every subcategory `itemCD` value.
  - Platform is a classic ASP.NET webshop (`.aspx` pages, `__doPostBack`
    postback handlers) — not a modern JS framework.
  - Product cards are `<div class="products-card">` containing:
      `<a class="products-card__link" href="/en/goodsDetail.aspx?sCD=<ID>">`
        — `sCD` is a real numeric SKU, reliable as-is.
      `<div class="products-card__brand">` and `<div class="products-card__name">`
        — genuinely SEPARATE Brand and Brandline fields (unlike most other
        retailers built this session, which bundle everything into one
        title string) — e.g. Brand "IWA 5", Brandline "IWA 5 Assemblage 6
        Gift Box　720ml".
      `<span class="products-card__price__amount"><span class="products-card__price__unit">¥</span><span>15,000</span></span>`
        — a single "Duty Free Price" label, no strike-through/discount
        markup found anywhere on the category page (checked all 40 cards
        on page 1) — Strike_Price and Price_Discounted are the same raw
        value.
      `<div class="products-card__id"><span class="products-card__id__num">`
        — duplicates the same sCD value, redundant with the link.
  - Size is NOT a separate field — embedded in `products-card__name` text
    when present (e.g. "720ml"), left for the cleaner's regex fallback.
  - GTR_exclusive — CONFIRMED REAL (verified against live DOM, not just a
    text-extraction proxy, which had initially mis-surfaced a same-worded
    navigation category link elsewhere on the page as a false lead):
    each card's `<div class="product-tag-list">` sometimes contains
    `<span class="product-tag product-tag--duty-free">Travel Exclusive
    <!--免税店限定--></span>` — a genuine per-product exclusivity tag,
    confirmed present on roughly a third of the 40 cards checked, absent
    (empty `product-tag-list` div, or a different tag entirely) on the
    rest. Other tag classes found on the same site — `product-tag--not-
    applicable` ("Ineligible for 5% Discount"), `product-tag--not-
    quantity` ("Limited Quantity"), `product-tag--recommend`
    ("RECOMMEND") — are NOT exclusivity signals and are ignored; only
    `product-tag--duty-free` maps to GTR_exclusive. Since the site
    genuinely tracks this concept (present on some products, legitimately
    absent on others, not just missing everywhere), every row gets a
    real "true"/"false" string here — the cleaner turns that into
    Yes/No, not null.
  - Pagination: real numbered pages via `&page=N` (confirmed a `<a
    class="pagination__next">` link and up to 4 total pages for cat=120,
    ~35-40 cards per page, no page 5 link found anywhere) — this scraper
    follows the "next" link until it disappears rather than hardcoding a
    page count, in case the real total grows over time.
  - Age gate: a real modal (`#ctl00_cphMainBefore_UC_ModalAgeAlert_pnlModalAge`,
    "Persons under the age of 20 are not allowed to view this page")
    with a `#yesBtn` confirm button — dismissed defensively in try/except;
    product data was already present in page_source even before dismissal
    in testing (the modal doesn't block the underlying DOM), but dismissing
    it is still done for correctness/robustness.
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

RETAILER_SLUG = "fasola_duty_free"
BASE_URL = "https://www.fasola-shop.com"
LIQUOR_CAT = "120"

# Single airport shop, no location split found.
LOCATIONS = {
    "Japan": ["Tokyo Narita International Airport (NRT)"],
}

# Master liquor category covers every alcohol subcategory combined — see
# module docstring.
CATEGORIES = [LIQUOR_CAT]


class FasolaDutyFreeScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page == 1:
            return f"{BASE_URL}/en/goodsList.aspx?cat={self.category}"
        return f"{BASE_URL}/en/goodsList.aspx?cat={self.category}&page={page}"

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
        try:
            self.driver.get(self.get_url(page=1))
        except Exception:
            pass
        time.sleep(5)

    def dismiss_age_gate(self):
        self.driver.find_element(By.ID, "yesBtn").click()
        time.sleep(1)

    def get_expected_item_count(self):
        """No genuine "N results" text was found anywhere on this
        category page — coverage confidence instead comes from following
        the "next" pagination link until it disappears. Returns None."""
        return None

    def has_next_page(self, soup):
        next_link = soup.find("a", class_="pagination__next")
        return bool(next_link and next_link.get("href"))

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="products-card")

        for card in cards:
            product_dict = {}
            try:
                link_el = card.find("a", class_="products-card__link")
                href = link_el["href"] if link_el else None
                product_dict["Product_link"] = BASE_URL + href if href else None
                id_match = re.search(r"sCD=(\d+)", href or "")
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None
                product_dict["ID_raw"] = None

            try:
                brand_el = card.find("div", class_="products-card__brand")
                product_dict["Brand"] = brand_el.get_text(strip=True) if brand_el else None
            except (AttributeError, TypeError):
                product_dict["Brand"] = None

            try:
                name_el = card.find("div", class_="products-card__name")
                product_dict["Brandline"] = name_el.get_text(strip=True) if name_el else None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None

            try:
                price_el = card.find("span", class_="products-card__price__amount")
                price_text = price_el.get_text(strip=True) if price_el else None
                product_dict["Strike Price"] = price_text
                product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # A genuine per-product exclusivity tag exists and is present
            # on some cards, legitimately absent on others (see module
            # docstring) — always set a real string, never left out,
            # since the site tracks this concept.
            try:
                is_exclusive = card.find("span", class_="product-tag--duty-free") is not None
                product_dict["GTR_exclusive"] = "true" if is_exclusive else "false"
            except (AttributeError, TypeError):
                product_dict["GTR_exclusive"] = "false"

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            try:
                self.dismiss_age_gate()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
            self.get_main()
            page = 2
            while True:
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                if not self.has_next_page(soup):
                    break
                try:
                    self.driver.get(self.get_url(page=page))
                except Exception:
                    break
                time.sleep(3)
                self.get_main()
                page += 1
                if page > 50:  # safety backstop against an infinite loop
                    break
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
                scraper = FasolaDutyFreeScraper(channel, category)
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
