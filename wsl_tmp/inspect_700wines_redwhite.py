import os
import re
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

CHROME_BIN = os.path.expanduser("~/chrome-for-testing/chrome-linux64/chrome")
CHROMEDRIVER_PATH = os.path.expanduser("~/chrome-for-testing/chromedriver-linux64/chromedriver")

def make_driver():
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    d = uc.Chrome(options=options, browser_executable_path=CHROME_BIN, driver_executable_path=CHROMEDRIVER_PATH)
    d.set_page_load_timeout(60)
    return d

def accept_cookies(driver):
    candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::div][contains(translate(text(), 'ACEPT', 'acept'), 'accept')]")
    for el in candidates:
        try:
            if el.text.strip().lower() == "accept" and el.is_displayed():
                el.click()
                return True
        except Exception:
            pass
    return False

BASE = "https://www.700winesandspirits.com"

for path in ["red", "white", "merlot", "wine-home", "all-brands"]:
    driver = make_driver()
    try:
        driver.get(f"{BASE}/{path}")
        time.sleep(5)
        accept_cookies(driver)
        time.sleep(6)
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".grid-product")
        text = soup.get_text(" ", strip=True)
        print(f"=== {path} === cards={len(cards)} url={driver.current_url} len={len(html)}")
        # look for any hint of empty category or different structure
        if "No products" in text or "no results" in text.lower():
            print("  -> appears EMPTY category message found")
        # look for tile/link elements suggesting a hub page
        tiles = soup.select("[class*='tile'], [class*='category-card'], [class*='collection-card']")
        print("  tile-like elements:", len(tiles))
        with open(os.path.expanduser(f"~/700wines_{path.replace('-','_')}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        print(f"{path}: ERROR {e}")
    finally:
        driver.quit()
