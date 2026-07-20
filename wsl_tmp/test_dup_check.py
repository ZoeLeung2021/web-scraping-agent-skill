import sys
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")
from gonsalves_liquors_scraper import GonsalvesLiquorsScraper
from collections import defaultdict

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()

groups = defaultdict(list)
for r in scraper.product_dicts:
    groups[r["ID_raw"]].append(r)

for slug, rows in groups.items():
    if len(rows) > 1:
        print(f"=== {slug} ({len(rows)}x) ===")
        for r in rows:
            print(f"  category={r['Category']!r} case={r['Case_Price_raw']} bottle={r['Strike Price']}")
