import sqlite3
import pandas as pd

# Table名: projects, campaigns
TB_NAME = "campaigns"

conn = sqlite3.connect("gofundme.db")
df = pd.read_sql("SELECT * FROM " + TB_NAME, conn)

df.to_excel(TB_NAME + ".xlsx", index=False)

print("✅ exporter完成")
