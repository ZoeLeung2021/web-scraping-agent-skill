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

BASE = "https://www.700winesandspirits.com"

def accept_cookies():
    candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::div][contains(translate(text(), 'ACEPT', 'acept'), 'accept')]")
    for el in candidates:
        try:
            if el.text.strip().lower() == "accept" and el.is_displayed():
                el.click()
                return True
        except Exception:
            pass
    return False

driver.get(f"{BASE}/featured-deals")
time.sleep(5)
accept_cookies()
time.sleep(5)
html = driver.page_source
with open(os.path.expanduser("~/700wines_deals.html"), "w", encoding="utf-8") as f:
    f.write(html)
soup = BeautifulSoup(html, "html.parser")
cards = soup.select(".grid-product")
print("featured-deals cards:", len(cards))
for c in cards[:8]:
    print("----")
    print(str(c.select_one(".grid-product__price"))[:600] if c.select_one(".grid-product__price") else "no price el")

# check for sale/old-price/compare classes sitewide on this page
text = html.lower()
for kw in ["old-price", "compare", "was $", "sale-badge", "discount", "strikethrough", "line-through", "exclusive", "badge"]:
    print(kw, "->", text.count(kw))

driver.quit()
