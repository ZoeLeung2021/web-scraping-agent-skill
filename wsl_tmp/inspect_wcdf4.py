import time
import undetected_chromedriver as uc
import os

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")

chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

driver = uc.Chrome(options=options, browser_executable_path=chrome_bin, driver_executable_path=driver_path)
driver.set_page_load_timeout(60)

import re

for sm in ["page-sitemap.xml", "post-sitemap.xml", "category-sitemap.xml"]:
    driver.get(f"https://westcoastdutyfree.com/{sm}")
    time.sleep(2)
    src = driver.page_source
    locs = re.findall(r"<loc>(.*?)</loc>", src)
    print(f"=== {sm} ({len(locs)} urls) ===")
    for l in locs:
        print(" ", l)

driver.quit()
