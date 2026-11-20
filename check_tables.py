import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'support_%'")
tables = cursor.fetchall()
print('Support tables:', tables)
conn.close()
