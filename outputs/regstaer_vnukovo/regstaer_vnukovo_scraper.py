"""
Scraper for RegStaer — https://regstaer.ru/en/?utm_source=vko

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/regstaer_vnukovo_scraper.py once validated (this
repo — web-scraping-agent-skill — is where retailer outputs are drafted and
reviewed).

CONFIRMED against the live rendered DOM / raw HTML (server-rendered Bitrix
site, no client-hydration needed to see product data — confirmed reachable
with plain HTTP GET, HTTP 200, no Cloudflare/bot-wall/geo-block/age-gate
encountered on any page fetched during this build):

  - Operator/brand: "Группа компаний RegStaer" (RegStaer Group of
    Companies) — confirmed via the site's own meta description: "ведущий
    оператор трэвел-ритейла в России... лидер беспошлинной торговли в
    аэропортах страны" ("leading travel-retail operator in Russia...
    leader in duty-free trade at the country's airports"). Genuinely GTR
    (duty-free), not domestic — confirmed from the site's own copy, not
    assumed from the URL.
  - Business model: "book online, pick up in the departure zone of the
    international flights area on the day of travel" — every product
    detail page carries the line "You can pick up your order in the
    departure zone of the international flights area." Same pre-order/
    click-and-collect pattern as other airport duty-free builds in this
    repo (Milano Malpensa Boutique, Le Marché Duty Free).
  - LOCATIONS / Channel — open item, decided as follows: the site's own
    footer ("Our Stores") lists exactly two named physical duty-free shops:
    "Vnukovo airport" (/en/shop/vnukovo/) and "Mineralnye Vody airport"
    (/en/shop/mineralnye_vody/). The task's own entry URL carries
    utm_source=vko (Vnukovo's IATA code), and the site's own session/
    terminal context defaults to "Vnukovo-A" (internal XML_ID "RSV1",
    stock XML_ID "RSV5") on every page fetched during this build —
    including after directly requesting the Mineralnye Vody shop page and
    its cookie. The "AIRPORT_CODE=mineralnye_vody" link visible in the
    header markup was confirmed to actually be the RU/EN language-switcher
    widget (a shared template that happens to carry that leftover query
    param name), not a real airport-context switcher — clicking/following
    it does not change the terminal context or the catalog. The alcohol
    category total ("Total items: 1317") was identical across every
    airport-context attempt tried. No per-product field or filter was
    found anywhere that ties a specific SKU to one airport over the other
    (the "Vnukovo" ribbon seen on some homepage promo-carousel cards is a
    homepage-only decorative label on a handful of promo items, not a
    catalog-wide per-SKU location tag). CONCLUSION: this build could not
    empirically prove a real per-airport catalog split exists, and the
    catalog that is actually reachable/scrapable resolves to Vnukovo by
    the site's own default — so Country/Channel below is scoped to
    Vnukovo only, matching the task's own traffic-source origin. This is
    an assumption, not a certainty: RegStaer's own copy says it is the
    leader in duty-free "at the country's airports" (plural), so a second,
    genuinely distinct Mineralnye Vody assortment may exist behind a
    mechanism this build didn't find (e.g. only exposed after an actual
    flight/boarding-pass selection at checkout). FLAGGED FOR USER SIGN-OFF
    — see this build's final report.
  - Channel format: per this project's schema.md airport-naming
    convention ("<City/Place + airport-specific name if any> [International]
    Airport (IATA)"), used here as "Vnukovo International Airport (VKO)"
    (official name of Moscow's Vnukovo airport). No pre-existing
    Vnukovo/RegStaer legacy scraper was found anywhere in GTR_Pricing to
    reuse an exact production string from (checked scrapers/, silver_scripts/,
    webscraping/, kestra_flows/ for "vnukovo"/"moscow"/"regstaer"/"VKO" —
    no hits), so this is a fresh application of the documented convention,
    not a precedent match.
  - Platform: 1C-Bitrix ("/bitrix/..." asset paths, JCSmartFilter,
    BX.message JS core). Fully server-side rendered — every category/
    product page returns complete product markup in the raw HTTP response,
    confirmed via plain (non-JS) HTTP fetch during investigation. Still
    built with Selenium + undetected_chromedriver + BeautifulSoup per this
    project's established tech choice.
  - Category taxonomy CHECKED for the nested/overlapping-dimension trap
    per this build's brief. The top "Alcoholic Beverages" category
    (id 761) reports "Total items: 1317". Summed independently across
    the 33 real leaf nav categories used below (Aperitifs, Vermouth,
    Digestifs, Port, Sherry; 8 Wine leaves split by COUNTRY; 7 Whisky
    leaves split by TYPE/tier; Armagnac, Brandy, Calvados, Cognac; Cream
    Liqueurs, Other Liqueurs; Vodka, Gin, Tinctures, Rum, Tequila/Mezcal;
    Sparkling Wine, Champagne) gives an EXACT match: 4+6+9+4+2 +12+7+46+
    43+2+81+344+11+9 +1+19+3+40+64+47+11 +2+23+6+66 +16+23 +145+76+27+31+24
    +69+44 = 1317, confirmed live by fetching every leaf category's own
    "Total items: N" header and summing. This is a clean SINGLE-dimension
    partition (Type is the primary split; Wine's only sub-split is
    Country, Whisky's only sub-split is type/tier — no leaf belongs to two
    parents at once) — NOT a Type+Country+Region overlapping trap. There
    IS a separate smart-filter "Country" facet panel on category pages
    (Chile/France/Georgia/Ireland/Italy/Russia/UK/etc.) and a "Brand" facet
    panel, but these are page-level FILTER facets for narrowing results
    within one category, not additional category-URL dimensions that
    would double-count if looped — this scraper does not loop them, only
    the 33 leaf category IDs above.
  - Category URLs are `/en/catalog/<numeric_id>__<any-slug>/` — Bitrix's
    SEF routing only checks the numeric ID; the slug text is decorative
    (confirmed: `/en/catalog/801__x/` served the identical Cognac category
    as the real `/en/catalog/801__konyak/`). Real slugs are still used
    below for readability/robustness.
  - Pagination: real server-side `?PAGEN_1=N` query param (30 items per
    page). CONFIRMED genuinely working (unlike the kings.sr client-state
    trap) — direct navigation to page 2 of the largest leaf (Wine France,
    id 832, 344 items) returned 30 entirely different product IDs with
    ZERO overlap against page 1.
  - Product listing cards: `<div class="container__item" data-role=
    "product">` each with one `<a class="container__name" href="...">
    <TITLE></a>`, a numeric product ID embedded in the URL
    (`/en/catalog/<cat_id>__<cat_slug>/<PRODUCT_ID>__<slug>/`), a current
    price (`<span class="container__current-price">`), and — on genuinely
    discounted items only — an original price (`<span class=
    "container__old-price">`) plus a `<span class="container__discount">
    -N%</span>` and a "Promotion" section label. Confirmed real (not
    invented): e.g. CAMUS VSOP INTENSELY AROMATIC 1L showed current €63 /
    old €90 / -30% consistently on both the listing card and its own
    detail page.
  - ID: the URL-embedded numeric ID (e.g. "590877") is NOT the retailer's
    real per-SKU code — every product detail page exposes an explicit,
    separate "Code" field (`data-role="code"`, e.g. "257642" for that same
    URL-id-590877 product) that differs from both the URL id and an
    "Articul"/article number also shown. Per this project's schema
    ("prefer the retailer's own numeric SKU/product code if the site
    exposes one"), this scraper does a second pass — visiting each
    product's detail page once — to capture that real Code as ID_raw,
    plus the structured Brand field (`data-role="brand"`, e.g. "DERBENT",
    "CAMUS") which is NOT reliably separable from the bundled listing
    title alone. Brandline is the listing title with the trailing
    Russian/English category tag ("... / КОНЬЯК", "... / Cognac") that
    every title carries stripped off (split on " / ", first segment kept)
    — Size is extracted from that Brandline text by the cleaner (titles
    bundle size in, e.g. "DERBENT COGNAC 0.5L", "CAMUS VSOP INTENSELY
    AROMATIC 40% 1L").
  - GTR_exclusive: NO exclusivity badge, ribbon, "Exclusives" nav category,
    or "exclusive"/"эксклюзив" text of any kind found anywhere on the site
    (homepage, category pages, product detail pages, category filter
    facets all checked) — the only per-product badge concept found is
    "Promotion" (a discount marker, already captured as Strike_Price/
    Price_Discounted). This is the genuine null case: this field is never
    set by this scraper.
  - Currency: every price on the /en/ site renders in EUR ("€ 13", "€ 63")
    — no currency selector found anywhere; not locale-dependent on the
    pages checked.
  - Non-alcohol filtering: enforced simply by which category IDs are
    looped — the 33 leaf IDs below all live under the "Alcoholic Beverages"
    (761) parent; sibling top-level categories (Toys id 765, Books/Press
    id 769, cosmetics, sportswear, etc., seen in the same nav tree) are
    never referenced, so no separate content-based alcohol filter is
    needed.
"""

import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "regstaer_vnukovo"
BASE_URL = "https://regstaer.ru"

# Single physical/online catalog scoped to Vnukovo — see module docstring
# for why Mineralnye Vody is NOT also modeled here (open item, flagged to
# the user rather than assumed).
LOCATIONS = {
    "Russia": ["Vnukovo International Airport (VKO)"],
}

# 33 real, non-overlapping leaf alcohol categories (numeric Bitrix ID ->
# real URL slug). See module docstring for the live sum-matches-1317 check
# that confirmed this is a clean single-dimension partition, not a
# Type+Country+Region overlap trap.
CATEGORIES = {
    "797__aperitiv": "Aperitifs",
    "794__vermut": "Vermouth",
    "798__dizhestiv": "Digestifs",
    "796__portveyn": "Port",
    "795__kheres": "Sherry",
    "845__avstraliya": "Wine - Australia",
    "846__argentina": "Wine - Argentina",
    "840__ispaniya": "Wine - Spain",
    "841__italiya": "Wine - Italy",
    "836__novaya_zelandiya": "Wine - New Zealand",
    "839__prochie": "Wine - Others",
    "832__frantsiya": "Wine - France",
    "843__chili": "Wine - Chile",
    "834__yuzhnaya_afrika": "Wine - South Africa",
    "821__amerikanskiy": "Whisky - American",
    "819__irlandskiy": "Whisky - Irish",
    "822__irlandskiy_odnosolodovyy": "Whisky - Irish Malt",
    "817__shotlandskiy": "Whisky - Scotch Standard",
    "818__shotlandskiy_odnosolodovyy": "Whisky - Scotch Malt",
    "823__shotlandskiy_premium": "Whisky - Scotch Premium",
    "824__shotlandskiy_super_premium": "Whisky - Scotch Super Premium",
    "802__armanyak": "Armagnac",
    "803__brendi": "Brandy",
    "805__kalvados": "Calvados",
    "801__konyak": "Cognac",
    "826__kremovye_likyery": "Cream Liqueurs",
    "827__prochie_likyery": "Other Liqueurs",
    "809__vodka": "Vodka",
    "807__dzhin": "Gin",
    "813__nastoyki": "Tinctures",
    "808__rom": "Rum",
    "810__tekila_meskal": "Tequila / Mezcal",
    "855__vino_igristoe": "Sparkling Wine",
    "854__shampanskoe": "Champagne",
}

_TOTAL_RE = re.compile(r"Total items:\s*(\d+)", re.IGNORECASE)
_PAGE_SIZE = 30
_MAX_PAGES = 20  # safety cap (600 products) — largest real leaf seen is 344 (12 pages)

_CODE_RE = re.compile(r"data-role=\"code\">\s*([^<\s][^<]*?)\s*</span>", re.IGNORECASE)


class RegstaerVnukovoScraper:
    def __init__(self, location, category_slug, category_name):
        self.location = location
        self.category_slug = category_slug
        self.category_name = category_name
        self.product_dicts = []
        self.expected_count = None

    def get_url(self, pagen=1):
        base = f"{BASE_URL}/en/catalog/{self.category_slug}/"
        return base if pagen <= 1 else f"{base}?PAGEN_1={pagen}"

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
        time.sleep(3)
        return BeautifulSoup(self.driver.page_source, "html.parser")

    def get_expected_item_count(self, soup):
        text = soup.get_text(" ", strip=True)
        match = _TOTAL_RE.search(text)
        return int(match.group(1)) if match else None

    def _extract_card(self, card):
        product_dict = {}
        try:
            link_el = card.find("a", class_="container__name", href=True)
            href = link_el["href"] if link_el else None
            product_dict["Product_link"] = urljoin(BASE_URL, href) if href else None
            raw_title = link_el.get_text(strip=True) if link_el else None
            # Every title bundles a trailing RU/EN category tag after " / "
            # (e.g. "DERBENT COGNAC 0.5L / КОНЬЯК") — strip it, keep the
            # product-name+size portion as Brandline.
            product_dict["Brandline"] = raw_title.split(" / ")[0].strip() if raw_title else None
            id_match = re.search(r"/(\d+)__[^/]+/?$", href or "")
            product_dict["ID_raw_url"] = id_match.group(1) if id_match else None
        except (AttributeError, TypeError):
            product_dict["Product_link"] = None
            product_dict["Brandline"] = None
            product_dict["ID_raw_url"] = None

        try:
            price_el = card.find("span", class_="container__current-price")
            product_dict["Price Discounted"] = price_el.get_text(strip=True) if price_el else None
        except (AttributeError, TypeError):
            product_dict["Price Discounted"] = None

        try:
            old_price_el = card.find("span", class_="container__old-price")
            product_dict["Strike Price"] = old_price_el.get_text(strip=True) if old_price_el else None
        except (AttributeError, TypeError):
            product_dict["Strike Price"] = None

        # No GTR-exclusive badge/ribbon/"exclusive" text found anywhere on
        # this site — see module docstring. Deliberately not set here.

        return product_dict

    def get_main(self):
        soup = self._load(self.get_url(pagen=1))
        self.expected_count = self.get_expected_item_count(soup)

        for page in range(1, _MAX_PAGES + 1):
            if page > 1:
                soup = self._load(self.get_url(pagen=page))
            cards = soup.find_all("div", class_="container__item", attrs={"data-role": "product"})
            if not cards:
                break
            for card in cards:
                self.product_dicts.append(self._extract_card(card))
            if len(cards) < _PAGE_SIZE:
                break
            if self.expected_count is not None and len(self.product_dicts) >= self.expected_count:
                break

    def fetch_code_and_brand(self, product_link):
        """Second pass — the real per-SKU 'Code' and structured 'Brand'
        field only live on the product detail page, not the listing card.
        See module docstring."""
        try:
            self.driver.get(product_link)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            code_el = soup.find("span", attrs={"data-role": "code"})
            brand_el = soup.find("span", attrs={"data-role": "brand"})
            code = code_el.get_text(strip=True) if code_el else None
            brand = brand_el.get_text(strip=True) if brand_el else None
            return code, brand
        except Exception:
            return None, None

    def run_all(self):
        try:
            self.open_website()
            self.get_main()

            for product_dict in self.product_dicts:
                link = product_dict.get("Product_link")
                if link:
                    code, brand = self.fetch_code_and_brand(link)
                else:
                    code, brand = None, None
                product_dict["ID_raw"] = code or product_dict.get("ID_raw_url")
                product_dict["Brand"] = brand
                # No dedicated Size field anywhere on this site — Size is
                # derived from Brandline text (e.g. "...0.5L") in the cleaner.
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
            for category_slug, category_name in CATEGORIES.items():
                print(f"Scraping {RETAILER_SLUG}: {country} / {channel} / {category_name}")
                scraper = RegstaerVnukovoScraper(channel, category_slug, category_name)
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
                        print(f"  -> {category_name}: scraped {scraped_count} / site says {scraper.expected_count} [{flag}]")
                    else:
                        print(f"  -> {category_name}: scraped {scraped_count} / site total unknown")
                except Exception as e:
                    print(f"FAILURE scraping {country}/{channel}/{category_name}: {e}")

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
