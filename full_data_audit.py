"""full_data_audit.py - Scans all tables for test/demo/fake data"""
from app import app
from models import db, Animal, Service, Event, Promotion, ParkRule, BookingBundle
from models import SubscriptionPlan, TriviaQuestion, ZooAdminFeedback
from models import EstablishmentRegistration, Zoo, ZooZone, Feedback, Booking, StaffTask

FAKE_WORDS = [
    'test', 'demo', 'sample', 'fake', 'dummy', 'placeholder',
    'qa', 'example', 'lorem', 'ipsum', 'temp', 'trial', 'mock'
]

def is_fake(*values):
    for v in values:
        if v and any(w in str(v).lower() for w in FAKE_WORDS):
            return True
    return False

def tag(condition):
    return '[FAKE?]' if condition else '[OK]   '

with app.app_context():
    found_any = False

    # ── Zoos ────────────────────────────────────────────────────────────────
    print('=== ZOOS ===')
    for z in Zoo.query.order_by(Zoo.id).all():
        f = is_fake(z.name, z.description, z.location)
        found_any = found_any or f
        print(f'  {tag(f)} [{z.id}] {z.name} | {z.location}')

    # ── Services ─────────────────────────────────────────────────────────────
    print('\n=== SERVICES ===')
    for s in Service.query.order_by(Service.zoo_id, Service.id).all():
        f = is_fake(s.name, s.description)
        found_any = found_any or f
        print(f'  {tag(f)} [{s.id}] zoo={s.zoo_id} | {s.name} | price={s.price}')

    # ── Animals ──────────────────────────────────────────────────────────────
    print('\n=== ANIMALS ===')
    for a in Animal.query.order_by(Animal.zoo_id, Animal.id).all():
        f = is_fake(a.name, a.species, a.description)
        found_any = found_any or f
        print(f'  {tag(f)} [{a.id}] zoo={a.zoo_id} | {a.name} | {a.species}')

    # ── Events ───────────────────────────────────────────────────────────────
    print('\n=== EVENTS ===')
    rows = Event.query.order_by(Event.zoo_id, Event.id).all()
    if not rows:
        print('  (none)')
    for e in rows:
        e_loc = getattr(e, 'location', '') or ''
        f = is_fake(e.name, e_loc)
        found_any = found_any or f
        print(f'  {tag(f)} [{e.id}] zoo={e.zoo_id} | {e.name} | {e_loc}')

    # ── Promotions ───────────────────────────────────────────────────────────
    print('\n=== PROMOTIONS ===')
    rows = Promotion.query.order_by(Promotion.zoo_id, Promotion.id).all()
    if not rows:
        print('  (none)')
    for p in rows:
        p_desc = getattr(p, 'description', '') or ''
        f = is_fake(p.name, p.code, p_desc)
        found_any = found_any or f
        print(f'  {tag(f)} [{p.id}] zoo={p.zoo_id} | {p.name} | code={p.code}')

    # ── Subscription Plans ───────────────────────────────────────────────────
    print('\n=== SUBSCRIPTION PLANS ===')
    for sp in SubscriptionPlan.query.order_by(SubscriptionPlan.id).all():
        f = is_fake(sp.name, sp.features)
        found_any = found_any or f
        print(f'  {tag(f)} [{sp.id}] {sp.name} | price={sp.price} | active={sp.is_active}')

    # ── Registrations ────────────────────────────────────────────────────────
    print('\n=== ESTABLISHMENT REGISTRATIONS ===')
    for r in EstablishmentRegistration.query.order_by(EstablishmentRegistration.id).all():
        f = is_fake(r.establishment_name, r.admin_email)
        found_any = found_any or f
        print(f'  {tag(f)} [{r.id}] {r.establishment_name} | {r.admin_email} | status={r.status} | legacy={r.is_legacy_migration}')

    # ── Trivia Questions ─────────────────────────────────────────────────────
    print('\n=== TRIVIA QUESTIONS ===')
    rows = TriviaQuestion.query.order_by(TriviaQuestion.id).all()
    if not rows:
        print('  (none)')
    for t in rows:
        q_short = (t.question or '')[:70]
        f = is_fake(t.question, t.category)
        found_any = found_any or f
        print(f'  {tag(f)} [{t.id}] zoo={t.zoo_id} | {q_short}')

    # ── Park Rules ───────────────────────────────────────────────────────────
    print('\n=== PARK RULES ===')
    rows = ParkRule.query.order_by(ParkRule.zoo_id, ParkRule.id).all()
    if not rows:
        print('  (none)')
    for pr in rows:
        f = is_fake(pr.title, pr.description)
        found_any = found_any or f
        print(f'  {tag(f)} [{pr.id}] zoo={pr.zoo_id} | {pr.title}')

    # ── Booking Bundles ──────────────────────────────────────────────────────
    print('\n=== BOOKING BUNDLES ===')
    rows = BookingBundle.query.order_by(BookingBundle.zoo_id, BookingBundle.id).all()
    if not rows:
        print('  (none)')
    for b in rows:
        f = is_fake(b.name, b.description)
        found_any = found_any or f
        print(f'  {tag(f)} [{b.id}] zoo={b.zoo_id} | {b.name}')

    # ── Zoo Zones ────────────────────────────────────────────────────────────
    print('\n=== ZOO ZONES ===')
    rows = ZooZone.query.order_by(ZooZone.zoo_id, ZooZone.id).all()
    if not rows:
        print('  (none)')
    for z in rows:
        f = is_fake(z.name, z.description)
        found_any = found_any or f
        print(f'  {tag(f)} [{z.id}] zoo={z.zoo_id} | {z.name}')

    # ── Bookings (visitor name check) ────────────────────────────────────────
    print('\n=== BOOKINGS (visitor name check) ===')
    conditions = [Booking.visitor_name.ilike(f'%{w}%') for w in FAKE_WORDS]
    bks = Booking.query.filter(db.or_(*conditions)).all()
    if bks:
        for b in bks:
            print(f'  [FAKE?] [{b.id}] visitor={b.visitor_name} | status={b.status} | zoo={b.zoo_id}')
            found_any = True
    else:
        print('  [OK]   No fake booking visitor names found.')

    # ── Staff Tasks ──────────────────────────────────────────────────────────
    print('\n=== STAFF TASKS ===')
    conditions2 = [StaffTask.title.ilike(f'%{w}%') for w in FAKE_WORDS]
    tasks = StaffTask.query.filter(db.or_(*conditions2)).all()
    if tasks:
        for t in tasks:
            print(f'  [FAKE?] [{t.id}] {t.title} | zoo={t.zoo_id}')
            found_any = True
    else:
        print('  [OK]   No fake staff tasks found.')

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print('=' * 60)
    if found_any:
        print('ACTION NEEDED: Review items flagged [FAKE?] above.')
    else:
        print('ALL CLEAR - No test/demo/fake data found in any table.')
    print('=' * 60)
