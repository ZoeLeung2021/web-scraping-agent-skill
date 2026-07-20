"""
Scraper for Calle (Grænsebutik / border shop) — https://www.calle.dk/da-dk

DEPLOY TARGET: copy this file to GTR_Pricing/scrapers/calle_bordershop_scraper.py
once validated (this repo — web-scraping-agent-skill — is where retailer
outputs are drafted and reviewed).

CONFIRMED against the live rendered DOM (headless Chrome, real page_source):
  - GTR retailer: Calle is a Danish-facing "grænsebutik"/"grænsehandel"
    (border shop/border trade) chain — every product shows a savings
    comparison vs. Denmark's own excise tax ("Spar ift. Danmark 39%" —
    "Save vs. Denmark 39%"), the same cross-border tax-arbitrage pattern
    as Travel FREE Bordershop (CZ/HR/BG) built earlier this session.
    Market = "GTR".
  - Physical stores are actually all located in Germany (Süderlügum,
    Aventoft, Kruså, Padborg, Harrislee, Fehmarn/Burg, Heiligenhafen —
    positioned just across the German border to sell at Germany's lower
    excise rates to Danish/Swedish cross-border shoppers), even though the
    site's default customer-facing locale (da-dk, DKK pricing) targets
    Danish customers. Following the same precedent as Travel FREE
    Bordershop (Country = the country the physical stores are actually
    in, not the customer nationality the copy targets), Country =
    "Germany" here, "DF Germany" after the cleaner's GTR prefix. One
    unified catalog across all branches — no evidence found of per-branch
    price variation, modeled as a single "N/A" channel like other
    single-catalog multi-shop retailers in this repo (e.g. Silk Road Duty
    Free).
  - Only the da-dk (Danish, DKK) locale is scraped here — the site also
    has an sv-se (Swedish, EUR-priced) locale for the same physical
    catalog, confirmed to exist but deliberately out of scope for this
    build (a genuinely different customer-facing price/currency context,
    not more physical locations — revisit as a separate Channel if ever
    needed).
  - 4 real alcohol categories confirmed via the site's own nav:
    spiritus (spirits), vin (wine), oel (beer), cider.
  - Platform is a custom Tailwind-CSS-styled React-ish storefront (not
    WooCommerce/Shopify/Dynamicweb despite a legacy `/pl/*.aspx` URL
    pattern still being indexed) — no `__NEXT_DATA__`/`__NUXT__` state
    blob or per-product embedded JSON was found; unlike several other
    retailers built this session, this one has to be scraped from the
    rendered DOM text/classes directly.
  - Product cards are `<article>` elements inside
    `<ul class="grid ... grid-cols-product-grid ...">` — confirmed via a
    live sample. Each card:
      - Product_link + Brandline: `<a href="/da-dk/<slug>-<numericID>">
        <div title="...">...</div></a>` — the `title` attribute holds the
        clean, untruncated name (the visible text is `line-clamp-2`
        truncated in the DOM, the title attribute isn't), e.g. "Små Fugle
        16,4% 1 l." — brand+ABV%+size all bundled into one string, same
        convention as other single-title-field retailers this session.
      - Size: also shown as a small overlay badge on the product image
        (e.g. `<span class="absolute z-10 ... left-1 top-1 ...">1
        liter</span>`) — this scraper grabs it directly from that badge
        rather than relying only on the title-text fallback, since it's a
        cleaner, dedicated signal when present.
      - Price: unusually split into two separate DOM nodes for the whole
        number and the decimal cents (e.g. `<div class="text-2xl
        leading-none">59</div><div class="align-super">99</div>` under a
        shared `div.flex.gap-px.font-bold` parent) — joined here as
        "59.99" rather than left as two fragments. No `<del>`/strike-
        through markup was found anywhere on the category page — no
        discount concept to capture; Strike_Price and Price_Discounted
        are the same raw value.
  - Pagination is a real "Vis 30 produkter mere" ("Show 30 more products")
    button, confirmed to load 30 more cards per click (not inert like
    Attenza's broken button — this one genuinely works). The page also
    shows a real independent total via `<p>Du har set 30 af 911</p>`
    ("You have seen 30 of 911") — used here as a genuine coverage-
    validation total, and also as the loop's stopping condition alongside
    the button disappearing.
  - No GTR-exclusive badge/ribbon/"Eksklusiv" text found anywhere on the
    category page — left unset for every row so the cleaner emits a true
    null for the whole column.
  - No blocking age-verification gate found. A Cookiebot-style consent
    banner may render but doesn't block `page_source` parsing (same
    reasoning as Attenza's CookieModal earlier this session) — not
    dismissed since it isn't functionally necessary.
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

RETAILER_SLUG = "calle_bordershop"
BASE_URL = "https://www.calle.dk"
LOCALE = "da-dk"

# One unified catalog across all German branches — see module docstring.
LOCATIONS = {
    "Germany": ["N/A"],
}

CATEGORIES = ["spiritus", "vin", "oel", "cider"]

_TOTAL_RE = re.compile(r"Du har set\s+\d+\s+af\s+(\d+)", re.IGNORECASE)
_SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:liter|cl|ml|l)\b", re.IGNORECASE)


class CalleBordershopScraper:
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
        """Real, working "Vis 30 produkter mere" button — unlike
        Attenza's inert one, this genuinely loads 30 more cards per
        click. Stop once the button disappears (all loaded) or the
        site's own "Du har set X af Y" counter reaches Y."""
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

            # No GTR-exclusive concept found anywhere on this site — see
            # module docstring. Deliberately not set here.

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
                scraper = CalleBordershopScraper(channel, category)
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
