import sqlite3

conn = sqlite3.connect("data/trinetra.db")
cursor = conn.cursor()

cursor.execute("""
    SELECT COUNT(*)
    FROM projects_latest
    WHERE sector IS NOT NULL
      AND TRIM(sector) != ''
""")

count = cursor.fetchone()[0]

print("Projects with sector:", count)

cursor.execute("""
    SELECT project_id, project_name, sector
    FROM projects_latest
    WHERE sector IS NOT NULL
      AND TRIM(sector) != ''
    LIMIT 10
""")

print("\nFirst 10 projects:")

for row in cursor.fetchall():
    print(row)

conn.close()