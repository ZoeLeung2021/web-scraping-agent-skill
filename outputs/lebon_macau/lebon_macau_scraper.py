"""
Scraper for Le Bon (Macau) — https://www.lebon.com.mo/

Corporate entity "Le Bon International (Macau) Limited" (footer address:
Level 20, AIA Tower, Avenida Comercial de Macau, Macau; contact
info_macau@leboninternational.com). Site title: "Le Bon Macau | Your One
Stop Liquor Supplier".

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/lebon_macau_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM / live JSON responses (headless
Chrome via undetected_chromedriver, not a text-extraction proxy):
  - NOT duty-free/travel-retail. Full homepage + nav + footer text checked
    for "duty free", "travellers", "airport", "passport", "boarding" —
    zero matches anywhere. This is an ordinary e-commerce liquor retailer
    selling to the general public with home delivery in Macau/Hong Kong
    (checkout flow's account redirect literally carries
    `region_country=HK`). Market = "Domestic", Country = "Macau" (no
    "DF " prefix), single "N/A" channel (one unified online catalog, no
    branch/location split found anywhere on the site).
  - Currency: the storefront's own `window.Shopify.currency` JS object is
    `{"active":"HKD","rate":"1.0"}` and `Shopify.country = "HK"` —
    confirmed live, no MOP figures or a currency/region selector anywhere
    on the page (the footer's `.footer__localization` block renders
    empty). So despite being a Macau-incorporated company, this storefront
    genuinely only ever charges in HKD. Currency = "HKD".
  - Platform: Shopify (`Shopify.shop = "le-bon-macau.myshopify.com"`).
    Rather than scraping rendered product-grid HTML, this scraper reads
    Shopify's own public `/collections/<handle>/products.json` REST
    endpoint directly (fetched through Selenium/undetected_chromedriver
    so it goes through the same browser context as every other scraper in
    this repo — no `requests`/httpx used) — this is standard, unauthenticated
    Shopify storefront JSON, not a private/admin API, and returns fully
    structured product+variant data (id, handle, title, vendor,
    product_type, tags, variants[].{id, sku, price, compare_at_price,
    title}) instead of ad-hoc HTML card scraping.
  - Category taxonomy CHECKED for the nested/overlapping-dimension trap
    per this build's brief, and it is a textbook example of it: the nav
    exposes "Scotch Whisky" (parent) with sub-region collections (Islay,
    Highland, Lowland, Speyside, Island) that are SUBSETS of the parent,
    "World Whisky" (parent) with sub-country collections (American,
    Taiwanese, Japanese, Indian, Canadian, Rest of World) that are
    likewise subsets of the parent, and a cross-cutting "Le Bon Exclusive"
    collection/tag that overlaps every spirit type simultaneously (e.g. a
    single product's `product_type` field is literally a comma-joined
    composite like "Islay Region, Le Bon Exclusive" — confirmed live).
    Looping every nav collection would massively double/triple-count SKUs.
    AVOIDED by looping exactly ONE non-overlapping dimension instead:
    Shopify's own `/collections/all` catalog, which contains every
    published product exactly once — confirmed live: paginating
    `/collections/all/products.json?limit=250&page=N` for pages 1-4
    (250+250+250+209=959, page 5 empty) returned 959 products with 959
    unique numeric `id` values and 959 unique `handle` values (zero
    duplicates), and the `/collections/all` HTML page's own visible
    "959 products" counter matches exactly. This single count is used
    directly as `get_expected_item_count()`'s coverage target.
  - Alcohol-only filter: this catalog is ~99.9% alcohol, but one genuine
    non-alcohol item was found and excluded — "Black Stainless Steel
    Barware Set (11 Pieces)" (`product_type` == "Cocktail Accessories"),
    a bar-tool set with no ABV/size-in-cl anywhere in its listing. Checked
    the full 959-product catalog for other accessory/gift-hardware
    keywords (glass, shaker, barware, decanter, tool, flask, jigger,
    strainer, muddler, opener, stopper, coaster, ice bucket, corkscrew) —
    the only other keyword hits were "Isle of Jura 12 Year Old Glass Set
    70cl | 40%" (a real 70cl whisky bottle bundled with glasses — kept,
    it's an alcohol SKU) and "Ardbeg Rollercoaster..." (false-positive
    substring match on "coaster") — so exactly one product_type value,
    "Cocktail Accessories" (case-insensitive exact match), is excluded.
  - Product cards / JSON records:
      - Product_link + ID: built directly from the JSON, not scraped from
        anchor tags. `https://www.lebon.com.mo/products/<handle>?variant=
        <variant_id>` where `<variant_id>` is Shopify's own numeric
        variant id — used as ID_raw. Deliberately NOT the site's `sku`
        field: checked live, the sku field is null on 2/967 variants and
        has 3 duplicate values reused across different products (e.g.
        "WHI00032CH" appears on two different SKUs) — the numeric
        Shopify variant id has zero nulls and zero duplicates across all
        967 variants, so it's the actually-stable identifier here.
      - Most products (951/959) have exactly one Shopify "Default Title"
        variant. 8 products genuinely have 2 real size variants each
        (e.g. Baileys Irish Cream 75cl/100cl, Johnnie Walker Black Label
        75cl/100cl) — this scraper emits one row per variant, not one row
        per product, so those 8 products contribute 2 rows each.
      - Brand: Shopify's own `vendor` field — populated on all 959
        products (0 empty), a real per-product field, not guessed.
      - Brandline: the product's `title` string as-is (e.g. "Ardbeg
        Perpetuum 70cl | 47.4%") — brand/name+size+ABV bundled into one
        string, same "one bundled title field" convention used by most
        other single-title-field retailers in this repo; the cleaner's
        standard title-regex fallback recovers Size from this when no
        dedicated Size is captured below.
      - Size: for the 8 multi-variant products, the variant's own
        `title` (e.g. "75cl", "100cl") is captured directly here as Size.
        For every other (single, "Default Title") variant, Size is left
        unset and recovered by the cleaner's regex fallback against
        Brandline — confirmed the size token (cl) is present in the title
        for 955/959 products. One confirmed real gap: "Hendrick's Gin |
        41.4%" has no size anywhere in its title, description, or JSON
        (checked its live product page for any size spec table — none
        found) — Size will be genuinely null for that one SKU, not a
        scraper bug.
      - Price: `variants[].price` is the current selling price.
        `variants[].compare_at_price` is Shopify's native "was" price —
        confirmed genuinely populated (not invented) on 176/959 products
        live (e.g. price 390.00 vs compare_at_price 480.00), and a real
        "sale" collection independently lists 139 of them. When
        compare_at_price is present and higher than price, Strike_Price =
        compare_at_price and Price_Discounted = price; otherwise both are
        set to the same `price` value (no discount to report), same
        convention as every other retailer built in this repo.
      - GTR_exclusive: "Le Bon Exclusive" is a real, per-product exclusive
        collection/tag on this site (confirmed two ways that agree
        exactly: the `/collections/le-bon-exclusive/products.json`
        listing paginates to 307 products, and a case-insensitive
        substring check for "le bon exclusive" in `product_type` across
        the full 959-product catalog also finds exactly 307, with 0
        products in one set but not the other). This is a genuine
        per-SKU exclusivity concept, so GTR_exclusive is a real
        "true"/"false" string here (mapped to "Yes"/"No" by the cleaner),
        never left unset.
  - Pagination: Shopify's `/products.json?...&page=N` query param is a
    real server-side parameter (documented Shopify Storefront behavior,
    not a client-side-only SPA state like the kings.sr trap flagged
    elsewhere in this repo) — confirmed directly: page=1..4 returned
    strictly decreasing/terminating counts (250, 250, 250, 209, then 0),
    with the combined 959 results containing zero duplicate ids across
    the whole run. No click-driven "next page" control was needed.
  - No blocking age-verification gate found: checked the homepage for any
    "age"/"verify"/"18"/gate-style interactive modal — Chrome loads
    `/collections/all/products.json` and every product page directly with
    no login/age-modal interstitial blocking content.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "lebon_macau"
BASE_URL = "https://www.lebon.com.mo"

# Single unified online catalog, no branch/location split found.
LOCATIONS = {
    "Macau": ["N/A"],
}

# Deliberately just ONE non-overlapping collection ("all") rather than the
# nav's many overlapping Type/Region/Exclusive collections — see module
# docstring for the nested-taxonomy trap this avoids.
COLLECTION_HANDLE = "all"
EXCLUSIVE_COLLECTION_HANDLE = "le-bon-exclusive"

# Real, confirmed non-alcohol product_type value to exclude (bar tools,
# no ABV/size — see module docstring).
EXCLUDED_PRODUCT_TYPES = {"cocktail accessories"}

PAGE_LIMIT = 250


class LeBonMacauScraper:
    def __init__(self, location, channel):
        self.location = location
        self.channel = channel
        self.product_dicts = []
        self.expected_count = None
        self.total_catalog_products = None
        self.excluded_nonalcohol_products = 0
        self.alcohol_products_kept = 0

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

    def _fetch_json(self, url):
        self.driver.get(url)
        time.sleep(1.5)
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        pre = soup.find("pre")
        text = pre.get_text() if pre else soup.get_text()
        return json.loads(text)

    def get_expected_item_count(self):
        """Independent coverage total straight from the /collections/all
        HTML page's own visible "<N> products" counter (confirmed live:
        matches the paginated JSON total of 959 exactly). The page ALSO
        renders smaller "<N> products" strings inside the Availability
        filter facets (e.g. "In stock (585 products)", "Out of stock
        (375 products)") — confirmed live these render BEFORE the real
        total in DOM order, so a naive first-match regex picks up 585
        instead of 959. The real catalog total is always the largest
        "<N> products" figure on the page (every facet is a subset of the
        whole), so this takes the max across all matches rather than the
        first."""
        self.driver.get(f"{BASE_URL}/collections/{COLLECTION_HANDLE}")
        time.sleep(4)
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        text = soup.get_text(" ", strip=True)
        matches = re.findall(r"(\d+)\s+products\b", text, re.IGNORECASE)
        return max((int(m) for m in matches), default=None)

    def fetch_all_products(self):
        """Paginates Shopify's own /collections/all/products.json REST
        endpoint (a real server-side page param, not a client-side SPA
        trap — see module docstring) until an empty page is returned."""
        all_products = []
        page = 1
        while True:
            url = f"{BASE_URL}/collections/{COLLECTION_HANDLE}/products.json?limit={PAGE_LIMIT}&page={page}"
            data = self._fetch_json(url)
            products = data.get("products", [])
            if not products:
                break
            all_products.extend(products)
            page += 1
            if page > 20:
                # safety valve — catalog should never realistically need
                # more than ~20*250=5000 products worth of pages.
                break
        return all_products

    def fetch_exclusive_handles(self):
        """Real per-product "Le Bon Exclusive" collection — paginated the
        same way as the main catalog."""
        handles = set()
        page = 1
        while True:
            url = f"{BASE_URL}/collections/{EXCLUSIVE_COLLECTION_HANDLE}/products.json?limit={PAGE_LIMIT}&page={page}"
            data = self._fetch_json(url)
            products = data.get("products", [])
            if not products:
                break
            handles.update(p["handle"] for p in products)
            page += 1
            if page > 20:
                break
        return handles

    def _price_pair(self, variant):
        price = variant.get("price")
        compare_at = variant.get("compare_at_price")
        try:
            has_real_discount = compare_at is not None and float(compare_at) > float(price)
        except (TypeError, ValueError):
            has_real_discount = False
        if has_real_discount:
            return compare_at, price
        return price, price

    def build_rows(self, products, exclusive_handles):
        self.total_catalog_products = len(products)
        for product in products:
            product_type = (product.get("product_type") or "").strip().lower()
            if product_type in EXCLUDED_PRODUCT_TYPES:
                self.excluded_nonalcohol_products += 1
                continue
            self.alcohol_products_kept += 1

            handle = product.get("handle")
            title = product.get("title")
            vendor = product.get("vendor")
            is_exclusive = handle in exclusive_handles or "le bon exclusive" in product_type

            for variant in product.get("variants", []):
                product_dict = {}
                variant_id = variant.get("id")
                product_dict["ID_raw"] = str(variant_id) if variant_id is not None else None
                product_dict["Product_link"] = (
                    f"{BASE_URL}/products/{handle}?variant={variant_id}" if handle else None
                )
                product_dict["Brand"] = vendor
                product_dict["Brandline"] = title

                variant_title = (variant.get("title") or "").strip()
                # "Default Title" is Shopify's placeholder for
                # single-variant products, not a real size string.
                product_dict["Size"] = variant_title if variant_title and variant_title.lower() != "default title" else None

                strike_price, price_discounted = self._price_pair(variant)
                product_dict["Strike Price"] = strike_price
                product_dict["Price Discounted"] = price_discounted

                product_dict["GTR_exclusive"] = "true" if is_exclusive else "false"
                product_dict["Category"] = product.get("product_type")

                self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            self.expected_count = self.get_expected_item_count()
            products = self.fetch_all_products()
            exclusive_handles = self.fetch_exclusive_handles()
            self.build_rows(products, exclusive_handles)
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
    total_scraped_products = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            print(f"Scraping {RETAILER_SLUG}: {country} / {channel}")
            scraper = LeBonMacauScraper(country, channel)
            try:
                scraper.run_all()
                for item in scraper.product_dicts:
                    item["Country"] = country
                    item["Channel"] = channel
                    item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                all_data.extend(scraper.product_dicts)
                unique_variant_ids = len({d["ID_raw"] for d in scraper.product_dicts if d.get("ID_raw")})
                total_scraped_products += scraper.alcohol_products_kept
                if scraper.expected_count is not None:
                    total_expected += scraper.expected_count
                    # Reconciliation: site's own "<N> products" total counts
                    # EVERY collections/all listing including the 1 confirmed
                    # non-alcohol item (see module docstring), so the exact
                    # expected match is: total_catalog_products ==
                    # expected_count, and alcohol_products_kept ==
                    # expected_count - excluded_nonalcohol_products.
                    catalog_flag = "OK" if scraper.total_catalog_products == scraper.expected_count else "MISMATCH"
                    print(
                        f"  -> site says {scraper.expected_count} products in /collections/all; "
                        f"fetched {scraper.total_catalog_products} via paginated JSON [{catalog_flag}]"
                    )
                    print(
                        f"  -> excluded {scraper.excluded_nonalcohol_products} confirmed non-alcohol product(s); "
                        f"kept {scraper.alcohol_products_kept} alcohol products "
                        f"-> {unique_variant_ids} unique SKU/variant rows "
                        f"(rows: {len(scraper.product_dicts)})"
                    )
                else:
                    print(f"  -> scraped {len(scraper.product_dicts)} rows / site total unknown")
            except Exception as e:
                print(f"FAILURE scraping {country}/{channel}: {e}")

    if total_expected:
        print(f"TOTAL: alcohol products scraped {total_scraped_products} / site catalog total {total_expected} products")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
