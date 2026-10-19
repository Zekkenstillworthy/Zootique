import sqlite3

conn = sqlite3.connect('zootique.db')
c = conn.cursor()

# List all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Find zoo-like table
for tbl in tables:
    if 'zoo' in tbl.lower() or 'establishment' in tbl.lower() or 'animal_farm' in tbl.lower():
        print(f"\n--- Table: {tbl} ---")
        c.execute(f"PRAGMA table_info({tbl})")
        cols = [r[1] for r in c.fetchall()]
        print("Columns:", cols)
        c.execute(f"SELECT * FROM {tbl} ORDER BY id")
        for row in c.fetchall():
            print(row)

conn.close()
