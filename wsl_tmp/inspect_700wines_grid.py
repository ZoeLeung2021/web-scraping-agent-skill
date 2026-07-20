import os
import re
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

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
time.sleep(4)

candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::div][contains(translate(text(), 'ACEPT', 'acept'), 'accept')]")
for el in candidates:
    try:
        if el.text.strip().lower() == "accept":
            el.click()
            break
    except Exception:
        pass
time.sleep(6)

# scroll to bottom to trigger lazy load / pagination widget
driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
time.sleep(3)

html = driver.page_source
with open(os.path.expanduser("~/700wines_rum_grid.html"), "w", encoding="utf-8") as f:
    f.write(html)

soup = BeautifulSoup(html, "html.parser")

# Find the results/count text
text = soup.get_text(" ", strip=True)
idx = text.find("result")
print("context around 'result':", text[max(0,idx-80):idx+40])

# product cards
cards = soup.select(".grid-product")
print("num .grid-product cards:", len(cards))
for c in cards[:5]:
    title_el = c.select_one(".grid-product__title")
    price_el = c.select_one(".grid-product__price")
    sku_el = c.select_one(".grid-product__sku")
    link_el = c.select_one("a")
    print("----")
    print("title:", title_el.get_text(strip=True) if title_el else None)
    print("price:", price_el.get_text(" ", strip=True) if price_el else None)
    print("sku:", sku_el.get_text(strip=True) if sku_el else None)
    print("href:", link_el.get("href") if link_el else None)
    print("classes:", c.get("class"))

# pagination
pag_candidates = soup.select("[class*='pagination'], [class*='Pagination'], a[href*='page']")
print("pagination candidates:", len(pag_candidates))
for p in pag_candidates[:10]:
    print(" ->", p.get("class"), p.get_text(strip=True)[:30], p.get("href"))

# look for "load more" button text
load_more = [b for b in soup.find_all(["button","a","div"]) if b.get_text(strip=True).lower() in ("load more", "show more", "next")]
print("load more candidates:", [b.get_text(strip=True) for b in load_more])

driver.quit()
