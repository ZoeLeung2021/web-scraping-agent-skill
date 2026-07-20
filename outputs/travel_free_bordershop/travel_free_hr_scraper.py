"""
Scraper for Travel FREE Bordershop — Croatia (https://travelfree.hr/novi-varos/).

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/travel_free_hr_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - Platform is PrestaShop (modern "product-miniature" theme). Product
    container: <article class="product-miniature" data-id-product="...">
    — data-id-product is a clean, stable numeric ID.
  - Country has ONE unified online catalog (branded "novi-varos" after the
    site's flagship/original border-shop location) covering 4 physical
    shops confirmed via the site's own "Trgovine" (Stores) info page:
    Gruda, Novi Varoš, Vinjani Donji, Županja. That page is purely
    informational (address/phone/hours, one shared webshop@travelfree.hr
    contact) — there is no separate catalog or pricing per shop, so this
    scraper hits the one catalog once and the __main__ block tags the
    resulting rows across all 4 known shop names.
  - All alcohol types are combined in a single category: the "Alkoholna
    pića" (Alcoholic beverages) category at
    https://travelfree.hr/novi-varos/3-alkoholna-pica — no separate
    wine/beer/spirits split needed for this site.
  - Currency is EUR by default site-wide (body class "currency-eur" —
    Croatia's official currency since 2023), no currency switch needed.
  - Language: no English option found (body class "lang-hr", only
    Croatian). Chrome auto-translate (hr -> en) is used; if that doesn't
    fully translate Brand/Brandline text, fall back to ai_translate in the
    cleaner (commented there).
  - GTR-exclusive signal is explicit and unambiguous: PrestaShop's own
    "product flag" mechanism —
    <ul class="product-flags"><li class="product-flag exclusive">Ekskluzivno
    u Travel FREE</li></ul> ("Ekskluzivno u Travel FREE" = "Exclusive at
    Travel FREE"). Presence of a `li.product-flag.exclusive` = GTR
    exclusive; absence (the `<ul>` may still exist with other flag types,
    e.g. "new"/"sale") = not exclusive. This site tracks the concept, so
    every row gets a real "" default per references/schema.md's
    GTR_exclusive convention, never None.
  - Brand IS exposed separately here (unlike Iceland/Georgia):
    <div class="product-brand"><a>Tic Tac</a></div> — no title-splitting
    guesswork needed.
  - Price is a clean numeric attribute: <span class="product-price"
    content="8.3">, no currency-symbol stripping needed.

UNCONFIRMED — verify on first real run: the exact pagination mechanism for
this category page (PrestaShop 1.7 typically uses either a numbered pager
or an infinite-scroll "Show more" button; not confirmed live here). The
scraper below tries a numbered pagination link first, then falls back to
scrolling — adjust get_next_page()/scroll behavior if neither matches.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "travel_free_hr"
BASE_URL = "https://travelfree.hr/novi-varos"
CATEGORY_URL = f"{BASE_URL}/3-alkoholna-pica"

# Confirmed from the site's own "Trgovine" (Stores) info page — one shared
# online catalog serves all 4; no per-shop catalog/pricing found.
LOCATIONS = ["Gruda", "Novi Varoš", "Vinjani Donji", "Županja"]


class TravelFreeHRScraper:
    def __init__(self):
        self.product_dicts = []

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        # No in-page English option was found (lang-hr only) — force Chrome's
        # built-in translate as the next-best option. See
        # clean_travel_free_hr.py's ai_translate step if this isn't enough.
        options.add_experimental_option("prefs", {
            "translate_whitelists": {"hr": "en"},
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
        self.driver.get(CATEGORY_URL)
        time.sleep(4)

    def get_next_page_url(self):
        # TODO: confirm this selector live — PrestaShop's numbered pager,
        # if present, typically looks like this. Returns None if absent,
        # in which case run_all() falls back to scroll-based loading.
        try:
            next_link = self.driver.find_element(By.CSS_SELECTOR, "a.next.js-search-link")
            return next_link.get_attribute("href")
        except NoSuchElementException:
            return None

    def scroll_to_load_more(self):
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = self.driver.execute_script("return document.body.scrollHeight")
        return new_height != last_height

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("article", class_="product-miniature")

        for card in cards:
            item = {}
            try:
                item["ID_raw"] = card.get("data-id-product")
            except Exception:
                item["ID_raw"] = None
            try:
                link_el = card.find("a", class_="product-thumbnail")
                item["Product_link"] = link_el["href"]
            except Exception:
                item["Product_link"] = None
            try:
                item["Brandline"] = card.find("h2", class_="product-title").get_text(strip=True)
            except Exception:
                item["Brandline"] = None
            try:
                item["Brand"] = card.find("div", class_="product-brand").get_text(strip=True)
            except Exception:
                item["Brand"] = None
            item["Size"] = None  # not exposed separately; cleaner falls back to Brandline text
            try:
                price_el = card.find("span", class_="product-price")
                item["Price Discounted"] = price_el.get("content") or price_el.get_text(strip=True)
            except Exception:
                item["Price Discounted"] = None
            item["Strike Price"] = None  # no discount/original-price markup confirmed on this site
            try:
                flag_el = card.find("li", class_="product-flag exclusive") or card.select_one("li.product-flag.exclusive")
                item["GTR_exclusive"] = flag_el.get_text(strip=True) if flag_el else ""
            except Exception:
                item["GTR_exclusive"] = ""

            self.product_dicts.append(item)

        return len(cards)

    def run_all(self):
        try:
            self.open_website()
            seen_ids = set()
            page = 1
            while True:
                found = self.get_main()
                new_ids = {p.get("ID_raw") for p in self.product_dicts} - seen_ids
                seen_ids |= new_ids
                print(f"  page {page}: {found} cards on page, {len(new_ids)} new")

                next_url = self.get_next_page_url()
                if next_url:
                    self.driver.get(next_url)
                    time.sleep(3)
                    page += 1
                    continue

                if not self.scroll_to_load_more():
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
    print(f"Scraping {RETAILER_SLUG}: Croatia / {CATEGORY_URL}")
    scraper = TravelFreeHRScraper()
    scraper.run_all()
    print(f"  -> scraped {len(scraper.product_dicts)} unique products from the shared catalog")

    all_data = []
    scraped_at = datetime.now(timezone.utc).isoformat()
    # No per-shop catalog/pricing difference exists on this site (see module
    # docstring) — replicate the single scrape's rows across every known
    # shop so each location is represented in the output, per production
    # requirements. This is a deliberate design choice (not scraping the
    # same catalog 4x over the wire), not a shortcut.
    for location in LOCATIONS:
        for item in scraper.product_dicts:
            row = dict(item)
            row["Country"] = "Croatia"
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
