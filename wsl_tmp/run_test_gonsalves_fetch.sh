#!/bin/bash
export LD_LIBRARY_PATH=/home/zoeliang/local_libs/usr/lib/x86_64-linux-gnu
export CHROME_BIN=/home/zoeliang/chrome-for-testing/chrome-linux64/chrome
export CHROMEDRIVER_PATH=/home/zoeliang/chrome-for-testing/chromedriver-linux64/chromedriver
/home/zoeliang/scraper_test_env/bin/python /mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/test_gonsalves_fetch.py > /mnt/c/Users/ZoeLiang/web-scraping-agent-skill/wsl_tmp/gonsalves_fetch_output.txt 2>&1
