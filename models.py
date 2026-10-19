from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json
from sqlalchemy import event, inspect as sqlalchemy_inspect
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
    phone = db.Column(db.String(50), nullable=True)
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
    landing_promo_title = db.Column(db.String(160), nullable=True)
    landing_promo_description = db.Column(db.Text, nullable=True)
    landing_promo_image_url = db.Column(db.String(500), nullable=True)
    cancellation_refund_hours = db.Column(db.Integer, nullable=False, default=24)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    animals = db.relationship('Animal', backref='zoo', lazy=True)
    services = db.relationship('Service', backref='zoo', lazy=True)
    users = db.relationship('User', back_populates='zoo', lazy=True)

    subscriptions = db.relationship('ZooSubscription', back_populates='zoo', lazy=True)
    admin_feedbacks = db.relationship('ZooAdminFeedback', back_populates='zoo', lazy=True)
    layout_config = db.relationship('ZooLayoutConfig', back_populates='zoo', uselist=False, cascade='all, delete-orphan', lazy=True)
    park_rules = db.relationship('ParkRule', back_populates='zoo', cascade='all, delete-orphan', lazy=True)

    zones = db.relationship('ZooZone', back_populates='zoo', lazy=True)
    staff_tasks = db.relationship('StaffTask', back_populates='zoo', lazy=True)


class EstablishmentType(db.Model):
    __tablename__ = 'establishment_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=True)
    icon_class = db.Column(db.String(100), nullable=True, default='fa-solid fa-tree')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class EstablishmentRegistration(db.Model):
    __tablename__ = 'establishment_registrations'
    id = db.Column(db.Integer, primary_key=True)
    establishment_name = db.Column(db.String(100), nullable=False)
    establishment_type = db.Column(db.String(50), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    admin_full_name = db.Column(db.String(100), nullable=True)
    admin_email = db.Column(db.String(120), nullable=True)
    admin_phone = db.Column(db.String(40), nullable=True)
    admin_password_hash = db.Column(db.String(256), nullable=True)
    establishment_contact_name = db.Column(db.String(100), nullable=True)
    establishment_contact_email = db.Column(db.String(120), nullable=True)
    establishment_contact_phone = db.Column(db.String(40), nullable=True)
    acknowledgement_email_status = db.Column(db.String(20), nullable=False, default='pending')
    confirmation_email_status = db.Column(db.String(20), nullable=False, default='pending')
    business_permit_url = db.Column(db.String(800), nullable=True)
    wildlife_license_url = db.Column(db.String(800), nullable=True)
    proof_of_address_url = db.Column(db.String(800), nullable=True)
    representative_id_url = db.Column(db.String(800), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='pending')
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='SET NULL'), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    rejection_note = db.Column(db.Text, nullable=True)
    reviewer_note = db.Column(db.Text, nullable=True)
    document_reviews = db.Column(db.JSON, nullable=False, default=dict)
    email_verification_token_hash = db.Column(db.String(128), nullable=True)
    email_verification_expires_at = db.Column(db.DateTime, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    activation_token_hash = db.Column(db.String(128), nullable=True)
    activation_expires_at = db.Column(db.DateTime, nullable=True)
    is_legacy_migration = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    zoo = db.relationship('Zoo', foreign_keys=[zoo_id], lazy=True)
    approver = db.relationship('User', foreign_keys=[approved_by], lazy=True)
    rejector = db.relationship('User', foreign_keys=[rejected_by], lazy=True)


class RegistrationEmailAttempt(db.Model):
    __tablename__ = 'registration_email_attempts'
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('establishment_registrations.id', ondelete='CASCADE'), nullable=False, index=True)
    recipient = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(255), nullable=False, default="")
    body = db.Column(db.Text, nullable=False, default="")
    notification_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    error_message = db.Column(db.String(500), nullable=True)
    attempted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    registration = db.relationship('EstablishmentRegistration', lazy=True)


class ZooLayoutConfig(db.Model):
    __tablename__ = 'zoo_layout_configs'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=False, unique=True)
    widget_visibility = db.Column(db.JSON, nullable=False, default=dict)
    widget_order = db.Column(db.JSON, nullable=False, default=list)
    layout_style = db.Column(db.String(20), nullable=False, default='grid')
    theme_variant = db.Column(db.String(30), nullable=False, default='light')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='layout_config', lazy=True)


class ZooGraphConfig(db.Model):
    __tablename__ = 'zoo_graph_configs'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    chart_type = db.Column(db.String(30), nullable=False, default='bar')
    data_source = db.Column(db.String(40), nullable=False, default='bookings')
    date_range = db.Column(db.String(20), nullable=False, default='last_6_months')
    group_by = db.Column(db.String(20), nullable=False, default='month')
    filters = db.Column(db.JSON, nullable=False, default=dict)
    is_visible = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)


class ParkRule(db.Model):
    __tablename__ = 'park_rules'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='park_rules', lazy=True)

class Animal(db.Model):
    __tablename__ = 'animals'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    zone_id = db.Column(db.Integer, db.ForeignKey('zoo_zones.id', ondelete='SET NULL'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    species = db.Column(db.String(100))
    habitat = db.Column(db.String(100))
    status = db.Column(db.String(50))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    age = db.Column(db.String(50), nullable=True)
    fun_facts = db.Column(db.Text, nullable=True)

    zone = db.relationship('ZooZone', backref=db.backref('animals', lazy=True))

class Service(db.Model):
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    opening_time = db.Column(db.String(10), nullable=True, default='08:00')
    closing_time = db.Column(db.String(10), nullable=True, default='17:00')
    slot_duration_minutes = db.Column(db.Integer, nullable=True, default=60)
    daily_capacity = db.Column(db.Integer, nullable=True, default=50)
    slot_capacity = db.Column(db.Integer, nullable=True, default=15)
    bundles = db.relationship('BookingBundle', back_populates='service', cascade='all, delete-orphan', lazy=True)


class BookingBundle(db.Model):
    __tablename__ = 'booking_bundles'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    eligibility = db.Column(db.String(255), nullable=True)
    min_guests = db.Column(db.Integer, nullable=False, default=1)
    max_guests = db.Column(db.Integer, nullable=False, default=50)
    price = db.Column(db.Float, nullable=False, default=0)
    discount_type = db.Column(db.String(20), nullable=False, default='none')
    discount_value = db.Column(db.Float, nullable=False, default=0)
    valid_from = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)
    service = db.relationship('Service', back_populates='bundles', lazy=True)

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
    bundle_id = db.Column(db.Integer, db.ForeignKey('booking_bundles.id', ondelete='SET NULL'), nullable=True)
    pricing_breakdown = db.Column(db.JSON, nullable=True)
    payment_reference = db.Column(db.String(100), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)
    service = db.relationship('Service', lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], back_populates='bookings', lazy=True)
    assigned_staff_user = db.relationship('User', foreign_keys=[assigned_staff_user_id], back_populates='assigned_bookings', lazy=True)
    payments = db.relationship('BookingPayment', back_populates='booking', lazy=True)
    bundle = db.relationship('BookingBundle', lazy=True)


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    booking_id = db.Column(db.String(20), db.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=True)
    notification_type = db.Column(db.String(40), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    dedupe_key = db.Column(db.String(180), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', lazy=True)
    booking = db.relationship('Booking', lazy=True)


@event.listens_for(Booking, 'after_update')
def create_booking_confirmation_notification(mapper, connection, booking):
    status_history = sqlalchemy_inspect(booking).attrs.status.history
    if not status_history.has_changes() or (booking.status or '').lower() != 'confirmed' or not booking.user_id:
        return

    notification_table = Notification.__table__
    dedupe_key = f'booking-confirmed:{booking.id}'
    existing = connection.execute(
        db.select(notification_table.c.id).where(notification_table.c.dedupe_key == dedupe_key)
    ).first()
    if existing:
        return

    connection.execute(
        notification_table.insert().values(
            user_id=booking.user_id,
            booking_id=booking.id,
            notification_type='booking_confirmation',
            message=f'Booking confirmed: {booking.service_name} on {booking.date}.',
            dedupe_key=dedupe_key,
        )
    )


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
    provider_reference = db.Column(db.String(120), nullable=True)
    idempotency_key = db.Column(db.String(120), nullable=True, unique=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)

    booking = db.relationship('Booking', back_populates='payments', lazy=True)
    payer = db.relationship('User', back_populates='booking_payments', lazy=True)


class UserLinkedAccount(db.Model):
    __tablename__ = 'user_linked_accounts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=False, index=True)
    provider = db.Column(db.String(50), nullable=False)  # gcash | google | facebook
    account_identifier = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    linked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_verified = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'provider', name='uq_user_provider'),
    )

    user = db.relationship('User', backref=db.backref('linked_accounts', cascade='all, delete-orphan', lazy=True))


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

    @property
    def event_date(self):
        val = getattr(self, 'time', None) or ""
        if not val:
            return None
        import re
        from datetime import date
        m = re.search(r'(\d{4}-\d{2}-\d{2})', str(val))
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                return None
        return None

    @property
    def is_past(self):
        from datetime import date
        d = self.event_date
        if d:
            return d < date.today()
        return False

class Promotion(db.Model):
    __tablename__ = 'promotions'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    promo_type = db.Column(db.String(50), nullable=True)  # Family|Group Tour|Student|Senior|Seasonal
    country = db.Column(db.String(60), nullable=True, default='Philippines')
    discount = db.Column(db.String(20))
    discount_value = db.Column(db.Float, nullable=True, default=0.0)
    discount_type = db.Column(db.String(20), nullable=True, default='percent')  # fixed | percent
    valid_until = db.Column(db.String(20))
    image_url = db.Column(db.String(500), nullable=True)

    zoo = db.relationship('Zoo', lazy=True)

    @property
    def effective_discount_value(self):
        val = float(self.discount_value or 0.0)
        if val <= 0 and self.discount:
            import re
            m = re.search(r"(\d+(?:\.\d+)?)", str(self.discount))
            if m:
                return float(m.group(1))
        return val

    @property
    def effective_discount_type(self):
        dtype = (self.discount_type or 'percent').lower()
        if self.discount:
            text = str(self.discount).lower()
            if 'php' in text or '₱' in text:
                return 'fixed'
            elif '%' in text:
                return 'percent'
        return dtype

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
    image_urls_json = db.Column(db.Text, nullable=True)
    panorama_360_url = db.Column(db.String(800), nullable=True)
    position_x = db.Column(db.Float, nullable=True)
    position_y = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='zones', lazy=True)

    @property
    def image_urls(self) -> list[str]:
        """Return visitor-facing zone photos while tolerating legacy rows."""
        if not self.image_urls_json:
            return []
        try:
            values = json.loads(self.image_urls_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        return [str(value) for value in values if isinstance(value, str) and value.strip()]

    @image_urls.setter
    def image_urls(self, values: list[str]) -> None:
        self.image_urls_json = json.dumps(
            [str(value) for value in values if isinstance(value, str) and value.strip()]
        )


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
    name = db.Column(db.String(50), nullable=False, unique=True)  # Standard/Pro
    price = db.Column(db.Float, nullable=False)
    duration = db.Column(db.String(10), nullable=False)  # monthly|yearly
    duration_months = db.Column(db.Integer, nullable=False)
    features = db.Column(db.Text, nullable=True)
    limits = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # tier_level: 0=free/basic, 1=standard, 2=pro/advanced
    tier_level = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subscriptions = db.relationship('ZooSubscription', back_populates='plan', lazy=True)


class ZooSubscription(db.Model):
    __tablename__ = 'zoo_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete="CASCADE"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id', ondelete="CASCADE"), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active')  # active|expired|pending
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', back_populates='subscriptions', lazy=True)
    plan = db.relationship('SubscriptionPlan', back_populates='subscriptions', lazy=True)
    payments = db.relationship('SubscriptionPayment', back_populates='subscription', lazy=True)

    def refresh_status(self, now: datetime | None = None):
        now = now or datetime.utcnow()
        if self.status == 'pending':
            return  # pending stays pending until Super Admin approves
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


class TriviaQuestion(db.Model):
    __tablename__ = 'trivia_questions'
    id = db.Column(db.Integer, primary_key=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=True)  # None = platform-wide
    animal_id = db.Column(db.Integer, db.ForeignKey('animals.id', ondelete='SET NULL'), nullable=True)
    category = db.Column(db.String(80), nullable=False, default='General Wildlife')  # General Wildlife, Habitats, Diets, Conservation
    difficulty = db.Column(db.String(20), nullable=False, default='medium')  # easy, medium, hard
    question = db.Column(db.Text, nullable=False)
    options = db.Column(db.JSON, nullable=False)  # ["Option A", "Option B", "Option C", "Option D"]
    correct_option_index = db.Column(db.Integer, nullable=False, default=0)
    explanation = db.Column(db.Text, nullable=True)
    points_reward = db.Column(db.Integer, nullable=False, default=15)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    zoo = db.relationship('Zoo', lazy=True)
    animal = db.relationship('Animal', lazy=True)


class VisitorTriviaLog(db.Model):
    __tablename__ = 'visitor_trivia_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('trivia_questions.id', ondelete='CASCADE'), nullable=False, index=True)
    selected_option = db.Column(db.Integer, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    points_awarded = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', lazy=True)
    question = db.relationship('TriviaQuestion', lazy=True)


class VisitorBadge(db.Model):
    __tablename__ = 'visitor_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    badge_key = db.Column(db.String(50), nullable=False)
    badge_name = db.Column(db.String(100), nullable=False)
    badge_description = db.Column(db.String(255), nullable=True)
    badge_icon = db.Column(db.String(80), nullable=False, default='fa-solid fa-medal')
    unlocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', lazy=True)


class LoyaltyAccount(db.Model):
    __tablename__ = 'loyalty_accounts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)
    balance = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', lazy=True)
    transactions = db.relationship('LoyaltyTransaction', back_populates='account', cascade='all, delete-orphan', lazy=True)


class LoyaltyTransaction(db.Model):
    __tablename__ = 'loyalty_transactions'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('loyalty_accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    points = db.Column(db.Integer, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # earn|redeem|adjust|reverse
    description = db.Column(db.String(255), nullable=False)
    booking_id = db.Column(db.String(20), db.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    account = db.relationship('LoyaltyAccount', back_populates='transactions', lazy=True)
    booking = db.relationship('Booking', lazy=True)


class LoyaltySetting(db.Model):
    __tablename__ = 'loyalty_settings'
    id = db.Column(db.Integer, primary_key=True)
    points_per_currency = db.Column(db.Float, nullable=False, default=1.0)
    minimum_redemption_points = db.Column(db.Integer, nullable=False, default=100)
    currency_per_point = db.Column(db.Float, nullable=False, default=0.01)
    maximum_redemption_percent = db.Column(db.Float, nullable=False, default=50.0)
    expiration_days = db.Column(db.Integer, nullable=True)
    trivia_enabled = db.Column(db.Boolean, nullable=False, default=True)
    booking_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class BookingTicket(db.Model):
    __tablename__ = 'booking_tickets'
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.String(20), db.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False, unique=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True)
    token_payload = db.Column(db.String(300), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='issued')  # issued|checked_in|cancelled
    checked_in_at = db.Column(db.DateTime, nullable=True)
    checked_in_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    booking = db.relationship('Booking', lazy=True)
    checker = db.relationship('User', lazy=True)


class BookingTicketScan(db.Model):
    __tablename__ = 'booking_ticket_scans'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('booking_tickets.id', ondelete='CASCADE'), nullable=True, index=True)
    booking_id = db.Column(db.String(20), db.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True, index=True)
    staff_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    zoo_id = db.Column(db.Integer, db.ForeignKey('zoos.id', ondelete='CASCADE'), nullable=False, index=True)
    result = db.Column(db.String(30), nullable=False)  # checked_in|rejected|reversal
    reason = db.Column(db.String(255), nullable=True)
    scanned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ticket = db.relationship('BookingTicket', lazy=True)
    booking = db.relationship('Booking', lazy=True)
    staff_user = db.relationship('User', lazy=True)
    zoo = db.relationship('Zoo', lazy=True)


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
