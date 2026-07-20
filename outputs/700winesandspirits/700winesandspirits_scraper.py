"""
Scraper for 700 Wines and Spirits — https://www.700winesandspirits.com/

Legal entity: "Commonwealth Brewery Ltd" (a Heineken subsidiary — footer
address P.O. Box N-4935, John F. Kennedy Drive, Nassau, Bahamas; contact
customercare700@heineken.com). Two online order/pickup locations found on
the site's own /location page: Nassau (JFK) and Freeport — both resolve to
the SAME single Ecwid catalog/domain (no location-scoped URL, pricing, or
inventory split found anywhere), so this scraper uses one "N/A" channel,
same convention as other single-catalog Domestic builds in this repo
(Le Bon Macau, Licoreria Disenzo).

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/700winesandspirits_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome via
undetected_chromedriver, real page_source, no text-extraction proxy):
  - NOT duty-free/travel-retail. Checked About/Location/Contact/FAQs for
    "duty free"/airport/traveler/passport language — zero matches. Site
    copy is explicitly a general-public Bahamas retailer ("your premier
    destination... in The Bahamas", home delivery, 2-hour pickup, 18+
    legal drinking age for the Bahamas). Market = "Domestic", Country =
    "Bahamas" (no "DF " prefix — that prefix is GTR-only per this repo's
    schema).
  - Platform: Ecwid (storefront store id 86599280, confirmed via product
    URLs like /main_shop/<name>-p<id> and the white-labeled Ecwid script
    loader `https://app.multiscreenstore.com/script.js?86599280`), embedded
    in a custom site built by an agency ("Powered by Sapodil" in the
    footer — that's the site builder, not the storefront engine).
  - REAL BLOCKER-ADJACENT QUIRK confirmed live: the site's cookie-consent
    tool (Termly) auto-blocks Ecwid's own storefront script on first load
    — the `<script id="ecwid-script">` tag ships as `type="text/plain"`
    with `data-autoblocked="1"` until the visible "Accept" cookie banner
    button is clicked, at which point Termly rewrites it to
    `type="text/javascript"` and the product grid actually renders. Every
    category page load in this scraper defensively looks for and clicks
    an "Accept" button before reading the grid (idempotent — harmless if
    already accepted earlier in the same browser session).
  - Category taxonomy CHECKED LIVE for the nested/overlapping-dimension
    trap per this build's brief, with two confirmed real findings (one
    per direction of the trap):
      1. SPIRITS — "Made in the Bahamas Spirits" (title "Local Rums", 21
         products) and "Flavored Vodka" (8 products) are cross-cutting
         attribute tags that are a 100% SUBSET of the base spirit-type
         leaves (confirmed live: 21/21 of "Local Rums" already appear
         under Rum/Gin; 8/8 of "Flavored Vodka" already appear under
         Vodka). Looping them in addition to the base types would double-
         count. AVOIDED by excluding both from CATEGORIES — the 8 base
         spirit-type leaves (Whiskey, Vodka, Rum, Tequila, Gin, Liqueur,
         Brandy, Ready-to-Drink) are confirmed mutually exclusive: their
         id-set union (223) exactly equals the sum of their individual
         counts (42+30+50+28+16+27+19+11=223), i.e. zero overlap among
         them. "/all-brands-spirits" was also checked and is a dead/empty
         page (0 product cards, generic fallback title) — not a real
         category, excluded.
      2. WINE — the opposite direction of the same trap: "/sparking-rose"
         (its real live title, via driver.title, is "Sparkling Wine", NOT
         "Sparkling Rose" as its stale nav label suggests — see the
         mislabeling note below) is the PARENT aggregate: confirmed live
         it is a 100% SUPERSET of both "/champagne" (14/14 ids present in
         Sparkling Wine) and "/prosecco" (5/5 ids present). AVOIDED here
         by doing the reverse of the spirits case — keeping the aggregate
         "Sparkling Wine" (37 products) and excluding "/champagne" and
         "/prosecco" as leaves, since they contribute zero unique ids not
         already in Sparkling Wine. A full pairwise duplicate-id sweep
         across all other candidate wine leaves came back clean (0 other
         overlaps; deduplicated union across every leaf checked = 134,
         exactly matching the sum of the 17 leaves actually kept below).
      3. BEER — checked "/made-in-the-bahamas-beer" (title "Bahamian", 10
         products) and "/all-beers" (title "Beer", 26 products) against
         the union of the 4 beer-style leaves (Light/Stout/Lager/IPA, 15
         products): "All Beers" is confirmed a SUPERSET of that union (all
         15 present, +11 more not covered by any style leaf), so it is
         used as the single non-overlapping catch-all for the whole Beer
         type — the 4 style leaves and "Made in the Bahamas Beer" are all
         excluded as redundant subsets of it.
  - REAL SITE CONTENT BUG confirmed live (unrelated to the trap above but
    load-bearing for correctness): several nav link LABELS do not match
    their live TARGET content — e.g. the nav's "Cabernet Sauvignon" link
    points to URL /pinot-noir, and /pinot-noir's own rendered page title
    (`driver.title`) is genuinely "Cabernet Sauvignon"; a *different* URL
    /pinot-noir254399a8 is the real "Pinot Noir". Likewise nav's "Pinot
    Grigio" points to /moscato (real title "Pino Grigio", the retailer's
    own typo for Pinot Grigio) while /moscato0df5aee4 is the real white
    "Moscato". This scraper's CATEGORIES dict keys are the real working
    URLs; the dict values are the confirmed live page titles, NOT the
    stale nav labels.
  - ALCOHOL-ONLY FILTER: the "Extras" top-level section (cider, water,
    soda, vita-malt, energy drinks, cigars, cigarettes, and the dedicated
    "/non-alcoholic" and "/non-alcoholic-beer" categories) is entirely
    excluded — never looped. Within the kept "Beer" catch-all (26
    products), the retailer's own "/non-alcoholic-beer" category (title
    "0% Alcohol") tags exactly one product id (596384834, labelled
    "Heineken • 35.5cl Bottle" on the grid card) as non-alcoholic —
    confirmed live and excluded by id. A second, real product ("Heineken
    0.0 • 33cl Bottle", id 596384836) is ALSO genuinely non-alcoholic by
    its own name but is NOT tagged in the retailer's "/non-alcoholic-beer"
    category (a real retailer tagging gap, not a scraper bug) — caught
    defensively here by a title keyword filter for "0.0"/"0%" alongside
    the id-based exclusion, documented so this isn't silently missed.
  - Product cards: Ecwid's own `.grid-product` cards (20 per page):
      - ID: the card's own `grid-product--id-<numeric>` CSS class — this
        is Ecwid's numeric product id, confirmed unique per product
        across every category tested (no collisions observed).
      - Product_link: the card's own `<a href="...">` wrapper, already an
        absolute-looking site path (`/main_shop/<name>-p<id>`) — resolved
        against BASE_URL defensively.
      - Brandline + Size: the card's title text consistently follows a
        real "<Name> • <Size>[ Bottle|Can]" convention (e.g. "Captain
        Morgan Spice • 1L", "Kalik Radler Guava • 34.5cl Bottle") —
        confirmed on every category tested. Split on the "•" bullet:
        left side -> Brandline (also carries the brand name, e.g.
        "Captain Morgan" — no separate dedicated brand field exists on
        the grid card or the PDP, so Brand is left null here, same
        "bundled title field" convention as Le Bon Macau/Licoreria
        Disenzo). Right side -> raw Size string, cleaned of the trailing
        "No reviews yet" review-widget text and passed to the cleaner's
        cl-normalizer as-is (it already strips "Bottle"/"Can" container
        words).
      - Price: `.grid-product__price` — a single plain price on every
        card checked across the whole site (rum, vodka, gin, kosher,
        the /featured-deals promo page, and a live PDP for Ron Ricardo
        Gold 1L). No `<del>`/`<ins>`/"compare at"/strikethrough pair was
        found ANYWHERE on this site (grid or PDP) — confirmed via a
        keyword sweep for old-price/compare/strikethrough/line-through
        classes on /featured-deals (0 hits). So Strike_Price and
        Price_Discounted are always set to the same scraped price — no
        genuine second price to report, never invented.
      - GTR_exclusive: checked the full text of every category page,
        /featured-deals, and a live PDP for "exclusiv*" — zero matches
        anywhere on the site. True null case — deliberately never set
        here (per this repo's three-way rule: null only when the site has
        no exclusivity concept anywhere, which is confirmed true here).
  - Pagination: Ecwid's pager control (`.pager__button--next`) uses a
    `href="javascript:;"` anchor (not a plain link), but confirmed live
    that CLICKING it updates `driver.current_url` to a real, directly
    re-navigable URL (`/main_shop/-c<categoryId>?offset=20&limit=20`) —
    re-loading that exact URL fresh reproduces the same page-2 content
    (verified: NOT a kings.sr-style client-only trap where direct URL nav
    silently resets to page 1). This scraper clicks the Next button
    rather than constructing offset URLs directly, since the numeric
    categoryId isn't exposed until after the first click and the friendly
    slug alone isn't sufficient to build page>=2 URLs up front.
  - No on-page "<N> results/products" total text was found anywhere on
    this site (unlike, e.g., Le Bon Macau's Shopify facet counters or
    Licoreria Disenzo's WooCommerce "<N> resultados") — confirmed via an
    exhaustive text sweep of the rum/vodka/gin category pages. So
    get_expected_item_count() always returns None here; the real
    "site's own displayed count" for validation purposes is the count
    obtained by fully walking the site's own pager control (Next button)
    to exhaustion, which is exactly what run_all() below does — there is
    no separate static count to cross-check against.
  - No blocking age-verification gate found anywhere on the site (only
    the cookie-consent banner, handled above).
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

RETAILER_SLUG = "700winesandspirits"
BASE_URL = "https://www.700winesandspirits.com"

# Single unified online catalog (Nassau/JFK + Freeport pickup, but no
# location-scoped URL/pricing/inventory split found anywhere) — see
# module docstring.
LOCATIONS = {
    "Bahamas": ["N/A"],
}

# Real, non-overlapping leaf categories confirmed live — see module
# docstring for the two directions of the nested-taxonomy trap this
# avoids (Spirits: exclude the cross-cutting subsets; Wine: keep the
# aggregate, exclude its subsets; Beer: keep the single catch-all).
# Values are the CONFIRMED LIVE page titles (driver.title), not the
# site's own (sometimes stale/mismatched) nav labels.
CATEGORIES = {
    # Wine
    "red-blends": "Red Blend",
    "malbec": "Malbec",
    "pinot-noir": "Cabernet Sauvignon",
    "pinot-noir254399a8": "Pinot Noir",
    "merlota37f80c5": "Merlot",
    "kosher": "Kosher",
    "sangria": "Sangria",
    "moscatoaaa1c01c": "Moscato (Red)",
    "zinfandel": "Zinfandel",
    "chardonnay": "Chardonnay",
    "moscato": "Pinot Grigio",
    "moscato0df5aee4": "Moscato (White)",
    "riesling": "Riesling",
    "sauvignon-blanc": "Sauvignon Blanc",
    "white-blend": "White Blend",
    "sparking-rose": "Sparkling Wine",
    "rose": "Rose",
    # Beer — single non-overlapping catch-all (see docstring finding #3)
    "all-beers": "Beer",
    # Spirits
    "whiskey7ec914dc": "Whiskey",
    "vodka": "Vodka",
    "rum": "Rum",
    "tequila": "Tequila",
    "gin": "Gin",
    "liqueur": "Liqueur",
    "brandy": "Brandy",
    "ready-to-drink-spirits": "Ready To Drink",
}

# Only the "Beer" catch-all category can contain non-alcohol items (the
# retailer's own "/non-alcoholic-beer" tag) — confirmed via live overlap
# check. Excluded by id (retailer's own tag) AND defensively by a title
# keyword match, since one genuinely non-alcoholic product ("Heineken
# 0.0") was confirmed NOT tagged in that category — see module docstring.
NON_ALCOHOL_BEER_IDS = {"596384834"}
NON_ALCOHOL_TITLE_RE = re.compile(r"(?<!\d)0\.0(?!\d)|\b0%\s*alcohol\b", re.IGNORECASE)

_BULLET_SPLIT_RE = re.compile(r"\s*•\s*")  # "•"
_REVIEWS_SUFFIX_RE = re.compile(r"no reviews yet\s*$", re.IGNORECASE)


class SevenHundredWinesScraper:
    def __init__(self, location, channel):
        self.location = location
        self.channel = channel
        self.product_dicts = []
        self.excluded_nonalcohol = 0

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

    def accept_cookies(self):
        """Termly auto-blocks Ecwid's storefront script until this is
        clicked — see module docstring. Idempotent/safe to call on every
        page load."""
        candidates = self.driver.find_elements(
            By.XPATH,
            "//*[self::button or self::a or self::div]"
            "[contains(translate(text(), 'ACEPT', 'acept'), 'accept')]",
        )
        for el in candidates:
            try:
                if el.text.strip().lower() == "accept" and el.is_displayed():
                    el.click()
                    return True
            except Exception:
                continue
        return False

    def _parse_card(self, card, category_label):
        product_dict = {}

        pid = None
        for cl in card.get("class", []):
            if cl.startswith("grid-product--id-"):
                pid = cl.replace("grid-product--id-", "")
        product_dict["ID_raw"] = pid

        link_el = card.select_one("a[href]")
        href = link_el.get("href") if link_el else None
        if href and href.startswith("/"):
            href = BASE_URL + href
        product_dict["Product_link"] = href

        title_el = card.select_one(".grid-product__title")
        raw_title = title_el.get_text(" ", strip=True) if title_el else ""
        raw_title = _REVIEWS_SUFFIX_RE.sub("", raw_title).strip()
        parts = _BULLET_SPLIT_RE.split(raw_title, maxsplit=1)
        product_dict["Brand"] = None
        product_dict["Brandline"] = parts[0].strip() if parts and parts[0].strip() else raw_title or None
        product_dict["Size"] = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

        price_el = card.select_one(".grid-product__price")
        price_text = price_el.get_text(" ", strip=True) if price_el else None
        # No compare-at/strikethrough price found anywhere on this site
        # (grid or PDP) — see module docstring. Both fields get the same
        # scraped price.
        product_dict["Strike Price"] = price_text
        product_dict["Price Discounted"] = price_text

        # GTR_exclusive: no exclusivity concept found anywhere on this
        # site — deliberately never set (stays null after the cleaner's
        # ensure-columns-exist backfill).

        product_dict["Category"] = category_label
        return product_dict

    def _is_nonalcohol(self, product_dict):
        if product_dict.get("ID_raw") in NON_ALCOHOL_BEER_IDS:
            return True
        brandline = product_dict.get("Brandline") or ""
        if NON_ALCOHOL_TITLE_RE.search(brandline):
            return True
        return False

    def scrape_category(self, path, category_label, max_pages_safety=25):
        url = f"{BASE_URL}/{path}"
        self.driver.get(url)
        time.sleep(5)
        self.accept_cookies()
        time.sleep(4)

        seen_ids = set()
        page = 1
        is_beer = category_label == "Beer"
        while page <= max_pages_safety:
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            cards = soup.select(".grid-product")
            new_this_page = 0
            for card in cards:
                product_dict = self._parse_card(card, category_label)
                pid = product_dict.get("ID_raw")
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                if is_beer and self._is_nonalcohol(product_dict):
                    self.excluded_nonalcohol += 1
                    continue
                self.product_dicts.append(product_dict)
                new_this_page += 1

            next_btns = self.driver.find_elements(By.CSS_SELECTOR, ".pager__button--next")
            has_next = False
            if next_btns:
                try:
                    parent_class = next_btns[0].find_element(By.XPATH, "..").get_attribute("class") or ""
                    has_next = "pager__body--has-next" in parent_class
                except Exception:
                    has_next = False
            if not has_next:
                break
            try:
                self.driver.execute_script("arguments[0].scrollIntoView();", next_btns[0])
                time.sleep(0.5)
                next_btns[0].click()
                time.sleep(4)
                self.accept_cookies()
                page += 1
            except Exception:
                break
        return len(seen_ids)

    def run_all(self):
        try:
            self.open_website()
            for path, label in CATEGORIES.items():
                self.scrape_category(path, label)
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

    for country, channels in LOCATIONS.items():
        for channel in channels:
            print(f"Scraping {RETAILER_SLUG}: {country} / {channel}")
            scraper = SevenHundredWinesScraper(country, channel)
            try:
                scraper.run_all()
                for item in scraper.product_dicts:
                    item["Country"] = country
                    item["Channel"] = channel
                    item["Scraped_At"] = datetime.now(timezone.utc).isoformat()
                all_data.extend(scraper.product_dicts)
                print(
                    f"  -> scraped {len(scraper.product_dicts)} alcohol rows "
                    f"(excluded {scraper.excluded_nonalcohol} confirmed non-alcohol beer item(s))"
                )
            except Exception as e:
                print(f"FAILURE scraping {country}/{channel}: {e}")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
