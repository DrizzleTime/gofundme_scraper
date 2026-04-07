import os
import time
import sqlite3
import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# ========= 配置 =========
# 每次运行，MAX_PROJECTS增大20-30
MAX_PROJECTS = 20
# 类别: medical, memorial, emergency, education, business, family
CATEGORY = "medical"
BASE_URL = "https://www.gofundme.com/discover/" + CATEGORY + "-fundraiser"
DB_NAME = "gofundme.db"

# ========= 初始化 =========
conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

chrome_options = Options()
chrome_options.add_argument("--start-maximized")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=chrome_options)
driver.get(BASE_URL)
time.sleep(5)

# ========= 点击 Show more =========
def load_more():
    while True:
        links = driver.find_elements(By.TAG_NAME, "a")
        project_links = [l.get_attribute("href") for l in links if l.get_attribute("href") and "/f/" in l.get_attribute("href")]

        if len(project_links) >= MAX_PROJECTS:
            break

        try:
            btn = driver.find_element(By.XPATH, "//button[contains(., 'Show more')]")
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except:
            break

# ========= 获取链接 =========
def get_links():
    links = set()
    elements = driver.find_elements(By.TAG_NAME, "a")

    for el in elements:
        href = el.get_attribute("href")
        if href and "/f/" in href:
            links.add(href.split("?")[0])

    return list(links)[:MAX_PROJECTS]

# ========= 主逻辑 =========
try:
    load_more()
    links = get_links()

    print(f"共获取 {len(links)} 个项目")

    for link in links:
        # 判断是否已存在
        cursor.execute("SELECT 1 FROM projects WHERE url=?", (link,))
        if cursor.fetchone():
            print("已存在，跳过:", link)
            continue

        # 使用时间戳生成id
        pid = int(time.time() * 1000)

        cursor.execute("""
        INSERT INTO projects (id, category, url)
        VALUES (?, ?, ?)
        """, (pid, CATEGORY, link))
        conn.commit()

        print("插入数据库:", link)

finally:
    driver.quit()
    conn.close()

print("✅ collector完成")
