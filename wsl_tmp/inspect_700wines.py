import os
import time
import undetected_chromedriver as uc

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
try:
    driver.get("https://www.700winesandspirits.com/")
except Exception as e:
    print("get() raised:", e)
time.sleep(6)

print("TITLE:", driver.title, "url:", driver.current_url, "bytes:", len(driver.page_source))

with open(os.path.expanduser("~/700wines_home.html"), "w", encoding="utf-8") as f:
    f.write(driver.page_source)

# Try to find nav links
from selenium.webdriver.common.by import By
links = driver.find_elements(By.TAG_NAME, "a")
seen = set()
print("---LINKS---")
for a in links:
    try:
        href = a.get_attribute("href")
        text = a.text.strip()
    except Exception:
        continue
    if href and href not in seen and ("700winesandspirits.com" in href or href.startswith("/")):
        seen.add(href)
        print(text, "|", href)

driver.quit()
