import os
import re
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

CHROME_BIN = os.path.expanduser("~/chrome-for-testing/chrome-linux64/chrome")
CHROMEDRIVER_PATH = os.path.expanduser("~/chrome-for-testing/chromedriver-linux64/chromedriver")

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

driver = uc.Chrome(options=options, browser_executable_path=CHROME_BIN, driver_executable_path=CHROMEDRIVER_PATH)
driver.set_page_load_timeout(60)

url = "https://www.700winesandspirits.com/rum"
driver.get(url)
time.sleep(8)

html = driver.page_source
with open(os.path.expanduser("~/700wines_rum.html"), "w", encoding="utf-8") as f:
    f.write(html)

print("TITLE:", driver.title, "bytes:", len(html))

# Look for ecwid store id patterns
m = re.findall(r"storeid[\"'=:\s]*([0-9]{5,12})", html, re.IGNORECASE)
print("storeid matches:", set(m))
m2 = re.findall(r"store_id[\"'=:\s]*([0-9]{5,12})", html, re.IGNORECASE)
print("store_id matches:", set(m2))
m3 = re.findall(r"data-store-id=\"([0-9]+)\"", html)
print("data-store-id:", set(m3))
m4 = re.findall(r"ecwid[_-]?store[_-]?id[\"'=:\s]*([0-9]{5,12})", html, re.IGNORECASE)
print("ecwid store id:", set(m4))
m5 = re.findall(r"app\.ecwid\.com[^\"'\s]*", html)
print("ecwid app urls (sample):", list(set(m5))[:10])

# try to find product grid items
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "html.parser")
grid_items = soup.select("[class*='grid-product'], [class*='ProductBrowserItem'], [class*='product-item'], .ec-store__product")
print("grid_items count (various selectors):", len(grid_items))

# Look for "results" or "showing" text with counts
text = soup.get_text(" ", strip=True)
count_matches = re.findall(r"(\d+)\s+(?:results|products|items)\b", text, re.IGNORECASE)
print("count text matches:", count_matches)

# check pagination controls
pag = soup.select("[class*='pagination'], [class*='page-'], a[href*='page=']")
print("pagination-ish elements:", len(pag))
for p in pag[:20]:
    print(" ->", p.get("class"), p.get("href"))

driver.quit()
