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

pages = [
    ("about", "https://www.700winesandspirits.com/about"),
    ("location", "https://www.700winesandspirits.com/location"),
    ("contact", "https://www.700winesandspirits.com/contact"),
    ("faqs", "https://www.700winesandspirits.com/faqs"),
    ("placing_order", "https://www.700winesandspirits.com/placing-an-order"),
]

for name, url in pages:
    try:
        driver.get(url)
    except Exception as e:
        print(name, "get() raised:", e)
        continue
    time.sleep(4)
    print(f"=== {name} ({url}) ===")
    print("TITLE:", driver.title)
    body_text = driver.find_element(By.TAG_NAME, "body").text
    print(body_text[:3000])
    print()

driver.quit()
