"""
Scraper for Siêu Thị Rượu Ngoại ("Foreign Liquor Supermarket") —
https://www.sieuthiruoungoai.com/

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/sieuthiruoungoai_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted
and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome via
undetected_chromedriver, real page_source, no text-extraction proxy):
  - NOT duty-free/travel-retail. Site is entirely in Vietnamese, no
    "duty free" / "vrijhaven" / airport / traveler language anywhere.
    "Giới thiệu" (About) and "Về chúng tôi" (About us) pages describe an
    ordinary retail/wholesale liquor business ("phân phối sỹ và lẻ các
    sản phẩm rượu ngoại" — "we distribute wholesale and retail foreign
    liquor products") with a physical showroom at 357 Trần Phú, Phường 8,
    Quận 5, TP.HCM, plus separate phone lines for Hà Nội and Đà Nẵng
    branches, home delivery nationwide. Brand name "Siêu Thị Rượu Ngoại"
    (no separate legal-entity name found anywhere on the site). Market =
    "Domestic", Country = "Vietnam" (no "DF " prefix — that prefix is
    GTR-only per this repo's schema). Currency VND ("đ" suffix on every
    price). Single unified nationwide online catalog — no branch-specific
    inventory or pricing found, so one "N/A" channel, same convention as
    every other single-catalog domestic retailer in this repo.
  - Platform: a small, dated, custom-built Vietnamese PHP e-commerce CMS
    (`themes/global/js/vcms.js`, `themes/ruoungoai/...` theme path,
    jQuery 3.1.1, Bootstrap 3, OwlCarousel) — not Shopify/WooCommerce/
    Magento/Sapo/Haravan (checked all of those brand strings in the raw
    HTML, zero matches). No public JSON/REST catalog API found (unlike
    Le Bon Macau's Shopify products.json) and no sitemap.xml — every
    category is scraped from server-rendered HTML.
  - Category taxonomy CHECKED for the nested/overlapping-dimension trap
    per this build's brief, and this site is a real, fairly severe
    example of it:
      * Every "type" mega-menu section (Cognac, Blended Scotch Whisky,
        Single Malt, Vodka, Gin-Tequila-Liqueur, Wine) has BRAND- or
        COUNTRY-specific sub-pages nested under it (e.g. "Rượu Hennessy"
        under Cognac, "Rượu Chivas" under Blended Scotch Whisky, "Rượu
        vang Pháp" under Wine) that are confirmed-live SUBSETS of their
        parent — e.g. live IDs 4846/4844/4848 appear on BOTH
        /ruou-cognac page 1 AND /ruou-hennessy page 1; IDs 4751/4753/
        4754/4758/4750 appear on BOTH /ruou-blended-scotch-whisky page 1
        AND /ruou-chivas page 1. Looping brand/country children as well
        as their type parent would massively double-count SKUs.
      * Gift-occasion collections ("Hộp quà Tết", "Giỏ quà tặng", "Set
        Quà Tết 2026", "Hộp Quà Rượu", "Set Quà Vang") are a THIRD,
        cross-cutting dimension over the exact same bottles — confirmed
        live: the Hennessy V.S.O.P Duluxe product page's own breadcrumb
        reads "Hộp Quà Rượu HENNESSY V.S.O.P DULUXE", i.e. a bottle
        already counted under Cognac is simultaneously filed as a gift
        box. Looping these would double-count again.
      * "Rượu Spirits" and "Rượu Gin - Tequila - Liqueur" have a small
        real overlap (5 of 24 live page-1 IDs — 4668-4672 — appear in
        both) — a minor, accepted exception (both are kept as their own
        category below; the shared handful of rows collapse naturally
        under the cleaner's existing Product_link/ID dedup, the same
        defensive posture used on every other build in this repo).
      * AVOIDED the trap by looping exactly ONE dimension: the top-level
        TYPE/origin categories from the main mega-menu (CATEGORIES
        below), never their brand/country child pages, and never the
        gift-occasion overlay. Confirmed disjoint pairwise on a live
        sample (Brandy vs Cognac: 0 shared IDs; hang-doc/ruou-nga vs
        Vodka: 0 shared IDs; Kho thanh lý/clearance vs Cognac, Blended
        Scotch Whisky, and Brandy: 0 shared IDs in each case).
      * "Danh mục bia" (beer) is a real nav entry but currently lists
        ZERO products live (confirmed: the page's own `#product-list`
        <main> renders only the sort dropdown, no product cards at all)
        — excluded for having nothing to scrape right now, not a bug.
      * "Phụ kiện rượu" (liquor accessories — openers, decanters,
        glassware) is real but non-alcohol — excluded per this skill's
        alcohol-only rule.
      * "Rượu hàng độc quý hiếm đẹp lạ" ("Rượu Phong Thủy - Độc Đáo" in
        the nav — a "rare/unique/novelty bottle" collection, e.g. zodiac-
        animal-shaped decanters and one-off vintages) LOOKED like it
        would be another cross-cutting overlay (one sampled sub-page,
        hang-doc/ruou-nga, is itself clearly a country-cut view) but a
        live full-catalog overlap check proved otherwise: of 157 unique
        IDs across its 8 pages, only 11 also appear in Cognac/Blended
        Scotch Whisky/Single Malt/Brandy/Wine/Vodka combined (112+323+
        645+48+865+104 IDs checked) — the other 146 (93%) are genuinely
        NOT in any of those six categories. Kept as its own category
        rather than excluded, since excluding it would silently drop
        real inventory; the small residual overlap (here and any overlap
        with the other seven categories below, not individually re-
        checked) is left to the cleaner's existing defensive
        Product_link/ID dedup, same posture as every other build in this
        repo.
  - CATEGORIES = 14 top-level type/origin/collection categories: Cognac,
    Blended Scotch Whisky, Single Malt Whisky, Brandy, Vodka,
    Gin-Tequila-Liqueur, Spirits, Wine (Vang — one aggregate category,
    NOT looped per-country), Champagne, Chinese liquor, Vietnamese
    liquor, Miniatures, Clearance (old/discontinued stock — confirmed
    genuinely disjoint from the live type categories tested, i.e. real
    additional inventory, not a duplicate view), and Rare/unique bottles
    (confirmed mostly — not entirely — disjoint from the six largest type
    categories, see above).
  - Product cards: `div.product-item-box > div.product-item`, ~24 per
    page (a handful fewer than 24 on a given page are common — see
    below):
      - Product_link + ID: the card's own `<a href="<slug>">` (a
        RELATIVE path with no leading slash — built here as
        f"{BASE_URL}/{slug}") is Product_link. The sibling
        `<a class="order-now" href="cart/add/<ID>/1">` carries the
        site's own numeric internal product ID, used directly as
        ID_raw — confirmed unique and stable across every category
        tested, and independently visible again as part of a PDP's own
        "Mã sản phẩm" field for the few products checked.
      - A real minority of cards (3/24 sampled on the Cognac category,
        e.g. "Dom Pérignon Blanc Vintage 2002") have NO `cart/add` link
        and show "Liên hệ" ("Contact us") instead of a price — genuinely
        price-on-request/out-of-stock listings, not a scraper bug. These
        correctly land in the cleaner's DLQ on the null-price condition.
      - Brandline: the card's `<strong>` text (e.g. "Cognac Lheraud
        Petite Champagne 1979", "HENNESSY V.S.O.P DULUXE") — brand+name
        bundled into one string, same convention as most other single-
        title-field retailers in this repo. Brand is left null (no
        separate brand field on the listing card — the PDP has a
        "Nhãn hiệu" (Brand) spec field, e.g. "Hennessy", but visiting
        every PDP individually for ~3,300 live products was judged not
        worth the added runtime for this build; Brand stays null and
        Brandline carries the full name, same tradeoff made on Kings
        Suriname/Le Bon Macau for their own unresolved fields).
      - Price: the card's `<ul><li>` text, e.g. "26.490.000 đ" (VND,
        dot-thousands, no decimals). Checked the live "Hot deal"/sale-off
        page (0 products currently listed), a product detail page, and
        the raw card HTML across 4 categories for any `<del>` tag, any
        "old-price"/"strike"/"sale"/"discount"-classed element, or a
        second price node on any card — zero found anywhere on this
        site. No discount/strikethrough concept exists here — Strike_Price
        and Price_Discounted are set to the same raw value, same
        convention as Kings Suriname.
      - GTR_exclusive: checked the homepage, category pages, and a
        product detail page for "độc quyền"/"exclusive"/"hàng độc"-style
        per-product exclusivity badges — zero matches. True null case
        (this domestic retailer never signals product-exclusivity at
        all) — deliberately never set here.
  - Pagination: real, working server-side `?page=N` query-string
    pagination — confirmed live on /ruou-vang: page=1 (23 IDs), page=2
    (24 IDs), page=3 (24 IDs), zero ID overlap between any pair of pages.
    Unlike kings.sr, direct URL navigation to `?page=N` genuinely
    advances the catalog here (this is a server-rendered PHP app, not a
    client-side SPA holding pagination state only in memory) — no click-
    driven pagination control is needed. Each category page's own
    pagination widget links (`<a href="...?page=N">`) expose the site's
    own max page number, which this scraper uses as
    `get_expected_item_count()`'s coverage target (paginating one page
    past that confirmed number returns zero cards on every category
    checked, i.e. the widget's stated max is exhaustive, not truncated).
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

RETAILER_SLUG = "sieuthiruoungoai"
BASE_URL = "https://www.sieuthiruoungoai.com"

# Single unified nationwide online catalog, no branch/location split found
# (showroom + phone lines exist for HCM/Hanoi/Da Nang, but inventory and
# pricing are not location-specific anywhere on the site).
LOCATIONS = {
    "Vietnam": ["N/A"],
}

# 14 top-level TYPE/origin/collection categories — the ONE non-overlapping
# dimension looped here (with one confirmed small residual overlap, see
# below). Deliberately EXCLUDES: brand-specific child pages (e.g.
# ruou-hennessy, ruou-chivas — confirmed subsets of their type parent),
# country-specific wine child pages (e.g. ruou-vang-phap — subset of
# ruou-vang), the gift-occasion overlay (Hộp quà Tết / Giỏ quà tặng / Set
# Quà Tết / Hộp Quà Rượu / Set Quà Vang — confirmed cross-cutting the same
# bottles), "Danh mục bia" (beer — 0 products live), and "Phụ kiện rượu"
# (accessories — non-alcohol). See module docstring for the confirmed
# overlap/emptiness evidence behind each exclusion.
#
# "Rare/unique bottles" (ruou-hang-doc-quy-hiem-dep-la) IS included
# despite looking at first like another overlay — a live check found 93%
# of its IDs (146/157) are NOT in the six largest type categories, so
# excluding it would drop real inventory. Its small residual overlap (11
# IDs against those six, untested against the other seven) is left to the
# cleaner's standard defensive dedup rather than hand-picked out here.
# Real leak found and fixed 2026-07-20: cocktail syrups (e.g. "SYRUP
# MARIE BRIZARD Grenadine") appear inside the Gin-Tequila-Liqueur
# category (~9% of that category's live sample) despite being non-
# alcoholic - Marie Brizard makes both real liqueurs AND syrups, so this
# only excludes the literal word "syrup", never the brand name alone.
_NON_ALCOHOLIC_RE = re.compile(r"\bsyrup\b", re.IGNORECASE)

CATEGORIES = {
    "ruou-cognac": "Cognac",
    "ruou-blended-scotch-whisky": "Blended Scotch Whisky",
    "ruou-single-malt-scotch-whisky": "Single Malt Whisky",
    "ruou-brandy": "Brandy",
    "ruou-vodka": "Vodka",
    "ruou-gin-tequila-liqueur": "Gin-Tequila-Liqueur",
    "ruou-spirits": "Spirits",
    "ruou-vang": "Wine",
    "ruou-champagne": "Champagne",
    "ruou-trung-quoc": "Chinese liquor",
    "ruou-viet-nam": "Vietnamese liquor",
    "ruou-mau-ruou-mini": "Miniatures",
    "kho-ruou-thanh-ly": "Clearance",
    "ruou-hang-doc-quy-hiem-dep-la": "Rare/unique bottles",
}


class SieuThiRuouNgoaiScraper:
    def __init__(self, location, category_slug, category_label):
        self.location = location
        self.category_slug = category_slug
        self.category_label = category_label
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, page=1):
        if page <= 1:
            return f"{BASE_URL}/{self.category_slug}"
        return f"{BASE_URL}/{self.category_slug}?page={page}"

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

    def get_max_page(self, soup):
        """Site's own pagination widget links (<a href="...?page=N">) —
        used as the real coverage target, same role as Kings Suriname's
        "X resultaten" text on a site that has no displayed item-count
        text anywhere."""
        max_page = 1
        for a in soup.find_all("a", href=True):
            m = re.search(r"[?&]page=(\d+)", a["href"])
            if m:
                max_page = max(max_page, int(m.group(1)))
        return max_page

    def get_main(self, soup):
        cards = soup.select("div.product-item-box")
        added = 0
        for card in cards:
            product_dict = {}
            try:
                link_el = card.select_one("div.product-item > a[href]")
                href = link_el["href"] if link_el else None
                # Relative slug, no leading slash.
                product_dict["Product_link"] = (
                    f"{BASE_URL}/{href.lstrip('/')}" if href else None
                )
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None

            try:
                order_link = card.select_one("a.order-now[href]")
                id_match = re.search(r"cart/add/(\d+)/1", order_link["href"]) if order_link else None
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError):
                product_dict["ID_raw"] = None

            try:
                title_el = card.select_one("div.product-item strong")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            if product_dict["Brandline"] and _NON_ALCOHOLIC_RE.search(product_dict["Brandline"]):
                continue

            try:
                price_el = card.select_one("div.product-item ul li")
                price_text = price_el.get_text(strip=True) if price_el else None
                # "Liên hệ" (contact for price) rows genuinely have no
                # numeric price — left as None, not invented, correctly
                # routed to the cleaner's DLQ.
                has_digit = bool(price_text and re.search(r"\d", price_text))
                product_dict["Strike Price"] = price_text if has_digit else None
                product_dict["Price Discounted"] = price_text if has_digit else None
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No exclusivity badge/tag concept found anywhere on this
            # site — see module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)
            added += 1
        return added

    def run_all(self, max_pages_safety=200):
        try:
            self.open_website()
            self.driver.get(self.get_url(1))
            time.sleep(3.5)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            self.expected_count = self.get_max_page(soup)
            self.get_main(soup)

            page = 2
            while page <= min(self.expected_count, max_pages_safety):
                self.driver.get(self.get_url(page))
                time.sleep(3)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                added = self.get_main(soup)
                if added == 0:
                    # page turned up empty before the widget's own stated
                    # max — stop rather than loop on nothing.
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
    total_expected_pages = 0
    total_scraped = 0

    for country, channels in LOCATIONS.items():
        for channel in channels:
            for category_slug, category_label in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_label}")
                scraper = SieuThiRuouNgoaiScraper(channel, category_slug, category_label)
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
                    print(f"  -> {category_label}: scraped {scraped_count} rows "
                          f"(site's own pagination widget max page: {scraper.expected_count})")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_label}: {e}")

    print(f"TOTAL: scraped {total_scraped} rows across {len(CATEGORIES)} categories")

    if all_data:
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        volume_path = (
            f"/Volumes/selfservice_nonprod/gtr_web_scraping/bronze_raw/"
            f"{RETAILER_SLUG}/{date_str}/raw_data_{int(time.time())}.json"
        )
        upload_to_databricks(all_data, volume_path)
    else:
        raise ValueError(f"No data extracted! {RETAILER_SLUG} scraper failed.")
