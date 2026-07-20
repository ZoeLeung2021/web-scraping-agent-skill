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

# Try to find and click the Accept button for cookie consent
clicked = False
candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::div][contains(translate(text(), 'ACEPT', 'acept'), 'accept')]")
print("candidate accept elements:", len(candidates))
for el in candidates:
    try:
        txt = el.text.strip()
        if txt.lower() == "accept":
            el.click()
            clicked = True
            print("Clicked element with text:", txt)
            break
    except Exception as e:
        print("click failed:", e)

if not clicked:
    # try termly specific id
    try:
        btn = driver.find_element(By.ID, "termly-code-snippet-support")
        print("found termly snippet support element")
    except Exception:
        pass
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "[id*='termly'] button, .t-preferences-btn, .accept-button, [class*='accept']")
        btn.click()
        clicked = True
        print("Clicked fallback accept button")
    except Exception as e:
        print("fallback click failed:", e)

print("clicked:", clicked)
time.sleep(6)

html = driver.page_source
with open(os.path.expanduser("~/700wines_rum_afterconsent.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("bytes after consent:", len(html))

soup = BeautifulSoup(html, "html.parser")
grid_items = soup.select("[class*='grid-product'], [class*='ProductBrowserItem'], [class*='product-item'], .ec-store__product, [class*='ecwid']")
print("grid_items count:", len(grid_items))
text = soup.get_text(" ", strip=True)
count_matches = re.findall(r"(\d+)\s+(?:results|products|items)\b", text, re.IGNORECASE)
print("count text matches:", count_matches)

# check if ecwid script now active (not text/plain)
scripts = soup.select("script#ecwid-script")
for s in scripts:
    print("ecwid-script type attr:", s.get("type"), "src:", s.get("src"))

driver.quit()
