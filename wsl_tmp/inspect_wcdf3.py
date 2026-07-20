import os
import time
from bs4 import BeautifulSoup
import undetected_chromedriver as uc

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

driver.get("https://westcoastdutyfree.com/liquor-specials/")
time.sleep(5)

with open("/home/zoeliang/wcdf_liquor_specials.html", "w", encoding="utf-8") as f:
    f.write(driver.page_source)

soup = BeautifulSoup(driver.page_source, "html.parser")

# Try to find repeating structure / cards
print("Looking for common container classes...")
from collections import Counter
class_counter = Counter()
for tag in soup.find_all(True):
    classes = tag.get("class")
    if classes:
        class_counter[" ".join(classes)] += 1

for cls, count in class_counter.most_common(30):
    print(count, cls)

print("\n\n--- Checking sitemap.xml ---")
driver.get("https://westcoastdutyfree.com/sitemap.xml")
time.sleep(3)
print(driver.page_source[:5000])

print("\n\n--- Checking wp sitemap index ---")
driver.get("https://westcoastdutyfree.com/sitemap_index.xml")
time.sleep(3)
print(driver.page_source[:3000])

driver.quit()
