import pdfplumber
import fitz  # pymupdf
import pypdf

PDF_PATH = "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/GLL_Price_List_VAT.pdf"

print("=" * 30, "PDFPLUMBER raw text page 1-2", "=" * 30)
with pdfplumber.open(PDF_PATH) as pdf:
    print("num pages:", len(pdf.pages))
    for i in range(min(2, len(pdf.pages))):
        page = pdf.pages[i]
        text = page.extract_text()
        print(f"--- page {i+1} extract_text ---")
        print(text)
        print(f"--- page {i+1} extract_table ---")
        table = page.extract_table()
        print(table)

print("\n" + "=" * 30, "PYMUPDF (fitz) raw text page 1-2", "=" * 30)
doc = fitz.open(PDF_PATH)
print("num pages:", doc.page_count)
for i in range(min(2, doc.page_count)):
    page = doc[i]
    print(f"--- page {i+1} get_text ---")
    print(page.get_text())

print("\n" + "=" * 30, "PYMUPDF get_text('words') sample page1", "=" * 30)
words = doc[0].get_text("words")
print("num words:", len(words))
for w in words[:40]:
    print(w)
