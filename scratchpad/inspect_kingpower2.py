import os, time, re, json
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

def load(url):
    driver.get(url)
    time.sleep(4)
    return driver.page_source

def count_and_ids(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    m = re.search(r"结果\((\d+)\)", text)
    total = m.group(1) if m else None
    # find product links - guess pattern
    links = soup.find_all("a", href=True)
    prod_links = [a["href"] for a in links if re.search(r"/(item|product|goods|detail)", a["href"], re.I)]
    return total, prod_links, soup

try:
    for label, url in [
        ("cat48_p1", "https://www.kingpower-cn.com/search?cat=48&type=cat"),
        ("cat48_p2", "https://www.kingpower-cn.com/search?cat=48&type=cat&page=2"),
        ("cat268_wine_p1", "https://www.kingpower-cn.com/search?cat=268&type=cat"),
        ("cat269_liquor_p1", "https://www.kingpower-cn.com/search?cat=269&type=cat"),
        ("cat270_coffee_p1", "https://www.kingpower-cn.com/search?cat=270&type=cat"),
        ("cat271_other_p1", "https://www.kingpower-cn.com/search?cat=271&type=cat"),
        ("cat272_nonalc_p1", "https://www.kingpower-cn.com/search?cat=272&type=cat"),
    ]:
        html = load(url)
        total, prod_links, soup = count_and_ids(html)
        print(f"=== {label} === url={url}")
        print("  displayed total:", total)
        print("  #product-like links found:", len(prod_links))
        print("  sample links:", prod_links[:5])
        with open(f"/home/zoeliang/kp_{label}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print()
finally:
    driver.quit()
