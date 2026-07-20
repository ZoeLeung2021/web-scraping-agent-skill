import sys
sys.path.insert(0, "/home/zoeliang")

import re
import time
import os
from bs4 import BeautifulSoup
import undetected_chromedriver as uc

BASE_URL = "https://westcoastdutyfree.com"
_WP_IMAGE_ID_RE = re.compile(r"wp-image-(\d+)")
_PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{1,2})?")

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

url = f"{BASE_URL}/liquor-specials/"
driver.get(url)
time.sleep(5)

soup = BeautifulSoup(driver.page_source, "html.parser")
cards = soup.find_all("div", class_="elementor-image-box-wrapper")
print(f"Found {len(cards)} product cards on {url}")

products = []
ids = set()
for card in cards:
    img = card.find("img")
    classes = " ".join(img.get("class", [])) if img else ""
    m = _WP_IMAGE_ID_RE.search(classes)
    wp_id = m.group(1) if m else None

    title_el = card.find("h6", class_="elementor-image-box-title")
    title = title_el.get_text(strip=True) if title_el else None

    desc_el = card.find("p", class_="elementor-image-box-description")
    desc_text = desc_el.get_text(" ", strip=True) if desc_el else ""
    price_match = _PRICE_RE.search(desc_text)
    price = price_match.group(0) if price_match else None

    product_link = f"{url}#wp-image-{wp_id}" if wp_id else url

    products.append({
        "ID": wp_id,
        "Title": title,
        "Price": price,
        "RawDesc": desc_text,
        "Product_link": product_link,
    })
    ids.add(wp_id)

print(f"\nUnique IDs: {len(ids)} (out of {len(products)} rows)")
print("\nFull product list:")
for p in products:
    print(f"  ID={p['ID']:>5}  {p['Title']:<32}  Price={p['Price']!s:<8}  RawDesc={p['RawDesc']!r}")

# sanity check: any missing ID / title / price?
missing = [p for p in products if not p["ID"] or not p["Title"] or not p["Price"]]
print(f"\nRows with missing ID/Title/Price: {len(missing)}")
for p in missing:
    print(" ", p)

driver.quit()
