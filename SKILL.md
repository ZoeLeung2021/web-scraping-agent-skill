---
name: web-price-scraper
description: Build a new retailer's scraper + cleaner pair for the GTR_Pricing bronze/silver pipeline — a Selenium scraper that lands raw SKU-level price data (brand, brandline, size, discounted price, strike price) into a Databricks Volume, and a PySpark cleaner that standardizes it into the shared gtr_silver_master Delta table. Use this whenever a teammate asks to scrape a new duty-free/travel-retail or domestic retailer site for pricing, add a retailer to the GTR pricing pipeline, or fix/extend an existing retailer's scraper or cleaner — even if they just paste a URL and say "can you get the prices off this site" or "add this retailer to our list."
---

# Web Price Scraper (GTR_Pricing pipeline)

Every new retailer follows the same two-step bronze/silver pattern already used by ~90 retailers in this repo (see `scrapers/cloud9_laos_scraper.py` + `silver_scripts/clean_cloud9_laos.py` as the canonical reference pair). This skill exists so a teammate doesn't have to re-derive that pattern from scratch each time — copy the templates, fill in the retailer-specific TODOs, and the plumbing (Databricks upload, currency conversion, dedup, Delta merge, orchestration) is already handled.

**Scope: alcohol (wine & spirits) pricing only.** Many duty-free/travel-retail sites also sell perfume, tobacco, chocolate, electronics, etc. — scrape only the alcohol category pages/codes on any given site, never the full catalog.

There is an older pattern in `webscraping/` (local CSV → Excel, no Databricks, run via `uv run run_all.py`). That's legacy — **new retailers go through the bronze/silver Databricks+Kestra pattern below**, not the old one, even though some existing retailers still have both.

## Output location

Draft every retailer's files under `outputs/<retailer_slug>/` **in this project**, not directly in GTR_Pricing (or whichever downstream repo will eventually run them) — that makes them easy to review in one place, and this skill isn't GTR_Pricing-specific: another team could point it at a different scraping repo entirely. Only copy the finished, tested files into the actual target repo (`GTR_Pricing/scrapers/`, `silver_scripts/`, `kestra_flows/`, or wherever the requester says) as an explicit, separate "deploy" step once they're validated — don't do that automatically as part of drafting.

## Workflow

### 1. Interview

Ask (or infer from what's already been shared):
- Retailer name, country/market, and the URL(s) to scrape — one category page, several category codes/IDs, or a list of per-airport/per-location URLs (many retailers loop over multiple airports or store locations)? For the `Channel` value itself, follow GTR_Pricing's real per-venue-type naming conventions (airport/ferry/train/land-border/diplomatic/combined-national) documented in `references/schema.md` — check for a matching legacy scraper there before inventing a format, and never default to `"N/A"` just because there's only one location if that location is a real, confirmable venue.
- Which categories on the site are actually alcohol (whisky/spirits/wine/beer/champagne, etc.) — scope to those, not the whole catalog (see the scope note above).
- Is this a **GTR** (duty-free/travel-retail) site or a **Domestic** retail site kept for pricing reference? This sets the `Market` column. Decide from the site itself, don't just ask up front: if "duty free"/"travel retail"/"bordershop" (or local-language equivalents) show up repeatedly across the site's branding and copy, that's GTR — confident enough to proceed without checking in. If the site never mentions any of that and you're genuinely not sure which it is, **stop and ask the user to confirm** before writing `Market` into the cleaner — don't guess on this one, it's load-bearing for FX/tax handling below. If it's Domestic, look up that country's consumer alcohol excise/duty tax rate(s) (they vary a lot by beverage type — spirits/wine/beer usually differ) and propose the figure(s) to the user for `Domestic_Tax` rather than leaving it null or inventing a number yourself; get their sign-off before writing it into the cleaner.
- What language is the site in? If not English, note it now — it affects both the scraper (step 3) and, if that doesn't fully work, the cleaner (step 4).
- Any known site quirks: age-verification gate, cookie banner, region/currency picker, infinite scroll vs. "load more" button vs. numbered pagination, product data embedded as JSON (many sites expose a `window.someProducts` JSON blob or JSON-LD `<script>` tag — check for this before falling back to DOM scraping, it's far more reliable).

### 2. Inspect the site before writing the scraper

Open one representative product-listing page (with dev tools) and check:
- View-source for embedded JSON (`window.linkedProducts`, JSON-LD, a `data-product` attribute) — several existing scrapers key off this instead of scraping rendered HTML.
- CSS selectors for: product name, brand, size/pack, discounted price, strike/full price, product ID, product URL.
- Whether prices/brand/brandline appear on the listing page itself, or only on individual product detail pages (several existing scrapers do two passes: scrape the listing, then visit each product page and merge). Size is a common one that's missing from the listing but present on the detail page — check both before assuming a fallback regex on the title will cover it.
- Pagination mechanism and roughly how many products total.
- Whether any products are GTR/travel-retail exclusive, and how the site signals it: usually a visual badge/ribbon/tag overlaid on the product image (e.g. `<span class="c-ribbon">Travel Edition</span>` right after the image wrapper) — check for that in the DOM before assuming it's only in a hidden JSON field, and don't trust a JSON field's absence on a single spot-checked product; it might just be that product isn't exclusive. Some sites also have a separate "Exclusives" nav category whose product IDs you can cross-reference as a second signal.
- If the site isn't in English: is there an explicit language/region switcher in the UI? That's simpler and more reliable than forcing a translation — prefer it over the Chrome auto-translate option in step 3 whenever it exists.
- robots.txt and terms of use. This team scrapes publicly visible retail pricing as standard practice, but respect `robots.txt` disallow rules and don't hammer the site — every existing scraper adds waits between actions.

### 3. Write the scraper (bronze)

Copy `scripts/scraper_template.py` into `outputs/<retailer_slug>/<retailer>_scraper.py` (this project — see "Output location" above). It's a Selenium + `undetected_chromedriver` skeleton — same shape as every other scraper in `scrapers/`: a class with `open_website()`, popup/age-verification handling wrapped in try/except (these don't appear on every page load), a pagination or infinite-scroll loop, `get_main()` parsing `driver.page_source` with BeautifulSoup, and a `run_all()` with **try/finally `driver.quit()`** — don't skip this, most of the historical bugs in this codebase were leaked Chrome processes from scrapers that didn't clean up their driver.

Fill in the `# TODO`s: the `LOCATIONS` map (country → channels/airports — a single-location retailer still uses this, just with one country and one channel), `CATEGORIES` (the alcohol-only category codes/slugs this site separates by — use a single placeholder if the site already has one alcohol-only listing page), the URL-building logic in `get_url()`, the selectors from step 2, and any interstitial dismissal. Each raw product dict needs `Product_link`, `ID_raw` (if the site has one), `Brand`, `Brandline`, `Size`, `Strike Price`, `Price Discounted`, and `GTR_exclusive` (raw promo text, blank if none) — don't drop `Brand` or `Price Discounted`, they're easy to forget since some sites only show one price when nothing's on sale. Keep the scraper's job narrow otherwise — extract raw fields as they appear on the page, don't normalize/clean here. That's the cleaner's job, and keeping them separate means a site layout change only breaks the scraper.

If the site isn't in English and has no in-page language switcher, force Chrome's built-in translate feature via the experimental `prefs` option in `open_website()` (see the commented example there, and `elitalco_kazakhstan_scraper.py` for the real reference). If that still doesn't reliably produce English text, don't fight it further in the scraper — leave the raw text as scraped and translate it in the cleaner instead (step 4).

The main loop tags every row with `Country`/`Channel`/`Scraped_At` at the point it flattens each location's results into `all_data` — this is what lets the cleaner tell locations apart later without hardcoding a single value for the whole file (see `dufry_europe_scraper.py` for the real multi-country version of this pattern). Then it uploads the raw JSON straight to the bronze Databricks Volume via `databricks.sdk.WorkspaceClient` — the template's `upload_to_databricks()` already does this, just update the volume path's retailer segment.

### 4. Write the cleaner (silver)

Copy `scripts/cleaner_template.py` into `outputs/<retailer_slug>/clean_<retailer>.py` (this project). It's a PySpark job — same shape as `clean_cloud9_laos.py` (single location) or `clean_dufry_europe.py` (many countries/channels). Fill in the `# TODO`s:
- `Market` (`"GTR"` or `"Domestic"`), `Retailer`, `LOCAL_CURRENCY`
- `CHANNEL_LABELS` — only needed if the raw `Channel` value from the scraper is a slug that should map to a human-readable label (e.g. `"zurich"` → `"Zurich International Airport (ZRH)"`); leave empty for single-location retailers
- `Country`/`Channel` themselves are read straight from the bronze JSON, not hardcoded here — the paired scraper already tagged every row (see step 3), even for a single-location retailer
- Price parsing regex if the site's price format needs more than the template's default currency-symbol strip (e.g. European `1.234,56` decimal comma format)
- If currency varies by `Country`/`Channel` rather than being one fixed value for the whole retailer, replace the single `Currency` literal with a `when/otherwise` chain — see `clean_dufry_europe.py`'s Armenia-default/Zurich-CHF-override for the shape to copy

The template already handles a few common gaps in the raw scrape, so you shouldn't need to rebuild these per retailer:
- **No dedicated `Size` field** — falls back to pulling a size-looking substring (`"750ml"`, `"70cl"`) out of `Brandline`/the product title before normalizing to cl. Only extend the regex if this site's size format isn't covered.
- **No explicit product ID** — falls back to pulling a run of digits out of `Product_link` before resorting to the full link as the `ID`. Only adjust this if the site's ID is a non-numeric slug instead.
- **Site couldn't be gotten into English at scrape time** — uncomment the `ai_translate(Brand, 'en')` / `ai_translate(Brandline, 'en')` calls (Databricks' built-in, on-cluster translation — see `clean_hyundai_duty_free_korea.py`). Only use this as a last resort after step 3's options, and keep it positioned **after** Size has already been extracted from `Brandline` — translating first can turn a recognizable `"750ml"` into text the size regex no longer matches.

**Always** convert currency via the shared `ExchangeRate_cleaning()` utility (`from ExRate_Cleaning_fx import ExchangeRate_cleaning`) rather than writing new conversion logic — every retailer's cleaner uses this same function against the shared IWSR exchange-rate reference file. Skip it only if the site's prices are already in the reporting currency (e.g. Singapore Changi skips it because SGD is the reporting currency for that market — note that exception in the cleaner if it applies here).

Volume anomaly detection (`check_volume_anomaly` from `volume_anomaly_detection.py`) is available but **not required** for every new cleaner — use your judgment on whether this retailer's data volume is unpredictable enough to warrant it; don't wire it in by default.

The cleaner must always emit exactly the 17 columns in `references/schema.md`, in that order — this feeds a single shared Delta table (`gtr_silver_master`) across every retailer, so an unplanned extra/missing/renamed column breaks the merge or downstream joins for everyone else, not just this retailer.

### 5. Actually run and validate the scraper — don't skip this

Writing the scraper isn't the finish line. Run it for real (a working no-sudo headless-Chrome test setup, plus the exact gotchas that trip this up, is documented in `references/testing.md` — build it once, reuse it every time) and confirm:
- It completes without crashing (the only expected failure locally is the final Databricks upload, since there won't be real credentials outside the `etl-scrapers` container — that's fine)
- The number of items scraped matches an independent ground truth, ideally something the site itself displays (a results count, "Showing X of Y", etc.) — wire this into `get_expected_item_count()` if the site has one. A wrong selector almost always shows up as a low/zero count here, not a crash, so don't skip this check even if the run "looked fine"
- If coverage doesn't match, fix the selector before moving on — don't hand off a scraper with a known undercount

Then run the cleaner against the bronze output it produced (locally against a downloaded copy of the JSON, or via a Databricks notebook) and check:
- Prices are numeric and in the expected reporting currency after FX conversion — not still in local currency, not left as strings
- `Month` is a month name (`"July"`), not a number — this trips people up since it's easy to default to an int
- `ID` is stable across scrapes of the same product (usually `Product_link` — a numeric SKU ID is more stable if the site exposes one, since a product's URL can occasionally change)
- Rows landing in the DLQ table look genuinely bad (null ID, no price at all) rather than a sign the mapping/regex is wrong

### 6. Wire it into Kestra

Copy `scripts/kestra_flow_template.yaml` into `outputs/<retailer_slug>/<retailer>_flow.yaml` (this project), following the two-task shape in `cloud9_laos_flow.yaml`: a bronze task that runs the scraper in the `etl-scrapers` Docker image, then a Subflow task that routes the silver step through `silver_clean_dispatcher` (this is what serializes every retailer's Delta `MERGE INTO` against the shared silver table — never call the Databricks silver job directly from a per-retailer flow). Add the failure alert tasks so a broken scraper pages `#data-engineering-alerts` instead of failing silently.

### 7. Deploy

Once steps 1–6 are done and validated, copy the three files from `outputs/<retailer_slug>/` into the actual target repo — for GTR_Pricing that's `scrapers/<retailer>_scraper.py`, `silver_scripts/clean_<retailer>.py`, and `kestra_flows/<retailer>_flow.yaml`. Treat this as an explicit step the user asks for, not something to do automatically right after drafting.

## Standardized schema

See `references/schema.md` for the exact 17 columns, types, and real-world gotchas (`Month` as name not number, `GTR_exclusive` as string not boolean, `Market` as Domestic/GTR channel classification not geography). Read it before writing the cleaner — don't assume the schema from a generic pricing pipeline; this one has retailer-specific conventions baked in that came from hard-won fixes (see `webscraping/code_review.md` for the kinds of bugs that have bitten this exact schema in the past: prices left as strings, missing columns, hardcoded exchange-rate years).

## Notes on repeat use

Copy the templates fresh for each new retailer rather than trying to generalize one universal scraper — retailer HTML is too inconsistent (see the quirks column in `GTR_Pricing/webscraping/SCRAPERS.md` for a sense of the range: shadow-DOM ad closing, Chrome auto-translate for non-English sites, per-product detail-page merges, `ThreadPoolExecutor` for parallel scraping, ctrl-click new-tab navigation). What must stay identical every time is the final schema, the shared FX conversion call, and the try/finally driver cleanup.
