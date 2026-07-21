"""
Scraper for Aelia Duty Free at Lima's Jorge Chávez International Airport —
https://marketplace.lima-airport.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/aelia_duty_free_lima_airport_scraper.py once validated
(this repo — web-scraping-agent-skill — is where retailer outputs are
drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome via
undetected_chromedriver, real page_source, not a text-extraction proxy —
every fact below was re-checked against the actual live site, 2026-07-20/21):

  - Site operator / branding: the *platform* ("marketplace.lima-airport.com",
    branded "LAP PERÚ") is operated by Lima Airport Partners S.R.L. (LAP) —
    confirmed via LAP's own "Nuestra Empresa"/corporate page and the site's
    own Terms & Conditions ("los servicios digitales de LIMA AIRPORT
    PARTNERS S.R.L. (LAP)"). LAP is the Jorge Chávez concession operator
    (Fraport AG 80.01% / IFC 19.99%), and is also the schema.org
    `offers.seller` on every product's structured data (i.e. LAP is the
    marketplace's commercial/merchant-of-record entity). HOWEVER every
    single alcohol product card on the site additionally carries its own
    "Vendido por: Aelia Duty Free" ("Sold by: Aelia Duty Free") line — this
    was checked on every product across both categories scraped here, with
    zero exceptions — confirming Aelia Duty Free (a Lagardère Travel Retail
    brand) is the actual duty-free concessionaire/brand whose catalog is
    being sold through LAP's VTEX marketplace storefront. RETAILER is set in
    the cleaner to "Lima Airport Partners (Aelia)" (user-confirmed
    2026-07-21) after a real cross-site ID check against the production
    "Aelia" retailer (France/Romania/Ireland etc.): this site's Hennessy XO
    VTEX sku ("1372") does NOT match Aelia Lyon's real Magento product id
    for the same bottle ("71968") - different, unrelated numbering systems
    - so this is named as its own distinct retailer rather than folded
    into plain "Aelia".
  - GTR retailer, confirmed via the site's own copy: the homepage banner
    reads "En Lima Airport nos dedicamos a ofrecerte una experiencia de
    compra única cuando viajas con compras de primera clase, libres de
    impuestos para viajeros de todo el mundo" ("...first-class, duty-free
    shopping for travelers from all over the world") — explicit "libres de
    impuestos" (duty-free) + "viajeros" (travelers). Physical location is
    Lima, Peru, so Market = "GTR", Country = "Peru" ("DF Peru" after the
    cleaner's GTR prefix).
  - Platform: VTEX (confirmed via asset host `lapperu.vtexassets.com`,
    `vtex-product-summary-2-x-*` / `vtex-flex-layout-*` CSS classes, and a
    `portal.vtexcommercestable.com.br` reference embedded in the page's
    Apollo/GraphQL state). This is NOT Magento — see the
    `div.price-box.price-final_price[data-product-id]` note below.
  - ID EXTRACTION — the task's suggested PRIMARY method
    (`product.find("div", class_="price-box price-final_price")["data-product-id"]`,
    a Magento 2 storefront pattern) was tested live and DOES NOT EXIST on
    this site: `soup.find_all("div", class_=re.compile("price-box"))`
    returned zero matches on the real rendered category page. This is
    expected — the site is VTEX, not Magento, and VTEX product cards carry
    no `data-product-id` attribute anywhere (a page-wide scan for any
    element with `data-product-id`/`data-sku`/`data-id` found exactly one
    hit, an unrelated mega-menu trigger button).
    FALLBACK USED: every category-listing page embeds up to three
    `<script type="application/ld+json">` blocks per page — a
    `BreadcrumbList`, then a real `ItemList` of the genuine per-category
    products, then a second `ItemList` that is a *fixed cross-sell/recommended
    widget* (confirmed identical/near-identical across both the Alcohol and
    Champagne category pages — Kerastase haircare, Carolina Herrera and
    Givenchy fragrance, Flightbox toothpaste — never alcohol). Each real
    `Product` entry in the first `ItemList` carries a clean schema.org `sku`
    field (e.g. `"623"`, `"1255"`) that is unique, stable, and matches the
    VTEX-internal `itemId` also embedded in the page's raw Apollo cache
    JSON (cross-checked: both extraction paths returned the identical value
    for all 8 Alcohol-page-1 products, e.g. sku="623"/itemId="623" for
    Chabot Armagnac XO Superior). This `sku`/`itemId` is used as `ID_raw`
    here. NOTE ON CROSS-RETAILER JOINING - RESOLVED 2026-07-21: the data
    owner asked whether this ID should match other Aelia-branded sites.
    This VTEX `sku` is scoped to this one VTEX tenant's catalog (the
    "lapperu" account); a real GTIN/EAN barcode field IS present in the
    PDP-level JSON-LD (`"gtin": "00001255"`) but was confirmed to be
    nothing more than the same internal sku zero-padded to 8 digits, not a
    genuine scanned barcode (the underlying raw `"ean"` field in the
    embedded VTEX state was an empty string, `"ean":""`, for the one PDP
    checked in detail) - so no true universal barcode exists here either.
    The data owner directly confirmed the answer with a real cross-check:
    this site's Hennessy XO sku ("1372") vs. Aelia Lyon's real Magento
    product id for the same bottle ("71968") - unrelated numbering
    systems, no match. So this VTEX sku does NOT line up with the
    production "Aelia" retailer's IDs, and RETAILER is named
    "Lima Airport Partners (Aelia)" (set in the cleaner) rather than
    folded into plain "Aelia" - see clean_aelia_duty_free_lima_airport.py
    docstring for the full resolution.
  - Two real top-level alcohol categories, found via the site's own top nav
    (not assumed from the URL) — "Confitería" (packaged food) and "Cuidado
    Facial" (personal care/fragrance) are the other two top-nav categories
    and are non-alcohol by the site's own labelling, so are simply never
    looped:
      - alcohol-fortif-wine   ("ALCOHOL&FORTIF WINE" — spirits/fortified
        wine: brandy, whisky, white spirits, cognac, etc.) — site's own
        header says "14 Productos".
      - champagne-spark-wine  ("CHAMPAGNE&SPARK WINE") — site's own header
        says "3 Productos".
  - NESTED-TAXONOMY TRAP CHECKED: the Alcohol category's left-nav facet
    panel shows what looks like 3 separate overlapping dimensions
    ("Categoría": BRANDY Y AGUA DE VIDA/WHISKIES/ESPÍRITUS BLANCOS/COÑAC;
    "Sub-Categoría": MALTA ESCOCESA/BRANDY/ARMAGNAC/VODKA/CALVADOS/etc.;
    "Category 4": more of the same terms again) with the same term (e.g.
    "Calvados", "Armagnac") appearing at every level. Investigated via a
    real PDP's embedded VTEX category-path data
    (`"categories":["/ALCOHOL&FORTIF WINE/BRANDY Y AGUA DE VIDA/CALVADOS/CALVADOS/", ...]`)
    — this confirmed it is a genuine SINGLE hierarchical taxonomy path
    (Alcohol > Brandy y Agua de Vida > Calvados), just rendered as 3
    separate facet-depth panels, NOT 3 independent overlapping dimensions.
    Trap avoided correctly either way: this scraper never loops any facet
    at all — it simply paginates the 2 top-level category pages
    end-to-end, which the site's own "N Productos" headers already confirm
    cover the complete real catalog with no double-counting.
  - Pagination genuinely works via direct URL (`?page=N`), verified against
    the kings.sr-style client-state trap: `?page=2` on the Alcohol category
    returned 6 completely different real products (Massenez, Glenlivet,
    Lagavulin, Belvedere, Glenmorangie, Hennessy) vs page 1's 8 (Chabot x2,
    Boulard, Moutai x3, Metaxa x2) — zero overlapping SKUs — and
    `?page=1 count + ?page=2 count = 8 + 6 = 14` exactly matches the site's
    own "14 Productos" header. A `?page=3` probe returned zero real
    products (the real `ItemList` JSON-LD block was empty, confirming the
    catalog end), used here as the pagination stop condition.
  - Currency: USD. Confirmed both from the visible price-range facet
    ("Gama de Precios USD USD ... USD 27.00 – USD 449.00") and from every
    product's own `offers.priceCurrency` in JSON-LD. Unusual for a
    Peru-based site, but expected for a duty-free/travel-retail storefront
    aimed at international travelers.
  - No genuine Strike_Price/discount concept found on any product checked
    (no `.strikethrough`/before-price class, no "before" price anywhere in
    JSON-LD `offers` — `lowPrice`/`highPrice` are always identical single
    values with `offerCount: 1`). Strike_Price and Price_Discounted are
    therefore captured as the same raw listing price, same convention as
    Le Marché/Fleggaard/Calle.
  - No GTR-exclusive badge/ribbon/"exclusivo"/"exclusive" text found
    anywhere on either category page or the two PDPs checked in detail (a
    full-page-text keyword scan for "exclusiv" returned zero hits) — no
    separate "Exclusives" nav category either. GTR_exclusive is therefore
    never set here (the true null case — the site has no exclusivity
    concept at all — not the "No" case).
  - Brand vs Brandline: JSON-LD gives a clean separate `brand.name` (e.g.
    "Chabot", "Metaxa") used as `Brand`. There is no dedicated Size field
    anywhere in the shelf-level JSON-LD, but each category-listing page's
    raw HTML embeds a VTEX Apollo-cache `nameComplete` string per SKU (e.g.
    `"CHABOT XO SUPERIOR 70CL 40%"`, `"METAXA 7* 40% 1L"`,
    `"MOUTAI DUFU LEGENDARY CHINA 37,5CL 53%"` — note the site mixes
    comma-decimal and dot-decimal size notation, and CL/L/no-space
    formatting inconsistently across products) which reliably carries the
    bottle size (and ABV, not used). This `nameComplete` is captured as
    `Brandline` here (falling back to the shorter JSON-LD `name` if the
    regex match is missing for a given SKU) so the cleaner's existing
    comma-normalizing size-from-text regex (same pattern as Le Marché/
    Licoreria Disenzo) can pull the real size out of it.
  - KNOWN SITE QUIRK — the on-page visible "SKU : <number>" text shown near
    each PDP's price (e.g. "SKU : 10338" on the Calvados Boulard XO PDP) is
    actually the schema.org `mpn` (manufacturer part number) field, NOT the
    real VTEX sku (`1255` for that same product, confirmed via both the
    JSON-LD `sku` field and the embedded `itemId`). Do not scrape that
    visible label as the ID — this scraper never does; it always reads the
    JSON-LD `sku` field.
  - Every product card's *own* wrapping `<a>` link (the one a naive
    `card.find("a", href=True)` would grab first) points to
    `/login?returnUrl=...` — clicking through to add-to-cart/view requires
    a login. This did NOT block scraping: the real per-product PDP URL
    (used here as `Product_link`) is available with no login wall, both as
    the JSON-LD `Product.@id` field on the category page and via direct
    navigation to `<slug>/p` for in-stock products (confirmed live on 2
    products). One out-of-stock product's PDP direct-navigated to a
    "product not found" page instead — out-of-stock items are still
    included here (JSON-LD still exposes name/brand/sku/price for them,
    same as every in-stock item) using the category-page-level JSON-LD
    Product_link rather than requiring a successful PDP visit.
"""

import html
import os
import re
import time
import json
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import io

RETAILER_SLUG = "aelia_duty_free_lima_airport"
BASE_URL = "https://marketplace.lima-airport.com"

# Single physical location (Jorge Chávez International Airport, Lima, Peru)
# — one unified online catalog, no store/terminal-specific price variation
# found anywhere on the site.
LOCATIONS = {
    "Peru": ["Lima Jorge Chavez International Airport (LIM)"],
}

# 2 real top-level alcohol categories confirmed live via the site's own top
# nav. "Confitería" (packaged food) and "Cuidado Facial" (personal
# care/fragrance) are the other 2 top-nav categories and are non-alcohol by
# the site's own labelling — deliberately excluded by never being listed
# here (see module docstring for the non-alcohol cross-sell-widget
# contamination this also has to filter out on every page).
CATEGORIES = [
    "alcohol-fortif-wine",
    "champagne-spark-wine",
]

_TOTAL_RE = re.compile(r"(\d+)\s+Productos", re.IGNORECASE)
_NAME_COMPLETE_RE = re.compile(r'"itemId":"(\d+)","name":"[^"]*","nameComplete":"([^"]*)","complementName"')
_MAX_PAGES = 15  # safety cap — largest real category seen is 14 across 2 pages


class AeliaLimaAirportScraper:
    def __init__(self, location, category_slug):
        self.location = location
        self.category_slug = category_slug
        self.product_dicts = []
        self.expected_count = None
        self._seen_ids = set()

    def get_url(self, page=1):
        base = f"{BASE_URL}/{self.category_slug}"
        return base if page == 1 else f"{base}?page={page}"

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

    def _load(self, url):
        try:
            self.driver.get(url)
        except Exception:
            pass
        time.sleep(8)
        return self.driver.page_source

    def get_expected_item_count(self, soup):
        text = soup.get_text(" ", strip=True)
        match = _TOTAL_RE.search(text)
        return int(match.group(1)) if match else None

    def _get_real_itemlist(self, soup):
        """The category page embeds up to 3 JSON-LD <script> blocks: a
        BreadcrumbList, then the real per-category ItemList, then a fixed
        cross-sell/recommended-products ItemList (never alcohol — see
        module docstring). The first ItemList encountered is always the
        real one; this held true even on the empty-page boundary case
        (?page=3 on Alcohol returned a first ItemList of length 0)."""
        itemlists = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
            except Exception:
                continue
            if data.get("@type") == "ItemList":
                itemlists.append(data.get("itemListElement", []))
        return itemlists[0] if itemlists else []

    def _extract_products(self, page_html, soup):
        name_complete_map = dict(_NAME_COMPLETE_RE.findall(page_html))
        real_items = self._get_real_itemlist(soup)

        products = []
        for entry in real_items:
            item = entry.get("item", {})
            sku = item.get("sku")
            if not sku or sku in self._seen_ids:
                continue
            self._seen_ids.add(sku)

            offers = item.get("offers", {}) or {}
            price = offers.get("lowPrice")
            offers_list = offers.get("offers") or []
            if price is None and offers_list:
                price = offers_list[0].get("price")
            price_str = str(price) if price is not None else None

            brand_raw = (item.get("brand") or {}).get("name")
            brandline_raw = name_complete_map.get(str(sku)) or item.get("name")
            product_dict = {
                "ID_raw": str(sku),
                # html.unescape() guards against a real site data-quality
                # quirk seen live: some brand names carry a literal "&amp;"
                # inside the JSON-LD text instead of "&" (e.g. Moët &
                # Chandon rendered as "Moët &amp; Chandon").
                "Brand": html.unescape(brand_raw) if brand_raw else None,
                "Brandline": html.unescape(brandline_raw) if brandline_raw else None,
                "Product_link": item.get("@id"),
                "Strike Price": price_str,
                "Price Discounted": price_str,
            }
            # No GTR-exclusive badge/ribbon/"exclusivo" text found anywhere
            # on this site — see module docstring. Deliberately not set.
            products.append(product_dict)
        return products

    def get_main(self):
        page = 1
        while page <= _MAX_PAGES:
            page_html = self._load(self.get_url(page=page))
            soup = BeautifulSoup(page_html, "html.parser")

            if page == 1:
                self.expected_count = self.get_expected_item_count(soup)

            page_products = self._extract_products(page_html, soup)
            if not page_products:
                break

            self.product_dicts.extend(page_products)
            page += 1

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
    total_expected = 0
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_slug in CATEGORIES:
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_slug}")
                scraper = AeliaLimaAirportScraper(channel, category_slug)
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
                        print(f"  -> {category_slug}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category_slug}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_slug}: {e}")

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
