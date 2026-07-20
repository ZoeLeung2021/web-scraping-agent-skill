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

paths = ["pinot-noir", "pinot-noir254399a8", "moscato", "moscato0df5aee4", "moscatoaaa1c01c"]
for p in paths:
    driver.get(f"{BASE}/{p}")
    time.sleep(5)
    accept_cookies()
    time.sleep(4)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    cards = soup.select(".grid-product")
    titles = [c.select_one(".grid-product__title").get_text(strip=True) for c in cards if c.select_one(".grid-product__title")]
    print(f"=== /{p} === driver.title={driver.title!r} cards={len(cards)}")
    for t in titles[:6]:
        print("   ", t)

driver.quit()
