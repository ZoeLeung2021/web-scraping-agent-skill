import sys
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")
from gonsalves_liquors_scraper import GonsalvesLiquorsScraper

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()

# Look for any suspicious non-alcohol-sounding names that leaked through
SUSPECT_WORDS = ["water", "coffee", "capsule", "olive", "syrup", "cigar",
                  "muddler", "bitters", "mix", "spring", "mineral"]
for r in scraper.product_dicts:
    name_l = r["Brandline"].lower()
    if any(w in name_l for w in SUSPECT_WORDS):
        print(r["Brandline"], "|", r["Category"], "| case=", r["Case_Price_raw"], "bottle=", r["Strike Price"])
