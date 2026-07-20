import pdfplumber

PDF_PATH = "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/the-exclusive-coll.pdf"
with pdfplumber.open(PDF_PATH) as pdf:
    print("num pages:", len(pdf.pages))
    for i in range(min(4, len(pdf.pages))):
        text = pdf.pages[i].extract_text() or ""
        print(f"--- page {i+1} ---")
        print(text[:1500])
        print()
