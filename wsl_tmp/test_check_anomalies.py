import sys
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")
from gonsalves_liquors_scraper import GonsalvesLiquorsScraper

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()

for token in ["0.05cl", "25lt", "3cl", "1.14Lt", "355ml"]:
    print(f"--- rows containing size token matching '{token}' ---")
    for r in scraper.product_dicts:
        if token.lower() in r["Brandline"].lower():
            print(" ", r["Brandline"], "| case=", r["Case_Price_raw"], "bottle=", r["Strike Price"], "| category=", r["Category"])
