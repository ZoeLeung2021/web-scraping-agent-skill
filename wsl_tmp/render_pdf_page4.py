import fitz

PDF_PATH = "/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/GLL_Price_List_VAT.pdf"
doc = fitz.open(PDF_PATH)
for i in [4, 8, 11]:  # pages 5, 9, 12
    page = doc[i]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    out_path = f"/mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/gll_page_{i+1}.png"
    pix.save(out_path)
    print("saved", out_path)
