"""
Script to list all users by role in the live database.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import create_app

app = create_app()
with app.app_context():
    from models import User, Zoo
    users = User.query.order_by(User.id.asc()).all()
    print(f"\nTotal users: {len(users)}\n")
    print(f"{'ID':>4} | {'Name':<30} | {'Email':<45} | {'Role':<25} | zoo_id")
    print("-" * 115)
    for u in users:
        print(f"{u.id:>4} | {(u.full_name or ''):<30} | {u.email:<45} | {u.role:<25} | {u.zoo_id}")
    print()
