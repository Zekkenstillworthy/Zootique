import sqlite3

conn = sqlite3.connect("instance/zootique.db")
cur = conn.cursor()
print("--- USERS ---")
cur.execute("SELECT id, email, role, zoo_id FROM users;")
for r in cur.fetchall():
    print(r)

print("--- SERVICES ---")
cur.execute("SELECT id, name, price, zoo_id FROM services;")
for r in cur.fetchall():
    print(r)

conn.close()
