import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

BASE_URL = "http://www.gonsalvesliquors.com"
TARGET = f"{BASE_URL}/prices.php"

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

print("=== Fetching homepage ===")
try:
    driver.get(BASE_URL + "/")
    time.sleep(3)
    print("HOMEPAGE TITLE:", driver.title)
    print("HOMEPAGE URL after load:", driver.current_url)
    print("HOMEPAGE length:", len(driver.page_source))
except Exception as e:
    print("HOMEPAGE ERROR:", e)

print("\n=== Fetching prices.php ===")
try:
    driver.get(TARGET)
    time.sleep(3)
    print("PRICES TITLE:", driver.title)
    print("PRICES URL after load:", driver.current_url)
    src = driver.page_source
    print("PRICES page_source length:", len(src))
    print("PRICES page_source first 3000 chars:")
    print(src[:3000])
except Exception as e:
    print("PRICES ERROR:", e)

print("\n=== Looking for PDF links/embeds anywhere ===")
try:
    for tag, attr in [("a", "href"), ("embed", "src"), ("iframe", "src"), ("object", "data")]:
        els = driver.find_elements(By.TAG_NAME, tag)
        for el in els:
            val = el.get_attribute(attr)
            if val and (".pdf" in val.lower() or "price" in val.lower()):
                print(f"{tag}[{attr}] =", val)
except Exception as e:
    print("LINK SCAN ERROR:", e)

driver.quit()
print("\nDONE")
