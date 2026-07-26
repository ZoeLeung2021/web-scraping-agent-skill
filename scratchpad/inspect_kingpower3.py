import os, time, re
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

chrome_bin = os.getenv("CHROME_BIN")
driver_path = os.getenv("CHROMEDRIVER_PATH")

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1400,2000")

driver = uc.Chrome(options=options, browser_executable_path=chrome_bin, driver_executable_path=driver_path)

def snapshot(label):
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    m = re.search(r"结果\((\d+)\)", text)
    total = m.group(1) if m else None
    ids = re.findall(r'data-common-id="(\d+)"', html)
    prices = re.findall(r'class="price_1"[^>]*>\s*([\d.]+)\s*THB', html)
    print(f"[{label}] total={total} n_ids={len(ids)} first5ids={ids[:5]} first5prices={prices[:5]}")
    return total, ids, prices

try:
    driver.get("https://www.kingpower-cn.com/search?cat=48&type=cat")
    time.sleep(4)
    snapshot("baseline-suvarnabhumi(default)")

    # Try to open the airport switcher and pick Don Mueang (廊曼机场)
    try:
        btn = driver.find_element(By.ID, "selectDeliveryTypeBtn")
        btn.click()
        time.sleep(1)
        print("Clicked selectDeliveryTypeBtn OK")
    except Exception as e:
        print("Could not click selectDeliveryTypeBtn:", e)

    try:
        donmueang = driver.find_element(By.XPATH, "//div[contains(@class,'airportGroupBtn') and contains(text(),'廊曼机场')]")
        donmueang.click()
        time.sleep(2)
        print("Clicked Don Mueang airport group OK")
    except Exception as e:
        print("Could not click Don Mueang group:", e)

    # there might be a confirm/submit button after selecting
    try:
        confirm_candidates = driver.find_elements(By.XPATH, "//*[contains(text(),'确定') or contains(text(),'确认')]")
        print("confirm candidates found:", len(confirm_candidates))
        for c in confirm_candidates[:3]:
            try:
                print(" -> trying click on:", c.text)
                c.click()
                time.sleep(2)
                break
            except Exception as ce:
                print("   click failed:", ce)
    except Exception as e:
        print("confirm search failed:", e)

    time.sleep(2)
    print("URL after switch attempt:", driver.current_url)
    driver.get("https://www.kingpower-cn.com/search?cat=48&type=cat")
    time.sleep(4)
    snapshot("after-switch-attempt-donmueang")

finally:
    driver.quit()
