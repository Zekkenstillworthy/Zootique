from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='visitor') 
    full_name = db.Column(db.String(100))
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')  # active|suspended
    profile_image = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='users', lazy=True)
    bookings = db.relationship('Booking', foreign_keys='Booking.user_id', back_populates='user', lazy=True)
    assigned_bookings = db.relationship('Booking', foreign_keys='Booking.assigned_staff_user_id', back_populates='assigned_staff_user', lazy=True)
    booking_payments = db.relationship('BookingPayment', back_populates='payer', lazy=True)
    feedbacks = db.relationship('Feedback', back_populates='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Zoo(db.Model):
    __tablename__ = 'zoos'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50))
    location = db.Column(db.String(255))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    landing_map_title = db.Column(db.String(160), nullable=True)
    landing_map_description = db.Column(db.Text, nullable=True)
    landing_map_image_url = db.Column(db.String(500), nullable=True)
    landing_map_updated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    animals = db.relationship('Animal', backref='zoo', lazy=True)
    services = db.relationship('Service', backref='zoo', lazy=True)
    users = db.relationship('User', back_populates='zoo', lazy=True)

    subscriptions = db.relationship('ZooSubscription', back_populates='zoo', lazy=True)
    admin_feedbacks = db.relationship('ZooAdminFeedback', back_populates='zoo', lazy=True)

    zones = db.relationship('ZooZone', back_populates='zoo', lazy=True)
    staff_tasks = db.relationship('StaffTask', back_populates='zoo', lazy=True)

class Animal(db.Model):
    __tablename__ = 'animals'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    species = db.Column(db.String(100))
    habitat = db.Column(db.String(100))
    status = db.Column(db.String(50))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))

class Service(db.Model):
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))

class Booking(db.Model):
    __tablename__ = 'bookings'
    # Keeping ID string specifically because the mock data has 'BK-1001' style IDs
    id = db.Column(db.String(20), primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete="CASCADE"), nullable=True)
    # New: true ownership. Existing databases need a one-time migration to add/backfill this column.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    assigned_staff_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    visitor_name = db.Column(db.String(100), nullable=False)
    service_name = db.Column(db.String(100))
    date = db.Column(db.String(20)) # Storing as string to match existing mock logic for simplicity
    time = db.Column(db.String(20))
    guests = db.Column(db.Integer)
    status = db.Column(db.String(50))
    amount = db.Column(db.Float)
    payment_status = db.Column(db.String(20), nullable=False, default='unpaid')  # unpaid|paid|refunded|failed
    payment_reference = db.Column(db.String(100), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)
    service = db.relationship('Service', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], back_populates='bookings', lazy=True)
    assigned_staff_user = db.relationship('User', foreign_keys=[assigned_staff_user_id], back_populates='assigned_bookings', lazy=True)
    payments = db.relationship('BookingPayment', back_populates='booking', lazy=True)


class BookingPayment(db.Model):
    __tablename__ = 'booking_payments'
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.String(20), db.ForeignKey('bookings.id', ondelete="CASCADE"), nullable=False)
    payer_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(30), nullable=False)  # card|gcash|cash_on_arrival
    status = db.Column(db.String(20), nullable=False, default='paid')  # paid|failed|refunded
    reference = db.Column(db.String(100), nullable=False, unique=True)
    provider = db.Column(db.String(50), nullable=False, default='simulated_gateway')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

    booking = db.relationship('Booking', back_populates='payments', lazy=True)
    payer = db.relationship('User', back_populates='booking_payments', lazy=True)

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(50))
    time = db.Column(db.String(50))
    location = db.Column(db.String(150))
    image_url = db.Column(db.String(500), nullable=True)

    zoo = db.relationship('Zoo', lazy=True)

    @property
    def banner_url(self):
        # Backwards-compatible alias used by visitor templates.
        return self.image_url

class Promotion(db.Model):
    __tablename__ = 'promotions'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    promo_type = db.Column(db.String(50), nullable=True)  # Family|Group Tour|Student|Senior|Seasonal
    country = db.Column(db.String(60), nullable=True, default='Philippines')
    discount = db.Column(db.String(20))
    valid_until = db.Column(db.String(20))
    image_url = db.Column(db.String(500), nullable=True)

    zoo = db.relationship('Zoo', lazy=True)

class Feedback(db.Model):
    __tablename__ = 'feedbacks'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    visitor_name = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Integer)
    comment = db.Column(db.Text)
    date = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)
    user = db.relationship('User', back_populates='feedbacks', lazy=True)


class ZooZone(db.Model):
    __tablename__ = 'zoo_zones'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    map_image_url = db.Column(db.String(500), nullable=True)
    panorama_360_url = db.Column(db.String(800), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='zones', lazy=True)


class StaffTask(db.Model):
    __tablename__ = 'staff_tasks'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|in_progress|done
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='staff_tasks', lazy=True)
    assigned_to_user = db.relationship('User', lazy=True)


class SubscriptionPlan(db.Model):
    __tablename__ = 'subscription_plans'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # Basic/Premium
    price = db.Column(db.Float, nullable=False)
    duration = db.Column(db.String(10), nullable=False)  # monthly|yearly
    duration_months = db.Column(db.Integer, nullable=False)
    features = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subscriptions = db.relationship('ZooSubscription', back_populates='plan', lazy=True)


class ZooSubscription(db.Model):
    __tablename__ = 'zoo_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id', ondelete="CASCADE"), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active')  # active|expired
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='subscriptions', lazy=True)
    plan = db.relationship('SubscriptionPlan', back_populates='subscriptions', lazy=True)
    payments = db.relationship('SubscriptionPayment', back_populates='subscription', lazy=True)

    def refresh_status(self, now: datetime | None = None):
        now = now or datetime.utcnow()
        self.status = 'active' if self.end_date >= now else 'expired'


class SubscriptionPayment(db.Model):
    __tablename__ = 'subscription_payments'
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('zoo_subscriptions.id', ondelete="CASCADE"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    period_start = db.Column(db.DateTime, nullable=True)
    period_end = db.Column(db.DateTime, nullable=True)
    reference = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='paid')  # paid|refunded|failed

    subscription = db.relationship('ZooSubscription', back_populates='payments', lazy=True)


class ZooAdminFeedback(db.Model):
    __tablename__ = 'zoo_admin_feedback'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    category = db.Column(db.String(50), nullable=False)  # Features|Support
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='admin_feedbacks', lazy=True)
    user = db.relationship('User', lazy=True)
    replies = db.relationship('ZooAdminFeedbackReply', back_populates='feedback', lazy=True)


class ZooAdminFeedbackReply(db.Model):
    __tablename__ = 'zoo_admin_feedback_replies'
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('zoo_admin_feedback.id', ondelete="CASCADE"), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=True)
    reply_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    feedback = db.relationship('ZooAdminFeedback', back_populates='replies', lazy=True)
    admin_user = db.relationship('User', lazy=True)
