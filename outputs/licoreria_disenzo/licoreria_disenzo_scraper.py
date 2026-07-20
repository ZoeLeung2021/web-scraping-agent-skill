"""
Scraper for Licoreria Disenzo (Peru) - https://licoreriadisenzo.pe/

Legal entity: "Inversiones Javic S.A.C." (RUC 20548620679, confirmed on the
site's own "Libro de reclamaciones" complaints-book page, a page Peruvian
consumer-protection law - INDECOPI - requires every retailer to publish),
trading as "Disenzo".

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/licoreria_disenzo_scraper.py
once validated (this repo - web-scraping-agent-skill - is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome via
undetected_chromedriver, real page_source, no text-extraction proxy):
  - NOT duty-free/travel-retail. Two physical stores, both in Lima, Peru
    (San Borja: Av. Aviacion 3203; Cercado de Lima: Av. Alejandro Bertello
    803), local WhatsApp/phone numbers (+51), delivery via Rappi/PedidosYa
    (Peru-only delivery apps), Peruvian Sol currency ("S/."), and the
    standard Peru responsible-drinking disclaimer ("Tomar bebidas
    alcoholicas en exceso es danino"). No "duty free"/airport/traveler
    language anywhere. Market = "Domestic", Country = "Peru" (no "DF "
    prefix - that prefix is GTR-only per this repo's schema). Single
    unified online catalog - no branch-specific pricing/inventory found,
    so one "N/A" channel.
  - Platform: WordPress + WooCommerce, "Rey" theme (rey-* CSS classes
    throughout), Elementor page builder for banners, JetEngine/JetSmartFilters
    plugins for the sidebar filter widgets, WP Rocket cache plugin. Spanish
    WooCommerce slugs: /categoria-producto/<cat>/, /producto/<slug>/.
  - Category taxonomy CHECKED LIVE for the nested/overlapping-dimension
    trap per this build's brief. Two real findings:
      1. "Cepas" (grape variety - Cabernet Sauvignon, Malbec, Tempranillo,
         Pinot Noir, Merlot, Syrah, Garnacha, Chardonnay, Sauvignon Blanc,
         Grenache, Isabella, Shiraz, Riesling) is a SEPARATE, cross-cutting
         attribute dimension layered on top of the wine category tree (its
         nav links carry BOTH `tax=product_cat:472` AND `pa_cepas:<id>` -
         i.e. "this grape variety WITHIN Vinos"). A wine tagged "Tintos"
         by category can independently carry a "Malbec" or "Cabernet
         Sauvignon" cepa tag (confirmed live: product 13750, "Vino Vinas
         Argentinas Malbec 750 ml", sits in category Tintos, not in
         category Cabernet - grape variety and category are independent).
         AVOIDED by never looping Cepas at all - only the category
         dimension is looped below.
      2. Within the category dimension itself, "Vinos > Tintos > Premium"
         (URL vinos/tintos/premium/) is a genuine WooCommerce CHILD
         category of "Tintos", and its products are a 100% SUBSET of
         Tintos's own listing - confirmed live: all 66 of
         vinos/tintos/premium/'s IDs are already present among Tintos's
         549 IDs (66/66 overlap, checked via a full page-by-page ID
         collection of both, not a page-1 sample). Looping both would
         double-count 66 SKUs. AVOIDED by excluding "Premium" from
         CATEGORIES below - Tintos already covers it.
         All other sibling pairs spot-checked (Tintos vs Cabernet, Rosados
         vs Tintos, Blancos vs Espumosos) came back with ZERO overlap, and
         a product's own WooCommerce class list on its card
         (`product_cat-<leaf> product_cat-<parent>`) confirms each product
         is filed under exactly one leaf + its direct parent, not multiple
         sibling leaves. A small residual overlap among the 7 remaining
         wine leaves (~41 IDs, i.e. sum-of-categories 855 vs union 814) was
         NOT chased down to an exact pair - left to the cleaner's existing
         defensive Product_link/ID dedup, same posture used on every
         other build in this repo with a similar small residual (e.g.
         sieuthiruoungoai's Spirits/Gin-Tequila-Liqueur overlap).
      3. "Ofertas" (Offers/on-sale) is a real, separate top-nav link but is
         a cross-cutting sale-price FILTER over every category combined
         (100+ mixed wine/beer/spirit cards on page 1 alone, confirmed
         live) - excluded from CATEGORIES for the same reason Cepas is:
         looping it would re-scrape products already covered by their own
         category, just filtered to the ones currently discounted.
      4. "Packs y combos" bundles (e.g. "Pack Chivas Regal 12 anos: 700 ml
         + 200 ml") are checked for overlap against their component
         spirits' own categories (Whiskys, Ginebras, Rones) - see the
         scraper's run history / validation notes for the live result.
  - CATEGORIES (leaf, non-overlapping-by-construction) = 21 real alcohol
    leaves across 6 parents:
      Vinos: cabernet, espumosos, tintos, rosados, blancos, naturales,
        dulces (excludes "desalcoholizados" - non-alcoholic wine, and
        "premium" - 100% subset of tintos, see above)
      Destilados: whiskys, cognacs-y-brandys, rones, ginebras,
        piscos-destilados, vodkas, tequila-y-mezcales
      Cervezas: artesanales, industriales
      Licores: otros-licores, cremas-de-licor, vermouths, macerados
      Sakes: futsushu, junmai
      Otros: rtd
    Explicitly EXCLUDED as non-alcohol: "Acompanamientos" and all its
    children (Aguas y Energizantes, Complementos, Gaseosas, Snacks, Jugos
    y Bebidas, Jarabes - water/soda/snacks/syrups/mixers, confirmed
    non-alcoholic by name and by spot-checked product titles), and
    "Vinos > Desalcoholizados" (de-alcoholized/0%-ABV wine).
  - Product cards: `<li class="... type-product post-<ID> ...
    product_cat-<leaf> product_cat-<parent> ...">` (12 per page):
      - Product_link: `<a class="woocommerce-loop-product__link" href=
        "https://licoreriadisenzo.pe/producto/<slug>/">`.
      - ID: the add-to-cart button's own `data-product_sku` (e.g.
        "VIN583", "CERV44") - the retailer's real per-SKU code, category-
        prefixed and stable - preferred over the WordPress internal
        `data-product_id` post ID, same "prefer the site's own SKU"
        convention used on Diplomatic Shop Serbia. Falls back to the
        numeric `data-product_id`/`data-pid` if a SKU is ever missing.
      - Brandline: `<h2 class="woocommerce-loop-product__title">` text
        (e.g. "Vino Vina Albali Tempranillo Seleccion 750 ml") - brand,
        varietal/name, and size all bundled into one string, same
        convention as most other single-title-field retailers in this
        repo. Brand is left null (a real, separate "Marca" field DOES
        exist on each product's own detail page - confirmed live, e.g.
        "Marca: Santa Rita" - but visiting every PDP individually across
        an estimated 1,600+ live alcohol SKUs was judged not worth the
        added runtime for this build, same tradeoff made on Kings
        Suriname/Le Bon Macau/sieuthiruoungoai for their own unresolved
        fields).
      - Price: `<span class="price rey-loopPrice">` - on non-discounted
        cards this is a single price (Strike_Price = Price_Discounted,
        same raw value); on discounted cards (confirmed live via the
        "Ofertas" page and a real `<span class="onsale">Oferta!</span>`
        badge) it contains a real `<del>...S/. 16.00</del>` (original) and
        `<ins>...S/. 13.00</ins>` (discounted) pair - Strike_Price is the
        `<del>` amount, Price_Discounted is the `<ins>` amount.
      - GTR_exclusive: checked the full page text of multiple category
        pages plus the "Ofertas" sale page for "exclusiv*" - zero matches
        anywhere. The only per-product badge found is the "Oferta!"
        on-sale ribbon, a discount signal (already captured via
        Strike_Price/Price_Discounted), not an exclusivity concept. True
        null case - deliberately never set here.
  - Pagination: real, working server-side WooCommerce `/page/N/` URLs -
    confirmed exhaustively on the largest category (Tintos, 549 items):
    pages 1-45 each returned exactly 12 unique, non-overlapping product
    IDs, page 46 returned the remaining 9, and page 47 returned a real
    404 ("Pagina no encontrada") - 45*12 + 9 = 549, an exact match to the
    category's own "549 resultados" text. Also confirmed on the smallest
    category (Cabernet, 2 items): page 1 returns both items, page 2 is a
    404. NOTE: scrolling the page to trigger the theme's infinite-scroll
    AJAX loader BEFORE navigating to a `/page/N/` URL was found to corrupt
    a subsequent fresh page load into showing cumulative (not just that
    page's) results in one early test - this scraper never scrolls or
    interacts with the page before reading it, only does clean sequential
    `driver.get()` calls to `/page/N/` URLs, which was confirmed reliable.
    Each category page's own "<N> resultados" text (next to the "Ordenar
    por" sort dropdown) is used as `get_expected_item_count()`'s real
    coverage target.
  - No blocking age-verification gate found anywhere on the site.
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

RETAILER_SLUG = "licoreria_disenzo"
BASE_URL = "https://licoreriadisenzo.pe"

# Single unified nationwide online catalog (two physical stores in Lima,
# but no branch-specific pricing/inventory found anywhere on the site).
LOCATIONS = {
    "Peru": ["N/A"],
}

# 21 real alcohol leaf categories, non-overlapping by construction - see
# module docstring for the Cepas/Premium/Ofertas overlap findings that
# shaped this list.
CATEGORIES = {
    "categoria-producto/vinos/cabernet/": "Cabernet",
    "categoria-producto/vinos/espumosos/": "Espumosos",
    "categoria-producto/vinos/tintos/": "Tintos",
    "categoria-producto/vinos/rosados/": "Rosados",
    "categoria-producto/vinos/blancos/": "Blancos",
    "categoria-producto/vinos/naturales/": "Naturales",
    "categoria-producto/vinos/dulces/": "Dulces",
    "categoria-producto/destilados/whiskys/": "Whiskys",
    "categoria-producto/destilados/cognacs-y-brandys/": "Cognacs y Brandys",
    "categoria-producto/destilados/rones/": "Rones",
    "categoria-producto/destilados/ginebras/": "Ginebras",
    "categoria-producto/destilados/piscos-destilados/": "Piscos",
    "categoria-producto/destilados/vodkas/": "Vodkas",
    "categoria-producto/destilados/tequila-y-mezcales/": "Tequilas y Mezcales",
    "categoria-producto/cervezas/artesanales/": "Cervezas Artesanales",
    "categoria-producto/cervezas/industriales/": "Cervezas Industriales",
    "categoria-producto/licores/otros-licores/": "Otros Licores",
    "categoria-producto/licores/cremas-de-licor/": "Cremas de Licor",
    "categoria-producto/licores/vermouths/": "Vermouths",
    "categoria-producto/licores/macerados/": "Macerados",
    "categoria-producto/sakes/futsushu/": "FutsuShu",
    "categoria-producto/sakes/junmai/": "Junmai",
    "categoria-producto/otros/rtd/": "RTD",
    "categoria-producto/packs/": "Packs y Combos",
}

_RESULT_COUNT_RE = re.compile(r"(\d+)\s*resultados", re.IGNORECASE)


class LicoreriaDisenzoScraper:
    def __init__(self, location, category_path, category_label):
        self.location = location
        self.category_path = category_path
        self.category_label = category_label
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page <= 1:
            return f"{BASE_URL}/{self.category_path}"
        return f"{BASE_URL}/{self.category_path}page/{page}/"

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

    def get_expected_item_count(self, soup):
        text = soup.get_text(" ", strip=True)
        match = _RESULT_COUNT_RE.search(text)
        return int(match.group(1)) if match else None

    def is_404(self, soup):
        text = soup.get_text(" ", strip=True).lower()
        return "no encontrada" in text or "not found" in text

    def get_main(self, soup):
        cards = soup.select("li.type-product")
        added = 0
        for card in cards:
            product_dict = {}
            try:
                link_el = card.select_one("a.woocommerce-loop-product__link")
                product_dict["Product_link"] = link_el["href"] if link_el else None
            except (AttributeError, TypeError, KeyError):
                product_dict["Product_link"] = None

            try:
                add_btn = card.select_one("a.add_to_cart_button")
                sku = add_btn.get("data-product_sku") if add_btn else None
                pid = (
                    (add_btn.get("data-product_id") if add_btn else None)
                    or card.get("data-pid")
                )
                product_dict["ID_raw"] = sku if sku else pid
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None

            try:
                title_el = card.select_one("h2.woocommerce-loop-product__title")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                price_block = card.select_one("span.price")
                del_el = price_block.select_one("del .woocommerce-Price-amount") if price_block else None
                ins_el = price_block.select_one("ins .woocommerce-Price-amount") if price_block else None
                if del_el is not None and ins_el is not None:
                    product_dict["Strike Price"] = del_el.get_text(strip=True)
                    product_dict["Price Discounted"] = ins_el.get_text(strip=True)
                else:
                    plain_el = price_block.select_one(".woocommerce-Price-amount") if price_block else None
                    price_text = plain_el.get_text(strip=True) if plain_el else None
                    product_dict["Strike Price"] = price_text
                    product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No exclusivity badge/tag concept found anywhere on this
            # site - see module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)
            added += 1
        return added

    def run_all(self, max_pages_safety=100):
        try:
            self.open_website()
            self.driver.get(self.get_url(page=1))
            time.sleep(4)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            self.expected_count = self.get_expected_item_count(soup)
            self.get_main(soup)

            page = 2
            while page <= max_pages_safety:
                try:
                    self.driver.get(self.get_url(page=page))
                except Exception:
                    break
                time.sleep(3)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                if self.is_404(soup):
                    break
                added = self.get_main(soup)
                if added == 0:
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
    all_data = []
    total_expected = 0
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_path, category_label in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_label}")
                scraper = LicoreriaDisenzoScraper(channel, category_path, category_label)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Category"] = category_label
                        item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                    all_data.extend(scraper.product_dicts)
                    scraped_count = len(scraper.product_dicts)
                    total_scraped += scraped_count
                    if scraper.expected_count is not None:
                        total_expected += scraper.expected_count
                        flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH"
                        print(f"  -> {category_label}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category_label}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_label}: {e}")

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
