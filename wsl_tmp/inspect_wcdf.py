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

urls = [
    "https://westcoastdutyfree.com/",
    "https://dutyfreecanada.com/stores/west-coast-duty-free/",
]

for url in urls:
    print("=" * 80)
    print("URL:", url)
    try:
        driver.get(url)
        time.sleep(5)
        print("Final URL:", driver.current_url)
        print("Title:", driver.title)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        text = soup.get_text(" ", strip=True)
        print("Text length:", len(text))
        print("First 1500 chars of text:")
        print(text[:1500])
        # find nav links
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/") or "westcoastdutyfree" in href or "dutyfreecanada" in href:
                links.add(href)
        print("\nSample links (up to 60):")
        for l in sorted(links)[:60]:
            print(" ", l)
    except Exception as e:
        print("ERROR:", e)

driver.quit()
