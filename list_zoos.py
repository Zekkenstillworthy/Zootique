"""
Script to list all zoos/establishments in the live Postgres database.
Run with: python list_zoos.py
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import create_app

app = create_app()
with app.app_context():
    from models import Zoo, User
    zoos = Zoo.query.order_by(Zoo.id.asc()).all()
    print(f"\nTotal zoos in database: {len(zoos)}\n")
    print(f"{'ID':>4} | {'Name':<45} | {'Location':<25} | Admins")
    print("-" * 100)
    for zoo in zoos:
        admins = User.query.filter(User.zoo_id == zoo.id, User.role.in_(['admin', 'animal_farm_admin'])).all()
        admin_emails = [u.email for u in admins]
        print(f"{zoo.id:>4} | {zoo.name:<45} | {(zoo.location or ''):<25} | {admin_emails}")
    print()
