"""
Scraper for DUTY ZERO by cdf — Hong Kong (China Duty Free Group)
https://preorder.dutyzero.com.hk/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/cdfg_hongkong_scraper.py
once validated.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - Same corporate family/platform as cdfg_cambodia_scraper.py (a Vue/Nuxt
    SPA) — this site's own region switcher on the Cambodia site lists
    "DUTY ZERO" as the Hong Kong sibling shop, and this site shares the
    same CSS class names (container-content__brand/__title,
    prod-price__content, etc.) confirmed via a raw page fetch. The product
    card structure and scroll-based pagination approach below are carried
    over from the Cambodia scraper on that basis.
  - Alcohol categories, confirmed via live nav (more granular than
    Cambodia's single "Liquor" bucket): Whisky-21029, Chinese-Liquor-21032,
    Wines-21037, Cognac-21034, Champagnes-Sparklings-21039, Gins-Others-21045.
    A separate "Food-47468" category exists in the same nav — not scraped
    (out of alcohol scope).

CONFIRMED via a real test run against this exact domain (Whisky category):
  - Prices are shown in HKD ("HK$<amount>"), not USD — different from
    Cambodia. The cleaner's LOCAL_CURRENCY is set accordingly.
  - GTR-exclusive signal confirmed directly: a real scraped product title
    was "Mortlach 20 Year Old Travellers' Exclusive Collection Single
    Malts Whisky 700ml" — exclusivity is signalled in the product title
    text itself, matching the Cambodia scraper's approach.
  - A "SALE" text prefix sometimes appears inside the price element (e.g.
    "SALE HK$ 871") with no separate original/full price shown in the
    listing grid — nothing numeric to extract for Strike_Price from this,
    just a flag that the item is discounted (see get_main()).

FIXED (2026-07-15): scroll_to_load_all() initially used Selenium's
send_keys(END) on <body> (which worked on the Cambodia sibling site) but
that silently failed to register on this domain — 12 scrolls against the
Wines category never moved the count past 20. Root cause was the
technique, not a different scroll container: the page confirmed
window-scrollable (document.body.scrollHeight 2119px vs a 937px viewport).
Switched to a direct JS window.scrollTo(0, document.body.scrollHeight)
with a longer 4s wait per step (2s wasn't enough for the next batch to
render) — confirmed live: count climbed steadily and kept climbing past
179 after 8 scrolls with no sign of stopping, so this genuinely is
indefinite/infinite scroll on this site, matching Cambodia's behavior.
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

RETAILER_SLUG = "cdfg_hongkong"
BASE_URL = "https://preorder.dutyzero.com.hk"

CATEGORIES = {
    "Whisky": "/showactivity/Whisky-21029",
    "Chinese Liquor": "/showactivity/Chinese-Liquor-21032",
    "Wines": "/showactivity/Wines-21037",
    "Cognac": "/showactivity/Cognac-21034",
    "Champagnes & Sparklings": "/showactivity/Champagnes-Sparklings-21039",
    "Gins & Others": "/showactivity/Gins-Others-21045",
}

LOCATIONS = {
    "Hong Kong": ["N/A"],
}


class CDFGHongKongScraper:
    def __init__(self, category_path):
        self.category_path = category_path
        self.product_dicts = []

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
        time.sleep(6)

    def scroll_to_load_all(self, max_scrolls=200, stable_target=3):
        """FIXED 2026-07-15: this domain's infinite scroll needs a direct JS
        window.scrollTo (not Selenium's send_keys(END) on <body>, which
        silently fails to register on this specific site even though it
        works fine on the Cambodia sibling site) plus a longer 4s wait per
        step — 2s wasn't enough for the next batch to render. Confirmed
        live: count climbed steadily (20 -> 39 -> 59 -> 79 -> ... -> 179 and
        still rising after 8 scrolls on the Wines category), so max_scrolls
        is set generously high here rather than assuming a small catalog."""
        last_count = -1
        stable = 0
        for _ in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(4)
            count = len(BeautifulSoup(self.driver.page_source, "html.parser").find_all(
                "a", href=re.compile(r"^/item/p\d+")
            ))
            if count == last_count:
                stable += 1
                if stable >= stable_target:
                    return
            else:
                stable = 0
            last_count = count

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("a", href=re.compile(r"^/item/p\d+"))

        for card in cards:
            item = {}
            try:
                item["Product_link"] = card["href"]
                item["ID_raw"] = re.search(r"/item/p(\d+)", card["href"]).group(1)
            except Exception:
                item["Product_link"] = None
                item["ID_raw"] = None
            try:
                item["Brand"] = card.find(class_="container-content__brand").get_text(strip=True)
            except Exception:
                item["Brand"] = None
            try:
                item["Brandline"] = card.find(class_="container-content__title").get_text(strip=True)
            except Exception:
                item["Brandline"] = None
            item["Size"] = None  # embedded in Brandline text — cleaner extracts it
            try:
                price_el = card.find(class_="prod-price__content")
                item["Price Discounted"] = price_el.get_text(" ", strip=True) if price_el else None
            except Exception:
                item["Price Discounted"] = None
            # CONFIRMED live: a "SALE" text prefix sometimes appears inside
            # this same price element (e.g. "SALE HK$ 871") with no separate
            # original/full price shown in the listing grid — there's
            # nothing numeric to put in Strike_Price from this, just a flag
            # that the item is discounted. Left as None; revisit if the
            # product detail page turns out to show the original price.
            item["Strike Price"] = None
            # GTR_exclusive: CONFIRMED live — a real product title contained
            # "...Travellers' Exclusive Collection..." directly in the text,
            # not a separate badge/ribbon. Real string ("" default) since
            # this platform tracks the concept.
            brandline_text = (item.get("Brandline") or "")
            item["GTR_exclusive"] = "exclusive" if "exclusive" in brandline_text.lower() else ""

            self.product_dicts.append(item)

        return len(cards)

    def run_all(self):
        try:
            self.open_website()
            self.scroll_to_load_all()
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

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_name, category_path in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_name}")
                scraper = CDFGHongKongScraper(category_path)
                try:
                    scraper.run_all()
                    scraped_at = datetime.now(timezone.utc).isoformat()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Scraped_At"] = scraped_at
                    all_data.extend(scraper.product_dicts)
                    print(f"  -> {category_name}: scraped {len(scraper.product_dicts)} items")
                except Exception as e:
                    print(f"FAILURE scraping {category_name}: {e}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
