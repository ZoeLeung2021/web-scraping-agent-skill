"""
Scraper for Spirits & Wine (Latvia) -- https://www.spiritsandwine.lv/

Corporate entity confirmed from the site's own footer ("Rekvizīti" block):
SIA "Riga Spirits & Wine Outlet", Reg. Nr. LV40103217488, alcohol trading
Licence Nr. MT00000006880, Buļļu iela 47A, Rīga, LV-1067. This is a
DIFFERENT legal entity from SuperAlko (already built in this project as
outputs/superalko_latvia/ -- that site's own footer names a different SIA
and a different licence number/address) -- genuinely independent
competing retailers, not shared ownership, just the same country and a
similar plain-e-commerce-liquor-shop template shape.

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/spiritsandwine_latvia_scraper.py once validated
(this repo -- web-scraping-agent-skill -- is where retailer outputs are
drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real
page_source, not a text-extraction proxy):
  - Domestic, not GTR. Full homepage nav + footer text checked for "duty
    free"/"travel retail"/"bordershop"/Latvian equivalents -- zero
    matches anywhere. Ordinary online liquor shop selling to the Latvian
    public (delivery + "Veikali" physical stores). Market = "Domestic" in
    the paired cleaner, Country = "Latvia" (no "DF " prefix -- that's
    GTR-only).
  - Single unified online catalog, no per-branch/location price split
    found -- modeled as a single "N/A" channel, same convention as
    SuperAlko Latvia and other single-catalog retailers.
  - No blocking age-verification gate found: category pages return full
    real product data on direct navigation with no login/age-modal
    interstitial in the way (unlike SuperAlko's dismissible #ageBtn modal
    -- this site simply doesn't have one blocking content).
  - Category taxonomy CHECKED for the nested/overlapping-dimension trap
    per this build's brief, and it IS one:
      - The nav's "Premium un dāvanas" group (Premium Konjaks, Premium
        Viskijs, Premium Rums, Premium Šampanietis, Premium Baltvīns,
        Premium Sarkanvīns) is a cross-cutting price/quality TIER over the
        same Type categories, not a distinct product type -- confirmed
        live: /lv/premium-konjaks and /lv/konjaks share 11 of the same
        product IDs on page 1 alone. Excluded from the loop entirely.
      - "SARKANĀS" (/lv/sarkanas, the site's clearance/sale nav item,
        "REDZI SARKANO? RĪKOJIES!") is a cross-cutting "on sale right now"
        filter that resurfaces products from many different Type
        categories AND non-alcohol items (e.g. Coca-Cola) in one list --
        confirmed live. Excluded from the loop entirely (its real
        discounted products are still captured once each under their own
        Type category).
      - The "0% ..." categories (0% Alus, 0% Vīns, 0% Sidrs, 0% Stiprie,
        0% Kokteiļi, 0% Dzirkstošais vīns) are non-alcoholic by definition
        (0% ABV) -- excluded as non-alcohol, not as an overlap.
      - Non-alcohol accessory/snack categories nested under each section
        (Glāzes/glasses, Gaļas uzkodas/meat snacks, Rieksti/nuts,
        Šokolāde/chocolate, Olīvas/olives, Čipši/chips, Sāļās
        uzkodas/salty snacks, Konfektes/candy, Aksesuāri, Dāvanu
        kartes/maisiņi) and the whole "Bezalkoholiski" section
        (Bezalkoholiskie dzērieni, Enerģijas dzērieni, Sīrupi, Sulas) are
        excluded as non-alcohol.
    AVOIDED the trap by looping exactly ONE non-overlapping dimension:
    the plain Type-category nav links (Rums, Džins, Viskijs, Konjaks,
    Sarkanvīns, Alus, ... below), confirmed each product card's own
    ".product-details" text starts with that same Type label (e.g.
    "Konjaks, 40%, 0.7L") -- this is the site's real, single, mutually
    exclusive product-type field, not a re-derived guess.
      - Two Type categories needed a closer look and turned out NOT to be
        overlaps: "Suvenīri" (miniature bottles, e.g. "Chivas Regal 12YO"
        0.05L) and "Mini" (miniature bottles of wine/sparkling/cognac,
        e.g. "Voyer VS Grande Champagne" 0.2L) render their own
        product-details Type as "Suvenīri"/"Mini" respectively, NOT as
        "Viskijs"/"Konjaks" -- confirmed these are distinct SKUs (their
        own product IDs, own small sizes), not the same product
        double-listed. Kept as their own categories.
  - Pagination: real server-side `?page=N` query param, NOT a
    client-side-only SPA trap (the kings.sr failure mode this project
    explicitly checks for). Confirmed live on Viskijs (nav badge said
    "234"): paginating page=1..10 returned 24/24/24/24/24/24/24/24/24/22
    = 238 total product cards with 238 unique data-product-id values and
    ZERO duplicates, and page 10 is genuinely the last page (its own
    page-link list only shows [1, 8, 9, 10], no 11). The loop below stops
    the same way: it keeps requesting page N+1 as long as a page-link to
    a page number > the current page is present in that page's own
    pagination controls.
  - Nav sidebar item-count badges (e.g. "Viskijs(234)") were checked
    against the live per-category pagination count and found consistently
    a few units LOW across every category tested (Viskijs 234 vs 238
    scraped, Konjaks 58 vs 59, Sidrs 65 vs 66, Vermuts 24 vs 26) -- with
    zero duplicate IDs and correct page-boundary behavior confirmed each
    time, this points to the nav badge being a slightly stale/cached
    counter on this platform, not a scraper undercount. get_expected_item_
    count() therefore returns the nav badge value as a rough sanity floor
    (scraped count should be >= it, not exactly ==), not an exact target.
  - Product cards: `<div class="product-container">` inside the category
    grid. Each card has:
      - `<a href="/lv/<type-slug>/<product-slug>-<id>">` wrapping the
        whole card -- Product_link.
      - `<h2 class="product-title">` -- the only name field on this site
        (no separate Brand field found anywhere, incl. on individual
        product pages -- checked). Full title becomes Brandline, Brand
        left null, same convention as SuperAlko Latvia and Silk Road Duty
        Free (Georgia) for the same reason.
      - `<div class="product-details">` -- a clean, structured
        "<Type>, <ABV>%, <Size>" string, e.g. "Konjaks, 40%, 0.7L". Parsed
        with two independent regexes (for ABV% and for the size token)
        rather than a fixed comma-split, since a few Type labels
        themselves contain a "/" but never a comma (e.g. "Vermuts /
        aperitīvs", "Portvīns / šerijs").
      - `<button class="add-to-cart-btn" data-product-id="...">` -- a
        clean numeric per-SKU ID, independent of the URL slug.
      - `<div class="product-price">` containing either:
          - a single `<span class="sale-price">...` or (for some products,
            confirmed cosmetic-only) `<span class="product-price
            mark-3">...` -- no discount, both Strike_Price and
            Price_Discounted get this one value.
          - a REAL two-price pair when genuinely on promotion:
            `<span class="sale-price">0.75 €</span><span class=
            "original-price">0.89 €</span>` -- confirmed live on multiple
            products (e.g. a Coca-Cola 0.75€/was 0.89€ on the sale page,
            several wines/champagnes with a real was-price on the same
            page). Strike_Price = original-price when present,
            Price_Discounted = the other (current) price -- same
            convention as every other retailer in this repo with a real
            strike-through concept.
  - GTR_exclusive: actively checked for a real per-product exclusivity
    badge/ribbon per the schema's "look properly" rule -- every card has
    an (always-empty, in every category and on the homepage) `<div
    class="badge-container">` template slot, and the full homepage/nav
    text has zero hits for "ekskluz"/"exclusive" anywhere. No GTR/travel-
    retail-exclusivity concept exists on this site at all -- never set
    here, so the paired cleaner emits a true null for the whole column,
    not "No".
  - ABV and Size come directly from the structured product-details field
    for every product in every alcohol category tested -- no title-regex
    fallback needed (unlike SuperAlko, where ABV had to be pulled out of
    the free-text title). Category is captured purely so the paired
    cleaner can pick the right Latvian VID excise-duty formula per
    product (see clean_spiritsandwine_latvia.py); it is dropped before
    the final 17-column schema.
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

RETAILER_SLUG = "spiritsandwine_latvia"
BASE_URL = "https://www.spiritsandwine.lv"

# Single unified online catalog, no per-branch/location price split found.
LOCATIONS = {
    "Latvia": ["N/A"],
}

# Real Type-category slugs (the ONE non-overlapping dimension -- see module
# docstring for the Premium/SARKANĀS/0%/accessory traps avoided) mapped to
# the Latvian VID excise-duty band the paired cleaner should apply. Nav
# badge counts (in comments) are the site's own sidebar counts, confirmed a
# few units low vs. live pagination -- see docstring, used only as a rough
# sanity floor, not an exact target.
CATEGORIES = {
    # --- Stiprie dzērieni (spirits) -- pure-alcohol VID formula ---
    "rums": "spirits",                 # Rums (156)
    "dzins": "spirits",                # Džins (92)
    "uzlejums": "spirits",             # Uzlējums (37)
    "absints": "spirits",              # Absints (1)
    "viskijs": "spirits",              # Viskijs (234)
    "degvins": "spirits",              # Degvīns (136)
    "armanjaks": "spirits",            # Armanjaks (3)
    "konjaks": "spirits",              # Konjaks (58)
    "likieris": "spirits",             # Liķieris (97)
    "kalvadoss": "spirits",            # Kalvadoss (2)
    "brendijs": "spirits",             # Brendijs (59)
    "tekila": "spirits",               # Tekila (30)
    "grappa": "spirits",               # Grappa (8)
    "suven%C4%ABri": "spirits",        # Suvenīri -- alcohol miniatures (16)

    # --- Vīns un šampanietis (wine/champagne) ---
    "sarkanvins": "wine",              # Sarkanvīns (420)
    "dzirkstosais-vins": "wine",       # Dzirkstošais vīns (195)
    "bag-in-box-sartvins": "wine",     # Bag-in-box sārtvīns (3)
    "baltvins": "wine",                # Baltvīns (289)
    "vermuts": "intermediate",         # Vermuts / aperitīvs (24) -- fortified, EU "intermediate product"
    "sartvins": "wine",                # Sārtvīns (66)
    "bag-in-box-sarkanvins": "wine",   # Bag-in-box sarkanvīns (18)
    "stiprinats-vins": "intermediate", # Portvīns / šerijs (15) -- fortified, EU "intermediate product"
    "sampanietis": "wine",             # Šampanietis (84)
    "bag-in-box-baltvins": "wine",     # Bag-in-box baltvīns (22)
    "karstvini-karstie-dzerieni": "wine",  # Karstvīns / karstie dzērieni (6) -- 0 live on this run, seasonal
    "mini": "mini",                    # Mini -- MIXED wine/spirits miniatures (59), banded by measured ABV in the cleaner

    # --- Alus, kokteiļi un sidrs ---
    "alus-alk": "beer",                # Alus (216)
    "kokteili": "intermediate",        # Kokteiļi (86) -- ready-to-drink cocktails, same concept as SuperAlko's "long-drinkcocktail"
    "sidrs": "fermented",              # Sidrs (65)
}

_ABV_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_SIZE_RE = re.compile(r"(?i)(\d+(?:[.,]\d+)?\s*(?:cl|ml|l)\b)")

# Rough sanity floor from the site's own nav badges (see docstring) --
# used only to flag a gross undercount, not as an exact expected total.
NAV_BADGE_COUNTS = {
    "rums": 156, "dzins": 92, "uzlejums": 37, "absints": 1, "viskijs": 234,
    "degvins": 136, "armanjaks": 3, "konjaks": 58, "likieris": 97,
    "kalvadoss": 2, "brendijs": 59, "tekila": 30, "grappa": 8,
    "suven%C4%ABri": 16, "sarkanvins": 420, "dzirkstosais-vins": 195,
    "bag-in-box-sartvins": 3, "baltvins": 289, "vermuts": 24, "sartvins": 66,
    "bag-in-box-sarkanvins": 18, "stiprinats-vins": 15, "sampanietis": 84,
    "bag-in-box-baltvins": 22, "karstvini-karstie-dzerieni": 6, "mini": 59,
    "alus-alk": 216, "kokteili": 86, "sidrs": 65,
}


class SpiritsAndWineLatviaScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = NAV_BADGE_COUNTS.get(category)

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
        self.driver.set_page_load_timeout(60)

    def _parse_card(self, card):
        product_dict = {}

        try:
            a = card.select_one("a[href]")
            href = a.get("href") if a else None
            product_dict["Product_link"] = (BASE_URL + href) if href and href.startswith("/") else href
        except (AttributeError, TypeError):
            product_dict["Product_link"] = None

        try:
            title_el = card.select_one(".product-title")
            product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
        except AttributeError:
            product_dict["Brandline"] = None
        # No separate Brand field anywhere on this site (card or product
        # page) -- see module docstring.
        product_dict["Brand"] = None

        try:
            btn = card.select_one("button.add-to-cart-btn")
            product_dict["ID_raw"] = btn.get("data-product-id") if btn else None
        except AttributeError:
            product_dict["ID_raw"] = None

        try:
            details_el = card.select_one(".product-details")
            details_text = details_el.get_text(strip=True) if details_el else ""
        except AttributeError:
            details_text = ""

        abv_match = _ABV_RE.search(details_text)
        product_dict["ABV"] = abv_match.group(1).replace(",", ".") if abv_match else None
        size_match = _SIZE_RE.search(details_text)
        product_dict["Size"] = size_match.group(1) if size_match else None

        try:
            price_el = card.select_one("div.product-price")
            orig_span = price_el.select_one("span.original-price") if price_el else None
            orig_txt = orig_span.get_text(strip=True) if orig_span else None
            current_txt = None
            if price_el:
                for sp in price_el.find_all("span"):
                    if "original-price" in (sp.get("class") or []):
                        continue
                    current_txt = sp.get_text(strip=True)
                    break
            product_dict["Price Discounted"] = current_txt
            product_dict["Strike Price"] = orig_txt if orig_txt else current_txt
        except AttributeError:
            product_dict["Price Discounted"] = None
            product_dict["Strike Price"] = None

        # Category is needed by the paired cleaner to pick the right
        # Latvian VID excise-duty band -- not part of the final 17-column
        # schema, dropped there after Domestic_Tax is computed.
        product_dict["Category"] = self.category

        # No GTR/travel-retail-exclusivity concept found anywhere on this
        # site -- see module docstring. Deliberately not set here so the
        # cleaner emits a true null for the whole column.

        return product_dict

    def scrape_category(self, max_pages=60):
        page = 1
        while page <= max_pages:
            url = f"{BASE_URL}/lv/{self.category}?page={page}"
            try:
                self.driver.get(url)
            except Exception:
                break
            time.sleep(2.2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            cards = soup.select("div.product-container")
            if not cards:
                break
            for card in cards:
                self.product_dicts.append(self._parse_card(card))

            # Real server-side pagination (confirmed live, see docstring) --
            # keep going only while a page-link to a page number GREATER
            # than the current page is present in this page's own controls.
            page_nums = set()
            for a in soup.select("a[href*='page=']"):
                m = re.search(r"page=(\d+)", a.get("href", ""))
                if m:
                    page_nums.add(int(m.group(1)))
            if not page_nums or max(page_nums) <= page:
                break
            page += 1

    def run_all(self):
        try:
            self.open_website()
            self.scrape_category()
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
                scraper = SpiritsAndWineLatviaScraper(channel, category)
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
                        flag = "OK" if scraped_count >= scraper.expected_count else "UNDER (check selector)"
                        print(f"  -> {category}: scraped {scraped_count} / nav badge says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category}: scraped {scraped_count} / nav badge unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category}: {e}")

    if total_expected:
        print(f"TOTAL: scraped {total_scraped} / nav badges sum to {total_expected}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
