import os
import re
import time
import json
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

def all_ids_titles(path, max_pages=10):
    driver.get(f"{BASE}/{path}")
    time.sleep(5)
    accept_cookies()
    time.sleep(4)
    real_title = driver.title
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
        next_btns = driver.find_elements(By.CSS_SELECTOR, ".pager__button--next")
        has_next = False
        if next_btns:
            parent_class = next_btns[0].find_element(By.XPATH, "..").get_attribute("class") or ""
            has_next = "pager__body--has-next" in parent_class
        if not has_next:
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView();", next_btns[0])
            time.sleep(0.5)
            next_btns[0].click()
            time.sleep(4)
            page += 1
        except Exception:
            break
    return real_title, all_ids

WINE_LEAVES = [
    "red-blends", "malbec", "pinot-noir", "pinot-noir254399a8", "merlota37f80c5",
    "kosher", "sangria", "moscatoaaa1c01c", "zinfandel", "chardonnay", "moscato",
    "moscato0df5aee4", "riesling", "sauvignon-blanc", "white-blend", "champagne",
    "sparking-rose", "prosecco", "rose",
]
BEER_LEAVES = ["light78599f84", "stout", "lager", "ipa"]
BEER_CROSSCUT = ["made-in-the-bahamas-beer", "all-beers", "non-alcoholic-beer"]
SPIRITS_LEAVES = ["whiskey7ec914dc", "vodka", "rum", "tequila", "gin", "liqueur", "brandy", "ready-to-drink-spirits"]
SPIRITS_CROSSCUT = ["made-in-the-bahamas-spirits", "flavored-vodka", "all-brands-spirits"]

data = {}
for group_name, paths in [("WINE", WINE_LEAVES), ("BEER", BEER_LEAVES), ("BEER_CROSSCUT", BEER_CROSSCUT),
                          ("SPIRITS", SPIRITS_LEAVES), ("SPIRITS_CROSSCUT", SPIRITS_CROSSCUT)]:
    print(f"\n### {group_name} ###")
    for p in paths:
        try:
            title, ids = all_ids_titles(p)
            data[p] = ids
            print(f"{p}: title={title!r} n={len(ids)}")
        except Exception as e:
            print(f"{p}: ERROR {e}")

print("\n### CROSS-CHECKS ###")
beer_union = set()
for p in BEER_LEAVES:
    beer_union |= set(data.get(p, {}).keys())
print("beer style-leaves union size:", len(beer_union))
for p in BEER_CROSSCUT:
    ids = set(data.get(p, {}).keys())
    inter = ids & beer_union
    print(f"{p}: n={len(ids)} overlap_with_style_union={len(inter)} only_in_crosscut={len(ids-beer_union)}")

spirits_union = set()
for p in SPIRITS_LEAVES:
    spirits_union |= set(data.get(p, {}).keys())
print("spirits style-leaves union size:", len(spirits_union))
for p in SPIRITS_CROSSCUT:
    ids = set(data.get(p, {}).keys())
    inter = ids & spirits_union
    print(f"{p}: n={len(ids)} overlap_with_style_union={len(inter)} only_in_crosscut={len(ids-spirits_union)}")

# check any duplicate ids across wine leaves themselves (should be none if truly non-overlapping)
seen = {}
dupe_count = 0
for p in WINE_LEAVES:
    for pid in data.get(p, {}):
        if pid in seen:
            dupe_count += 1
            print("WINE DUPLICATE:", pid, "in", seen[pid], "and", p)
        seen[pid] = p
print("wine total unique ids across leaves:", len(seen), "dupe instances:", dupe_count)

with open(os.path.expanduser("~/700wines_final_data.json"), "w") as f:
    json.dump({k: v for k, v in data.items()}, f)

driver.quit()
