import re
import sqlite3

DB_NAME = "gofundme.db"


# ======================
# 解析函数
# ======================
def extract_data(text):
    data = {}

    # Title
    title_match = re.search(r'Read story\s+([\s\S]+?)\n\n', text)
    if title_match:
        data['title'] = title_match.group(1).strip()

    # Words of support
    ws_match = re.search(r'Words of support\s+(\d+)', text)
    if ws_match:
        data['words_of_support'] = ws_match.group(1)
    else:
        data['words_of_support'] = 0

    # Time
    time_match = re.search(r'Created (.+)', text)
    if time_match:
        data['time'] = time_match.group(1).strip()
    else:
        time_match = re.search(
            r'\n([A-Z][a-z]+ \d{1,2}(st|nd|rd|th), \d{4}|\d+\s*[dh]\s*ago)\n[^\n]*\nReport fundraiser',
            text
        )
        if time_match:
            data['time'] = time_match.group(1)

    # Recent donations
    rd_match = re.search(r'([\d\.]+[KMB]?)\s+recent donations', text)
    if rd_match:
        data['recent_donations'] = rd_match.group(1)

    # Goal
    goal_match = re.search(r'of\s+\$([\d\.]+[KMB]?)\s+USD', text)
    if goal_match:
        data['goal'] = goal_match.group(1)

    # Progress
    progress_match = re.search(r'(\d+)%', text)
    if progress_match:
        data['progress'] = progress_match.group(1) + "%"

    # Amount
    amount_match = re.search(r'\$([\d,]+)\s+raised', text)
    if amount_match:
        data['amount'] = amount_match.group(1)

    # Number of donations
    nd_match = re.search(r'([\d\.]+[KMB]?)\s+donors', text)
    if nd_match:
        data['number_of_donations'] = nd_match.group(1)
    else:
        nd_match = re.search(r'Donations\s+([\d\.]+[KMB]?)', text)
        if nd_match:
            data['number_of_donations'] = nd_match.group(1)

    # Updates
    updates_match = re.search(r'Updates\s+(\d+)', text)
    if updates_match:
        data['updates'] = updates_match.group(1)
    else:
        data['updates'] = 0

    # Description
    desc_match = re.search(r'Donation protected\n(.+?)(\nReact|\nDonations)', text, re.S)
    if desc_match:
        data['description'] = desc_match.group(1).strip()
    else:
        desc_match = re.search(r'Donations paused\n(.+?)(\nReact)', text, re.S)
        if desc_match:
            data['description'] = desc_match.group(1).strip()

    return data


# ======================
# 主逻辑（数据库版本）
# ======================
def main():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 从 projects 表读取
    is_add = True # True: 增加条目；False: 更新条目
    if is_add:
        cursor.execute("""
            SELECT p.id, p.category, p.content
            FROM projects p
            WHERE p.content IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM campaigns c WHERE c.id = p.id
            )
        """)
    else:
        cursor.execute("""
            SELECT id, category, content 
            FROM projects 
            WHERE content IS NOT NULL
              AND image_name IS NOT NULL
              AND REPLACE(image_name, '.jpg', '') != scrape_time
        """)
    rows = cursor.fetchall()

    print(f"读取 {len(rows)} 条数据")

    for row in rows:
        pid, category, content = row

        try:
            data = extract_data(content)

            cursor.execute("""
            INSERT OR REPLACE INTO campaigns (
                id, category, title, words_of_support, time,
                recent_donations, goal, progress, amount,
                number_of_donations, updates, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid,
                category,
                data.get('title'),
                data.get('words_of_support'),
                data.get('time'),
                data.get('recent_donations'),
                data.get('goal'),
                data.get('progress'),
                data.get('amount'),
                data.get('number_of_donations'),
                data.get('updates'),
                data.get('description')
            ))

            print(f"✅ 解析完成 ID={pid}")

        except Exception as e:
            print(f"❌ 解析失败 ID={pid}:", e)

    conn.commit()
    conn.close()

    print("🎉 parser完成")


if __name__ == "__main__":
    main()
