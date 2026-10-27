# -*- coding: utf-8 -*-
"""
cleanup_fake_accounts.py
Removes all user accounts NOT in the approved credential list.
Run once to clean the database.
"""
from app import app
from models import db, User, Notification, Booking, StaffTask

# ── Approved account emails (exact, lowercase) ──────────────────────────────
KEEP_EMAILS = {
    "admin@zootique.com",                       # Super Admin
    "gracofarmsandleisure@gmail.com",           # Zoo Admin – Graco Farms
    "hirayachildhoodplayfarm22@gmail.com",      # Zoo Admin – Hiraya
    "apawildlife@gmail.com",                    # Zoo Admin – APA Wildlife
    "lygeranimalsanctuary123@gmail.com",        # Zoo Admin – Lyger Zoo
    "gracostaff@gmail.com",                     # Zoo Staff – Graco
    "apastaff0@gmail.com",                      # Zoo Staff – APA
    "markjosephmerana127@gmail.com",            # Visitor – MJ
}

with app.app_context():
    all_users = User.query.order_by(User.id).all()

    to_delete = [u for u in all_users if (u.email or "").strip().lower() not in KEEP_EMAILS]

    if not to_delete:
        print("[OK]  No fake accounts found - database is already clean.")
    else:
        print(f"Found {len(to_delete)} account(s) to remove:\n")
        for u in to_delete:
            print(f"  [{u.id}] {u.full_name or '—'} | {u.email} | {u.role}")

        print("\nRemoving...")

        for u in to_delete:
            uid = u.id

            # Unassign bookings where this user was a staff assignee
            Booking.query.filter(Booking.assigned_staff_user_id == uid).update(
                {Booking.assigned_staff_user_id: None},
                synchronize_session=False,
            )

            # Unassign staff tasks
            StaffTask.query.filter(StaffTask.assigned_to_user_id == uid).update(
                {StaffTask.assigned_to_user_id: None},
                synchronize_session=False,
            )

            # Delete notifications
            Notification.query.filter_by(user_id=uid).delete(synchronize_session=False)

            # Delete the user
            db.session.delete(u)
            print(f"  [DEL] Deleted [{uid}] {u.email}")

        db.session.commit()
        print(f"\n[DONE] {len(to_delete)} account(s) removed.")

    # Final state
    print("\n-- Remaining accounts --------------------------------------------------")
    remaining = User.query.order_by(User.id).all()
    for u in remaining:
        print(f"  [{u.id}] {u.full_name or '—'} | {u.email} | {u.role} | zoo_id={u.zoo_id}")
