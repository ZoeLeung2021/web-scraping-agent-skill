import importlib.util
import time

spec = importlib.util.spec_from_file_location("wines700scraper", "/home/zoeliang/700winesandspirits_scraper.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

Scraper = mod.SevenHundredWinesScraper

# Ground-truth counts independently confirmed during live investigation
# (separate script run, separate day/session) — used here purely as a
# cross-check for this validation pass, not hardcoded into the scraper
# itself.
GROUND_TRUTH = {
    "rum": 50,
    "vodka": 30,
    "kosher": 2,
    "all-beers": 26,  # before non-alcohol filtering (25 alcohol expected after)
}

scraper = Scraper("Bahamas", "N/A")
scraper.open_website()
try:
    for path, label in [("rum", "Rum"), ("vodka", "Vodka"), ("kosher", "Kosher"), ("all-beers", "Beer")]:
        before = len(scraper.product_dicts)
        before_excluded = scraper.excluded_nonalcohol
        t0 = time.time()
        n_seen = scraper.scrape_category(path, label)
        dt = time.time() - t0
        rows_added = len(scraper.product_dicts) - before
        excluded_added = scraper.excluded_nonalcohol - before_excluded
        expected = GROUND_TRUTH.get(path)
        flag = "OK" if (expected is None or n_seen == expected) else "MISMATCH"
        print(
            f"{path} ({label}): unique_ids_seen={n_seen} rows_kept={rows_added} "
            f"excluded_nonalcohol={excluded_added} expected={expected} [{flag}] time={dt:.1f}s"
        )
        # print a couple sample rows for sanity
        for r in scraper.product_dicts[-min(3, rows_added):]:
            print("   sample:", r.get("ID_raw"), "|", r.get("Brandline"), "|", r.get("Size"), "|", r.get("Strike Price"), "|", r.get("Product_link"))
finally:
    scraper.driver.quit()

print("\nTOTAL rows collected:", len(scraper.product_dicts))
print("TOTAL excluded non-alcohol:", scraper.excluded_nonalcohol)

# duplicate ID check across everything collected in this run
ids = [r.get("ID_raw") for r in scraper.product_dicts]
print("duplicate ids within this run:", len(ids) - len(set(ids)))
