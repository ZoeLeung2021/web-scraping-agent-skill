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
    clicked = False
    for el in candidates:
        try:
            if el.text.strip().lower() == "accept" and el.is_displayed():
                el.click()
                clicked = True
                break
        except Exception:
            pass
    return clicked

def ecwid_script_type():
    soup = BeautifulSoup(driver.page_source, "html.parser")
    s = soup.select_one("script#ecwid-script")
    return s.get("type") if s else "NOTFOUND"

driver.get(BASE + "/rum")
time.sleep(4)
print("before accept, ecwid-script type:", ecwid_script_type())
clicked = accept_cookies()
print("clicked accept:", clicked)
time.sleep(6)
print("after accept, ecwid-script type:", ecwid_script_type())
print("cookies:", [c["name"] for c in driver.get_cookies()])

soup = BeautifulSoup(driver.page_source, "html.parser")
cards = soup.select(".grid-product")
print("rum cards after accept (same page, no nav):", len(cards))

# Now navigate to another category WITHOUT clicking accept again
driver.get(BASE + "/vodka")
time.sleep(6)
print("vodka ecwid-script type:", ecwid_script_type())
soup2 = BeautifulSoup(driver.page_source, "html.parser")
cards2 = soup2.select(".grid-product")
print("vodka cards:", len(cards2))
