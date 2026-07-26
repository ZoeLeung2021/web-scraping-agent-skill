import os, time, json
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc

chrome_bin = os.getenv("CHROME_BIN")
driver_path = os.getenv("CHROMEDRIVER_PATH")

options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1400,2000")

driver = uc.Chrome(options=options, browser_executable_path=chrome_bin, driver_executable_path=driver_path)
try:
    url = "https://www.kingpower-cn.com/search?cat=48&type=cat"
    driver.get(url)
    time.sleep(6)
    print("TITLE:", driver.title)
    print("URL:", driver.current_url)

    # Try to find any age gate / popup / cookie banner
    print("\n--- BODY TEXT (first 3000 chars) ---")
    body_text = driver.find_element(By.TAG_NAME, "body").text
    print(body_text[:3000])

    print("\n--- PAGE SOURCE LENGTH ---", len(driver.page_source))
    with open("/home/zoeliang/kingpower_cat48_page1.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)

    # look for nav / category menu
    print("\n--- Looking for category/nav links ---")
    links = driver.find_elements(By.TAG_NAME, "a")
    seen = set()
    for l in links:
        try:
            href = l.get_attribute("href")
            text = l.text.strip()
            if href and ("cat=" in href or "search" in href) and text:
                key = (href, text)
                if key not in seen:
                    seen.add(key)
        except Exception:
            pass
    for href, text in list(seen)[:80]:
        print(text, "->", href)

finally:
    driver.quit()
