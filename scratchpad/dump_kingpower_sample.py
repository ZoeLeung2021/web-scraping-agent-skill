import sys, json
sys.path.insert(0, "/home/zoeliang")
import kingpower_cn_scraper as kp

scraper = kp.KingpowerCnScraper("Thailand Duty Free", "48", "Alcohol & Beverages (酒水)")
scraper.run_all()
print("count:", len(scraper.product_dicts))
print("expected_count (raw, incl non-alcohol):", scraper.expected_count)

# Check for duplicate IDs
ids = [p.get("ID_raw") for p in scraper.product_dicts]
print("unique ids:", len(set(ids)), "/ total:", len(ids))
dupes = [i for i in set(ids) if ids.count(i) > 1]
print("duplicate ids:", dupes)

# Check for any None Product_link / ID_raw / Brand / Price
none_link = sum(1 for p in scraper.product_dicts if not p.get("Product_link"))
none_id = sum(1 for p in scraper.product_dicts if not p.get("ID_raw"))
none_brand = sum(1 for p in scraper.product_dicts if not p.get("Brand"))
none_price = sum(1 for p in scraper.product_dicts if not p.get("Price Discounted"))
print("none Product_link:", none_link, "none ID_raw:", none_id, "none Brand:", none_brand, "none Price:", none_price)

print("\n--- sample 8 rows ---")
for row in scraper.product_dicts[:8]:
    print(json.dumps(row, ensure_ascii=False))

print("\n--- any row with a real (non-duplicated) Strike Price != Price Discounted ---")
for row in scraper.product_dicts:
    if row.get("Strike Price") != row.get("Price Discounted"):
        print(json.dumps(row, ensure_ascii=False))

with open("/home/zoeliang/kingpower_cn_sample.json", "w", encoding="utf-8") as f:
    json.dump(scraper.product_dicts, f, ensure_ascii=False, indent=2)
