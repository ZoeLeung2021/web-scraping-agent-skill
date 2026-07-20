"""
Scraper for Travel FREE Bordershop — Czech Republic (https://www.travel-free.cz/).

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/travel_free_cz_scraper.py
once validated.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - Product container: <div class="Box Box-ProductCard ...">. Product link
    is the first <a href="/de/waren/produktdetails/...">. Product ID is on
    a nearby favourite-button link within the same card:
    <a data-component="popupOpener" data-product-id="18237443">.
  - Alcohol category URLs: /de/produkte/spirituosen (spirits),
    /de/produkte/wein (wine), /de/premium-spirituosen (a separate premium
    spirits section — included for completeness; possible overlap with
    regular spirits doesn't matter, the silver MERGE key is per-product ID
    so duplicates across categories collapse naturally). No beer category
    was found anywhere in this site's nav — Travel FREE CZ doesn't appear
    to carry it prominently, or it's absent from this site's range.
  - Price: <div class="Price ..."><p class="promotion-price">99<span
    class="cents">.90 </span><span class="currency">€</span></p></div> —
    concatenating the element's own text already yields "99.90 €", no
    special parsing needed beyond the usual symbol-stripping in the
    cleaner. Only a single "Price-standard" price was found on the
    products checked — a discount/original-price variant (mentioned
    elsewhere on-site as "Aktionsangebot"/promotional offers) was NOT
    directly confirmed on a live discounted product; verify on first real
    run and adjust get_main() if a "Price-old"-style class exists.
  - GTR-exclusive signal: a <div class="Product-stickers"> appears on SOME
    product cards (confirmed: 1 of 16 sampled) containing an <img> whose
    src encodes which sticker (e.g. "de-travel-sm.svg" — "travel" in the
    filename). The div itself is absent (not just empty) on non-stickered
    products, so this scraper defaults to "" when the div/img isn't found —
    the site clearly tracks this concept (confirmed present on at least one
    real product), so every row gets a real string, never None.
  - Currency: a plain link sets it site-wide — /setcurrency/eur (no
    interaction needed beyond navigating there once per session).
  - Language: only Czech (CZ) and German (DE) are offered — no English
    option exists on this site. Chrome auto-translate (de -> en) is used;
    if Brand/Brandline text still isn't in English, fall back to
    ai_translate in the cleaner (commented there).
  - Country has ONE unified catalog serving 29 physical border-crossing
    shops (confirmed via the site's own store-locator data, which is
    address/hours info only — no separate per-shop catalog or pricing was
    found; attempting to navigate directly to a "/de/travel-free-shops/N-*"
    link redirected back to the homepage rather than showing a distinct
    catalog). The __main__ block below tags the one scrape's rows across
    all 29 known location names.

CONFIRMED pagination (2026-07-15, after the first version of this scraper
under-counted badly — 14 items instead of 300+): this site uses a "Load
more" button, <a class="js-products-paginator-next-link">Nacist vice -
page: N</a> (Czech text even on the German-language path). Scrolling alone
does NOT trigger more items to load (confirmed live: 10 scrolls, count
never moved past 14). The button must be clicked via JS execute_script,
since Selenium's native .click() hits a stale-element error as the page
re-renders after each click (retried below). Verified live: clicking it
repeatedly kept adding ~24 products per click well past 370 with no sign of
stopping, so Spirituosen alone is a much bigger catalog than initially
assumed. click_load_more() loops until the button no longer exists in the
DOM (last page reached).
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

RETAILER_SLUG = "travel_free_cz"
BASE_URL = "https://www.travel-free.cz"

CATEGORIES = {
    "Spirituosen": "/de/produkte/spirituosen",
    "Premium Spirituosen": "/de/premium-spirituosen",
    "Wein": "/de/produkte/wein",
}

# Confirmed from the site's own store-locator JSON — one shared catalog
# serves all 29; no per-shop catalog/pricing found (see module docstring).
LOCATIONS = [
    "Aš", "Aš 2", "Broumov", "Cínovec", "České Velenice", "Dolní Dvořiště",
    "Folmava", "Halámky", "Hatě", "Hevlín", "Hřensko", "Kraslice",
    "Loučná pod Klínovcem", "Mikulov", "Petrovice", "Petrovice Fashion Store",
    "Pomezí", "Potůčky", "Rozvadov 1", "Rozvadov 2", "Rožany", "Slavonice",
    "Strážný", "Studánky", "Svatý Kříž 1", "Svatý Kříž 2", "Vejprty",
    "Železná", "Železná Ruda",
]


class TravelFreeCZScraper:
    def __init__(self, category_path):
        self.category_path = category_path
        self.product_dicts = []

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        # No English option exists on this site (CZ/DE only) — force
        # Chrome's built-in translate as the next-best option.
        options.add_experimental_option("prefs", {
            "translate_whitelists": {"de": "en"},
            "translate": {"enabled": True},
        })

        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.driver.set_page_load_timeout(30)
        # Set currency once per session before hitting the category page.
        self.driver.get(f"{BASE_URL}/setcurrency/eur")
        time.sleep(1)
        self.driver.get(f"{BASE_URL}{self.category_path}")
        time.sleep(4)

    def click_load_more(self, max_clicks=100):
        """Confirmed live: clicking a.js-products-paginator-next-link
        repeatedly is what actually loads more products (scrolling alone
        does nothing). Uses JS execute_script rather than Selenium's native
        .click() since the page re-renders after each click and a plain
        .click() hits a stale-element-reference error; re-finds the button
        fresh on each retry rather than reusing a handle across clicks."""
        for _ in range(max_clicks):
            clicked = False
            for _attempt in range(3):
                try:
                    btn = self.driver.find_element(By.CSS_SELECTOR, "a.js-products-paginator-next-link")
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView(true); arguments[0].click();", btn
                    )
                    clicked = True
                    break
                except (NoSuchElementException, StaleElementReferenceException):
                    time.sleep(1)
            if not clicked:
                return  # no more pages
            time.sleep(2.5)

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="Box-ProductCard")
        skipped = 0

        for card in cards:
            item = {}
            try:
                link_el = card.find("a", href=True)
                item["Product_link"] = link_el["href"]
            except Exception:
                item["Product_link"] = None
            # A card with no link at all isn't a real product (confirmed
            # live: the selector occasionally matches a non-product element
            # styled with the same class) — skip it rather than emit an
            # all-null row.
            if not item["Product_link"]:
                skipped += 1
                continue
            try:
                fav_el = card.find("a", attrs={"data-product-id": True})
                item["ID_raw"] = fav_el["data-product-id"]
            except Exception:
                item["ID_raw"] = None
            try:
                item["Brandline"] = card.find("div", class_="Box-name").get_text(strip=True)
            except Exception:
                item["Brandline"] = None
            item["Brand"] = None  # not exposed separately; whole title captured as Brandline
            item["Size"] = None  # embedded in Brandline text (e.g. "40% 1L") — cleaner extracts it
            try:
                price_el = card.find("p", class_=re.compile(r"promotion-price"))
                item["Price Discounted"] = price_el.get_text(" ", strip=True) if price_el else None
            except Exception:
                item["Price Discounted"] = None
            # TODO: verify a discount/original-price element exists on a
            # real sale item and capture it here — not confirmed live.
            item["Strike Price"] = None
            try:
                sticker_div = card.find("div", class_="Product-stickers")
                sticker_img = sticker_div.find("img") if sticker_div else None
                item["GTR_exclusive"] = sticker_img.get("src", "") if sticker_img else ""
            except Exception:
                item["GTR_exclusive"] = ""

            self.product_dicts.append(item)

        if skipped:
            print(f"  (skipped {skipped} non-product card(s) matching the selector)")
        return len(cards) - skipped

    def run_all(self):
        try:
            self.open_website()
            self.click_load_more()
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
    category_results = {}

    for category_name, category_path in CATEGORIES.items():
        print(f"Scraping {RETAILER_SLUG}: {category_name}")
        scraper = TravelFreeCZScraper(category_path)
        try:
            scraper.run_all()
            category_results[category_name] = scraper.product_dicts
            print(f"  -> {category_name}: scraped {len(scraper.product_dicts)} items")
        except Exception as e:
            print(f"FAILURE scraping {category_name}: {e}")

    all_data = []
    scraped_at = datetime.now(timezone.utc).isoformat()
    # No per-shop catalog/pricing difference exists on this site (see
    # module docstring) — replicate each category's single scrape across
    # every known location so all 29 are represented in the output.
    for category_name, rows in category_results.items():
        for location in LOCATIONS:
            for item in rows:
                row = dict(item)
                row["Country"] = "Czech Republic"
                row["Channel"] = location
                row["Scraped_At"] = scraped_at
                all_data.append(row)

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
