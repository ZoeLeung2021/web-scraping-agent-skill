"""
Selenium + undetected_chromedriver scraper template for a single retailer
site — the "bronze" step of the GTR_Pricing pipeline.

Copy this into outputs/<retailer_slug>/<retailer>_scraper.py in THIS project
first — draft and test it here, then deploy the finished version into
GTR_Pricing/scrapers/<retailer>_scraper.py as a separate step (see SKILL.md's
"Output location" section). Fill in the TODOs. This script's only job is to
extract RAW fields as they appear on the page and land them in the bronze
Databricks Volume — no cleaning/normalizing here, that happens in the paired
silver script (see cleaner_template.py).

This mirrors the shape of every other scraper in scrapers/ so that the
try/finally driver cleanup, popup handling, and upload step stay consistent
across retailers. Two real scrapers to compare against depending on shape:
  - cloud9_laos_scraper.py   — single country/site, loops over categories
  - dufry_europe_scraper.py  — many countries, many airports per country

This pipeline scrapes alcohol (wine & spirits) pricing ONLY — see the
CATEGORIES note below before picking which pages/codes to scrape on a site
that sells other product types alongside liquor.

Runs inside the etl-scrapers Docker image via Kestra — see
kestra_flow_template.yaml. CHROME_BIN / CHROMEDRIVER_PATH are set by that
image; running locally, either set those env vars yourself or let
undetected_chromedriver auto-detect Chrome.
"""

import io
import json
import os
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient

# TODO: set this for the retailer being scraped
RETAILER_SLUG = "TODO_retailer_slug"  # used in the bronze Volume path, e.g. "cloud9_laos"

# TODO: map every country this retailer's site serves to the list of
# locations/channels within it (airport codes, store branches, etc).
#
# - Single-site retailer (no real multi-location split, e.g. cloud9_laos):
#     use one country with one placeholder channel, e.g. {"Laos": ["N/A"]}
# - Multi-airport, single-country retailer (e.g. Dufry UK):
#     {"UK": ["london-heathrow", "manchester", "edinburgh", ...]}
# - Multi-country retailer (e.g. Dufry Europe):
#     {"Italy": ["milan", "pisa", "bergamo"], "Finland": ["helsinki"], ...}
#
# If this site's real "loop dimension" is product category rather than
# location (like cloud9_laos's Beer&Sake/Whisky/Spirits categories), put the
# category codes here instead and set Country/Channel to fixed values in the
# cleaner rather than tagging them per-row below.
LOCATIONS = {
    "TODO_Country": ["TODO_channel_or_location_code"],
}

# TODO: this team scrapes alcohol (wine & spirits) pricing ONLY — even on
# sites that also sell perfume, tobacco, chocolate, electronics, etc.
# alongside liquor. List only the alcohol category codes/slugs the site
# separates by, e.g. ["whisky", "spirits", "wine", "beer", "champagne"]
# (see cloud9_laos_scraper.py's Category_code dict for the reference shape).
# Scope to alcohol at the URL/category level rather than scraping the whole
# catalog and filtering afterward — it's far more reliable than trying to
# guess "is this product alcohol?" from the DOM. If the site already has one
# alcohol-only listing page covering everything (e.g. Dufry's "liquor" view),
# use a single placeholder category here so the loop below still runs once.
CATEGORIES = ["TODO_alcohol_category_code_or_slug"]


class RetailerScraper:
    """TODO: rename to <Retailer>Scraper."""

    def __init__(self, location, category):
        self.location = location  # a value from LOCATIONS[country] above
        self.category = category  # a value from CATEGORIES above
        self.product_dicts = []
        self.expected_count = None  # from get_expected_item_count(), for validation only — see references/testing.md

    def get_url(self):
        # TODO: build the location+category-specific URL. If every
        # location/category shares the same URL, just return a fixed URL.
        self.url = f"https://example.com/TODO/{self.location}/{self.category}"

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # TODO: if this site's language isn't English, first look for an
        # explicit language/region switcher in the page UI (many sites have
        # one — it's simpler and more reliable than auto-translate). Only if
        # there's no such switcher, force Chrome's built-in translate feature
        # like this (see elitalco_kazakhstan_scraper.py for the reference):
        #   options.add_experimental_option("prefs", {
        #       "translate_whitelists": {"ru": "en"},  # source-lang -> "en"
        #       "translate": {"enabled": True},
        #   })
        # If neither works reliably, leave the raw text as-is here and
        # translate Brand/Brandline in the cleaner instead via Databricks'
        # ai_translate — see cleaner_template.py.

        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.get_url()
        self.driver.get(self.url)
        time.sleep(1)

    def dismiss_age_verification(self):
        """TODO: fill in the real selector, or delete this call in run_all()
        if the site has no age gate. Wrapped in try/except by the caller
        since this popup doesn't reliably appear on every page load."""
        self.driver.find_element(By.ID, "TODO_age_verify_button_id").click()

    def dismiss_cookie_banner(self):
        """TODO: same as above — fill in or remove."""
        self.driver.find_element(By.XPATH, "//TODO/cookie/accept/button").click()

    def get_expected_item_count(self):
        """TODO: if this category page shows its own total ("N results",
        "Showing 1-24 of 179", etc.), extract and return it as an int here.
        Used purely to validate scrape coverage against — see
        references/testing.md — not part of the product data. Return None
        if the site doesn't display one; the caller handles that."""
        return None

    def paginate_or_scroll(self):
        """
        TODO: implement whichever pagination style this site uses.
        Two common patterns already used elsewhere in scrapers/:

        1. Infinite scroll (see cloud9_laos_scraper.py):
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            while True:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
                time.sleep(2)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

        2. Numbered "next page" button:
            while True:
                self.get_main()
                next_btn = self.driver.find_element(By.CSS_SELECTOR, "TODO_next_button")
                if not next_btn.is_enabled():
                    break
                next_btn.click()
                time.sleep(2)
        """
        pass

    def get_main(self):
        page_html = self.driver.page_source
        soup = BeautifulSoup(page_html, "html.parser")
        # TODO: replace with the real product-card container selector.
        # If the site embeds a JSON blob (window.someProducts, JSON-LD, or a
        # data-product attribute) instead, parse that directly here rather
        # than scraping the rendered DOM — it's usually far more reliable.
        # If this category page ever mixes in non-alcohol items despite the
        # CATEGORIES scoping above (rare, but happens on "gifts"/"featured"
        # style pages), add a per-card skip check here rather than relying
        # on the cleaner to filter it out downstream.
        products = soup.find_all("div", class_="TODO_product_card_class")

        for product in products:
            # Every field extraction below should get its own try/except in
            # the real implementation (see dufry_europe_scraper.py) so one
            # missing selector doesn't blank out the rest of the item — the
            # single try/except here is just a placeholder shape.
            product_dict = {}
            try:
                product_dict["Product_link"] = "TODO"
                product_dict["ID_raw"] = "TODO"  # retailer's own SKU/product code, if it has one
                product_dict["Brand"] = "TODO"
                product_dict["Brandline"] = "TODO"
                product_dict["Size"] = "TODO"
                product_dict["Strike Price"] = "TODO"       # full/original price (space in the key, matches raw convention)
                product_dict["Price Discounted"] = "TODO"    # current/selling price
                # GTR_exclusive: look for a visual badge/ribbon/tag on the
                # product — often overlaid on the product image itself
                # (a class like "ribbon"/"badge"/"tag"/"flag" inside the
                # card, e.g. a <span class="c-ribbon">Travel Edition</span>
                # sitting right after the image wrapper), not just a hidden
                # JSON field. If you find one JSON key that seems related
                # (e.g. a generic tracking field), verify it actually
                # correlates with a real visually-badged product before
                # trusting it — don't assume it's populated from a single
                # spot-check on a non-exclusive item. Some sites also have a
                # dedicated "Exclusives" nav category you can cross-reference
                # product IDs against as a second signal.
                #
                # Decide this ONCE for the whole retailer during step 2
                # inspection, not per-product: if the site has this concept
                # at all, always set a real string here (blank "" default,
                # the flagged text when present) — the cleaner turns that
                # into "Yes"/"No". If the site has NO such concept anywhere,
                # leave this key out entirely (or set it to Python None) for
                # every row — the cleaner then emits a true null for the
                # whole column instead of "No" everywhere, since "No" and
                # "this site doesn't track that" are different facts.
                product_dict["GTR_exclusive"] = "TODO"
            except (AttributeError, TypeError):
                # A malformed card shouldn't kill the whole scrape.
                pass

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            time.sleep(2)
            try:
                self.dismiss_age_verification()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            try:
                self.dismiss_cookie_banner()
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


def upload_to_databricks(data: list[dict], volume_path: str) -> None:
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
                scraper = RetailerScraper(channel, category)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        # Tagging Country/Channel here (not as a fixed literal)
                        # is what lets the cleaner tell locations apart — see
                        # clean_dufry_europe.py, which reads these per-row rather
                        # than assuming one Country/Channel for the whole file.
                        # If this retailer really only has one location, this
                        # still works fine — it just tags every row the same way.
                        # Category isn't part of the output schema (it was only
                        # used to scope the URL to alcohol products), so it's
                        # not tagged onto the row here.
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    # Coverage check against the site's own count, if
                    # get_expected_item_count() was filled in — see
                    # references/testing.md. Don't skip this: a wrong
                    # selector usually shows up as a low/zero count here,
                    # not a crash.
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
