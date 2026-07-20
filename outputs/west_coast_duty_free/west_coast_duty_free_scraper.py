"""
Scraper for West Coast Duty Free — https://westcoastdutyfree.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/west_coast_duty_free_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):

  - Investigation started from https://dutyfreecanada.com/stores/west-coast-duty-free/,
    which is an FDFA (Frontier Duty Free Association / "Duty Free and
    Frontier Association") industry directory site — "Canada's Privately
    Owned Land Border Duty Free Shops". That page and the dutyfreecanada.com
    site as a whole have NO product catalog or prices anywhere: they are
    pure store-locator pages (address, phone, border-crossing name, generic
    "perfume, cosmetics, alcohol, tobacco..." category blurb, border wait
    times). dutyfreecanada.com/stores/ lists ~25 separate, independently
    OPERATED land-border duty-free shops across BC/AB/SK/MB/ON/QC/NB (e.g.
    Aldergrove, Osoyoos, Kingsgate, Niagara Falls-Rainbow Bridge, Windsor,
    Stanstead, St. Stephen, etc.) — this is an association/directory site,
    NOT a retail chain with a shared parent catalog. Each listed store is a
    genuinely separate business, most with their own separate website (the
    West Coast page itself links out to westcoastdutyfree.com as "the"
    website; the Niagara Falls store in this same directory was already
    built separately in this project as niagara_duty_free, sourced from its
    own site niagaradutyfree.com, confirming the pattern). No per-location
    catalog scraping of dutyfreecanada.com is possible or needed — there is
    nothing there to scrape, and the other directory entries are OUT OF
    SCOPE for this build (separate businesses, would need their own
    from-scratch investigation each, same as Niagara was).
  - The real retailer operates at westcoastdutyfree.com: "West Coast Tax &
    Duty Free" (site title "Liquor - West Coast Tax & Duty Free Store",
    footer copyright "West Coast Tax & Duty Free"). Physical location: 111
    - 176th Street, Surrey, BC, Canada V3Z 9S4, phone 604-538-3222 — on the
    Pacific Highway border crossing (Highway 15/99), the Canadian side of
    the Surrey, BC <-> Blaine, WA (Peace Arch/Pacific Highway) crossing
    into the United States.
  - Genuinely confirmed GTR via the site's own copy: FAQ states "'Duty
    Free' refers to items that can be purchased when crossing national
    borders... Duty free items are for export only and must be taken out
    of the country" and "anyone shopping at West Coast Duty Free must cross
    the border into the United States". Market = "GTR". Country = "Canada"
    (-> "DF Canada" after the cleaner's GTR prefix).
  - Platform: WordPress + Elementor page builder (Rank Math SEO sitemap
    plugin). Confirmed via /sitemap_index.xml -> page-sitemap.xml (10
    static pages total), post-sitemap.xml (1 dummy "hello-world" post),
    category-sitemap.xml (1 dummy "uncategorized" term) — there is NO
    WooCommerce/product post type and NO per-product detail pages anywhere
    on this site. This is a small marketing brochure site, not an
    e-commerce storefront.
  - REAL, SMALL alcohol assortment confirmed: exactly ONE page,
    /liquor-specials/, holds the entire liquor catalog — 15 static
    Elementor "image-box" widgets (name + one price + product photo each).
    There is no broader "Liquor" category page, no per-spirit-type pages
    (no whisky/vodka/gin/rum breakdown), no pagination, and no other page
    on the site (home, /products/, /new-arrivals/) adds any additional
    liquor SKUs beyond what's already in this one list — confirmed by
    reading the full rendered text of every page in the main nav
    (Home, Products, Treats, Sun Glasses, Jewellery, Handbags, Liquor
    Specials, New Arrivals). The home page's "Liquor Specials" teaser
    section shows 4 of these same 15 items verbatim, not a different set.
    /products/ covers Cosmetics, Fragrances, Chocolates, Sunglasses,
    Jewellery, Handbags — zero liquor content, correctly excluded here.
    /new-arrivals/ is skincare/fragrance/sunglasses only, zero liquor.
    NESTED-TAXONOMY TRAP: N/A — there is only one flat list, no competing
    category dimensions to accidentally double-loop.
  - Each of the 15 items is a `<div class="elementor-image-box-wrapper">`
    containing:
      - `<img class="... wp-image-<N> ...">` — the WordPress media
        attachment ID. This is the only stable per-item identifier on the
        page (no separate SKU/product ID exists anywhere); used as
        ID_raw here.
      - `<h6 class="elementor-image-box-title">` — a single bundled field,
        e.g. "Crown Royal 1.14 litre", "Don Julio Reposado 750ml" — Brand
        and Size are not separately tagged anywhere in the DOM, so (same
        convention as niagara_duty_free/Calle/Fleggaard) the whole string
        is captured into Brandline, Brand left None, and Size is pulled
        out of Brandline by the cleaner's fallback regex.
      - `<p class="elementor-image-box-description">` — the price text.
        For 14 of 15 items this is a single "$NN" value. Crown Royal is
        the one exception: "$30 *2/$56 *3/$78 *4/$96" — a multi-buy bundle
        note (buy 2 for $56, etc.), NOT a strikethrough/discount pair
        (confirmed: grepped the whole rendered homepage/liquor-specials
        HTML for "sale", "discount", "line-through", "<del" — zero hits
        anywhere on the site). Only the single per-bottle price ("$30") is
        captured here, into both Strike_Price and Price_Discounted, same
        "no real discount concept" convention as niagara_duty_free.
      - No GTR-exclusive badge/ribbon/tag anywhere on the site. The word
        "exclusive" appears only in generic marketing copy ("Explore our
        exclusive collection...", "premium spirits at exclusive duty-free
        prices") describing the whole store, never a specific SKU.
        Deliberately not set here, so the cleaner emits a true null for
        the whole column (no GTR_exclusive concept found at all).
  - No pagination anywhere (single static page, all 15 items render
    server-side on first load) — one driver.get() + short wait is enough.
  - Product_link: there are no individual product detail pages on this
    site — everything lives as a static block on /liquor-specials/, with
    no <a href> at all on any item (not even a modal). Per this project's
    convention for no-PDP sites, Product_link is built as
    `<liquor_specials_url>#wp-image-<N>` — a stable, unique anchor keyed to
    the same WordPress attachment ID used as ID_raw, pointing back at the
    exact page.
  - Currency: site states prices are "in Canadian dollars" explicitly
    (homepage: "...jewellery in Canadian dollars"), and the shop is
    physically in BC, Canada — LOCAL_CURRENCY = "CAD" in the cleaner.
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

RETAILER_SLUG = "west_coast_duty_free"
BASE_URL = "https://westcoastdutyfree.com"

# Single physical shop, single catalog — see module docstring.
LOCATIONS = {
    "Canada": ["N/A"],
}

# Single flat liquor listing page — see module docstring for why this is
# the entire alcohol assortment (no whisky/vodka/gin/etc. sub-pages exist).
CATEGORIES = [
    "liquor-specials",
]

_WP_IMAGE_ID_RE = re.compile(r"wp-image-(\d+)")
_PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{1,2})?")


class WestCoastDutyFreeScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/{self.category}/"

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
        time.sleep(5)

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.find_all("div", class_="elementor-image-box-wrapper")

        for card in cards:
            product_dict = {}

            try:
                img = card.find("img")
                classes = " ".join(img.get("class", [])) if img else ""
                m = _WP_IMAGE_ID_RE.search(classes)
                wp_id = m.group(1) if m else None
                product_dict["ID_raw"] = wp_id
                product_dict["Product_link"] = (
                    f"{self.url}#wp-image-{wp_id}" if wp_id else self.url
                )
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None
                product_dict["Product_link"] = self.url

            try:
                title_el = card.find("h6", class_="elementor-image-box-title")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            # No dedicated Size field anywhere on this site — Size lives
            # (when present at all) inside the bundled title text, so it's
            # left unset here and pulled out of Brandline by the cleaner's
            # fallback regex, same as niagara_duty_free/Calle/Fleggaard.
            product_dict["Size"] = None

            try:
                desc_el = card.find("p", class_="elementor-image-box-description")
                desc_text = desc_el.get_text(" ", strip=True) if desc_el else ""
                # Only the first "$NN" token is the real per-bottle price —
                # any further tokens (e.g. Crown Royal's "*2/$56 *3/$78
                # *4/$96") are multi-buy bundle notes, not a strikethrough/
                # discount pair — see module docstring.
                price_match = _PRICE_RE.search(desc_text)
                price = price_match.group(0) if price_match else None
                product_dict["Strike Price"] = price
                product_dict["Price Discounted"] = price
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive badge/ribbon/"Exclusive" SKU tag found
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
                scraper = WestCoastDutyFreeScraper(channel, category)
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
