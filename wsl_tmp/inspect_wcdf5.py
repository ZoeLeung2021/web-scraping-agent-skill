import os
import time
from bs4 import BeautifulSoup
import undetected_chromedriver as uc

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")

chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
driver_path = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")

driver = uc.Chrome(options=options, browser_executable_path=chrome_bin, driver_executable_path=driver_path)
driver.set_page_load_timeout(60)

for url in ["https://westcoastdutyfree.com/", "https://westcoastdutyfree.com/products/"]:
    driver.get(url)
    time.sleep(4)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    text = soup.get_text(" ", strip=True)
    print("="*80)
    print(url, "FULL TEXT LEN", len(text))
    print(text)
    print()

# grep whole home page html for "exclusive" case-insensitive and "%" discount and currency symbols
driver.get("https://westcoastdutyfree.com/")
time.sleep(3)
html = driver.page_source
for kw in ["xclusive", "CAD", "USD", "sale", "discount", "line-through", "<del", "off"]:
    idx = html.lower().find(kw.lower())
    print(f"kw={kw!r} found_at={idx}")
    if idx != -1:
        print("   context:", html[max(0,idx-100):idx+100])

driver.quit()
