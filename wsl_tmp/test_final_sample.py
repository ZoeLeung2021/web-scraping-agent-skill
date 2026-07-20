import sys
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")
from gonsalves_liquors_scraper import GonsalvesLiquorsScraper

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()
print("TOTAL:", len(scraper.product_dicts))

picks = ["jack-daniels-75cl", "grey-goose-75cl", "havana-club-7-yr-old-70cl",
         "hennessy-xo-70cl" if False else None]
names_wanted = [
    "Jack Daniels 75cl", "Grey Goose 75cl", "Macallan Double Cask 18 yr 75cl",
    "Havana Club 7 yr Old 70cl", "Moet & Chandon Imperial 20cl",
    "Tignanello 2022 75cl", "Corona Extra Beer 355ml",
]
by_brandline = {r["Brandline"]: r for r in scraper.product_dicts}
for n in names_wanted:
    print(by_brandline.get(n, f"NOT FOUND: {n}"))
