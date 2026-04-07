import time
import sqlite3
import pyperclip
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from datetime import datetime
import os

DB_NAME = "gofundme.db"
IMAGE_DIR = "images"
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

chrome_options = Options()
chrome_options.add_argument("--start-maximized")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=chrome_options)

# 获取待抓取的项目
is_fill = True # True: 填充内容；False: 更新内容
if is_fill:
    cursor.execute("SELECT id, url, image_name FROM projects WHERE image_name IS NULL OR content = '' OR content IS NULL")
else:
    cursor.execute("SELECT id, url, image_name FROM projects")
rows = cursor.fetchall()

for pid, url, image_name in rows:
    print(f"处理 {pid}: {url}")

    try:
        driver.get(url)
        time.sleep(6)

        # 滚动触发 Updates / Words
        for _ in range(10):
            driver.execute_script("window.scrollBy(0, 1000)")
            time.sleep(1)

        # 点击 Read more
        for _ in range(5):
            buttons = driver.find_elements(By.XPATH, "//button[contains(., 'Read more')]")
            for b in buttons:
                try:
                    b.click()
                    time.sleep(0.5)
                except:
                    pass

        time.sleep(2)

        # Ctrl+A + Ctrl+C + 读取剪贴板
        body = driver.find_element(By.TAG_NAME, "body")
        body.click()
        time.sleep(1)
        body.send_keys(Keys.CONTROL, 'a')
        time.sleep(1)
        body.send_keys(Keys.CONTROL, 'c')
        time.sleep(2)
        full_text = pyperclip.paste()

        scrape_time = datetime.now().strftime("%Y%m%d%H%M%S")
        updated_image_name = image_name

        # 下载封面图，如果 image_name 为空
        if not image_name:
            try:
                img_url = driver.find_element(By.XPATH, "//meta[@property='og:image']").get_attribute("content")
                if img_url:
                    res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    if res.status_code == 200:
                        updated_image_name = f"{scrape_time}.jpg"
                        with open(os.path.join(IMAGE_DIR, updated_image_name), "wb") as f:
                            f.write(res.content)
                        print("✅ 下载封面图:", updated_image_name)
            except Exception as e:
                print("❌ 下载失败:", e)

        # 更新数据库
        if updated_image_name != image_name:
            cursor.execute("""
            UPDATE projects
            SET content=?, image_name=?, scrape_time=?
            WHERE id=?
            """, (full_text, updated_image_name, scrape_time, pid))
        else:
            cursor.execute("""
            UPDATE projects
            SET content=?, scrape_time=?
            WHERE id=?
            """, (full_text, scrape_time, pid))

        conn.commit()
        print("✅ 完成")

    except Exception as e:
        print("❌ 错误:", e)

driver.quit()
conn.close()

print("🎉 scraper完成")
