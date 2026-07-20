import sys
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")

from gonsalves_liquors_scraper import GonsalvesLiquorsScraper

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()

print(f"PDF URL used: {scraper._pdf_url_cache}")
print(f"Total alcohol rows extracted: {len(scraper.product_dicts)}")

print("\n--- First 10 rows ---")
for row in scraper.product_dicts[:10]:
    print(row)

print("\n--- Random sample of 20 rows across the document ---")
import random
random.seed(7)
sample = random.sample(scraper.product_dicts, min(20, len(scraper.product_dicts)))
for row in sample:
    print(row)

# Check for duplicate IDs
ids = [r["ID_raw"] for r in scraper.product_dicts]
from collections import Counter
dupe_ids = {k: v for k, v in Counter(ids).items() if v > 1}
print(f"\nDuplicate ID_raw count: {len(dupe_ids)}")
for k, v in list(dupe_ids.items())[:15]:
    print(f"  {k}: {v}x")

# Category breakdown
cats = Counter(r["Category"] for r in scraper.product_dicts)
print(f"\nDistinct categories represented: {len(cats)}")
print(f"Null-brand count: {sum(1 for r in scraper.product_dicts if r['Brand'] is None)}")
print(f"Null-price count: {sum(1 for r in scraper.product_dicts if not r['Strike Price'])}")
print(f"Null-ID count: {sum(1 for r in scraper.product_dicts if not r['ID_raw'])}")
