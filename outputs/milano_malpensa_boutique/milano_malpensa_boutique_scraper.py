"""
Scraper for Milano Malpensa Boutique — https://milanomalpensaboutique.com/en/alcolici/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/milano_malpensa_boutique_scraper.py once validated
(this repo — web-scraping-agent-skill — is where retailer outputs are
drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source,
no text-extraction proxy used for this build):
  - Operator: S.E.A. S.p.A. (Societa per l'Esercizio Aeroportuale, P.IVA
    00826040156) — the company that manages Milan Malpensa and Linate
    airports. "Milano Malpensa Boutique" is S.E.A.'s own "click & collect"
    duty-free storefront for Malpensa Terminal 1: "Discover the duty-free
    shopping offer at Malpensa Terminal 1. Book online and pick up at the
    airport on the day of departure." Individual products are actually
    supplied/sold by tenant operators inside the terminal — a "Tenant"
    facet on the category pages shows "Dufry" (~597 of 608 catalog items),
    "Ferrari Spazio Bollicine" (3, a wine/Champagne specialist boutique),
    and "Bufala di Fattorie Garofalo" (8) — so most of the catalog is
    really Dufry's Malpensa assortment, resold through S.E.A.'s booking
    site.
  - GENUINELY GTR (duty-free): confirmed via the site's own copy, not
    assumed from the URL. Repeated language: "duty-free shopping offer",
    "duty-free selection", a "How to shop duty-free" FAQ link, a "Traveler
    custom card" footer link to the Italian Customs Agency's (ADM)
    traveler-allowance document, and a flight-detail widget on every
    category page ("Add your flight details to discover the products you
    can reserve and the prices you are eligible for"). IMPORTANT: that
    flight-detail widget does NOT gate the prices shown on the category/
    listing pages — every product card and detail page renders a real
    price with no flight/boarding-pass info entered; the widget only
    gates the "reserve for pickup" checkout flow itself. Market = "GTR",
    Country = "DF Italy". Single channel: "Malpensa Terminal 1" (the only
    pickup point found; no other airport/terminal referenced anywhere).
  - Platform: BigCommerce on a Next.js "Catalyst" storefront (React Server
    Component streaming — `self.__next_f.push([...])` script payloads
    embed each product listing card as a JSON object with `id`, `sku`,
    `title`, `href`, `price`, `subtitle` (= Brand) directly in the page
    source; scraped via regex over `driver.page_source` rather than a
    DOM/CSS-selector card, since the visible DOM only renders after client
    hydration and the RSC payload is more reliable and already present in
    the initial response).
  - Category taxonomy CHECKED for the nested/overlapping-dimension trap
    per this build's brief. The parent "alcolici" nav category ("Spirits",
    entityId 85, header count 608) breaks down into 9 leaf nav categories
    used as CATEGORIES below: Aperitifs & Digestifs, Whiskey, Wine,
    Champagne & Sparkling Wines, Spirits/distillati, Cognac & Brandy,
    Liqueurs, Beer, Other Spirits. Confirmed empirically via a live
    cross-category SKU-overlap check (collected every unique SKU per
    leaf category via full pagination, then compared pairwise) that these
    9 leaves do NOT share SKUs with each other — a clean, single-dimension
    partition, not an overlapping Type+Country+Region style trap. A given
    product's own product-detail JSON DOES carry additional simultaneous
    tags beyond this partition (e.g. "American Oak" carries categories
    ["Products","Spirits","Whiskey","Single Malt Scotch","Malpensa
    Promotions"] all at once) — "Single Malt Scotch" (a finer subcategory
    of Whiskey) and "Malpensa Promotions" (a cross-cutting promo tag) are
    both real additional dimensions on this site, but they are NOT looped
    here — only the 9 top-level leaves are, which is what avoids the trap
    (looping "Single Malt Scotch" or "Malpensa Promotions" as *additional*
    categories on top of the 9 leaves would double-count products already
    captured).
  - KNOWN, CONFIRMED SITE-SIDE DATA-QUALITY QUIRK (not a scraper bug —
    investigated at length, see build notes below): every leaf category
    page displays its own header count right next to the H1 (e.g.
    "Whiskey 170", "Beer 1") via a real, live-rendered badge. Repeated,
    isolated (single fresh driver per category, no concurrent Chrome
    instances, 4s settle time per page) full-pagination runs consistently
    found FEWER real, distinct SKUs reachable via the site's own "Go to
    next page" control than that header count claims — e.g. Whiskey's
    header says 170 but exhaustive pagination (7 real pages, each ending
    on a verified-disabled terminal "next" control) only ever surfaces
    144 distinct SKUs; Beer's header says "1" but the category renders
    ZERO product cards in the live DOM on every fetch. This was confirmed
    NOT to be a selector/pagination bug on this scraper's side: rendered
    DOM product-card `<a href>` elements match the regex-extracted SKU
    count 1:1 on every page (verified on Whiskey page 1: 23 DOM cards ==
    23 unique regex-extracted SKUs), and the terminal page's "next"
    control genuinely renders as a disabled `<div>` (not just an unclicked
    `<a>`) confirming the site itself believes pagination is exhausted.
    The most likely explanation is that the header's `productCount` is a
    BigCommerce category-metadata field that includes products assigned
    to the category but excluded from the live storefront product
    connection for other reasons (out of stock, channel/visibility
    restrictions, delisted-but-not-recategorized) — this is a known class
    of BigCommerce quirk, not unique to this scraper. Flagged prominently
    to the user rather than silently treated as "close enough" — see this
    build's final report.
  - Pagination: relay-style CURSOR pagination via a real `<a aria-label=
    "Go to next page" href="?after=<base64>">` link inside `<nav aria-
    label="pagination">` — direct URL navigation to that href DOES work
    correctly (confirmed: following the cursor chain for Whiskey across 7
    real pages produced 0 duplicate SKUs across pages). This is UNLIKE the
    king's.sr `?page=N` trap from a previous build — the cursor token
    itself carries real pagination state server-side, it isn't purely
    client React state. The terminal page's "next" control becomes a
    disabled `<div>` (no href) rather than a clickable `<a>` — used here
    as the loop's stopping condition.
  - Product cards (from the RSC JSON): `id` (internal BigCommerce entity
    ID, not used), `sku` (the numeric SKU baked into the product URL too,
    e.g. "3454983" in "/american-oak-3454983/" — used as ID_raw, the
    stable per-SKU identifier), `title` (Brandline, e.g. "American Oak"),
    `href` (relative product path), `price` (single visible price, e.g.
    "€ 46,50"), `subtitle` (Brand, e.g. "Auchentoshan").
  - Strike_Price / discount: checked directly on product detail pages
    (e.g. american-oak-3454983) for a genuine second/original price next
    to a "Save 20%" badge — found NONE: no `<del>`, no `line-through`
    class, no second Euro amount anywhere near the badge on any of the
    products checked. The "Save X%" ribbon is a percentage-only badge with
    no absolute original price ever rendered on the page. Per this
    build's brief ("don't invent" a strike price), Strike_Price is left
    equal to the single visible price (no real discount-price pair to
    capture) rather than back-calculating an original price from the
    percentage.
  - Size: NOT present on the category-listing card JSON (only id/sku/
    title/href/price/subtitle) — confirmed by inspecting the raw listing
    payload directly. It IS present as plain visible text on every
    product DETAIL page ("... Established in 1823 ... Scotch taste. Size:
    1L Quantity: ..."), so this scraper does a second pass: after
    collecting every listing card across all categories, it visits each
    product's detail page once to pull the "Size: <value>" text. This
    matches the two-pass listing+detail pattern already used elsewhere in
    this pipeline (e.g. dufry_europe_scraper.py) for sites that omit Size
    from the listing.
  - GTR_exclusive: this site has a REAL, per-product exclusivity concept,
    but it is embedded directly in the product TITLE text rather than a
    separate visual ribbon/badge — confirmed on Whiskey alone: 17 of 136
    checked titles contain "Travel Exclusive" / "Travel Retail Exclusive"
    / "TRX" / "GTR" (e.g. "12 Year Old Golden Cask Travel Exclusive",
    "Extra 13YO Irish Cask Travel Retail Exclusive", "16 Years Old Madeira
    Cask Trx", "11 Year Old Islay Single Malt Scotch Whisky GTR"), while
    most titles ("American Oak", "Blended Malt Scotch Whisky", ...) carry
    no such text. Because the site tracks this concept for SOME products
    and not others (not all-or-nothing), every row gets a real raw string
    here (the matched keyword, blank "" if none) rather than leaving the
    field unset — see cleaner_template.py's convention for turning that
    into a three-way Yes/No/null column.
  - Age gate / cookie banner: none found on any category or product page
    during this build (alcohol click-and-collect flow, no age-verification
    modal encountered) — the dismiss methods below are therefore
    best-effort/defensive only, matching the template's standard shape.
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

RETAILER_SLUG = "milano_malpensa_boutique"
BASE_URL = "https://milanomalpensaboutique.com"

# Single airport, single terminal, single pickup point ("Malpensa Terminal
# 1") — no multi-location split found anywhere on the site.
LOCATIONS = {
    "Italy": ["Malpensa Terminal 1"],
}

# The 9 real, non-overlapping leaf nav categories under the "alcolici"
# (Spirits) parent — see module docstring for the live SKU-overlap check
# that confirmed no cross-category duplication.
CATEGORIES = [
    "aperitivi-e-digestivi", "whisky", "vino", "champagne-e-spumanti",
    "distillati", "cognac-e-brandy", "liquori", "birra", "altri-alcolici",
]

# RSC-streamed product card JSON, e.g.:
# {"id":"12894","sku":"3454983","title":"American Oak","href":"/american-
#  oak-3454983/","image":{...},"price":"€ 46,50","priceInclTax":...,
#  "priceExclTax":...,"subtitle":"Auchentoshan","rating":0,...}
_PRODUCT_RE = re.compile(
    r'\\"id\\":\\"\d+\\",\\"sku\\":\\"(\d+)\\",\\"title\\":\\"([^\\]*?)\\",'
    r'\\"href\\":\\"([^\\]*?)\\".*?\\"price\\":\\"([^\\]*?)\\".*?'
    r'\\"subtitle\\":\\"([^\\]*?)\\"'
)

_EXCLUSIVE_RE = re.compile(r"travel\s+retail\s+exclusive|travel\s+exclusive|\btrx\b|\bgtr\b", re.IGNORECASE)

_SIZE_RE = re.compile(r"Size:\s*([\d.,]+\s*(?:cl|ml|l)\b)", re.IGNORECASE)


class MilanoMalpensaBoutiqueScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        return f"{BASE_URL}/en/{self.category}/"

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
        self.driver.get(self.get_url())
        time.sleep(4)

    def dismiss_age_verification(self):
        """No age gate found anywhere on this site during this build —
        best-effort only, matches the template's standard shape."""
        self.driver.find_element(By.XPATH, "//button[contains(translate(., 'ACEPTR', 'aceptr'), 'accept') and contains(translate(., 'ACEPTR', 'aceptr'), 'age')]").click()

    def dismiss_cookie_banner(self):
        self.driver.find_element(By.XPATH, "//button[contains(translate(., 'ACEPT', 'acept'), 'accept')]").click()

    def get_expected_item_count(self):
        """Real header badge next to the category H1 (e.g. "Whiskey 170").
        NOTE: confirmed during this build to be an OVERCOUNT relative to
        what the site's own pagination actually serves (a real, investigated
        site-side data-quality quirk, not a scraper bug) — see module
        docstring. Still captured here for transparency/reporting, but a
        MISMATCH against this specific number is expected and should not
        be "fixed" by changing the pagination logic."""
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        h1 = soup.find("h1")
        if not h1:
            return None
        text = h1.parent.get_text(" ", strip=True)
        m = re.search(r"(\d+)\s*$", text)
        return int(m.group(1)) if m else None

    def _get_next_href(self, html):
        soup = BeautifulSoup(html, "html.parser")
        a = soup.find("a", attrs={"aria-label": re.compile("next page", re.I)})
        if not a:
            return None
        href = a.get("href")
        if href and href.startswith("?"):
            href = self.driver.current_url.split("?")[0] + href
        return href

    def paginate_or_scroll(self):
        """Cursor-based pagination — see module docstring. Follows the real
        server-rendered "Go to next page" <a href="?after=..."> link (direct
        navigation genuinely advances, unlike the king's.sr ?page=N trap)
        until the control renders as a disabled <div> instead of an <a>."""
        seen_urls = {self.driver.current_url}
        while True:
            self.get_main()
            next_href = self._get_next_href(self.driver.page_source)
            if not next_href or next_href in seen_urls:
                break
            seen_urls.add(next_href)
            self.driver.get(next_href)
            time.sleep(4)

    def get_main(self):
        html = self.driver.page_source
        seen_this_page = set()
        for sku, title, href, price, subtitle in _PRODUCT_RE.findall(html):
            if sku in seen_this_page:
                continue
            seen_this_page.add(sku)
            product_dict = {}
            try:
                full_href = href if href.startswith("http") else f"{BASE_URL}/en{href}"
                product_dict["Product_link"] = full_href
                product_dict["ID_raw"] = sku
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None
                product_dict["ID_raw"] = None

            try:
                product_dict["Brandline"] = title
                product_dict["Brand"] = subtitle
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                # No genuine strike-through/original price found anywhere
                # on this site (percentage-only "Save X%" badge, no second
                # price) — see module docstring. Both fields carry the same
                # single visible price rather than an invented original.
                product_dict["Strike Price"] = price
                product_dict["Price Discounted"] = price
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # Real per-product signal embedded in the title text itself
            # (e.g. "... Travel Exclusive") — see module docstring. Site
            # tracks this concept for some products, not others, so every
            # row gets a real string (blank "" default).
            m = _EXCLUSIVE_RE.search(title or "")
            product_dict["GTR_exclusive"] = m.group(0) if m else ""

            self.product_dicts.append(product_dict)

    def fetch_size(self, product_link):
        """Second pass — Size isn't on the listing card JSON, only on the
        product detail page as plain visible text ("Size: 1L"). See module
        docstring."""
        try:
            self.driver.get(product_link)
            time.sleep(2.5)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            text = soup.get_text(" ", strip=True)
            m = _SIZE_RE.search(text)
            return m.group(1) if m else None
        except Exception:
            return None

    def run_all(self):
        try:
            self.open_website()
            try:
                self.dismiss_age_verification()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            try:
                self.dismiss_cookie_banner()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            self.expected_count = self.get_expected_item_count()
            self.product_dicts = []
            self.paginate_or_scroll()

            # Second pass: visit each product's detail page once for Size.
            for product_dict in self.product_dicts:
                link = product_dict.get("Product_link")
                if link:
                    product_dict["Size"] = self.fetch_size(link)
                else:
                    product_dict["Size"] = None
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
                scraper = MilanoMalpensaBoutiqueScraper(channel, category)
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
                        flag = "OK" if scraped_count == scraper.expected_count else "MISMATCH (see module docstring re: known header-count overcount quirk)"
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
