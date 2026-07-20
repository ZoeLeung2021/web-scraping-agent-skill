import sys
import re
sys.path.insert(0, "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/outputs/gonsalves_liquors")
from gonsalves_liquors_scraper import GonsalvesLiquorsScraper

scraper = GonsalvesLiquorsScraper("Saint Vincent and the Grenadines", "N/A")
scraper.run_all()

SIZE_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:cl|ml|lt|l)\b)", re.IGNORECASE)


def normalize_size_to_cl(token):
    t = token.lower().replace(" ", "")
    if "cl" in t:
        return float(t.replace("cl", ""))
    if "ml" in t:
        return float(t.replace("ml", "")) / 10
    if "lt" in t:
        return float(t.replace("lt", "")) * 100
    if "l" in t:
        return float(t.replace("l", "")) * 100
    return None


def fix_price(text):
    cleaned = re.sub(r"[^\d.,]", "", text)
    cleaned = cleaned.replace(",", "")
    return float(cleaned)


fail_size = []
sizes_seen = {}
for r in scraper.product_dicts:
    m = SIZE_RE.search(r["Brandline"])
    if not m:
        fail_size.append(r["Brandline"])
        continue
    token = m.group(1)
    cl = normalize_size_to_cl(token)
    if cl is None or cl <= 0:
        fail_size.append((r["Brandline"], token, cl))
    sizes_seen[token] = sizes_seen.get(token, 0) + 1

print(f"Total rows: {len(scraper.product_dicts)}")
print(f"Size extraction failures: {len(fail_size)}")
for f in fail_size[:20]:
    print(" FAIL:", f)

print("\nDistinct raw size tokens seen (and counts):")
for tok, cnt in sorted(sizes_seen.items(), key=lambda x: -x[1]):
    print(f"  {tok!r}: {cnt}  -> {normalize_size_to_cl(tok)} cl")

# price check
fail_price = []
for r in scraper.product_dicts:
    try:
        p = fix_price(r["Strike Price"])
        if p <= 0:
            fail_price.append(r)
    except Exception as e:
        fail_price.append((r, str(e)))
print(f"\nPrice parse failures: {len(fail_price)}")
for f in fail_price[:10]:
    print(" FAIL:", f)
