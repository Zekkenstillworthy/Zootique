import os
import psycopg
from dotenv import load_dotenv

load_dotenv(".env")
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise SystemExit("DATABASE_URL is not set.")

# Clean up postgresql+psycopg if needed
clean_url = db_url
if clean_url.startswith("postgresql+psycopg://"):
    clean_url = "postgresql://" + clean_url[len("postgresql+psycopg://"):]
elif clean_url.startswith("postgres://"):
    clean_url = "postgresql://" + clean_url[len("postgres://"):]

print(f"Connecting to database...")
conn = psycopg.connect(clean_url)
with conn.cursor() as cur:
    cur.execute("SELECT id, establishment_name, status FROM establishment_registrations WHERE LOWER(status) = 'draft';")
    drafts = cur.fetchall()
    print(f"Found {len(drafts)} draft registrations:")
    for d in drafts:
        print(f"  - ID {d[0]}: {d[1]} (current status: {d[2]})")
    
    if drafts:
        cur.execute("UPDATE establishment_registrations SET status = 'pending' WHERE LOWER(status) = 'draft';")
        conn.commit()
        print(f"Successfully updated {len(drafts)} registrations from 'draft' to 'pending'.")
    else:
        print("No draft registrations found in the database.")
        
    cur.execute("SELECT status, count(*) FROM establishment_registrations GROUP BY status;")
    print("Updated status summary:")
    for row in cur.fetchall():
        print(f"  - {row[0]}: {row[1]}")
conn.close()
