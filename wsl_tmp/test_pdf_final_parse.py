import re
import pdfplumber

PDF_PATH = "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/GLL_Price_List_VAT.pdf"

CATEGORY_RE = re.compile(r"^(?:New\s+)?~\s*(.+?)\s*~", re.IGNORECASE)
NAMED_ROW_RE = re.compile(
    r"^(?P<isnew>New\s+)?(?P<name>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>[A-Za-z]+)\s+"
    r"(?P<case>[\d,]+\.\d{2})\s+"
    r"(?P<bottle>[\d,]+\.\d{2})\s*$"
)
SKIP_PATTERNS = [
    re.compile(r"Prices subject to change", re.IGNORECASE),
    re.compile(r"^Page \d+"),
    re.compile(r"^\d{2}/\d{2}/\d{4}"),
    re.compile(r"^QTY/SIZE"),
    re.compile(r"^CASE\s*$"),
    re.compile(r"^BOTTLE\s*$"),
    re.compile(r"^EC\.\s*\$"),
    re.compile(r"Wholesale prices offered"),
    re.compile(r"Prices quoted are VAT"),
    re.compile(r"^\d{4} PRICE LIST"),
    re.compile(r"Wines are stored"),
    re.compile(r"largest selection"),
    re.compile(r"GONSALVES LIQUORS"),
    re.compile(r"Cor\. Middle"),
    re.compile(r"P\. O\. Box"),
    re.compile(r"^Tel:"),
    re.compile(r"^Email:"),
    re.compile(r"^Website:"),
    re.compile(r"Vintages may vary"),
]

# Category (tilde-header) based exclusions - confirmed non-alcohol sections
NON_ALCOHOL_CATEGORY_KEYWORDS = [
    "coffee", "olive oil", "syrup", "epic products", "cigar", "mixer",
]
# Fallback per-row keyword denylist for non-alcohol rows that land under an
# ambiguous/missing category header (confirmed live: the water/mixer
# section on the price list has a blank/logo-only header with no text of
# its own, so these specific brand names are matched directly). Cigars and
# EPIC PRODUCTS bar-accessory lines are NOT included here because they use
# a single-price format ("Product Name  12.34") with no "qty x size"
# token at all, so they never match NAMED_ROW_RE in the first place -
# confirmed live, zero cigar/bar-accessory rows ever reach this list.
# "cazadores" was deliberately tried and REMOVED from this list: it
# collided with the real alcoholic product "Cazadores Blanco" tequila and
# wrongly excluded it - the Jose L. Piedra Cazadores cigar it was meant to
# catch never reaches this filter anyway (same single-price-format reason).
NON_ALCOHOL_NAME_KEYWORDS = [
    "evian", "san pellegrino sparkling", "perrier sparkling",
    "mountain top natural spring", "angostura", "zing zang",
]


def is_alcohol(category, name):
    cat_l = (category or "").lower()
    name_l = name.lower()
    if any(k in cat_l for k in NON_ALCOHOL_CATEGORY_KEYWORDS):
        return False
    if any(k in name_l for k in NON_ALCOHOL_NAME_KEYWORDS):
        return False
    return True


named_rows = []
skipped_orphan = 0
skipped_unmatched = []
current_category = None  # persists across pages (fix vs earlier test)

with pdfplumber.open(PDF_PATH) as pdf:
    total_pages = len(pdf.pages)
    for pi, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if any(p.search(line) for p in SKIP_PATTERNS):
                continue
            cat_match = CATEGORY_RE.match(line)
            if cat_match:
                current_category = cat_match.group(1).strip()
                continue
            m = NAMED_ROW_RE.match(line)
            if m:
                d = m.groupdict()
                named_rows.append({
                    "page": pi + 1,
                    "category": current_category,
                    "is_new": bool(d["isnew"]),
                    "name": d["name"].strip(),
                    "case_qty": d["qty"],
                    "size": d["size"],
                    "unit": d["unit"],
                    "case_price": d["case"],
                    "bottle_price": d["bottle"],
                    "raw_line": line,
                })
                continue
            # orphan (qty/size/price with no name) vs genuinely unmatched junk
            orphan_re = re.compile(
                r"^\d+(?:\.\d+)?\s*x\s*[\d.]+\s*[A-Za-z]+\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s*$"
            )
            if orphan_re.match(line):
                skipped_orphan += 1
            else:
                skipped_unmatched.append((pi + 1, current_category, line))

alcohol_rows = [r for r in named_rows if is_alcohol(r["category"], r["name"])]
nonalcohol_rows = [r for r in named_rows if not is_alcohol(r["category"], r["name"])]

print(f"Total pages: {total_pages}")
print(f"Total named rows parsed: {len(named_rows)}")
print(f"  -> Alcohol rows: {len(alcohol_rows)}")
print(f"  -> Non-alcohol rows (excluded): {len(nonalcohol_rows)}")
print(f"Orphan rows skipped (qty/size/price, no name text): {skipped_orphan}")
print(f"Genuinely unmatched/junk lines skipped: {len(skipped_unmatched)}")

print("\n--- Non-alcohol rows excluded (for review) ---")
seen_cats = set()
for r in nonalcohol_rows:
    key = r["category"]
    seen_cats.add(key)
print("Non-alcohol categories/keywords triggered:", seen_cats)
for r in nonalcohol_rows[:40]:
    print(f"  [{r['category']}] {r['name']} {r['case_qty']}x{r['size']}{r['unit']} case={r['case_price']} bottle={r['bottle_price']}")

print(f"\n--- Sample of 25 ALCOHOL rows across categories ---")
import random
random.seed(42)
sample = random.sample(alcohol_rows, min(25, len(alcohol_rows)))
for r in sample:
    print(f"  page{r['page']:>2} [{r['category']}] name='{r['name']}' new={r['is_new']} qty={r['case_qty']} size={r['size']}{r['unit']} case_price={r['case_price']} bottle_price={r['bottle_price']}")

print("\n--- Category breakdown of alcohol rows ---")
from collections import Counter
cat_counts = Counter(r["category"] for r in alcohol_rows)
for cat, cnt in cat_counts.most_common():
    print(f"  {cat}: {cnt}")

print(f"\n--- All unmatched/junk lines (should be non-product headers/labels only) ---")
for row in skipped_unmatched:
    print(row)
