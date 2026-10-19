"""
Script to remove all orphaned (no-admin) establishments from the database,
keeping only the 4 active ones linked to real Zoo Admin accounts.

KEEP: ID 2 (Lyger Zoo), ID 4 (Graco Farms), ID 5 (Hiraya Childhood Playfarm), ID 29 (APA Wildlife)
DELETE: all other zoos with no active admin accounts.
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

KEEP_ZOO_IDS = {2, 4, 5, 29}  # Lyger Zoo, Graco Farms, Hiraya Childhood Playfarm, APA Wildlife

app = create_app()
with app.app_context():
    from models import (
        Zoo, User, Animal, Service, Booking, BookingPayment, BookingTicket, BookingTicketScan,
        Event, Promotion, Feedback, Notification, ZooZone, ZooAdminFeedback, ZooAdminFeedbackReply,
        ZooSubscription, SubscriptionPayment, ZooLayoutConfig, StaffTask,
        TriviaQuestion, VisitorTriviaLog, LoyaltyTransaction, db
    )

    all_zoos = Zoo.query.order_by(Zoo.id.asc()).all()
    to_delete = [z for z in all_zoos if z.id not in KEEP_ZOO_IDS]
    to_delete_ids = [z.id for z in to_delete]

    print(f"\nZoos to DELETE ({len(to_delete)}):")
    for z in to_delete:
        print(f"  ID {z.id}: {z.name} ({z.location})")

    print(f"\nZoos to KEEP ({len(KEEP_ZOO_IDS)}):")
    keep_zoos = Zoo.query.filter(Zoo.id.in_(KEEP_ZOO_IDS)).all()
    for z in keep_zoos:
        print(f"  ID {z.id}: {z.name} ({z.location})")

    if not to_delete_ids:
        print("\nNothing to delete!")
        sys.exit(0)

    print(f"\nDeleting {len(to_delete_ids)} establishments and all related data...")
    deleted_counts = {}

    try:
        # 1. Feedback Replies & Feedbacks
        subq_fb = db.session.query(ZooAdminFeedback.id).filter(ZooAdminFeedback.zoo_id.in_(to_delete_ids))
        count = ZooAdminFeedbackReply.query.filter(ZooAdminFeedbackReply.feedback_id.in_(subq_fb)).delete(synchronize_session=False)
        deleted_counts['zoo_admin_feedback_replies'] = count

        count = ZooAdminFeedback.query.filter(ZooAdminFeedback.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['zoo_admin_feedbacks'] = count

        # 2. Subscription Payments & Subscriptions
        subq_sub = db.session.query(ZooSubscription.id).filter(ZooSubscription.zoo_id.in_(to_delete_ids))
        count = SubscriptionPayment.query.filter(SubscriptionPayment.subscription_id.in_(subq_sub)).delete(synchronize_session=False)
        deleted_counts['subscription_payments'] = count

        count = ZooSubscription.query.filter(ZooSubscription.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['zoo_subscriptions'] = count

        # 3. Layout config & staff tasks & zones
        count = ZooLayoutConfig.query.filter(ZooLayoutConfig.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['zoo_layout_configs'] = count

        count = StaffTask.query.filter(StaffTask.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['staff_tasks'] = count

        count = ZooZone.query.filter(ZooZone.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['zoo_zones'] = count

        # 4. Bookings and booking relations
        booking_ids = [b.id for b in Booking.query.filter(Booking.zoo_id.in_(to_delete_ids)).all()]
        if booking_ids:
            # Ticket scans by zoo or booking
            count = BookingTicketScan.query.filter(
                (BookingTicketScan.zoo_id.in_(to_delete_ids)) | (BookingTicketScan.booking_id.in_(booking_ids))
            ).delete(synchronize_session=False)
            deleted_counts['booking_ticket_scans'] = count

            # Tickets
            count = BookingTicket.query.filter(BookingTicket.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            deleted_counts['booking_tickets'] = count

            # Payments
            count = BookingPayment.query.filter(BookingPayment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            deleted_counts['booking_payments'] = count

            # Loyalty transactions linked to booking
            count = LoyaltyTransaction.query.filter(LoyaltyTransaction.booking_id.in_(booking_ids)).update({'booking_id': None}, synchronize_session=False)
            deleted_counts['loyalty_transactions_unlinked'] = count

            # Notifications linked to booking
            count = Notification.query.filter(Notification.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            deleted_counts['notifications'] = count
        else:
            # Still check ticket scans by zoo_id
            count = BookingTicketScan.query.filter(BookingTicketScan.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
            deleted_counts['booking_ticket_scans'] = count

        # 5. Visitor feedback
        count = Feedback.query.filter(Feedback.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['visitor_feedbacks'] = count

        # 6. Bookings
        count = Booking.query.filter(Booking.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['bookings'] = count

        # 7. Events & Promotions
        count = Event.query.filter(Event.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['events'] = count

        count = Promotion.query.filter(Promotion.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['promotions'] = count

        # 8. Trivia
        subq_trivia = db.session.query(TriviaQuestion.id).filter(TriviaQuestion.zoo_id.in_(to_delete_ids))
        count = VisitorTriviaLog.query.filter(VisitorTriviaLog.question_id.in_(subq_trivia)).delete(synchronize_session=False)
        deleted_counts['visitor_trivia_logs'] = count

        count = TriviaQuestion.query.filter(TriviaQuestion.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['trivia_questions'] = count

        # 9. Animals & Services
        count = Animal.query.filter(Animal.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['animals'] = count

        count = Service.query.filter(Service.zoo_id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['services'] = count

        # 10. Unlink any users
        count = User.query.filter(User.zoo_id.in_(to_delete_ids)).update({'zoo_id': None}, synchronize_session=False)
        deleted_counts['users_unlinked'] = count

        # 11. Zoos
        count = Zoo.query.filter(Zoo.id.in_(to_delete_ids)).delete(synchronize_session=False)
        deleted_counts['zoos'] = count

        db.session.commit()

        print("\n✅ Deletion complete! Summary:")
        for table, cnt in deleted_counts.items():
            if cnt:
                print(f"  {table}: {cnt}")

    except Exception as e:
        db.session.rollback()
        print(f"\n❌ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Verification
    remaining = Zoo.query.order_by(Zoo.id.asc()).all()
    print(f"\nRemaining zoos ({len(remaining)}):")
    for z in remaining:
        admins = User.query.filter(User.zoo_id == z.id, User.role.in_(['zoo_admin', 'animal_farm_admin', 'admin'])).all()
        staff = User.query.filter(User.zoo_id == z.id, User.role.in_(['zoo_staff', 'staff'])).all()
        print(f"  ID {z.id}: {z.name} | Location: {z.location}")
        print(f"       Admins: {[u.email for u in admins]}")
        print(f"       Staff:  {[u.email for u in staff]}")

    print("\nDone! Slider will now show only the 4 active establishments.\n")
