"""
Scraper for King Power CN — https://www.kingpower-cn.com/search?cat=48&type=cat

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/kingpower_cn_scraper.py once validated (this repo —
web-scraping-agent-skill — is where retailer outputs are drafted and
reviewed).

CONFIRMED against the live rendered DOM (Selenium + undetected_chromedriver,
site is JS-rendered / needs a real browser, not just plain HTTP GET):

  - Operator/brand: this is the Chinese-language-facing storefront of
    KING POWER — the well-known Thai duty-free/travel-retail operator
    ("King Power International Group"). Page <title> is literally
    "泰国KingPower王权免税店 - Powered by Jescard" ("Thailand KingPower Duty-Free
    Shop"), and the meta description explicitly says it belongs to "泰国王权
    国际集团" (Thailand King Power International Group) and is a "泰国离境
    ...免税店" (Thailand departure ... duty-free shop). This is the SAME
    underlying King Power operator/catalog family as the main kingpower.com
    site, not an unrelated company that merely licensed the name — it is a
    genuinely separate storefront/domain built for Chinese travelers
    specifically (site is Chinese-only; the header's "EN"/"TH" language
    links do NOT switch language in-page — they are outbound links to the
    entirely different kingpower.com domain, confirmed live: href=
    "https://www.kingpower.com/?lang=en" / "?lang=th"). No in-page English
    version exists on kingpower-cn.com itself.
  - Business model: "离境订购" (departure pre-order) — shoppers pre-order
    online (must be 24h-30 days before departure per the site's own
    shopping-notes copy) and collect the goods at a Thai international
    airport departure zone, or at a King Power downtown store. This is the
    same pre-order/click-and-collect GTR pattern as other airport duty-free
    builds in this repo (Milano Malpensa Boutique, Le Marché Duty Free,
    RegStaer Vnukovo). Genuinely GTR (duty-free), confirmed from the site's
    own repeated "免税店" (duty-free shop) branding, not assumed from the URL.
  - Location(s) served — CONFIRMED LIVE, not assumed: the site's own airport
    switcher (id="selectDeliveryTypeBtn") lists FOUR pickup airports
    (素万那普/Suvarnabhumi, 廊曼/Don Mueang, 清迈/Chiang Mai, 普吉/Phuket) plus a
    footer store-locator listing TWO downtown branches (Bangkok, Phuket) and
    FOUR airport branches (Suvarnabhumi, Don Mueang, Phuket, Chiang Mai — a
    5th, U-Tapao, is mentioned in the shopping-notes copy text but has no
    dedicated store-locator entry). This build tested empirically whether
    switching the pickup-airport selector changes the product catalog/
    pricing on /search?cat=48: it does NOT — before and after clicking
    through the full "switch to Don Mueang" UI flow (open switcher -> click
    廊曼机场 group -> click 确定 confirm), the cat=48 listing returned an
    IDENTICAL total (91), identical first-5 product IDs, and identical
    first-5 prices. CONCLUSION: kingpower-cn.com runs ONE unified online
    catalog for pre-order across all its Thai airport/downtown pickup
    points — the airport/store selector is a pickup-LOGISTICS choice made
    at checkout, not a catalog/pricing fork. There is therefore no genuine
    per-location Channel split to key off of here.
  - Channel format: no exact "kingpower"/"king_power"/"king power" legacy
    scraper, cleaner, or Channel string was found anywhere in GTR_Pricing
    (scrapers/, silver_scripts/, webscraping/, kestra_flows/ all checked —
    no hits) to reuse verbatim, and no existing "Suvarnabhumi" Channel
    string exists there either. User-confirmed 2026-07-23: despite the
    catalog being genuinely unified across all Thai pickup points (see
    above), Channel is set to "Suvarnabhumi Airport (BKK)" — Suvarnabhumi
    is King Power's flagship/primary Bangkok airport location, and this
    airport-specific format matches this project's standing "<Place>
    [International] Airport (IATA)" convention (see
    references/schema.md's Channel table) more closely than the
    combined-national-retailer alternative previously flagged. "BKK" per
    Suvarnabhumi's real IATA code; no "International" included since the
    airport's own common English name doesn't carry it, matching the
    precedent set by e.g. "Auckland Airport (AKL)".
  - Platform: custom PHP-ish storefront, "Powered by Jescard" per the page
    <title> (Jescard appears to be the e-commerce platform vendor, not the
    retailer). Fully client-rendered on page load (server returns complete
    product markup on GET, actually — confirmed via view-source-equivalent
    page_source after Selenium load; no additional AJAX/scroll needed to
    see the first page of results).
  - Category taxonomy — CHECKED for the nested/overlapping-dimension trap
    per this build's brief, and a real one was found. cat=48 ("酒水" —
    literally "alcohol & beverages", the department that bundles liquor
    together with coffee and soft drinks on this site) is the PARENT/
    umbrella category and itself reports a deduplicated total of 91 via its
    own "结果(91)" ("results (91)") text. Its own page lists five
    "包含分类" ("included sub-categories"): 葡萄酒/Wine (cat=268, 30 items),
    洋酒/Foreign liquor (cat=269, 79 items), 咖啡/Coffee (cat=270, 5 items),
    其他/Other (cat=271, 7 items), 非酒精饮料/Non-alcoholic beverages (cat=272,
    2 items). These sub-category totals SUM to 123 (30+79+5+7+2), which is
    MORE than the parent's 91 — confirmed live that products are tagged
    under multiple simultaneous child categories at once (e.g. product
    90873 appears in both cat=48 and cat=269; product 48581 appears in both
    cat=269 and cat=271) — a real Type-style overlapping-dimension trap.
    RESOLUTION: this scraper loops ONLY the parent cat=48 (a single,
    already-deduplicated pass — its own listing has no duplicate product
    IDs across its two pages), never the overlapping children, avoiding
    double-counting entirely.
  - Alcohol-only filtering: cat=48's own 91-item listing is NOT alcohol-only
    — it bundles in the two non-alcohol children found above: 咖啡/Coffee
    (5 SKUs, all brand "THE COFFEE HOUSE") and 非酒精饮料/Non-alcoholic
    beverages (2 SKUs, both brand "Gold Bird's Nest/金燕" — bird's-nest
    tonic drinks, no alcohol). 其他/Other (cat=271, 7 SKUs) is NOT excluded
    — despite the generic name, it is genuinely alcohol: it's where this
    site buckets Chinese baijiu (MOUTAI/茅台, SHUI JING FANG/水井坊) that
    doesn't fit under 洋酒 ("foreign/Western liquor"). Manually reviewed
    every one of the 91 raw brand names across both pages of cat=48 live —
    the ONLY two non-alcohol brands present anywhere in the set are "THE
    COFFEE HOUSE" and "Gold Bird's Nest/金燕" (5+2=7 SKUs, exactly matching
    the cat=270/cat=272 totals with zero overlap between them) — every
    other brand (Johnnie Walker, Hennessy, Macallan, Moutai, Penfolds,
    Dom Pérignon/唐培里侬, Château Mouton Rothschild, etc.) is genuine wine/
    spirits. This scraper drops any card whose Brand contains "COFFEE"/
    "咖啡" or "BIRD'S NEST"/"燕窝" (case-insensitive), leaving the expected
    91 - 7 = 84 alcohol SKUs. See _is_alcohol() below.
  - Pagination: real server-side `?page=N` query param, 60 items per page.
    CONFIRMED genuinely working (not a kings.sr-style client-state trap):
    direct navigation to page=2 of cat=48 returned 31 entirely different
    product IDs (first 5: 48582, 5446, 32017, ... vs page 1's 90873, 6840,
    90881, 48581, 34540) with zero overlap. 60 + 31 = 91, matching the
    site's own displayed total exactly.
  - Product listing cards: `<div class="goods-content" goods-item
    data-common-id="..." data-goods-id="..." data-storage="...">` (a
    `<li class="item">` wrapper around each). Product link + numeric ID:
    `div.goods-pic > a[href]` -> `https://www.kingpower-cn.com/goods/<ID>`
    (the URL's trailing ID is the same value as the card's own
    `data-common-id` attribute — confirmed consistent on every card
    checked, so `data-common-id` is used directly as ID_raw, no separate
    detail-page fetch needed). Brand: `h1.promotion_name` (e.g. "JOHNNIE
    WALKER/尊尼获加", sometimes English-only e.g. "SHUI JING FANG", sometimes
    Chinese-only e.g. "云雾之湾" [Cloudy Bay wine] — no consistent
    English/Chinese split, left for the cleaner to normalize via
    ai_translate). Brandline+Size are bundled together in a single Chinese
    product title, `p.promotion_texted` (e.g. "三得利 响大师臻选威士忌700ml") —
    per this project's convention, the cleaner splits Size out of this text
    rather than the scraper.
  - Price: `span.price_1` = current/selling price in THB (e.g.
    "4250.00 THB"). A second `span.price_2` right next to it is NOT a
    strike/original price — it's the site's own live estimated CNY
    conversion for the Chinese shopper's convenience (e.g. "(约￥855.61)",
    using Alipay/UnionPay/WeChat exchange rates shown in the header) and is
    deliberately NOT captured; the scraper always captures the THB figure
    and lets the shared `ExchangeRate_cleaning()` utility do the real
    IWSR-rate conversion in the cleaner. A genuine strike/original price
    DOES exist on real promo items: `span.price_3` (confirmed live, with an
    HTML comment literally reading "原价（划线价）" — "original price
    (strikethrough price)" — e.g. a Coffee House item showing "最优到手"
    /"best price" 272.00 THB as price_1 next to a 340.00 THB price_3, with a
    `label-info-text` badge "满1件8折" — "20% off per unit" spend-based
    promo). Only single-price items were found within the genuine alcohol
    set during this build's live check (no alcohol SKU with a populated
    price_3 was found on either page of cat=48) — per this project's
    convention, when only one price shows, it's duplicated into both raw
    fields here at scrape time (belt-and-braces alongside the cleaner's own
    mandatory backfill step).
  - GTR_exclusive: NO exclusivity badge, ribbon, or "Exclusives" nav
    category found anywhere on the site (checked every card across both
    pages of cat=48, plus the wine/liquor/coffee/other/non-alcohol child
    category pages). The only per-product badge concept found at all is a
    `label-div` > `label-info-text` promotional/discount label (e.g. "满1件
    8折" quantity discount, "满1000减500" spend-threshold discount) — already
    captured via Strike_Price/Price_Discounted. This is the genuine null
    case: this field is never set by this scraper.
  - Currency: every price renders in THB (Thai Baht) — the real transaction
    currency for these Thailand-fulfilled duty-free goods. No currency
    selector found; the CNY figures shown alongside are a display-only
    convenience conversion, not the real price (see Price note above).
  - Age gate / cookie banner: none encountered on any page fetched during
    this build (category pages load straight to product listings, no
    modal/interstitial). Dismissal methods below are defensive no-ops.
"""

import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "kingpower_cn"
BASE_URL = "https://www.kingpower-cn.com"

# One unified online catalog across all Thai pickup airports/downtown
# stores — confirmed live (see module docstring) that switching the pickup
# airport does not change cat=48's listing or prices at all. Channel is
# user-confirmed 2026-07-23 as Suvarnabhumi Airport (BKK), King Power's
# flagship Bangkok location, per this project's standard airport-naming
# convention — see module docstring for the full reasoning.
LOCATIONS = {
    "Thailand": ["Suvarnabhumi Airport (BKK)"],
}

# Single parent category (cat=48, "酒水") looped alone — NOT its overlapping
# children (cat=268/269/270/271/272) — see module docstring's nested-
# taxonomy-trap note. Non-alcohol SKUs that leak into this parent listing
# (Coffee, non-alcoholic bird's-nest drinks) are filtered per-card below.
CATEGORIES = {
    "48": "Alcohol & Beverages (酒水)",
}

_PAGE_SIZE = 60
_MAX_PAGES = 10  # safety cap (600 products) — real total seen live is 91 (2 pages)
_RESULT_COUNT_RE = re.compile(r"结果\((\d+)\)")

# The only two non-alcohol brands found anywhere in cat=48's 91-item listing
# during this build's live check (see module docstring) — every other brand
# present is genuine wine/spirits/baijiu.
_NON_ALCOHOL_BRAND_MARKERS = ["COFFEE", "咖啡", "BIRD'S NEST", "燕窝"]


def _is_alcohol(brand_raw: str) -> bool:
    if not brand_raw:
        return True  # don't drop a row just because Brand failed to parse
    upper = brand_raw.upper()
    return not any(marker.upper() in upper for marker in _NON_ALCOHOL_BRAND_MARKERS)


class KingpowerCnScraper:
    def __init__(self, location, category_id, category_name):
        self.location = location
        self.category_id = category_id
        self.category_name = category_name
        self.product_dicts = []
        self.expected_count = None  # site's own RAW total for cat=48 (includes non-alcohol) — see run_all()

    def get_url(self, page=1):
        url = f"{BASE_URL}/search?cat={self.category_id}&type=cat"
        if page > 1:
            url += f"&page={page}"
        return url

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1400,2000")

        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.driver.set_page_load_timeout(60)

    def dismiss_age_verification(self):
        """No age gate found anywhere on this site during this build —
        defensive no-op, wrapped in try/except by run_all()."""
        self.driver.find_element(By.CSS_SELECTOR, ".age-verify-confirm, .age-gate-confirm")

    def dismiss_cookie_banner(self):
        """No cookie banner found anywhere on this site during this build —
        defensive no-op, wrapped in try/except by run_all()."""
        self.driver.find_element(By.XPATH, "//*[contains(@class,'cookie') and contains(@class,'accept')]")

    def _load(self, url):
        try:
            self.driver.get(url)
        except Exception:
            pass
        time.sleep(3)
        return BeautifulSoup(self.driver.page_source, "html.parser")

    def get_expected_item_count(self, soup):
        text = soup.get_text(" ", strip=True)
        match = _RESULT_COUNT_RE.search(text)
        return int(match.group(1)) if match else None

    def _extract_price_thb(self, price_el):
        """price_1/price_3 elements sometimes wrap a nested price_2 (CNY
        estimate) span inside them (the "预估价" promo layout — see module
        docstring) — regex out just the "<number> THB" portion of the
        element's own text rather than trusting get_text() verbatim, so the
        CNY figure never leaks into the raw price field."""
        if price_el is None:
            return None
        text = price_el.get_text(" ", strip=True)
        m = re.search(r"[\d,]+\.?\d*\s*THB", text)
        return m.group(0) if m else (text or None)

    def _extract_card(self, card):
        product_dict = {}
        try:
            common_id = card.get("data-common-id")
            product_dict["ID_raw"] = common_id
            link_el = card.select_one("div.goods-pic a[href]")
            href = link_el["href"] if link_el else (f"{BASE_URL}/goods/{common_id}" if common_id else None)
            product_dict["Product_link"] = urljoin(BASE_URL, href) if href else None
        except (AttributeError, TypeError):
            product_dict["ID_raw"] = None
            product_dict["Product_link"] = None

        try:
            brand_el = card.select_one("h1.promotion_name")
            product_dict["Brand"] = brand_el.get_text(strip=True) if brand_el else None
        except (AttributeError, TypeError):
            product_dict["Brand"] = None

        try:
            title_el = card.select_one("p.promotion_texted")
            # Brandline+Size bundled together in one Chinese title — the
            # cleaner splits Size out of this text, per this project's
            # convention for sites with no dedicated Size field.
            product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
        except (AttributeError, TypeError):
            product_dict["Brandline"] = None

        product_dict["Size"] = None  # no dedicated Size field on this site — see Brandline note above

        try:
            price1_el = card.select_one("span.price_1")
            price3_el = card.select_one("span.price_3")
            price_discounted = self._extract_price_thb(price1_el)
            strike_price = self._extract_price_thb(price3_el)
            product_dict["Price Discounted"] = price_discounted
            # Only single-price alcohol SKUs were found live during this
            # build (see module docstring) — duplicate the one real price
            # into both raw fields when no genuine price_3 strike price
            # exists, matching this project's single-price convention.
            product_dict["Strike Price"] = strike_price or price_discounted
        except (AttributeError, TypeError):
            product_dict["Price Discounted"] = None
            product_dict["Strike Price"] = None

        # GTR_exclusive: no exclusivity badge/ribbon/"Exclusives" concept
        # found anywhere on this site (see module docstring) — deliberately
        # never set here, so the cleaner emits a true null for this field.

        return product_dict

    def get_main(self):
        soup = self._load(self.get_url(page=1))
        self.expected_count = self.get_expected_item_count(soup)

        for page in range(1, _MAX_PAGES + 1):
            if page > 1:
                soup = self._load(self.get_url(page=page))
            cards = soup.select("div.goods-content[goods-item]")
            if not cards:
                break
            for card in cards:
                raw = self._extract_card(card)
                if _is_alcohol(raw.get("Brand")):
                    self.product_dicts.append(raw)
            if len(cards) < _PAGE_SIZE:
                break

    def run_all(self):
        try:
            self.open_website()
            self.get_main()
            try:
                self.dismiss_age_verification()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            try:
                self.dismiss_cookie_banner()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
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
    total_expected_raw = 0  # site's own displayed total (includes non-alcohol Coffee/Bird's-Nest SKUs)
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_id, category_name in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_name}")
                scraper = KingpowerCnScraper(channel, category_id, category_name)
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
                        total_expected_raw += scraper.expected_count
                        expected_alcohol = scraper.expected_count - 7  # minus known Coffee(5)+Bird's Nest(2) — see docstring
                        flag = "OK" if scraped_count == expected_alcohol else "MISMATCH"
                        print(
                            f"  -> {category_name}: scraped {scraped_count} alcohol SKUs / "
                            f"site says {scraper.expected_count} raw (expected alcohol-only: {expected_alcohol}) [{flag}]"
                        )
                    else:
                        print(f"  -> {category_name}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_name}: {e}")

    if total_expected_raw:
        print(f"TOTAL: scraped {total_scraped} alcohol SKUs / site says {total_expected_raw} raw (incl. non-alcohol)")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
