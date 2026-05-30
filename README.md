# Zootique

## Database (Postgres only)

This app is configured to run on **PostgreSQL** via `DATABASE_URL`.

For local development, you can set `DATABASE_URL` in a `.env` file (recommended). The app loads `.env` automatically (via `python-dotenv`).

Set `DATABASE_URL` to a SQLAlchemy URL using the psycopg (v3) driver:

- `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`

If you have an older URL like `postgresql://...` or `postgres://...`, the app will normalize it to `postgresql+psycopg://...`.

## Migrating existing data from SQLite (instance/zootique.db)

Your existing data lives in `instance/zootique.db`. To copy that data into Postgres and produce a Postgres backup dump:

1) Ensure `DATABASE_URL` points at your Postgres database.
2) Install dependencies: `python -m pip install -r requirements.txt`
3) Run the migration script:

- `python scripts/migrate_sqlite_to_postgres.py --create-schema`

By default it reads `instance/zootique.db` and writes a timestamped dump into `backups/` using `pg_dump` if it is available on your PATH.

If you want to re-import from scratch (DANGEROUS; deletes Postgres data first):

- `python scripts/migrate_sqlite_to_postgres.py --create-schema --truncate-first`

## Running locally

### Using a .env file (recommended)

1) Copy `.env.example` to `.env`
2) Edit `.env` and set `DATABASE_URL`
3) Install dependencies: `python -m pip install -r requirements.txt`
4) Run: `python app.py`

With `DATABASE_URL` set:

- `python app.py`

Optional environment variables:

- `SECRET_KEY` (recommended)
- `SESSION_LIFETIME_DAYS` (defaults to 3650)

## Zootique Admin login (Super Admin)

There is no public registration flow for the `zootique_admin` role.

To create (or ensure) a Super Admin account on your Postgres database:

- `python scripts/ensure_zootique_admin.py --email admin@example.com --password "change-me" --full-name "Super Admin"`

If you omit `--password`, the script will generate a secure temporary password and print it.
