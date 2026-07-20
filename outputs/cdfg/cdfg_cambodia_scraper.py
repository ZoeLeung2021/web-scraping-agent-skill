"""
Scraper for cdf Cambodia (China Duty Free Group) — https://pc.cdfgkhm.com/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/cdfg_cambodia_scraper.py
once validated.

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - Platform is a Vue/Nuxt SPA (data-v-* scoped-style attributes, "__nuxt"
    root element). Same corporate family as https://preorder.dutyzero.com.hk/
    (Hong Kong) — the site's own region switcher lists both, plus cdf Macao
    and cdf Beauty, as sibling shops under the same operator.
  - All alcohol is combined into a single category: /showactivity/Liquor-13977
    (nav also has Skincare/Cosmetic/Perfume/Watch — not scraped, out of
    alcohol scope). Category count confirmed live: 81 products, reached via
    scroll (20 -> 40 -> 60 -> 80 -> 81, stable after that — infinite scroll
    genuinely works here, unlike Travel FREE Czech Republic which needed an
    explicit button click instead).
  - Product card: <a href="/item/p<digits>"> wraps the whole card, including
    <div class="container-content__brand">, <div
    class="container-content__title">, and a price block
    (<div class="prod-price__content"><div>$</div><div>1280</div></div> —
    currency symbol and amount in separate sibling divs, concatenate via
    get_text() before parsing in the cleaner).
  - Currency is USD ($) by default — no currency-switcher interaction needed.
  - Language: the header's language dropdown already shows "English" as the
    active language (with 简体中文 as the only alternative) — but a real test
    run found this only covers the UI chrome, not every product: some SKUs
    have no English translation entered by the retailer and fall back to
    Chinese even in "English mode" (e.g. Brandline "波特嘉星尘PROSECCO起泡酒").
    This is a per-SKU data gap, not a language-switch step this scraper can
    fix — the paired cleaner applies ai_translate unconditionally as a
    safety net instead (harmless no-op on text already in English).
  - Country has ONE online catalog (Channel = "N/A") — no evidence of a
    multi-location split was found for this site.
  - GTR-exclusive signal: CONFIRMED (via the Hong Kong sibling site, whose
    real product data included "...Travellers' Exclusive Collection...")
    that this platform signals exclusivity directly in the product title
    text, not a separate badge/ribbon. get_main() checks for "exclusive"
    (case-insensitive) in the raw Brandline text before translation.

UNCONFIRMED / not checked given time constraints: whether any product
carries a discount/strike price (all sampled Cambodia products had a
single price only — though Hong Kong's sibling site did show a "SALE"
text prefix on some, see cdfg_hongkong_scraper.py).
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

RETAILER_SLUG = "cdfg_cambodia"
BASE_URL = "https://pc.cdfgkhm.com"

CATEGORIES = {
    "Liquor": "/showactivity/Liquor-13977",
}

LOCATIONS = {
    "Cambodia": ["N/A"],
}


class CDFGCambodiaScraper:
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

    def scroll_to_load_all(self, max_scrolls=60, stable_target=3):
        """Confirmed live: this site's infinite scroll genuinely works
        (unlike Travel FREE Czech Republic, which needed an explicit button
        click) — keep scrolling until the count stops changing across
        several consecutive checks. Uses a direct JS window.scrollTo rather
        than Selenium's send_keys(END) on <body> — the Hong Kong sibling
        site showed that technique can silently fail to register even
        though it happened to work here; scrollTo is the more reliable
        choice across both."""
        last_count = -1
        stable = 0
        for _ in range(max_scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
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
            item["Size"] = None  # embedded in Brandline text (e.g. "500ml") — cleaner extracts it
            try:
                price_el = card.find(class_="prod-price__content")
                item["Price Discounted"] = price_el.get_text(" ", strip=True) if price_el else None
            except Exception:
                item["Price Discounted"] = None
            item["Strike Price"] = None  # no discount markup confirmed — see module docstring
            # GTR_exclusive: confirmed on the Hong Kong sibling site that
            # exclusivity is signalled directly in the product title text
            # (e.g. "...Travellers' Exclusive Collection..."), not a
            # separate badge/ribbon — check for that here too rather than
            # leaving this null. Real string ("" default) since the
            # platform tracks this concept, even if it's rare on this site.
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
                scraper = CDFGCambodiaScraper(category_path)
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
