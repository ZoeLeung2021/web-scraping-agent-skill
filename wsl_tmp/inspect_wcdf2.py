import os
import time
from bs4 import BeautifulSoup
import undetected_chromedriver as uc

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

driver = uc.Chrome(options=options, browser_executable_path=chrome_bin, driver_executable_path=driver_path)
driver.set_page_load_timeout(60)

# First get homepage and find the exact href for "Liquor" nav item
driver.get("https://westcoastdutyfree.com/")
time.sleep(4)
soup = BeautifulSoup(driver.page_source, "html.parser")
for a in soup.find_all("a", href=True):
    txt = a.get_text(strip=True)
    if txt.lower() in ("liquor", "specials", "products", "new arrivals", "liquor specials"):
        print("NAV LINK:", txt, "->", a["href"])

candidate_urls = [
    "https://westcoastdutyfree.com/liquor/",
    "https://westcoastdutyfree.com/products/liquor/",
    "https://westcoastdutyfree.com/product-category/liquor/",
    "https://westcoastdutyfree.com/liquor-specials/",
    "https://westcoastdutyfree.com/products/",
    "https://westcoastdutyfree.com/new-arrivals/",
]

for url in candidate_urls:
    print("=" * 80)
    print("URL:", url)
    try:
        driver.get(url)
        time.sleep(5)
        print("Final URL:", driver.current_url)
        print("Title:", driver.title)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        text = soup.get_text(" ", strip=True)
        print("Text length:", len(text))
        print(text[:2000])
        # Look for price-like patterns
        import re
        prices = re.findall(r"\$\s?\d+[\.,]\d{2}", text)
        print("Price-like matches (first 20):", prices[:20], "count=", len(prices))
    except Exception as e:
        print("ERROR:", e)

driver.quit()
