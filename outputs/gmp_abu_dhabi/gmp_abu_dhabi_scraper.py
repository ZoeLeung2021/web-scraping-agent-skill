"""
Scraper for GMP (Abu Dhabi alcohol home-delivery retailer) — https://gmp.ae/

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/gmp_abu_dhabi_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source,
no text-extraction proxy used for this build):
  - NOT duty-free/travel-retail. GMP is a UAE domestic online alcohol
    retailer with home delivery in Abu Dhabi and Al Ain — the homepage nav
    itself uses SEO slugs like "order-alcohol-online-free-liquor-delivery-
    store-abu-dhabi-al-ain" and "alcohol-free-delivery-liquor-store-and-
    beverage-shops-in-abu-dhabi-uae." No "duty free"/"travel retail"
    language anywhere on the site. Physical branches are listed under
    "Our Locations" — Khalidiya, Mussafah, Najda, Reem Island, AD WTC,
    Centro, Saadiyat, Al Muneera — all Abu Dhabi neighborhoods/malls, all
    served by one unified online catalog (no per-branch price variation
    found; a store-locator page exists but the shop/category pages
    themselves show no branch selector affecting price). Market =
    "Domestic", Country = "Abu Dhabi" (user's explicit call — GMP is
    specifically an Abu Dhabi/Al Ain delivery service, not a nationwide
    UAE retailer, so the emirate-level name is used rather than the
    country) (no "DF " prefix),
    single "N/A" channel.
  - **Domestic_Tax is an open item requiring the user's sign-off before
    it's written into the cleaner** (per this skill's rule that a
    Domestic retailer's tax figure must be proposed and confirmed, never
    invented). Researched proposal: Abu Dhabi has retained a 30%
    municipality tax on retail alcohol purchases (it did NOT suspend this
    tax the way Dubai did from Jan 2023–Dec 2024 before Dubai reinstated
    its own 30% tax in Jan 2025 — the two emirates have genuinely
    different histories here, so "UAE" isn't a single answer). Alcohol
    also carries a 50% import/customs duty at the CIF value, which the
    retail price already embeds without a separate line item (same
    "most retail sites don't show tax-inclusive breakdown" situation the
    schema doc warns about) — the import duty is a wholesale/importer-
    level cost baked into shelf price, not a separate consumer-facing tax,
    so the retail-level figure to propose for Domestic_Tax is the 30%
    Abu Dhabi municipality tax, not the 50% import duty. This is left
    null in clean_gmp_abu_dhabi.py pending explicit confirmation — see
    that file's docstring and the project memory file for the same note.
  - Platform: WordPress + WooCommerce, Avada theme (`fusion-*` CSS
    classes throughout). Real per-product SKUs exist (`data-product_sku`
    on the add-to-cart button, e.g. "SV0022", "WG1655") — also duplicated
    in a `data-gtm4wp_product_data` JSON attribute per card (Google Tag
    Manager for WooCommerce plugin) that additionally carries
    `item_category`/`item_brand`, but `item_brand` was confirmed EMPTY on
    every sampled product (checked 12 across the Spirits category) so it
    isn't used — Brand is left null, Brandline is the full product title,
    same convention as most other single-title-field retailers built this
    session (e.g. Diplomatic Shop Serbia, Calle).
  - The catalog mixes real alcohol with bar merchandise/glassware
    (Bar Essentials, Cocktail sets, Wine Opener nav items — corkscrews,
    glasses, shakers, hats, bar mats) and a promotional "Gift with
    Purchase" (vap) bundle category — all deliberately EXCLUDED per this
    skill's alcohol-only scope. "Premium Products" is also excluded: it's
    a cross-cutting merchandising tag layered on top of real categories
    (confirmed via product li classes — a Chateau Palmer wine carries
    both `product_cat-wines` AND `product_cat-premium-products`
    simultaneously), not a distinct product family, so scraping the real
    categories below already covers everything tagged "premium."
  - Category taxonomy is genuinely messy — several nav labels map to
    slugs that don't match their own subcategory parents (e.g. top-nav
    "Wine" links to `/product-category/wines/` but its child links
    Fine Wines/Champagne/Red Wine/Rose Wine/White Wine/Sparkling all
    live under a DIFFERENT parent slug, `/product-category/wine-
    champagne/`). Confirmed live that `wine-champagne` (15 pages) is a
    strict superset of `wines` (10 pages, missing Champagne/Sparkling) —
    so `wine-champagne` is used, not `wines`. Similarly `spirits-abu-
    dhabi` and `spirits-abu-dhabi-gmp-online-liquor-store-in-abu-dhabi`
    are the SAME taxonomy term under two slugs (identical title, identical
    20-page count, and WooCommerce's own pagination links canonicalize to
    the long slug) — the long slug is used directly to avoid relying on
    the redirect. Beer/cider is split across two genuinely different
    parents that don't fully overlap: `beer-rtd` (Cider/Lager-Pilsner/
    Strong Beer, 5 pages) and `beer-and-cider` (Weizen plus other beer
    products, 2 pages) — both are scraped since neither is a superset of
    the other; any product appearing in both is deduplicated by SKU in
    the cleaner, same as every other retailer's cleaner in this repo.
  - CATEGORIES (6 real alcohol taxonomy slugs, chosen as the broadest
    non-overlapping-as-possible set after checking every candidate slug
    live): wine-champagne, spirits-abu-dhabi-gmp-online-liquor-store-in-
    abu-dhabi, beer-rtd, beer-and-cider, liqueur-aperitif, ready-to-drink-
    products.
  - Product cards are `<li class="product ...">` inside `<ul class=
    "products">`. Each card:
      - Product_link + Brandline: `<h3 class="product-title ..."><a
        href="...">Title</a></h3>` — e.g. "Absolut Blue Vodka (75CL)",
        "2014 Chateau Palmer Cantenac Margaux (75CL)" — brand+name+size
        bundled into one string.
      - ID: the add-to-cart button's `data-product_sku` attribute (e.g.
        "SV0022") — a real, stable retailer SKU, used directly rather
        than the numeric `data-product_id`/GTM `internal_id` (both also
        present and equally stable, but the SKU is the retailer's own
        product code per the schema's stated preference).
      - Price: standard WooCommerce markup. Non-sale products show a
        single `<span class="price"><span class="woocommerce-Price-
        amount">` (e.g. "AED 2,900.00"); sale products (confirmed live,
        9 of 12 sampled cards in Spirits were on sale) show real `<del>`
        (original) and `<ins>` (current) price nodes inside the same
        `span.price` — captured separately as Strike_Price (del) and
        Price_Discounted (ins), a genuine discount concept unlike most
        other retailers built this session. Currency is AED throughout.
      - GTR_exclusive: checked the full page text and every badge-style
        span/div for "exclusive," "only at GMP," "GMP exclusive," "members
        only" — zero matches on every category checked. The only badge
        found anywhere is the standard WooCommerce `<span class=
        "onsale">Sale!</span>`, a discount indicator, not an exclusivity
        signal. This is the true null case (the site never signals any
        product-exclusivity concept at all) — GTR_exclusive is left unset
        for every row.
  - WooCommerce "variable" products (multi-pack/case options, e.g.
    "Krombacher Long Neck (33CL)", confirmed live on beer-and-cider page
    2 — 3 of 24 sampled items) don't render a simple `add_to_cart_button`
    with a fixed SKU/price on the listing page (they need a "Select
    options" variation click instead, and the GTM JSON's `price` field is
    a `0` placeholder for these). ID_raw falls back to the GTM JSON's own
    `sku`/`internal_id` fields for these rows so they don't get a null ID
    — but Price_Discounted/Strike_Price are genuinely unknown from the
    listing page for a variable product and are correctly left null,
    which is real, not a scraper bug (confirmed by inspecting the raw
    card HTML: no price is rendered anywhere in `fusion-price-rating` for
    these three products). These rows will land in the cleaner's DLQ on
    the price-null condition, which is the correct outcome, not a mapping
    error — visiting each variable product's detail page to resolve a
    per-variant price is a possible future enhancement, not done here.
  - Pagination: real numbered WooCommerce pages at `/product-category/
    <slug>/page/N/` (confirmed via live `a.page-numbers` hrefs — note the
    href always uses the canonical long slug even when page 1 was loaded
    from an alias slug). No "Showing X of Y results" text was found on
    any category page (checked specifically — GMP's Avada/WooCommerce
    setup doesn't render the usual `p.woocommerce-result-count` element
    unlike Diplomatic Shop Serbia's Woodmart theme), so
    `get_expected_item_count()` returns None; coverage instead comes from
    reading the pagination nav's own highest page number
    (`get_total_pages()`) and following every page up to it, the same
    fallback Diplomatic Shop Serbia's scraper uses when its own result-
    count text happens to be absent.
  - Age gate: a real, blocking WordPress "Age Gate" plugin modal — the
    very first page load's title is literally "Age Verification - GMP"
    and no product data is present underneath until dismissed (confirmed
    by diffing page_source before/after the dismiss click — unlike
    Fasola/Calle where the modal didn't block the DOM, this one
    genuinely does). Dismissed via a real `button.age-gate-submit-yes`
    click, followed by a re-navigation to the target URL since the
    dismissed state is cookie-based and the original page load already
    rendered the gate rather than the real content.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "gmp_abu_dhabi"
BASE_URL = "https://gmp.ae"

# Single unified online catalog serving Abu Dhabi/Al Ain home delivery —
# no per-branch price variation found. See module docstring.
LOCATIONS = {
    "Abu Dhabi": ["N/A"],
}

# 6 real alcohol taxonomy slugs — see module docstring for why these were
# chosen over the shorter/alias slugs and why beer needs two categories.
CATEGORIES = [
    "wine-champagne",
    "spirits-abu-dhabi-gmp-online-liquor-store-in-abu-dhabi",
    "beer-rtd",
    "beer-and-cider",
    "liqueur-aperitif",
    "ready-to-drink-products",
]


class GmpAbuDhabiScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page == 1:
            return f"{BASE_URL}/product-category/{self.category}/"
        return f"{BASE_URL}/product-category/{self.category}/page/{page}/"

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

    def dismiss_age_gate(self):
        """Real, blocking age gate — the first page load shows nothing
        but the gate. Click "Yes" then re-navigate to the real category
        URL, since the dismissed state is cookie-based and the original
        load already rendered the gate, not the listing."""
        btn = self.driver.find_element(By.CSS_SELECTOR, ".age-gate-submit-yes")
        self.driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        try:
            self.driver.get(self.get_url(page=1))
        except Exception:
            pass
        time.sleep(4)

    def get_expected_item_count(self):
        """No genuine "Showing X of Y results" text found on this site's
        category pages — see module docstring. Returns None; coverage
        instead comes from get_total_pages()."""
        return None

    def get_total_pages(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        page_links = soup.select(
            "nav.woocommerce-pagination a.page-numbers, "
            "nav.woocommerce-pagination span.page-numbers"
        )
        numbers = [int(a.get_text(strip=True)) for a in page_links if a.get_text(strip=True).isdigit()]
        return max(numbers) if numbers else 1

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = soup.select("ul.products > li")

        for card in cards:
            product_dict = {}
            try:
                title_el = card.select_one("h3.product-title a")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Product_link"] = title_el["href"] if title_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Brandline"] = None
                product_dict["Product_link"] = None
            product_dict["Brand"] = None

            try:
                add_to_cart = card.find("a", class_="add_to_cart_button")
                sku = add_to_cart.get("data-product_sku") if add_to_cart else None
                pid = add_to_cart.get("data-product_id") if add_to_cart else None
                if not sku and not pid:
                    # WooCommerce "variable" products (multi-pack/case
                    # options, confirmed live e.g. "Krombacher Long Neck
                    # (33CL)") don't render a simple add_to_cart_button
                    # with a fixed SKU on the listing page — they need a
                    # "Select options" variation click instead. The GTM
                    # JSON blob still carries the real SKU even for these,
                    # so it's used as a fallback rather than leaving ID
                    # null for an otherwise-real product.
                    gtm = card.find("span", class_="gtm4wp_productdata")
                    if gtm and gtm.get("data-gtm4wp_product_data"):
                        gtm_data = json.loads(gtm["data-gtm4wp_product_data"])
                        sku = gtm_data.get("sku")
                        pid = gtm_data.get("internal_id")
                product_dict["ID_raw"] = sku if sku else pid
            except (AttributeError, TypeError, ValueError):
                product_dict["ID_raw"] = None

            try:
                price_span = card.find("span", class_="price")
                del_el = price_span.find("del") if price_span else None
                ins_el = price_span.find("ins") if price_span else None
                if del_el and ins_el:
                    strike_text = del_el.find("span", class_="woocommerce-Price-amount")
                    disc_text = ins_el.find("span", class_="woocommerce-Price-amount")
                    product_dict["Strike Price"] = strike_text.get_text(strip=True) if strike_text else None
                    product_dict["Price Discounted"] = disc_text.get_text(strip=True) if disc_text else None
                else:
                    amount_el = price_span.find("span", class_="woocommerce-Price-amount") if price_span else None
                    price_text = amount_el.get_text(strip=True) if amount_el else None
                    product_dict["Strike Price"] = price_text
                    product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive/exclusivity badge or text found anywhere on
            # this site — see module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            try:
                self.dismiss_age_gate()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
            total_pages = self.get_total_pages()
            self.get_main()
            for page in range(2, total_pages + 1):
                try:
                    self.driver.get(self.get_url(page=page))
                except Exception:
                    break
                time.sleep(3)
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
                scraper = GmpAbuDhabiScraper(channel, category)
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
