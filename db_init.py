import sqlite3

conn = sqlite3.connect("gofundme.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    category TEXT,
    url TEXT UNIQUE,
    image_name TEXT,
    content TEXT,
    scrape_time TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY,
    category TEXT,
    title TEXT,
    words_of_support TEXT,
    time TEXT,
    recent_donations TEXT,
    goal TEXT,
    progress TEXT,
    amount TEXT,
    number_of_donations TEXT,
    updates TEXT,
    description TEXT,
    main_picture TEXT
)
""")

conn.commit()
conn.close()

print("✅ db_init完成")
