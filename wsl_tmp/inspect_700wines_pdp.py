import os
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

driver.get("https://www.700winesandspirits.com/main_shop/Ron-Ricardo-Gold-*-1L-p597056497")
time.sleep(5)
accept_cookies()
time.sleep(4)
html = driver.page_source
with open(os.path.expanduser("~/700wines_pdp.html"), "w", encoding="utf-8") as f:
    f.write(html)
soup = BeautifulSoup(html, "html.parser")
price_area = soup.select_one("[class*='details-product__price'], [class*='product-details__price'], [class*='price']")
print("price area html snippet:")
els = soup.select("[class*='price']")
for e in els[:15]:
    print(e.get("class"), "|", e.get_text(strip=True)[:60])

badge_els = soup.select("[class*='badge'], [class*='label'], [class*='tag']")
for e in badge_els[:15]:
    print("BADGE:", e.get("class"), "|", e.get_text(strip=True)[:60])

driver.quit()
