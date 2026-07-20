import re
import pdfplumber

PDF_PATH = "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/GLL_Price_List_VAT.pdf"

CATEGORY_RE = re.compile(r"^~\s*(.+?)\s*~")
NAMED_ROW_RE = re.compile(
    r"^(?:New\s+)?(?P<name>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>[A-Za-z]+)\s+"
    r"(?P<case>[\d,]+\.\d{2})\s+"
    r"(?P<bottle>[\d,]+\.\d{2})\s*$"
)
ORPHAN_ROW_RE = re.compile(
    r"^(?P<qty>\d+(?:\.\d+)?)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>[A-Za-z]+)\s+"
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
]

named_matches = 0
orphan_matches = 0
unmatched_lines = []
categories_seen = []
all_named_rows = []
all_orphan_rows = []

with pdfplumber.open(PDF_PATH) as pdf:
    total_pages = len(pdf.pages)
    for pi, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        current_category = None
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if any(p.search(line) for p in SKIP_PATTERNS):
                continue
            cat_match = CATEGORY_RE.match(line)
            if cat_match:
                current_category = cat_match.group(1).strip()
                categories_seen.append((pi + 1, current_category))
                continue
            m = NAMED_ROW_RE.match(line)
            if m:
                named_matches += 1
                all_named_rows.append((pi + 1, current_category, m.groupdict(), line))
                continue
            m2 = ORPHAN_ROW_RE.match(line)
            if m2:
                orphan_matches += 1
                all_orphan_rows.append((pi + 1, current_category, m2.groupdict(), line))
                continue
            unmatched_lines.append((pi + 1, current_category, line))

print(f"Total pages: {total_pages}")
print(f"Named product rows matched: {named_matches}")
print(f"Orphan (size/price only, no name) rows: {orphan_matches}")
print(f"Unmatched lines: {len(unmatched_lines)}")
print(f"\nCategories seen ({len(categories_seen)}):")
for pg, cat in categories_seen:
    print(f"  page {pg}: {cat}")

print("\n--- Sample of 15 named rows ---")
for row in all_named_rows[:15]:
    print(row)

print("\n--- All orphan rows (need brand-name backfill) ---")
for row in all_orphan_rows:
    print(row)

print("\n--- Unmatched lines (needs review) ---")
for row in unmatched_lines:
    print(row)
