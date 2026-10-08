"""
Scraper for Adanione (Mumbai International Airport duty free) — Arrival store
https://www.adanione.com/csmia-mumbai-airport/duty-free/liquor?location=arrival

DEPLOY TARGET: copy this file to
GTR_Pricing/scrapers/adanione_scraper.py once validated (this repo —
web-scraping-agent-skill — is where retailer outputs are drafted and
reviewed).

CONFIRMED against the live rendered site on 2026-10-01 (Selenium +
undetected_chromedriver; plain HTTP clients get nothing back):

  - Operator/brand: Adani One is the Adani Airports super-app; this is its
    duty-free pre-order storefront for Chhatrapati Shivaji Maharaj
    International Airport, Mumbai (BOM). The site's own SEO title says
    "Pre-Order Premium Liquor Online at Mumbai Duty Free ... at Mumbai
    Airport", and the header says "Pre-order Collect at Mumbai Terminal 2".
    Genuinely GTR (duty-free). No existing Mumbai/Adani scraper exists in
    GTR_Pricing. Retailer "Adanione" and Channel "Mumbai International
    Airport (BOM)" were user-confirmed on 2026-10-01 and are set in the
    cleaner.
  - Arrival only. The ?location= query param sets localStorage storeType,
    and every product record in the listing API carries storeType "Arrival"
    (store code MDFS01). The Departure store is separate but out of scope
    (user-confirmed 2026-10-01), so it is not scraped. Note that the
    header text still reads "Terminal 2, Departure" even when the arrival
    store is active. That text is a static default label, NOT the active
    store. Verified via the API's storeType field, which is what matters.
  - Bot protection: Akamai Bot Manager (edgekey CDN). curl/WebFetch hang
    with no response, and stock headless Chrome gets ERR_HTTP2_PROTOCOL_
    ERROR. What works: overriding the "HeadlessChrome" user-agent with a
    normal desktop Chrome UA (Linux, version taken from the running
    browser), plus a homepage visit first so the Akamai cookies (_abck,
    bm_sz, ak_bmsc) are set before the listing request. No display is
    needed: everything runs with --headless=new, as in the etl-scrapers
    Docker image.
  - Platform: Next.js App Router (CSS-module class names like
    listing_card_column__3yJtN, self.__next_f RSC payload) on a Sitecore
    JSS backend. The first 16 products are server-rendered into the RSC
    payload (ProductListServerData.productList). The rest load via
    infinite scroll, 16 at a time, from
    POST /api/dutyfreeservicev2/api/DutyFree/GetListingSKUByFilterV1. That
    response's data.count is the site's own total (353 on 2026-10-01), used
    as the ground-truth count in get_expected_item_count().
  - Scope: /duty-free/liquor is already an alcohol-only listing (API
    materialGroup = "liquor" for every row: whisky, vodka, gin, tequila,
    wine, rum, liqueur, brandy, champagne, plus a single "cocktail-mixers"
    SKU that is Aperol Spritz, which is alcoholic, so it's kept). One
    category pass, so there is no nested-taxonomy overlap risk.

FIELD SOURCES:
  - ID_raw: the last path segment of each listing card's product link, as
    specified by the requester. E.g. in
      <div class="col-6 col-md-4 col-lg-3 listing_card_column__3yJtN ...">
        <div class="prod-card listing_product_card__BQMGJ card">
          <a href="/csmia-mumbai-airport/duty-free/p/ardmore-triplewood-100cl/02N03220">
    the ID is "02N03220". It is the same value as the API's skuCode, which
    is how the card is joined to its JSON record below. Note: IDs are
    alphanumeric, not numeric, and one live SKU even has a letter O where a
    zero is expected ("02NO2092"), so treat them as opaque strings.
  - Product_link, Brandline (card title), Strike Price, Price Discounted:
    read from the rendered card DOM. The card has two price layouts:
      a) "Pre-order at" block, for SKUs with a pre-order discount:
         <p class="pre-order-price-formate"><span class="line-through">₹8,000
         </span>₹4,680<span class="offbox-percentage">41% OFF</span></p>
      b) plain <aside>: optional <p class="line-through"> (strike) plus
         <span class="final-price-content"> (selling price)
    The displayed selling price was verified against the API for all 337
    API-backed cards (337/337 exact). It equals preOrderDiscountPrice if
    that is > 0, else skuDiscountPrice if > 0, else unitPrice. Strike equals
    unitPrice whenever it is above the selling price. If a card's DOM price
    can't be read, the same rule is applied to the JSON record as a
    fallback.
  - Brand: the API's brand field, a lowercase slug ("royal-salute",
    "jack-daniel-s"). It is sometimes an owner/importer slug instead of the
    real brand ("moet-hennessy" on Ardbeg, "gran-cru-club-private-limited"
    on Bordeaux wines) or misspelled ("avitation"). It is landed raw here
    and resolved against the product name in the cleaner.
  - Size: the API's unitSize ("700 ml", "1 ltr", "1.75 ltr"). Twin packs
    report their total pack volume ("2 ltr" for 2x1L), which matches the
    pack price.
  - GTR_exclusive: the API's isExclusive boolean. It is a real per-product
    concept on this site: 9 of 337 SKUs were flagged on 2026-10-01, all
    recognisable travel-retail exclusives (Macallan GTR 15 Yo, Hibiki
    Master's Select, Johnnie Walker XR 21, Glenfiddich 18 VAT 4, ...). The
    listing cards show NO visual badge for these, so the API flag is the
    only signal. Emitted as "Exclusive" or blank "" (never None), so the
    cleaner maps it to Yes/No. Unrelated to the nav's "Online Exclusive
    Offers" link, which is a promotions page, not a product attribute.

INFINITE SCROLL ALONE IS NOT COMPLETE on this site. The scroll API pages
with sort="discount", and discount ties make the server's order shift
between page requests. On one live run SKU 02N03753 came back on two pages
and another SKU was silently skipped: 353 cards, but only 352 unique. So
after scrolling, reconcile_with_api() replays the page's own captured
listing request (same headers, from inside the page) in 100-row pages,
unioning up to three sort orders until the unique total reaches data.count.
Any SKU it finds without a card becomes a row built from its JSON record,
using the same link format, so the ID still comes from the link.
Validated 2026-10-01: a full run gave 353/353 unique. A run with scrolling
disabled also reached 353/353, with the reconcile step adding 321, and those
JSON-built rows matched the card-built rows field for field. Re-validated
2026-10-02 after the version-matched UA change: the site's count was now 339,
and the run gave 339/339. With scrolling disabled, the reconcile step added
307 to reach 339/339, again with zero field differences.

JSON records come from three places: the RSC payload (first 16), the
infinite-scroll responses captured by a fetch/XHR hook (installed with CDP
Page.addScriptToEvaluateOnNewDocument before the listing loads), and the
reconcile sweep.
"""

import io
import json
import os
import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from databricks.sdk import WorkspaceClient

RETAILER_SLUG = "adanione"

BASE_URL = "https://www.adanione.com"
AIRPORT_PATH = "csmia-mumbai-airport"

# Country -> store. The store value is the site's own ?location= value and is
# mapped to the Channel label in the cleaner (CHANNEL_LABELS). Arrival only.
LOCATIONS = {
    "India": ["arrival"],
}

# /duty-free/liquor is already an alcohol-only listing (see docstring).
CATEGORIES = ["liquor"]

# HeadlessChrome's default UA is rejected by Akamai, so present as desktop
# Chrome. The version is filled in from the browser that's actually running,
# because the etl-scrapers image installs the current Chrome stable and a
# stale hardcoded version would drift further from the real one each update.
# Keep the Windows platform: a Linux UA was tested on 2026-10-02 and Akamai
# blocked the listing API every time (16/353, reproduced twice), while the
# Windows UA got through in the same session.
USER_AGENT_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
)

# Records every GetListingSKUByFilter response the page itself makes during
# infinite scroll, so get_main() can join each card to its JSON record.
LISTING_API_HOOK = r"""
(function () {
  window.__adaniPages = [];
  window.__adaniCount = null;
  function record(url, text) {
    if (!url || String(url).indexOf('GetListingSKUByFilter') === -1) return;
    try {
      var j = JSON.parse(text);
      if (j && j.data) {
        window.__adaniPages.push(j.data.result || []);
        if (j.data.count !== null && j.data.count !== undefined) window.__adaniCount = j.data.count;
      }
    } catch (e) {}
  }
  // First listing request {url, body, headers}, replayed by
  // reconcile_with_api(). Captured from fetch(url, init), fetch(Request) or
  // XHR, whichever the site uses. Headers are kept as a plain object.
  window.__adaniRequest = null;
  function isListing(url) { return url && String(url).indexOf('GetListingSKUByFilter') !== -1; }
  function plainHeaders(h) {
    var out = {};
    try {
      if (h && typeof h.forEach === 'function' && !Array.isArray(h)) { h.forEach(function (v, k) { out[k] = v; }); }
      else if (Array.isArray(h)) { h.forEach(function (p) { out[p[0]] = p[1]; }); }
      else if (h) { for (var k in h) { out[k] = h[k]; } }
    } catch (e) {}
    return out;
  }
  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function () {
      var a = arguments[0];
      var init = arguments[1];
      var url = (a && a.url) ? a.url : String(a);
      try {
        if (!window.__adaniRequest && isListing(url)) {
          if (init && init.body) {
            window.__adaniRequest = {url: url, body: String(init.body), headers: plainHeaders(init.headers)};
          } else if (a && typeof a.clone === 'function') {
            var hdrs = plainHeaders(a.headers);
            a.clone().text().then(function (b) {
              if (!window.__adaniRequest && b) window.__adaniRequest = {url: url, body: b, headers: hdrs};
            });
          }
        }
      } catch (e) {}
      return origFetch.apply(this, arguments).then(function (resp) {
        try { resp.clone().text().then(function (t) { record(url, t); }); } catch (e) {}
        return resp;
      });
    };
  }
  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__adaniUrl = url;
    this.__adaniHeaders = {};
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    try { this.__adaniHeaders[k] = v; } catch (e) {}
    return origSetHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    try {
      if (!window.__adaniRequest && isListing(this.__adaniUrl) && body) {
        window.__adaniRequest = {url: String(this.__adaniUrl), body: String(body), headers: this.__adaniHeaders || {}};
      }
    } catch (e) {}
    this.addEventListener('load', function () {
      try { record(this.__adaniUrl, this.responseText); } catch (e) {}
    });
    return origSend.apply(this, arguments);
  };
})();
"""

# Replays the page's own captured listing request with a different sort/page/
# size, from inside the page (same Akamai session and API headers).
REPLAY_LISTING_JS = r"""
var done = arguments[arguments.length - 1];
var req = window.__adaniRequest;
if (!req) { done({error: 'no listing request captured'}); return; }
var body = JSON.parse(req.body);
body.sort = arguments[0]; body.page = arguments[1]; body.size = arguments[2];
fetch(req.url, {method: 'POST', headers: req.headers, body: JSON.stringify(body)})
  .then(function (r) { return r.text().then(function (t) { done({status: r.status, text: t}); }); })
  .catch(function (e) { done({error: 'fetch failed: ' + e}); });
"""

# The API returns 0 rows for size=400. 100 is confirmed to work.
SWEEP_PAGE_SIZE = 100
# Sort keys from the site's own sort menu. The infinite scroll uses
# "discount", which has many ties and so isn't a stable order between page
# requests. Unioning several orders recovers anything one order skipped.
SWEEP_SORTS = ["discount", "pricehl", "pricelh"]

CARD_SELECTOR = 'div[class*="listing_card_column"]'


def _rupees_to_str(text):
    """'₹3,26,700' -> '326700'. Raw string only; the cleaner casts to float."""
    if not text:
        return None
    digits = re.sub(r"[^\d.]", "", text)
    return digits or None


class AdanioneScraper:

    def __init__(self, location, category):
        self.location = location  # "arrival" (site's own ?location= value)
        self.category = category  # "liquor"
        self.product_dicts = []
        self.expected_count = None  # site's own data.count, for validation only

    def get_url(self):
        self.url = f"{BASE_URL}/{AIRPORT_PATH}/duty-free/{self.category}?location={self.location}"

    def open_website(self):
        options = uc.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1400,1000")
        chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
        driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

        self.driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_bin,
            driver_executable_path=driver_path,
        )
        self.driver.set_page_load_timeout(90)

        major = str(self.driver.capabilities.get("browserVersion", "")).split(".")[0] or "140"
        self.driver.execute_cdp_cmd(
            "Network.setUserAgentOverride", {"userAgent": USER_AGENT_TEMPLATE.format(major=major)}
        )

        # Homepage first so Akamai's sensor cookies are set before the listing
        # request; going straight to the listing gets ERR_HTTP2_PROTOCOL_ERROR.
        self.driver.get(f"{BASE_URL}/")
        time.sleep(6)

        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": LISTING_API_HOOK}
        )
        self.get_url()
        self.driver.get(self.url)
        time.sleep(12)

    def verify_store(self):
        """Fails loudly if the site didn't switch to the requested store,
        rather than silently landing the other store's prices under this
        Channel. localStorage storeType is what drives the listing API."""
        store = self.driver.execute_script("return window.localStorage.getItem('storeType')")
        if (store or "").lower() != self.location:
            raise RuntimeError(f"Expected storeType '{self.location}', site is on '{store}'")

    def _card_count(self):
        return len(self.driver.find_elements("css selector", CARD_SELECTOR))

    def get_expected_item_count(self):
        """data.count from the first infinite-scroll API response. It's only
        known once the first scroll has fired one, so this is called after
        paginate_or_scroll(). Returns None if no response was captured."""
        try:
            count = self.driver.execute_script("return window.__adaniCount")
            return int(count) if count is not None else None
        except Exception:
            return None

    def paginate_or_scroll(self):
        """Infinite scroll, 16 products per batch. Stops once the card count
        reaches the site's own total, or after 4 scrolls with no new cards
        (end of list, or the site stopped responding)."""
        last = self._card_count()
        stalled = 0
        for _ in range(200):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            now = self._card_count()
            expected = self.get_expected_item_count()
            if expected is not None and now >= expected:
                break
            stalled = stalled + 1 if now == last else 0
            if stalled >= 4:
                break
            last = now

    def reconcile_with_api(self):
        """Infinite scroll is not a complete list on this site. The scroll
        API pages with sort="discount", whose many ties make the server's
        order shift between requests. One live run got SKU 02N03753 on two
        pages and silently skipped another SKU: 353 cards, 352 unique.

        Re-reads the full listing in a few 100-row pages per sort order,
        stopping once the union of unique skuCodes reaches the site's
        count. Returns skuCode -> record."""
        self.driver.set_script_timeout(60)
        expected = self.get_expected_item_count()
        swept = {}
        for sort in SWEEP_SORTS:
            page = 1
            while True:
                reply = self.driver.execute_async_script(REPLAY_LISTING_JS, sort, page, SWEEP_PAGE_SIZE) or {}
                if reply.get("error"):
                    print(f"  WARNING: couldn't replay listing API ({reply['error']}); relying on scroll only")
                    return swept
                try:
                    data = json.loads(reply.get("text") or "").get("data") or {}
                except (ValueError, AttributeError):
                    print(f"  WARNING: listing API replay returned HTTP {reply.get('status')} with no JSON "
                          f"(sort={sort}, page={page}); trying the next sort order")
                    break
                result = data.get("result") or []
                for rec in result:
                    if isinstance(rec, dict) and rec.get("skuCode"):
                        swept[rec["skuCode"]] = rec
                if len(result) < SWEEP_PAGE_SIZE:
                    break
                page += 1
                time.sleep(1)
            if expected is not None and len(swept) >= expected:
                break
        return swept

    def _json_records(self, page_html):
        """skuCode -> product record, from the SSR RSC payload (first 16)
        plus every captured infinite-scroll API response."""
        records = {}

        # The RSC payload is a series of self.__next_f.push([1,"<json-escaped
        # string>"]) script chunks. Unescape and concatenate them, then pull
        # out the server-rendered productList array.
        soup = BeautifulSoup(page_html, "html.parser")
        rsc = []
        for script in soup.find_all("script"):
            text = script.string or ""
            for m in re.finditer(r'self\.__next_f\.push\(\[1,"(.*)"\]\)', text, flags=re.S):
                try:
                    rsc.append(json.loads('"' + m.group(1) + '"'))
                except ValueError:
                    pass
        rsc = "".join(rsc)
        start = rsc.find('"productList":[')
        if start != -1:
            try:
                product_list, _ = json.JSONDecoder().raw_decode(rsc, start + len('"productList":'))
                for rec in product_list:
                    if isinstance(rec, dict) and rec.get("skuCode"):
                        records[rec["skuCode"]] = rec
            except ValueError:
                print("WARNING: couldn't parse server-rendered productList from RSC payload")

        try:
            pages = self.driver.execute_script("return window.__adaniPages") or []
        except Exception:
            pages = []
        for page in pages:
            for rec in page or []:
                if isinstance(rec, dict) and rec.get("skuCode"):
                    records[rec["skuCode"]] = rec
        return records

    @staticmethod
    def _prices_from_record(rec):
        """Same rule the card uses to display prices (verified 337/337)."""
        unit = rec.get("unitPrice") or 0
        selling = rec.get("preOrderDiscountPrice") or rec.get("skuDiscountPrice") or unit
        strike = unit if unit and unit > selling else selling
        # Same string form the card text produces ("2200", not "2200.0").
        fmt = lambda v: (str(int(v)) if float(v).is_integer() else str(v)) if v else None
        return fmt(strike), fmt(selling)

    @staticmethod
    def _prices_from_card(card):
        """Returns (strike, selling) raw strings from either card layout."""
        pre = card.select_one(".pre-order-price-formate")
        if pre:
            strike_el = pre.select_one(".line-through")
            # The selling price is the <p>'s own text node, between the
            # line-through span and the "% OFF" span.
            selling = "".join(pre.find_all(string=True, recursive=False)).strip()
            strike = strike_el.get_text(strip=True) if strike_el else None
        else:
            aside = card.select_one("aside")
            strike_el = aside.select_one(".line-through") if aside else None
            final_el = aside.select_one(".final-price-content") if aside else None
            strike = strike_el.get_text(strip=True) if strike_el else None
            selling = final_el.get_text(strip=True) if final_el else None
        selling = _rupees_to_str(selling)
        strike = _rupees_to_str(strike) or selling  # no discount: both share the one price
        return strike, selling

    def get_main(self, swept=None):
        page_html = self.driver.page_source
        swept = swept or {}
        records = dict(swept)
        records.update(self._json_records(page_html))
        soup = BeautifulSoup(page_html, "html.parser")
        cards = soup.select(CARD_SELECTOR)
        seen = set()

        for card in cards:
            product_dict = {}

            try:
                link = card.find("a", href=True)["href"]
                product_dict["Product_link"] = link if link.startswith("http") else BASE_URL + link
            except (AttributeError, TypeError, KeyError):
                product_dict["Product_link"] = None

            # ID = last path segment of the card's product link, e.g.
            # /csmia-mumbai-airport/duty-free/p/ardmore-triplewood-100cl/02N03220 -> 02N03220
            try:
                product_dict["ID_raw"] = product_dict["Product_link"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            except AttributeError:
                product_dict["ID_raw"] = None

            if product_dict["ID_raw"] in seen:
                continue
            seen.add(product_dict["ID_raw"])
            rec = records.get(product_dict["ID_raw"], {})

            try:
                product_dict["Brandline"] = card.select_one(".card-title").get_text(" ", strip=True)
            except AttributeError:
                product_dict["Brandline"] = rec.get("skuName")

            product_dict["Brand"] = rec.get("brand")
            product_dict["Size"] = rec.get("unitSize")

            try:
                strike, selling = self._prices_from_card(card)
            except AttributeError:
                strike, selling = None, None
            if not selling and rec:
                strike, selling = self._prices_from_record(rec)
            product_dict["Strike Price"] = strike
            product_dict["Price Discounted"] = selling

            # Real per-product concept on this site (API isExclusive), so
            # always a string: "Exclusive" or "" (see docstring).
            product_dict["GTR_exclusive"] = "Exclusive" if rec.get("isExclusive") else ""

            if not rec:
                print(f"  WARNING: no JSON record for card {product_dict['ID_raw']} (Brand/Size will be blank)")

            self.product_dicts.append(product_dict)

        # Products the infinite scroll skipped (see reconcile_with_api) have
        # no card. Build their row from the JSON record instead, with the same
        # link format the cards use, so the ID still comes from the link's
        # last path segment.
        added = 0
        for sku, rec in swept.items():
            if sku in seen:
                continue
            seen.add(sku)
            strike, selling = self._prices_from_record(rec)
            # Card hrefs lowercase the slug ("...-2x1l") even where the API's
            # productName doesn't ("...-2X1L"). Product_link is part of the
            # silver MERGE key, so match the card form exactly.
            link = f"{BASE_URL}/{AIRPORT_PATH}/duty-free/p/{(rec.get('productName') or '').lower()}/{sku}"
            self.product_dicts.append({
                "Product_link": link,
                "ID_raw": link.rsplit("/", 1)[-1],
                "Brandline": rec.get("skuName"),
                "Brand": rec.get("brand"),
                "Size": rec.get("unitSize"),
                "Strike Price": strike,
                "Price Discounted": selling,
                "GTR_exclusive": "Exclusive" if rec.get("isExclusive") else "",
            })
            added += 1
        if added:
            print(f"  reconcile: added {added} product(s) the infinite scroll skipped")

    def run_all(self):
        try:
            self.open_website()
            self.verify_store()
            self.paginate_or_scroll()
            self.expected_count = self.get_expected_item_count()
            swept = self.reconcile_with_api()
            self.get_main(swept)
        finally:
            try:
                if hasattr(self, "driver"):
                    self.driver.quit()
            except Exception:
                pass


def upload_to_databricks(data: list[dict], volume_path: str) -> None:
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
                scraper = AdanioneScraper(channel, category)
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
