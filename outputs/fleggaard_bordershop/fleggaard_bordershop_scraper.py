"""
Scraper for Fleggaard (Grænsebutik / border shop) — https://www.fleggaard.dk/da-dk

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/fleggaard_bordershop_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source,
not the HTML-stripping proxy used for preliminary research — every fact
below was re-checked against the actual page):
  - GTR retailer: Fleggaard is a Danish-facing "grænsehandel" (border
    trade) chain — homepage/category titles read "Køb spiritus - Altid
    lav pris hos Fleggaard" ("Buy spirits - Always low price at
    Fleggaard"), and individual product cards show a genuine per-product
    "Spar ift. Danmark <N>%" ("Save vs. Denmark <N>%") link/badge (e.g.
    "36%", "32%" confirmed on live cards) — the same cross-border
    tax-arbitrage pattern as Calle (calle_bordershop_scraper.py, built
    earlier this session) and Travel FREE Bordershop (CZ/HR/BG). Market =
    "GTR".
  - Physical stores are all in Germany near the Danish border (Harrislee,
    Padborg, Süderlügum, Aventoft, Burg, etc. — confirmed via footer nav
    links "Butikker og åbningstider" / store-locator copy), even though
    the scraped locale (da-dk, DKK pricing) targets Danish customers.
    Following the same Calle/Travel FREE Bordershop precedent (Country =
    where the physical stores actually are, not the customer nationality
    the copy targets), Country = "Germany" here, "DF Germany" after the
    cleaner's GTR prefix. One unified online catalog — no store-specific
    price variation found on the listing page (only a stock-status line
    per card, e.g. "Click&Collect - på lager" / "På lager i de fleste
    butikker" — stock availability text, not a price difference); modeled
    as a single "N/A" channel, same as Calle.
  - Only the da-dk (Danish, DKK) locale is scraped here — an sv-se
    (Swedish) locale also exists per robots.txt checkout paths, mirroring
    Calle's da-dk/sv-se split, and is deliberately out of scope for this
    build for the same reason Calle's sv-se was skipped (a different
    customer-facing price/currency context, not more physical locations).
  - 3 real alcohol categories confirmed live, with the site's own "Du har
    set X af Y" totals matching the preliminary research exactly:
    spiritus (915), vin (644), oel (152, cider lives inside oel as a
    subcategory/facet — confirmed no separate cider top-level category
    exists, so it is NOT looped separately here, unlike Calle which has
    a standalone cider category).
  - Platform: same underlying storefront template family as Calle (both
    render `<ul class="grid ... grid-cols-product-grid ...">` of
    `<article>` cards with an identical whole/decimal split price
    structure) but is NOT the identical codebase — Fleggaard's cards
    additionally expose colored corner badges (see below) that weren't
    present on Calle's cards. No `__NEXT_DATA__`/JSON-LD product blob
    was used; scraped from rendered DOM directly, same as Calle.
  - Product cards are `<article>` elements inside
    `<ul class="grid w-full grid-cols-product-grid gap-2 md:gap-4">` —
    confirmed via a live sample (30 cards on initial load, matching the
    "Vis 30 produkter mere" increment). Each card:
      - Product_link + ID: `<a href="/da-dk/<slug>-<numericID>">` e.g.
        "/da-dk/primakov-vodka-375-07-l-500024930" -> ID "500024930"
        (a run of digits at the end of the slug, same convention as
        Calle).
      - Brandline: a second `<a>` wraps a `<div title="...">` holding the
        clean, untruncated name (visible text is `line-clamp-2`
        truncated, the title attribute isn't), e.g. "Primakov Vodka
        37,5% 0,7 l." — brand+ABV%+size bundled into one string, same
        convention as Calle.
      - Size: sometimes shown as its own small overlay badge on the
        image (e.g. `<span class="... bottom-1 left-1 bg-grey-500 ...
        text-xs">1 liter</span>`) — confirmed present on at least one
        live card. This scraper scans all badge-style spans on the card
        and returns the first one that looks like a size (reusing the
        same size regex as Calle), since the badge position/side (left
        vs. right, top vs. bottom) varies per card depending on which
        other badges are also present.
      - Price: same unusual whole-number/decimal-cents split as Calle
        (`<div class="text-2xl leading-none">49</div><div
        class="align-super">99</div>` under a shared
        `div.flex.gap-px.font-bold` parent) — joined here as "49.99".
        No `<del>`/strikethrough/before-price markup was found on any
        sampled card (checked specifically for "før-pris"/`<del>`/
        `line-through` — zero matches across 30 cards); the "Spar ift.
        Danmark N%" badge is a comparison against a hypothetical Danish
        retail price, not an internal Fleggaard discount, so it is not
        captured as a Strike_Price. Strike_Price and Price_Discounted
        are the same raw value.
  - Colored corner badges confirmed live and enumerated across a 30-card
    sample: "Avisvare" (flyer/advertised item), "Nyhed" (new), "Kassesalg"
    (checkout/till sale) — matches the preliminary research's proxied
    list. None of these say anything resembling "Eksklusiv"/"exclusive"/
    "travel"/"kun hos Fleggaard" ("only at Fleggaard") — checked the full
    page text for "eksklusiv" and "kun hos", zero matches — and there is
    no separate "Exclusives" nav category either. This is the null case,
    not the "No" case: the site never signals GTR-exclusivity anywhere,
    so GTR_exclusive is left unset for every row, same as Calle.
  - Pagination is a real "Vis 30 produkter mere" ("Show 30 more
    products") button — same working mechanism as Calle (confirmed, not
    assumed from the proxy). The page also shows a real independent total
    via "Du har set 30 af 915" ("You have seen 30 of 915") on spiritus —
    used here as a genuine coverage-validation total and as the loop's
    stopping condition, same as Calle.
  - No blocking age-verification gate found on any category, including
    oel/beer (checked specifically per the preliminary research's open
    question — no age-gate CSS class, no "18 år"/"fyldt 18" text found).
    "Alder" only appears as a footer nav link ("Aldersgrænser" / "Age
    limits" info page), not an interactive gate. A Cookiebot-style
    consent banner may render but doesn't block `page_source` parsing.
"""

import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from databricks.sdk import WorkspaceClient
import json
import io

RETAILER_SLUG = "fleggaard_bordershop"
BASE_URL = "https://www.fleggaard.dk"
LOCALE = "da-dk"

# One unified catalog across all German branches — see module docstring.
LOCATIONS = {
    "Germany": ["N/A"],
}

# cider lives inside oel as a subcategory on this site — no standalone
# cider category exists, unlike Calle. See module docstring.
CATEGORIES = ["spiritus", "vin", "oel"]

_TOTAL_RE = re.compile(r"Du har set\s+\d+\s+af\s+(\d+)", re.IGNORECASE)
_SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:liter|cl|ml|l)\b", re.IGNORECASE)


class FleggaardBordershopScraper:
    def __init__(self, location, category):
        self.location = location
        self.category = category
        self.product_dicts = []
        self.expected_count = None

    def get_url(self):
        self.url = f"{BASE_URL}/{LOCALE}/{self.category}"

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
        self.get_url()
        try:
            self.driver.get(self.url)
        except Exception:
            pass
        time.sleep(6)

    def get_expected_item_count(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        text = soup.get_text()
        match = _TOTAL_RE.search(text)
        return int(match.group(1)) if match else None

    def paginate_or_scroll(self, max_clicks=60):
        """Real, working "Vis 30 produkter mere" button — same genuine
        load-more mechanism as Calle. Stop once the button disappears
        (all loaded) or the site's own "Du har set X af Y" counter
        reaches Y."""
        for _ in range(max_clicks):
            if self.expected_count is not None:
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                seen_match = re.search(r"Du har set\s+(\d+)\s+af", soup.get_text())
                if seen_match and int(seen_match.group(1)) >= self.expected_count:
                    break
            clicked = False
            for _attempt in range(3):
                try:
                    btn = self.driver.find_element(
                        By.XPATH, "//button[contains(., 'Vis') and contains(., 'mere')]"
                    )
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView(true); arguments[0].click();", btn
                    )
                    clicked = True
                    break
                except (NoSuchElementException, StaleElementReferenceException):
                    time.sleep(1)
            if not clicked:
                break
            time.sleep(2)

    def _extract_size(self, card):
        """Scans every badge-style span on the card for a size-looking
        string. Position varies (left/right, top/bottom) depending on
        which other promo badges (Avisvare/Nyhed/Kassesalg) are also
        present, so this doesn't key off a single fixed selector."""
        for span in card.find_all("span"):
            text = span.get_text(strip=True)
            if _SIZE_RE.match(text):
                return text
        return None

    def get_main(self):
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        grid = soup.find("ul", class_=lambda c: c and "grid-cols-product-grid" in c)
        cards = grid.find_all("article") if grid else []

        for card in cards:
            product_dict = {}
            try:
                link_el = card.find("a", href=True)
                href = link_el["href"] if link_el else None
                product_dict["Product_link"] = BASE_URL + href if href else None
                id_match = re.search(r"-(\d+)$", href or "")
                product_dict["ID_raw"] = id_match.group(1) if id_match else None
            except (AttributeError, TypeError):
                product_dict["Product_link"] = None
                product_dict["ID_raw"] = None

            try:
                title_el = card.find("div", title=True)
                product_dict["Brandline"] = title_el["title"] if title_el else None
                product_dict["Brand"] = None
            except (AttributeError, TypeError):
                product_dict["Brandline"] = None
                product_dict["Brand"] = None

            try:
                product_dict["Size"] = self._extract_size(card)
            except (AttributeError, TypeError):
                product_dict["Size"] = None

            try:
                price_container = card.find("div", class_=lambda c: c and "font-bold" in c and "gap-px" in c)
                whole = price_container.find("div", class_=lambda c: c and "text-2xl" in c) if price_container else None
                decimal = price_container.find("div", class_=lambda c: c and "align-super" in c) if price_container else None
                if whole and decimal:
                    price_text = f"{whole.get_text(strip=True)}.{decimal.get_text(strip=True)}"
                else:
                    price_text = None
                product_dict["Strike Price"] = price_text
                product_dict["Price Discounted"] = price_text
            except (AttributeError, TypeError):
                product_dict["Strike Price"] = None
                product_dict["Price Discounted"] = None

            # No GTR-exclusive badge/ribbon/"Eksklusiv"/"kun hos Fleggaard"
            # text found anywhere on the category page — see module
            # docstring. Deliberately not set here.

            self.product_dicts.append(product_dict)

    def run_all(self):
        try:
            self.open_website()
            self.expected_count = self.get_expected_item_count()
            self.paginate_or_scroll()
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
                scraper = FleggaardBordershopScraper(channel, category)
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
