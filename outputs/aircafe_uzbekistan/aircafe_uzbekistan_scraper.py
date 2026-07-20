"""
Scraper for Air-Cafe by DutyFree (Uzbekistan) — https://aircafe.dutyfree.uz/home

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/aircafe_uzbekistan_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: the site's own name ("Air-Cafe by DutyFree") and domain
    (aircafe.dutyfree.uz, a subdomain of dutyfree.uz) both carry "DutyFree"
    branding directly, even though the on-page body copy itself never
    repeats "duty free"/"travel retail" text — same bar other duty-free-
    branded retailers in this pipeline were accepted on. Market = "GTR",
    Country = "DF Uzbekistan".
  - This is a single continuous page built on Quasar Framework (Vue.js),
    not a set of category URLs like every other retailer in this repo.
    Product categories are inline DOM sections
    <div id="category-N"><div class="q-my-sm fs-24">EMOJI Category Name</div>
    ...<div class="flex justify-between"> of q-card items </div></div>,
    NOT separate pages — there's no <a href> anywhere on the whole page (no
    per-product detail URL exists at all). id="category-2" is confirmed the
    stable ID for "🍷 Алкогольные напитки" ("Alcoholic beverages") — found
    by enumerating all 8 category IDs on the page and reading each one's
    header text; the numeric ID appears to be assigned by the POS backend
    and stays consistent, which is what makes scoping straight to
    #category-2 reliable instead of the originally-planned "track the
    nearest preceding header during scroll" approach.
  - Despite this being described as `q-virtual-scroll` (a Vue technique
    that normally unmounts off-screen DOM nodes), a live test found this
    catalog's total size (319 items across 8 categories, 174 of them
    alcohol) is small enough that a single `driver.get()` + a several-
    second wait already renders every item in `page_source` — a follow-up
    scroll-and-recheck test found zero additional item IDs after 15 scroll
    steps versus the initial snapshot. So, unlike the incremental
    per-scroll-capture design originally planned for this site, one
    snapshot after a short defensive scroll is sufficient. If this
    retailer's catalog grows much larger in the future and virtual-scroll
    unmounting starts actually dropping items, revisit this — the
    incremental-capture approach documented in an earlier version of this
    project's investigation notes is the fallback design.
  - Each product card is <div class="q-card q-ma-sm shadow-5"> containing:
      <img src="https://pos.dutyfree.uz/api/v.1/item/photo/<ID>"> — a clean
        numeric per-product ID embedded in the (otherwise-only-existing)
        image URL. Since there's no separate product page, this photo URL
        doubles as Product_link too (see references/schema.md's "or the
        product image, for a few sites that only expose that" note).
      <div class="q-item__label ellipsis text-center">Title</div> — the
        only name field on this site (no separate Brand). Size and,
        inconsistently, ABV% are embedded directly in this title text in a
        mix of formats confirmed across real samples: "Ararat 5* 40%
        0.7L GP", "Bacardi 8Y 1L", "Absolut Vodka Blue 0.5L", "Alcohol
        Free Gin ... 0,5 litre" (comma decimal + "litre" spelled out),
        "Ballantine's Finest 0.5l glasses". The paired cleaner's size
        regex is extended beyond the shared template's default to cover
        the comma-decimal and "litre" cases seen here.
      <div class="q-item__label text-bold text-primary">€ N.NN</div> — a
        single price, already in EUR. No strike-through/discount markup
        found anywhere on the page (grepped for "line-through",
        "text-decoration", "old_price", "discount", "sale", "strike" —
        none present) — Strike_Price and Price_Discounted are the same
        raw value.
  - No age-verification gate and no cookie-consent banner exist anywhere
    on this page (grepped and found none) — nothing to dismiss, unlike
    most other duty-free sites in this repo.
  - No GTR-exclusive badge/ribbon/tag of any kind was found anywhere in
    the card markup (grepped for "ribbon"/"badge"/"exclusive" — none
    present) — GTR_exclusive is left unset for every row so the cleaner
    emits a true null for the whole column.
  - No independent "N items"/"Showing X of Y" counter exists anywhere on
    the page to validate scrape coverage against — get_expected_item_count()
    returns None.
  - driver.get() reliably raises a Selenium TimeoutException on this
    domain ("Timed out receiving message from renderer") even at a 60s
    timeout, though the page evidently finishes loading in the background
    regardless — always wrap navigation in try/except here and follow it
    with an explicit sleep, don't treat the exception itself as a failure.
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

RETAILER_SLUG = "aircafe_uzbekistan"
BASE_URL = "https://aircafe.dutyfree.uz/home"
ALCOHOL_CATEGORY_DOM_ID = "category-2"

# Single site, single continuous catalog page — no real location or
# category-URL split, everything is scoped via the DOM section id above.
LOCATIONS = {
    "Uzbekistan": ["N/A"],
}
CATEGORIES = ["alcohol"]

_PRICE_RE = re.compile(r"([\d.,]+)")


class AirCafeUzbekistanScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

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
            self.driver.get(BASE_URL)
        except Exception:
            pass
        time.sleep(6)

    def get_expected_item_count(self):
        """No independent per-category count exists anywhere on this
        page — nothing to validate scrape coverage against here."""
        return None

    def paginate_or_scroll(self):
        """Confirmed live that this catalog's full item set (319 total,
        174 alcohol) already renders in a single page_source snapshot with
        no scrolling at all, and scrolling adds zero new items. Scroll a
        few times anyway as a defensive measure in case the real
        production catalog grows past whatever buffer Quasar renders by
        default."""
        for _ in range(10):
            self.driver.execute_script(
                "var el = document.querySelector('.q-scrollarea__container');"
                "if (el) { el.scrollTop = el.scrollHeight; }"
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(1.5)

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        category_section = soup.find("div", id=ALCOHOL_CATEGORY_DOM_ID)
        if category_section is None:
            return
        cards = category_section.find_all("div", class_="q-card")

        for card in cards:
            product_dict = {}
            try:
                img = card.find("img")
                photo_url = img["src"] if img else None
                product_dict["Product_link"] = photo_url
                id_match = re.search(r"/photo/(\d+)", photo_url or "")
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Product_link"] = None
                product_dict["ID_raw"] = None

            try:
                title_el = card.find("div", class_="q-item__label ellipsis text-center")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                price_el = card.find("div", class_="q-item__label text-bold text-primary")
                price_text = price_el.get_text(strip=True) if price_el else None
                price_match = _PRICE_RE.search(price_text or "")
                price_val = price_match.group(1) if price_match else None
                product_dict["Strike Price"] = price_val
                product_dict["Price Discounted"] = price_val
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # Size is left for the cleaner to extract from Brandline — no
            # dedicated Size field exists anywhere on this site (see module
            # docstring for the mixed real formats found).
            product_dict["Size"] = None

            # No GTR-exclusive concept found anywhere on this site — see
            # module docstring. Deliberately not set here so the cleaner
            # emits a true null for the whole column.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
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
                scraper = AirCafeUzbekistanScraper(channel, category)
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
