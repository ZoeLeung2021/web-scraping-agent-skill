"""
Scraper for Niagara Duty Free — https://niagaradutyfree.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/niagara_duty_free_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer, genuinely confirmed via the site's own copy: operator is
    "Niagara Falls Duty Free Shop", 5726 Falls Ave, Niagara Falls, ON,
    Canada (footer address + phone), physically on the Canadian side of
    the Rainbow Bridge. The /can-i-shop FAQ page states outright "Can I
    shop duty free? Yes you can!" and walks through Canadian- and
    American-traveler duty allowances for crossing into the USA — this is
    a real land-border duty-free shop, same template as the Calle/
    Fleggaard bordershop builds, just the reverse direction (Canada ->
    USA instead of Denmark -> Germany). Market = "GTR". Country =
    "Canada" (-> "DF Canada" after the cleaner's GTR prefix).
    "Designed and Developed by DANIMA Creative Group" in the footer is
    just the web vendor/platform builder (danimatechnologies.com), not
    the retailer — do not confuse it for the operator.
  - Platform is a custom DANIMA Technologies catalogue CMS (not
    Shopify/WooCommerce/Magento) — server-rendered `.category_items_wrapper`
    markup, Bootstrap 5 modals for the "how do I buy this duty free"
    popup on each card, no JSON state blob.
  - Single physical location, single catalog/price list — no per-store
    variation found (unlike Calle/Fleggaard's multi-branch-but-same-catalog
    pattern, Niagara Duty Free is literally one shop). Modeled as one
    "Canada" -> ["N/A"] channel, same convention as other single-site
    retailers in this repo.
  - Real category taxonomy, confirmed via the site's own nav (footer +
    header menu), restricted here to the two alcohol-relevant top nav
    items and their leaf subcategories (Fragrance & Cosmetics,
    Confections, and Souvenirs & Jewelry are separate top-nav items and
    are deliberately excluded — that's how non-alcohol is filtered out,
    at the category-selection level, not by per-item text matching):
      Alcohol: canadian-whisky, american-whiskey, irish-whiskey, brandy,
        cognac, gin, liqueurs, rum, scotch, tequila, vodka
      Beer & Wine: beer, icewine, wine
  - NESTED-TAXONOMY TRAP CHECKED AND AVOIDED: visiting the bare parent
    URL (e.g. /catalogues/alcohol with no leaf slug) renders an
    aggregate "<Category> > All" view unioning every leaf subcategory
    (confirmed: 129 items on /catalogues/alcohol == exact sum of all 11
    alcohol leaf pages; 46 on /catalogues/beer-and-wine == exact sum of
    beer+icewine+wine). Crucially, the per-product modal IDs are
    disjoint across every leaf subcategory (verified: 175 leaf-page
    items scraped across all 14 leaves -> 175 unique modal IDs, zero
    duplicates) — so, unlike some sites, a product here lives under
    exactly ONE leaf category, not several simultaneous tag dimensions.
    This scraper loops the 14 LEAF pages only (never the 2 aggregate
    "All" parent pages) to keep the loop semantically clean, but doing
    so introduces no double-counting risk either way given the disjoint
    IDs confirmed above.
  - `/catalogues/alcohol/american-whiskey` is a genuine, confirmed-empty
    leaf category right now (0 products in `.category_items_wrapper`,
    the "Alcohol > American Whiskey" heading still renders) — not a
    scraping bug, just nothing currently stocked there. Left in the
    category list; the scraper naturally yields 0 rows for it.
  - No pagination anywhere: every leaf page renders its full item list
    server-side on first load (confirmed no `.pagination`/`.pager`/
    "load more" elements on any tested category, including the largest,
    Scotch, at 29 items). A single `driver.get()` + short wait is
    sufficient; no scrolling or clicking required.
  - Each product card is `<div class="items-wrapper" data-bs-toggle="modal"
    data-bs-target="#modal_<N>">` inside
    `.category_items_wrapper .category_items`:
      - `data-bs-target="#modal_<N>"` — a genuinely stable, retailer-
        owned numeric per-product ID (confirmed disjoint across every
        category, see above). Used as ID_raw here.
      - `.item-name` — a single bundled title field, e.g.
        "Crown Royal Deluxe (1L)", "Alexander Keith's Cans
        (24 x 355mL)", or, for every Wine item and a few Liqueurs (e.g.
        "Drambuie", "Luxardo Sambuca"), just a bare name with NO size at
        all — confirmed live, not a scraping gap. No separate Brand
        field exists anywhere in the DOM; captured whole into Brandline
        here (Brand left None), same convention as the Calle/Fleggaard
        precedent for single-title-field sites — Brand/Brandline split
        is genuinely ambiguous without a maintained brand dictionary.
      - `.item-prices` holds exactly two `.item-price` nodes: a CAD
        price (flag_ca.png) and a USD price (flag_us.png). These are
        NOT a strike-through/discount pair — they're the same
        transaction priced in two currencies for cross-border shoppers
        (confirmed: grepped the whole rendered DOM for "line-through",
        "<del", "text-decoration" (only hit was a generic CSS link
        reset), "old-price", "sale", "strike" — nothing). Only the CAD
        price (the shop's actual selling currency, since the physical
        store is in Canada) is captured, into both Strike_Price and
        Price_Discounted (same value) — same "no real discount concept"
        pattern as Calle/Fleggaard.
      - No GTR-exclusive badge/ribbon/"Exclusive" text found anywhere
        (grepped category pages, the /specials page — currently an
        empty placeholder, "Check out our current Duty Free Specials"
        with zero items — and /can-i-shop). Deliberately not set here,
        so the cleaner emits a true null for the whole column.
  - Product_link: there is no separate per-product detail page on this
    site (everything lives on the category page + a Bootstrap modal) —
    so, per this project's schema convention for sites with no PDP,
    Product_link is built as `<category_page_url>#modal_<N>`, a stable,
    unique, dereferenceable anchor back to the exact card/modal.
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

RETAILER_SLUG = "niagara_duty_free"
BASE_URL = "https://niagaradutyfree.com"

# Single physical shop, single catalog — see module docstring.
LOCATIONS = {
    "Canada": ["N/A"],
}

# Leaf (non-overlapping) alcohol categories only — see module docstring
# for the nested-taxonomy check that confirmed these don't overlap and
# for why the two aggregate "All" parent pages are deliberately skipped.
CATEGORIES = [
    "catalogues/alcohol/canadian-whisky",
    "catalogues/alcohol/american-whiskey",
    "catalogues/alcohol/irish-whiskey",
    "catalogues/alcohol/brandy",
    "catalogues/alcohol/cognac",
    "catalogues/alcohol/gin",
    "catalogues/alcohol/liqueurs",
    "catalogues/alcohol/rum",
    "catalogues/alcohol/scotch",
    "catalogues/alcohol/tequila",
    "catalogues/alcohol/vodka",
    "catalogues/beer-and-wine/beer",
    "catalogues/beer-and-wine/icewine",
    "catalogues/beer-and-wine/wine",
]

_MODAL_ID_RE = re.compile(r"#modal_(\d+)")


class NiagaraDutyFreeScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/{self.category}"

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
        self.get_url()
        try:
            self.driver.get(self.url)
        except Exception:
            pass
        time.sleep(6)

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        wrapper = soup.find("div", class_="category_items_wrapper")
        cards = wrapper.find_all("div", class_="items-wrapper") if wrapper else []

        for card in cards:
            product_dict = {}

            try:
                target = card.get("data-bs-target", "")
                m = _MODAL_ID_RE.search(target)
                modal_id = m.group(1) if m else None
                product_dict["ID_raw"] = modal_id
                product_dict["Product_link"] = (
                    f"{self.url}#modal_{modal_id}" if modal_id else self.url
                )
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None
                product_dict["Product_link"] = self.url

            try:
                name_el = card.find("div", class_="item-name")
                product_dict["Brandline"] = name_el.get_text(strip=True) if name_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            # No dedicated Size field anywhere on this site — Size lives
            # (when present at all) inside the bundled item-name text, so
            # it's left unset here and pulled out of Brandline by the
            # cleaner's fallback regex, same as Calle/Fleggaard.
            product_dict["Size"] = None

            try:
                price_els = card.find_all("div", class_="item-price")
                # First .item-price (flag_ca.png) is the CAD price — the
                # shop's real selling currency, since the physical store
                # is in Canada. The second (flag_us.png) is a USD
                # conversion for American shoppers, not a discount — see
                # module docstring.
                cad_price = price_els[0].get_text(strip=True) if price_els else None
                product_dict["Strike Price"] = cad_price
                product_dict["Price Discounted"] = cad_price
            except (AttributeError, TypeError, IndexError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive badge/ribbon/"Exclusive" text found
            # anywhere on this site — see module docstring. Deliberately
            # not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
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
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category in CATEGORIES:
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category}")
                scraper = NiagaraDutyFreeScraper(channel, category)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    print(f"  -> {category}: scraped {scraped_count}")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category}: {e}")

    print(f"TOTAL: scraped {total_scraped}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
