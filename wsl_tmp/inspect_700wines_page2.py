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

soup1 = BeautifulSoup(driver.page_source, "html.parser")
cards1 = soup1.select(".grid-product")
ids1 = [c.get("class")[1].replace("grid-product--id-", "") for c in cards1 if len(c.get("class",[]))>1]
print("PAGE1 url:", driver.current_url)
print("PAGE1 count:", len(cards1), "ids sample:", ids1[:5])

pager_numbers = soup1.select(".pager__number")
print("pager numbers:", [ (p.get_text(strip=True), p.get("data-page-number")) for p in pager_numbers])

# click Next
next_btn = driver.find_element(By.CSS_SELECTOR, ".pager__button--next")
driver.execute_script("arguments[0].scrollIntoView();", next_btn)
time.sleep(1)
next_btn.click()
time.sleep(5)

print("AFTER CLICK url:", driver.current_url)
soup2 = BeautifulSoup(driver.page_source, "html.parser")
cards2 = soup2.select(".grid-product")
ids2 = [c.get("class")[1].replace("grid-product--id-", "") for c in cards2 if len(c.get("class",[]))>1]
print("PAGE2 count:", len(cards2), "ids sample:", ids2[:5])
print("overlap between page1 and page2 ids:", set(ids1) & set(ids2))

# Now try navigating directly to a URL with page param to see if it resets to page1 content
test_url = driver.current_url
print("Testing direct GET of current_url in new load...")
driver.get(test_url)
time.sleep(5)
soup3 = BeautifulSoup(driver.page_source, "html.parser")
cards3 = soup3.select(".grid-product")
ids3 = [c.get("class")[1].replace("grid-product--id-", "") for c in cards3 if len(c.get("class",[]))>1]
print("PAGE via direct nav to same URL count:", len(cards3), "ids sample:", ids3[:5])
print("matches page2 ids (direct nav preserved state?):", set(ids2) == set(ids3))
print("matches page1 ids (direct nav reset to page1?):", set(ids1) == set(ids3))

driver.quit()
