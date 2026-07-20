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

def all_ids_for_category(path, max_pages=10):
    """Collect ALL product ids across every pager page for this category."""
    url = f"{BASE}/{path}"
    driver.get(url)
    time.sleep(5)
    accept_cookies()
    time.sleep(4)
    all_ids = {}
    page = 1
    while page <= max_pages:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = soup.select(".grid-product")
        for c in cards:
            pid = None
            for cl in c.get("class", []):
                if cl.startswith("grid-product--id-"):
                    pid = cl.replace("grid-product--id-", "")
            title_el = c.select_one(".grid-product__title")
            title = title_el.get_text(strip=True) if title_el else None
            if pid:
                all_ids[pid] = title
        next_btn = driver.find_elements(By.CSS_SELECTOR, ".pager__button--next")
        if not next_btn or "pager__body--has-next" not in (next_btn[0].find_element(By.XPATH, "..").get_attribute("class") or ""):
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView();", next_btn[0])
            time.sleep(0.5)
            next_btn[0].click()
            time.sleep(4)
            page += 1
        except Exception:
            break
    return all_ids

pairs_to_check = [
    ("rum", "made-in-the-bahamas-spirits"),
    ("vodka", "flavored-vodka"),
    ("merlota37f80c5", "kosher"),
    ("vodka", "made-in-the-bahamas-spirits"),
    ("rum", "ready-to-drink-spirits"),
]

results_cache = {}
def get_cached(path):
    if path not in results_cache:
        results_cache[path] = all_ids_for_category(path)
        print(f"[{path}] total ids collected: {len(results_cache[path])}")
    return results_cache[path]

for a, b in pairs_to_check:
    ia = get_cached(a)
    ib = get_cached(b)
    inter = set(ia.keys()) & set(ib.keys())
    print(f"OVERLAP {a} ({len(ia)}) vs {b} ({len(ib)}): {len(inter)}")
    for pid in list(inter)[:5]:
        print("   ", pid, ia.get(pid) or ib.get(pid))

driver.quit()
