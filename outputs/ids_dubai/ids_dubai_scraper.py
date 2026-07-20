"""
Scraper for IDS (International Diplomatic Supply) — https://www.i-d-s.com/dubai/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/ids_dubai_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: homepage title is "Trusted to serve Diplomats worldwide";
    meta keywords include "IDS, Diplomatic supply, duty free diplomatic
    shop, diplomatic duty-free products". This is the same diplomatic-
    duty-free business model as Diplomatic Shop (Serbia) and DM Diplomat
    Duty Free (South Korea) built earlier this session. Market = "GTR".
    The scraped storefront is specifically the `/dubai/` path (IDS
    appears to run per-city/country storefronts for a global diplomatic
    client base), so Country = "Dubai" here (not "United Arab Emirates"
    generically) — same precedent as GMP's "Abu Dhabi" (emirate/city-
    specific service area, not the whole country).
  - Platform is Magento 2 (`data-role="priceBox"`, `data-product-id`,
    Knockout.js `data-bind` attributes, `.html`-suffixed category/product
    URLs) — same platform family as Garrafeira Nacional Portugal.
  - **Category taxonomy has a real duplication trap, confirmed live**:
    the top-level "Wine" and "Spirits" hub pages (`/wine.html`,
    `/spirits.html`) are pure navigation pages with NO products listed
    directly — they show category tiles across MULTIPLE overlapping
    dimensions simultaneously (Wine: Type / Wines by Country / Wines by
    Region / Wines by Variety / Sake / Award Winners — the same physical
    wine product would appear under its Type AND its Country AND its
    Region AND its Variety tile). Looping every dimension would cause
    massive duplicate scraping. This scraper loops ONLY the "Wine Type"
    and "Spirits" sub-type dimensions (confirmed to have real, large,
    independently-paginated product listings, e.g. Red Wine alone = 269
    items via a genuine "Items 1-12 of 269" count) — Country/Region/
    Variety dimensions are deliberately NOT looped, since they're
    redundant re-slices of the same underlying wine catalog, not
    additional products. "Fine Wine"/"Organic Wine"/"Vegan Wine"/
    "Miniature Wine"/"Wine Boxes"/"Sustainable Wine"/"Award Winners" and
    "Nemiroff"/"Sustainable Spirits" sub-tiles were also excluded as
    marketing cross-tags over the same core types, not distinct product
    families — kept the category list to the core, non-marketing types.
  - WINE_CATEGORIES (`/wine/wine-type/<slug>.html` unless noted):
    red-wine, white-wine, rose-wine, champagne, fortified-dessert-wine,
    sparkling-wine-prosecco, plus `/wine/sake.html`.
  - SPIRITS_CATEGORIES (`/spirits/<slug>.html`): bourbon-other-whiskey,
    brandy-cognac, gin, hard-seltzer, other-spirits, ready-to-drink, rum,
    scotch-whisky, tequila-mezcal, vodka.
  - BEER_CIDER_CATEGORY: `/beer-cider.html` is a single flat category (no
    sub-tiles, real products listed directly, confirmed small — 37 total
    items) but **mixes real alcoholic beer/cider with non-alcoholic
    soft-drink mixers** (e.g. "Bundaberg Ginger Beer" — a well-known
    non-alcoholic Australian soft drink brand — appears here alongside
    genuinely alcoholic items like "Crabbies Alcoholic Ginger Beer",
    whose title explicitly says "Alcoholic" to distinguish it from the
    regular non-alcoholic version). The site's own product titles often
    explicitly flag this (e.g. "Corona Cero Non Alcoholic", "Biere des
    Amis 0.0% (Non Alcoholic)") — this scraper filters out any product
    whose title contains "non alcoholic"/"non-alcoholic"/"0.0%" as a
    best-effort exclusion. This is NOT a complete classifier (e.g. plain
    "Bundaberg Ginger Beer" doesn't self-flag as non-alcoholic in its
    title) — a known, documented gap, not silently assumed to be perfect.
  - Product cards are `<li class="item product product-item">` /
    `<div class="product-item-info" data-container="product-grid">`.
    `Product_link`/`Brandline` from `a.product-item-link`. A real SKU
    exists on the add-to-cart form's `data-product-sku` attribute (e.g.
    "WB1022") — used as ID_raw, preferred over the numeric
    `data-product-id` (e.g. "258994"). Price: the human-readable
    `.price-wrapper .price` text (e.g. "$60.00") is used, NOT the
    `data-price-amount` attribute on the same element — confirmed live
    these two disagree on at least one product (attribute said "220.8",
    visible text said "$60.00", likely a base-currency-vs-displayed or
    per-case-vs-per-unit mismatch) — the visible, human-facing price is
    the more trustworthy one. A real `<span class="old-price">` exists
    for discounted items (empty when there's no discount, as confirmed on
    the sampled product) — captured as Strike_Price when present.
  - Size is not a separate field — each product has a "qty-options"
    dropdown (e.g. "BOTTLE: 75CL" / "CASE: 6X75CL") whose first/default
    option text is captured raw; the cleaner's existing multi-pack "x"
    exclusion already handles the case-vs-bottle distinction correctly
    (single "75CL" resolves, "6X75CL" correctly stays unresolved).
  - No GTR-exclusive badge found on any sampled product — the only
    promotional badge seen was "previously_purchased" (a personalization
    label, not exclusivity), and the only "exclusive" text on the page was
    generic marketing copy in a login modal ("exclusive shopping
    experience"), not a per-product signal. Left unset for every row.
  - No age-verification gate found anywhere on this site.
  - Pagination: standard Magento numbered pages via `?p=N`, with a
    genuine "Items X-Y of Z" count (`#toolbar-amount`) used for real
    coverage validation.
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

RETAILER_SLUG = "ids_dubai"
BASE_URL = "https://www.i-d-s.com/dubai"

LOCATIONS = {
    "Dubai": ["N/A"],
}

WINE_CATEGORIES = [
    "wine/wine-type/red-wine",
    "wine/wine-type/white-wine",
    "wine/wine-type/rose-wine",
    "wine/wine-type/champagne",
    "wine/wine-type/fortified-dessert-wine",
    "wine/wine-type/sparkling-wine-prosecco",
    "wine/sake",
]
SPIRITS_CATEGORIES = [
    "spirits/bourbon-other-whiskey",
    "spirits/brandy-cognac",
    "spirits/gin",
    "spirits/hard-seltzer",
    "spirits/other-spirits",
    "spirits/ready-to-drink",
    "spirits/rum",
    "spirits/scotch-whisky",
    "spirits/tequila-mezcal",
    "spirits/vodka",
]
BEER_CIDER_CATEGORIES = ["beer-cider"]

CATEGORIES = WINE_CATEGORIES + SPIRITS_CATEGORIES + BEER_CIDER_CATEGORIES

_NON_ALCOHOLIC_RE = re.compile(r"non[\s-]?alcoholic|0\.0%", re.IGNORECASE)


class IdsDubaiScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page == 1:
            return f"{BASE_URL}/{self.category}.html"
        return f"{BASE_URL}/{self.category}.html?p={page}"

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

    def get_expected_item_count(self, soup):
        el = soup.find(id="toolbar-amount")
        if not el:
            return None
        numbers = el.find_all("span", class_="toolbar-number")
        return int(numbers[-1].get_text(strip=True)) if numbers else None

    def get_total_pages(self, soup):
        page_links = soup.select("ul.pages-items li.item a.page span")
        numbers = [int(s.get_text(strip=True)) for s in page_links if s.get_text(strip=True).isdigit()]
        return max(numbers) if numbers else 1

    def get_main(self, soup):
        cards = soup.find_all("div", class_="product-item-info")

        for card in cards:
            product_dict = {}
            try:
                link_el = card.find("a", class_="product-item-link")
                product_dict["Brandline"] = link_el.get_text(strip=True) if link_el else None
                product_dict["Product_link"] = link_el["href"] if link_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Brandline"] = None
                product_dict["Product_link"] = None
            product_dict["Brand"] = None

            # Non-alcoholic soft-drink mixers get filtered out here (best
            # effort — see module docstring for the known limitation).
            if product_dict["Brandline"] and _NON_ALCOHOLIC_RE.search(product_dict["Brandline"]):
                continue

            try:
                cart_form = card.find("form", attrs={"data-role": "tocart-form"})
                product_dict["ID_raw"] = cart_form.get("data-product-sku") if cart_form else None
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None

            try:
                price_el = card.select_one("span.price-wrapper span.price")
                price_text = price_el.get_text(strip=True) if price_el else None
                product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Price Discounted"] = None

            try:
                old_price_el = card.select_one("span.old-price .price")
                old_price_text = old_price_el.get_text(strip=True) if old_price_el else None
                product_dict["Strike Price"] = old_price_text if old_price_text else product_dict["Price Discounted"]
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = product_dict["Price Discounted"]

            try:
                qty_option = card.find("option", attrs={"data-type": "qty_for_bottle"}) or card.find(
                    "span", string=re.compile(r"\d+\s*X?\s*\d*\s*CL", re.IGNORECASE)
                )
                product_dict["Size"] = qty_option.get_text(strip=True) if qty_option else None
            except (AttributeError, TypeError):
                product_dict["Size"] = None

            # No GTR-exclusive badge found anywhere on this site — see
            # module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            self.expected_count = self.get_expected_item_count(soup)
            total_pages = self.get_total_pages(soup)
            self.get_main(soup)
            for page in range(2, total_pages + 1):
                try:
                    self.driver.get(self.get_url(page=page))
                except Exception:
                    break
                time.sleep(3)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                self.get_main(soup)
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
                scraper = IdsDubaiScraper(channel, category)
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
                        flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH (some may be filtered non-alcoholic)"
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
