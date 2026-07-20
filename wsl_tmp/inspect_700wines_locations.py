import os
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
driver.get("https://www.700winesandspirits.com/location")
time.sleep(5)
candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::div][contains(translate(text(), 'ACEPT', 'acept'), 'accept')]")
for el in candidates:
    try:
        if el.text.strip().lower() == "accept" and el.is_displayed():
            el.click(); break
    except Exception:
        pass
time.sleep(4)

links = driver.find_elements(By.XPATH, "//a[contains(text(),'Start Shopping') or contains(text(),'SHOP ONLINE')]")
print("found", len(links), "shopping links")
for a in links:
    print(a.text, "->", a.get_attribute("href"))

driver.quit()
