# Testing a scraper for real

Don't consider a retailer's scraper done just because it looks right — actually run it and check its coverage against the site before handing it off. A guessed CSS selector reads exactly like a correct one until you run it; the failure mode is usually silent (0 products, or fewer than expected), not a crash.

## What "done" means

1. The scraper runs against the live site without crashing (other than the final Databricks upload, which will fail locally — see below).
2. It scrapes a number of items that matches an independent ground truth — ideally something the site itself displays (a "N Item(s)"/results-count element), not just trusting the scraper's own pagination loop covered everything.
3. If any category/location comes back at 0 or noticeably under the site's count, that's a selector bug to fix before calling it done — not something to hand off with a caveat.

## One-time environment setup (WSL, no sudo required)

A working headless-Chrome + Selenium test environment can be built entirely in user space — no root needed, even for Chrome itself:

```bash
# 1. Python venv with the scraper's real dependencies
python3 -m venv ~/scraper_test_env
~/scraper_test_env/bin/pip install selenium undetected-chromedriver beautifulsoup4 requests pandas databricks-sdk

# 2. Portable Chrome + matching chromedriver (same source scrapers/Dockerfile uses)
#    Download via the "last-known-good-versions-with-downloads.json" endpoint,
#    unzip with Python's zipfile module (no `unzip` binary needed), extract to
#    ~/chrome-for-testing/, then:
chmod -R +x ~/chrome-for-testing/chrome-linux64 ~/chrome-for-testing/chromedriver-linux64
#    (extraction drops the executable bit on helper binaries like
#    chrome_crashpad_handler — without this chmod, Chrome fatals with
#    "posix_spawn ... Permission denied" on startup)

# 3. Missing shared libs (libnss3, libnspr4, libasound2t64, libatk*, libgtk-3*,
#    libx11-6, etc.) — apt-get download works WITHOUT sudo (just fetches the
#    .deb, doesn't install), then dpkg-deb -x extracts it without root:
cd /tmp && apt-get download libnss3 libnspr4 libasound2t64 libatk1.0-0t64 \
  libatk-bridge2.0-0t64 libcups2t64 libdrm2 libgbm1 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libxkbcommon0 libpango-1.0-0 libcairo2 \
  libgtk-3-0t64 libx11-6 libxcb1 libxext6 libxi6 libxtst6 libxrender1
for f in *.deb; do dpkg-deb -x "$f" ~/local_libs; done
```

**Known gotcha — `undetected-chromedriver` on newer Python:** the version pinned in `scrapers/requirements.txt` (matching the Docker image's Python 3.10) imports `distutils`, which Python 3.12+ removed. If your local/WSL Python is 3.12+, add a minimal shim at `<venv>/lib/pythonX.Y/site-packages/distutils/version.py` with just a `LooseVersion` class (reproducing the old stdlib implementation). This is test-venv-only — production runs Python 3.10 in the `etl-scrapers` Docker image, where real `distutils` still exists.

To actually run a scraper:

```bash
export LD_LIBRARY_PATH=~/local_libs/usr/lib/x86_64-linux-gnu
export CHROME_BIN=~/chrome-for-testing/chrome-linux64/chrome
export CHROMEDRIVER_PATH=~/chrome-for-testing/chromedriver-linux64/chromedriver
~/scraper_test_env/bin/python <retailer>_scraper.py
```

Scraping will complete normally; only the final `upload_to_databricks()` call will fail (`WorkspaceClient()` can't find credentials locally) — that's expected, not a bug. Everything printed before that traceback is the real result.

## Output-capture gotcha

Long-running `wsl -e bash script.sh` commands piped through a background-task wrapper can lose, truncate, or reorder `print()` output — even with `PYTHONUNBUFFERED=1`. Don't trust that capture for a scraper run. Instead have the script itself redirect straight to a file:

```bash
python <retailer>_scraper.py > ~/scrape_test_output.txt 2>&1
echo "EXIT:$?" >> ~/scrape_test_output.txt
```

Then read `~/scrape_test_output.txt` directly once the run finishes.

## Infinite-scroll pagination gotcha

If a site's product count stalls no matter how many times you scroll, don't conclude it isn't infinite scroll — check whether the *technique* is the problem before the *site*. `driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)` can silently fail to register in headless Chrome even when the page is genuinely window-scrollable, and this can happen on one retailer's site while the identical code works fine on another (confirmed: it worked on cdfg_cambodia_scraper.py but silently failed on the near-identical cdfg_hongkong_scraper.py, same platform, same code). Prefer a direct JS scroll by default:

```python
self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
time.sleep(3)  # some sites need 3-4s, not 2s, for the next batch to render
```

To confirm which is actually true (real infinite scroll vs. a wrong technique vs. a genuinely different scroll container) before spending time guessing, check scroll dimensions directly:

```python
sh = driver.execute_script("return document.body.scrollHeight")
ch = driver.execute_script("return window.innerHeight")
# sh > ch by a lot → the page is window-scrollable; a stuck count means
# your scroll technique isn't registering, not that scrolling is the wrong
# approach for this site.
```

## Getting a ground-truth count

Check the live category/listing page for something the site displays itself — a results count, a "Showing X of Y" string, a page-count times per-page-count estimate. If found, extract it the same way the scraper extracts products (`get_expected_item_count()` in `scripts/scraper_template.py` is a hook for this) and compare per category and in total. If the site displays nothing like this, fall back to a manual spot-check: open one category in a browser, note the total, compare.
