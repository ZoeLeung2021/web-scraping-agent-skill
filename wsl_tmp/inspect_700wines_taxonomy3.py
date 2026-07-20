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
    for el in candidates:
        try:
            if el.text.strip().lower() == "accept" and el.is_displayed():
                el.click()
                return True
        except Exception:
            pass
    return False

def get_ids_and_meta(path, retries=2):
    url = f"{BASE}/{path}"
    for attempt in range(retries + 1):
        driver.get(url)
        time.sleep(5)
        accept_cookies()
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select(".grid-product")
        if cards:
            break
        time.sleep(3)
    ids = set()
    for c in cards:
        for cl in c.get("class", []):
            if cl.startswith("grid-product--id-"):
                ids.add(cl.replace("grid-product--id-", ""))
    pager_numbers = [p.get_text(strip=True) for p in soup.select(".pager__number")]
    cur_url = driver.current_url
    catid_m = re.search(r"-c(\d+)", cur_url)
    catid = catid_m.group(1) if catid_m else None
    return {
        "path": path, "current_url": cur_url, "catid": catid,
        "num_cards": len(cards), "ids": ids, "pager_numbers": pager_numbers,
    }

paths = [
    "wine-home", "spirits-home", "beer-main", "all-brands",
    "rum", "vodka", "kosher", "merlot", "red", "white",
    "all-brands-spirits", "all-beers", "gin",
]

results = {}
for p in paths:
    try:
        r = get_ids_and_meta(p)
        results[p] = r
        print(f"{p}: catid={r['catid']} cards={r['num_cards']} pages={r['pager_numbers']} url={r['current_url']}")
    except Exception as e:
        print(f"{p}: ERROR {e}")

print("\n--- OVERLAP CHECKS ---")
def overlap(a, b):
    if a in results and b in results:
        ia, ib = results[a]["ids"], results[b]["ids"]
        inter = ia & ib
        print(f"{a} ({len(ia)}) vs {b} ({len(ib)}): overlap={len(inter)} sample={list(inter)[:5]}")

overlap("merlot", "kosher")
overlap("merlot", "red")
overlap("rum", "all-brands-spirits")
overlap("rum", "all-brands")
overlap("wine-home", "merlot")
overlap("wine-home", "red")
overlap("spirits-home", "rum")
overlap("spirits-home", "vodka")
overlap("beer-main", "all-beers")

driver.quit()
