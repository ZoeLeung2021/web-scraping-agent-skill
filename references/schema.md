# Standardized price-data schema (`gtr_silver_master`)

Every cleaner script must output exactly these 17 columns, in this order, regardless of retailer — they all merge into the single shared Delta table `selfservice_nonprod.gtr_web_scraping.gtr_silver_master`. If a value isn't available for a given retailer, leave it null rather than omitting the column.

This is drawn from the real `clean_cloud9_laos.py` pipeline (the canonical reference cleaner) plus the older `webscraping/README.md` format doc — the two mostly agree, with the differences noted below resolved in favor of what the live Databricks pipeline actually does.

| Column | Type | Description |
|---|---|---|
| `Year` | int | Calendar year the scrape ran, derived from `Scraped_At` — e.g. `2026`. |
| `Month` | string | **Month name**, not a number — e.g. `"July"`. Derived from `Scraped_At` via `date_format(..., "MMMM")`. Easy to get wrong by defaulting to an int; don't. |
| `Market` | string | `"GTR"` for duty-free/travel-retail sites, `"Domestic"` for domestic retail sites kept as a pricing reference (e.g. Cloud 9 Laos, Dan Murphy's). This is a channel classification, not a geographic region. Decide it from the site itself: if "duty free"/"travel retail"/"bordershop" show up repeatedly in the site's own branding/copy, it's GTR — confident enough to proceed. If the site never says either and you're not sure, **ask the user to confirm** rather than guessing; this also decides whether `Domestic_Tax` below needs real data. |
| `Retailer` | string | Retailer name matching the existing retailer list, e.g. `"Cloud 9"`, `"Dubai Duty Free"`. |
| `Country` | string | Country the retailer site serves. For `Market = "GTR"` retailers, prefix it `"DF "` (e.g. `"DF Czech Republic"`, `"DF Iceland"`) to distinguish duty-free pricing from a domestic entry for the same country — a newer convention (not present in the older `clean_cloud9_laos.py`/`clean_dufry_europe.py`, which predate it and aren't being retrofitted). For `Market = "Domestic"`, use the plain country name, no prefix. Must match the `Country` values in the exchange-rate reference file exactly, or the FX join in `ExchangeRate_cleaning()` silently produces nulls. |
| `Channel` | string | Airport/shop/site name where relevant. Follow GTR_Pricing's own existing conventions per venue type (see below) rather than inventing a format — check for a legacy scraper covering the same retailer/venue first, since the exact production string may already exist. Use `"N/A"` only for a genuinely non-location-specific catalog (nationwide domestic e-commerce with home delivery, no storefront/terminal concept at all) — never as a stand-in for "there's only one location" when that location is a real, confirmable venue. |
| `ID` | string | Stable per-SKU identifier. Prefer the retailer's own numeric SKU/product code if the site exposes one — it survives a product URL changing. If not, don't just fall back to the whole `Product_link`: first try pulling a numeric-ID-looking substring out of the URL (most product URLs embed one), and only use the full link as a last resort if the URL has no such substring. |
| `Brand` | string | Brand name, e.g. `"Johnnie Walker"`. |
| `Brandline` | string | Brand line/variant, e.g. `"Black Label"`. Often bundled into a single product title on the raw page — split it in the cleaner. |
| `Size` | float | Bottle size **normalized to cl** (centiliters) — not left as the site's raw string. `ml` → divide by 10, `L` → multiply by 100. Every existing cleaner does this conversion; don't introduce a new unit. If the site has no dedicated Size field, fall back to extracting a size-looking substring (e.g. `"750ml"`) out of `Brandline`/the product title before normalizing — many sites only show size as part of the product name. |
| `Domestic_Tax` | string/null | Domestic tax component. For `Market = "GTR"`, always null — duty-free prices are pre-tax by definition, don't invent a value. For `Market = "Domestic"`, look up that country's real consumer alcohol excise/duty tax rate(s) (spirits/wine/beer usually differ) and propose the figure(s) to the user for sign-off before writing them in — don't silently pick a number yourself, and don't leave it null just because the site itself doesn't show tax separately (most retail sites show tax-inclusive prices, not a tax line item). |
| `Price_Discounted` | float | Current/selling price, in the **IWSR reporting currency** (post-FX-conversion), numeric only. |
| `Strike_Price` | float or null | Full/original price if on promotion, also post-FX-conversion. Null if not discounted. |
| `Currency` | string | The reporting currency code **after** conversion (e.g. `"EUR"` or `"USD"`), not the site's original local currency — `ExchangeRate_cleaning()` overwrites this field when it converts. |
| `GTR_exclusive` | string/null | Three-way, not a plain boolean: `"Yes"` if this product carries the site's own GTR/travel-exclusive tag; `"No"` if the site tracks this concept (badges some products) but not this one; **true null** if the whole site never mentions GTR-exclusivity anywhere at all (no badge, no ribbon, no "Exclusives" category — e.g. Silk Road Duty Free). Don't collapse "No" and "site doesn't have this concept" into the same blank value — they mean different things. Look properly before concluding a site is the null case: it's usually a visual ribbon/badge overlaid on the product image (e.g. Ísland Duty Free's `<span class="c-ribbon">Travel Edition</span>`, which corresponds to a `dimension3: "travel exclusive"` field in that site's tracking JSON — the two agree, confirming the field is real). Don't rule a field out from spot-checking one non-exclusive product; find an actually-badged product first. |
| `Product_link` | string | Full URL to the product (or product image, for a few sites that only expose that) as scraped. |
| `Scraped_At` | timestamp | When the scraper captured this row. `Year`/`Month` are both derived from this — get this right and the other two follow. |

## Channel naming conventions by venue type

All five confirmed directly against real GTR_Pricing production scrapers (not invented) — check for a retailer/venue-specific legacy scraper first, since the exact string you need may already exist verbatim.

| Venue type | Format | Real example(s) | Source |
|---|---|---|---|
| Airport | `"<City/Place + airport-specific name if any> [International] Airport (IATA)"` | `"Rome Fiumicino International Airport (FCO)"`, `"Auckland Airport (AKL)"` (no "International" — matches the airport's real name) | `scrapers/adr_italy_scraper.py`, `scrapers/newzealand_themall_scraper.py`, and ~25 more |
| Ferry | `"Ferry - <name>"` | `"Ferry - Inishmore"` (ship/route name) | legacy `webscraping/Aelia/Aelia_cleaner.py` `CHANNEL_MAP` |
| Train station | `"Train Station: <name>"` | `"Train Station: Paris Gare du Nord"` | same `CHANNEL_MAP` |
| Land border crossing | `"Border - <State/Province>: <Crossing Name>"` | `"Border - Texas: Brownsville B&M"`, `"Border - Washington: Blaine"` | `scrapers/dutyfreeamericas_scraper.py`'s `Locations` dict — a retailer-specific legacy scraper, not one of the commonly-referenced Aelia/Dufry files, so check niche venue types like this even when the obvious references don't have it |
| Diplomatic shop | `"<Region or Country> Diplomatic Services"` | `"Europe Diplomatic Services"` | `scrapers/peterjustesen_denmark_scraper.py` |
| Combined/no-split national retailer | `"<Country> Duty Free"` — for a genuinely nationwide or multi-channel GTR retailer whose own site has no per-location split to key a more specific Channel off of | `"South Africa Duty Free"`, `"Romania Duty Free"`, `"Cayman Islands Duty Free"` | `scrapers/big_five_south_africa_scraper.py`, `scrapers/romania_best_value_scraper.py`, `scrapers/tortuga_cayman_scraper.py` |

If a retailer spans multiple towns/venues under one combined catalog with no single named crossing/venue to point to (e.g. a border-shop brand with 5+ towns), a reasoned extension of the closest pattern is acceptable — e.g. Country substituting for State and the brand name substituting for a specific crossing name in the land-border format — but document that it's an extension, not an exact precedent match.

Before applying any of these, verify the retailer's real physical situation live rather than assume from its name or category — e.g. a "duty-free" site can genuinely combine both downtown AND airport channels with no split (confirmed on one retailer via the homepage's own title text), in which case the combined/no-split format applies instead of a single-venue one.

## Known gotchas (from `webscraping/code_review.md` — don't repeat these)

- Don't leave `Price_Discounted`/`Strike_Price` as strings after currency-symbol stripping — cast to float explicitly.
- Don't hardcode the exchange-rate reference file's year (e.g. `Ex.Rates_2025.csv`) — derive the year or otherwise ensure it doesn't silently apply stale rates from 2026 onward.
- Don't emit a subset of the 17 columns because the raw scrape happens to already have some of them under different names — always explicitly select/alias to the full column list.
- Don't wrap FX conversion in a bare `except: pass` — if the `Country`/`Currency` join fails, you want to see it, not silently ship unconverted prices.

## Adding a new column

If a retailer needs data this schema doesn't capture, don't add a column silently — every retailer's cleaner MERGEs into the same shared table, so an ad hoc column breaks the merge for everyone else. Flag it to whoever owns the `gtr_silver_master` schema first.
