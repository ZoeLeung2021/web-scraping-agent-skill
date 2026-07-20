"""
Scraper for King's (Suriname) — https://www.kings.sr/

Site brand name is "Kings Drankenpaleis" ("Kings Drinks Palace"),
corporate entity "King's Enterprises N.V." — a Suriname domestic general
retailer (drinks, fashion, food, perfume, tobacco, etc.), not just a
liquor store, but alcohol is a real, large part of its catalog.

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/kings_suriname_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source,
no text-extraction proxy used for this build):
  - NOT duty-free/travel-retail. Default site language is Dutch (Suriname's
    official language) — "Welkom op onze nieuwe webshop!", "Inloggen"
    (Log in), prices tagged "(Excl. BTW)" (BTW = Dutch VAT). Checked the
    full homepage text for "duty free," "vrijhaven" (Dutch "free port"),
    and "douane" (Dutch "customs") — zero matches anywhere. Currency SRD
    (Surinamese Dollar). Market = "Domestic", Country = "Suriname" (no
    "DF " prefix), single "N/A" channel (one online catalog, no branch/
    location split found anywhere on the site).
  - Platform: a custom Next.js frontend (Mantine UI component library —
    confirmed via `mantine-*` class names on the pagination and filter
    accordion) backed by a **headless WordPress** instance at
    `admin.kings.tad.sr` (product image URLs are plain `wp-content/
    uploads/...` paths) — built by a local Suriname agency, "TAD"
    (`https://www.tad.sr`, credited in the footer). Not WooCommerce
    storefront markup on the customer-facing side despite the WordPress
    backend — this is a decoupled/headless setup, so none of the usual
    WooCommerce CSS classes apply; every selector below was derived from
    scratch against the real rendered cards.
  - Category taxonomy CHECKED for the same nested/overlapping-dimension
    trap confirmed on i-d-s.com before picking categories, per this
    build's brief. Real finding: King's "Beverages" master category
    (`?category=beverage`, "1012 resultaten") is a CLEAN, EXHAUSTIVE
    PARTITION into 20 mutually-exclusive leaf subcategories — confirmed
    by summing every leaf category's own "X resultaten" count live:
    aguardente(1)+beer(20)+bitter(5)+champagne(37)+cocktail(11)+
    cognac(63)+gin(29)+jenever(16)+liqueur(86)+malt-whisky(82)+
    non-alcoholic(14)+port(5)+rum(131)+sparkling(20)+spirit(4)+
    tequila(47)+vermouth(5)+vodka(124)+whisky(139)+wines(173) = exactly
    1012, matching the parent's own count exactly. No overlap, no
    duplication risk — unlike i-d-s.com's Wine (Type/Country/Region/
    Variety all cross-tagging), unlike GMP Abu Dhabi's beer categories
    (two genuinely overlapping parents). This means every leaf category
    can be looped independently with NO cross-category SKU dedup needed
    for correctness (the cleaner's existing dedup logic still runs
    defensively, but isn't papering over a real duplication problem
    here).
  - CATEGORIES = the 19 leaf slugs above MINUS "non-alcoholic" (a real
    beverage subcategory but not alcohol — out of scope per this skill's
    alcohol-only rule). "Cocktail" and "Spirit" are kept (pre-mixed
    alcoholic cocktails / a generic spirits bucket, both genuinely
    alcoholic per their product listings, e.g. "Spirit" contains RTD
    spirit-based drinks). Total alcohol-relevant expected: 1012 - 14
    (non-alcoholic) = 998 across 19 categories.
  - Product cards are `<div class="relative h-full">` (12 per page) —
    confirmed via a live 12-card sample on the Whisky category. Each
    card:
      - Product_link + ID: the card's inner `<a href="/products/<slug>
        ?variation=<ID>">` — e.g. "/products/100-pipers-75cl?variation=
        11291-DO". The `variation` query param (e.g. "11291-DO",
        "11409-FL") is the real, stable per-SKU/variant identifier used
        directly as ID_raw — the alphabetic suffix (DO/FL/BO, etc.
        confirmed to vary) looks like a pack-type/unit code, kept as
        part of the ID rather than stripped, since it's what makes two
        otherwise-identical product-link slugs resolve to distinct SKUs.
      - Brandline: `<h4 class="mb-4 font-medium leading-snug">` — e.g.
        "100 PIPERS 75CL", "BALLANTINE'S 12 YO 1L" — brand+size bundled
        into one string, same convention as most other single-title-
        field retailers built this session. Brand is left null.
      - Price: `<span class="font-bold mr-1">SRD 7.360,50</span>` next
        to a `(Excl. BTW)` note — European decimal-comma format (dot for
        thousands, comma for decimals). No `<del>`/strike-through/second-
        price markup found anywhere (checked 48 cards across 4 different
        categories — whisky/rum/wines/vodka — for `<del>`, `line-
        through`, and any card rendering more than one `span.font-bold`
        price node; zero found) — no discount concept to capture here,
        Strike_Price and Price_Discounted are the same raw value.
      - GTR_exclusive: checked the same 48-card sample for any
        "exclusi*"-containing text/badge — zero matches, no ribbon/tag
        overlay of any kind on any card. True null case (this domestic
        retailer never signals product-exclusivity at all) — left unset
        for every row.
  - Pagination: real numbered pages via a Mantine `<button>` pagination
    component (JS-driven, `<button>` elements, not `<a href>` links).
    **IMPORTANT, found the hard way during testing**: a direct URL
    navigation to `?category=whisky&page=2` does NOT actually work
    despite looking like it should — the app's pagination state lives in
    client-side React state, not the URL, so a fresh `driver.get()` to a
    `page=N` URL silently re-renders page 1's content every time (the
    `page` query param is cosmetic/ignored on load). First-pass testing
    that used direct URL navigation scraped 144 "items" for a category
    the site itself reports as 139 — but only 12 unique IDs, proving it
    was re-scraping the same page-1 content 12 times rather than
    advancing. The only reliable way to advance pages is clicking the
    real pagination button: Mantine renders pagination as `[first(disabled
    on pg1), previous(disabled on pg1), ...page-number buttons..., a
    "dots" placeholder if truncated, next, last]` — confirmed live via
    the exact `disabled`/`aria-disabled`/`data-active`/`data-dots`
    attributes on each button. The reliable "next" button is the
    second-to-last `button.mantine-Pagination-item` in DOM order (the
    last one is "jump to last page"); it gains `disabled`/`aria-disabled=
    "true"` once on the final page, which is what this scraper uses as
    its stopping condition alongside the expected-count check. The
    category page also displays a real, independent total via Dutch
    "X resultaten" ("X results") text next to the category filter list —
    used here as `get_expected_item_count()` real coverage validation,
    and as the signal that first caught the click-vs-URL pagination bug
    above (a 144-vs-139 mismatch that a naive "trust whichever number
    you got" read would have missed).
  - Age gate: a real, dismissible modal ("Hierbij verklaar ik ouder te
    zijn dan 18 jaar" — "I hereby declare I am older than 18 years" — with
    "JA, DOORGAAN" / "NEE, TERUG" buttons). Dismissed via a real click on
    the "JA, DOORGAAN" button; confirmed necessary (page content behind
    it wasn't tested without dismissal, dismissed defensively like every
    other age-gated retailer in this repo).
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

RETAILER_SLUG = "kings_suriname"
BASE_URL = "https://www.kings.sr"

# Single unified online catalog, no branch/location split found.
LOCATIONS = {
    "Suriname": ["N/A"],
}

# 19 real alcohol leaf categories — "beverage" (the parent) is a clean,
# non-overlapping partition into these 20 leaves plus "non-alcoholic"
# (excluded, not alcohol). See module docstring for the exact sum-match
# confirmation.
CATEGORIES = [
    "aguardente", "beer", "bitter", "champagne", "cocktail", "cognac",
    "gin", "jenever", "liqueur", "malt-whisky", "port", "rum",
    "sparkling", "spirit", "tequila", "vermouth", "vodka", "whisky",
    "wines",
]

_RESULT_COUNT_RE = re.compile(r"(\d+)\s*resultaten", re.IGNORECASE)


class KingsSurinameScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        return f"{BASE_URL}/shop?category={self.category}"

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
            self.driver.get(f"{BASE_URL}/")
        except Exception:
            pass
        time.sleep(5)

    def dismiss_age_gate(self):
        btn = self.driver.find_element(
            By.XPATH, "//button[contains(., 'JA') or contains(., 'DOORGAAN')]"
        )
        self.driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)

    def get_expected_item_count(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        match = _RESULT_COUNT_RE.search(soup.get_text())
        return int(match.group(1)) if match else None

    def click_next_page(self):
        """The real "next" button is the second-to-last
        button.mantine-Pagination-item in DOM order — see module
        docstring for why direct ?page=N URL navigation doesn't work.
        Returns False (nothing clicked) once on the final page, where
        this button carries disabled/aria-disabled="true"."""
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.mantine-Pagination-item")
        if len(buttons) < 2:
            return False
        next_btn = buttons[-2]
        if next_btn.get_attribute("disabled") is not None or next_btn.get_attribute("aria-disabled") == "true":
            return False
        self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", next_btn)
        return True

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        cards = [d for d in soup.find_all("div", recursive=True) if d.get("class") == ["relative", "h-full"]]

        for card in cards:
            product_dict = {}
            try:
                link_el = card.find("a", href=lambda h: h and "/products/" in h)
                href = link_el["href"] if link_el else None
                product_dict["Product_link"] = BASE_URL + href if href else None
                id_match = re.search(r"variation=([\w-]+)", href or "")
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None
                product_dict["ID_raw"] = None

            try:
                title_el = card.find("h4")
                product_dict["Brandline"] = title_el.get_text(strip=True) if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                price_el = card.select_one("span.font-bold")
                price_text = price_el.get_text(strip=True) if price_el else None
                product_dict["Strike Price"] = price_text
                product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive/exclusivity badge or text found anywhere on
            # this site — see module docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self, max_pages=100):
        try:
            self.open_website()
            try:
                self.dismiss_age_gate()
            except (NoSuchElementException, ElementNotInteractableException):
                pass
            try:
                self.driver.get(self.get_url())
            except Exception:
                pass
            time.sleep(4)
            self.expected_count = self.get_expected_item_count()
            self.get_main()
            seen_count = len(self.product_dicts)
            pages_clicked = 1
            while pages_clicked < max_pages and (
                self.expected_count is None or seen_count < self.expected_count
            ):
                clicked = self.click_next_page()
                if not clicked:
                    break
                time.sleep(3)
                before = len(self.product_dicts)
                self.get_main()
                added = len(self.product_dicts) - before
                pages_clicked += 1
                if added == 0:
                    # clicked but the DOM didn't change — stop rather
                    # than loop forever appending nothing new.
                    break
                seen_count += added
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
                scraper = KingsSurinameScraper(channel, category)
                try:
                    scraper.run_all()
                    for item in scraper.product_dicts:
                        item["Country"] = country
                        item["Channel"] = channel
                        item["Category"] = category
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
