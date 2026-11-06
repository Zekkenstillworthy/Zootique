import sys
sys.path.insert(0, '.')
from app import create_app
from models import ZooSubscription, SubscriptionPayment, Zoo, db
from datetime import datetime

a = create_app()
c = a.app_context()
c.push()

now = datetime.utcnow()

print('=== ALL SUBSCRIPTIONS ===')
for s in ZooSubscription.query.order_by(ZooSubscription.zoo_id.asc(), ZooSubscription.end_date.desc()).all():
    lp = SubscriptionPayment.query.filter_by(subscription_id=s.id).order_by(SubscriptionPayment.paid_at.desc()).first()
    is_active = s.end_date >= now and s.status != 'expired'
    print(f'  Sub {s.id}: Zoo={s.zoo_id}, Plan={s.plan.name}, Status={s.status}, EndDate={s.end_date.date()}, is_active={is_active}, LatestPay={lp.amount if lp else None}')

print()
print('=== COUNT BY END_DATE (raw) ===')
active_raw = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date >= now).scalar() or 0
expired_raw = db.session.query(db.func.count(ZooSubscription.id)).filter(ZooSubscription.end_date < now).scalar() or 0
print(f'  raw active_subs (end_date >= now): {active_raw}')
print(f'  raw expired_subs (end_date < now): {expired_raw}')

print()
print('=== PER-ZOO EFFECTIVE STATUS ===')
per_zoo_active = 0
per_zoo_expired = 0
zoos = Zoo.query.order_by(Zoo.name.asc()).all()
for zoo in zoos:
    subs = ZooSubscription.query.filter_by(zoo_id=zoo.id).order_by(ZooSubscription.end_date.desc()).all()
    if not subs:
        continue
    # Pick best subscription: active preferred, then latest
    best = None
    for s in subs:
        if s.status == 'active' and s.end_date >= now:
            best = s
            break
    if best is None:
        best = subs[0]
    is_active = best.end_date >= now and best.status != 'expired'
    if is_active:
        per_zoo_active += 1
    else:
        per_zoo_expired += 1
    print(f'  Zoo {zoo.id} ({zoo.name}): best_sub={best.id}, best_status={best.status}, best_end={best.end_date.date()}, is_active={is_active}')
print(f'Per-zoo ACTIVE: {per_zoo_active}')
print(f'Per-zoo EXPIRED: {per_zoo_expired}')

print()
print('=== MONTHLY REVENUE CALCULATION ===')
sub_monthly_by_zoo = {}
tier_counts = {}
tier_revenue = {}
active_sub_rows = (
    ZooSubscription.query
    .filter(ZooSubscription.end_date >= now)
    .order_by(ZooSubscription.zoo_id.asc(), ZooSubscription.end_date.desc())
    .all()
)
tier_by_zoo = {}
for s in active_sub_rows:
    if s.zoo_id not in tier_by_zoo:
        plan_name = s.plan.name if s.plan else 'Standard'
        tier_by_zoo[s.zoo_id] = plan_name
        dur = max(int(getattr(s.plan, 'duration_months', 1) or 1), 1)
        lp = SubscriptionPayment.query.filter_by(subscription_id=s.id).order_by(SubscriptionPayment.paid_at.desc()).first()
        plan_price = float(getattr(s.plan, 'price', 0.0) or 0.0)
        payment_amount = float(lp.amount) if (lp and lp.amount) else 0.0
        price = payment_amount if payment_amount > 0 else plan_price
        monthly_val = price / dur
        sub_monthly_by_zoo[s.zoo_id] = monthly_val
        tier_counts[plan_name] = tier_counts.get(plan_name, 0) + 1
        tier_revenue[plan_name] = tier_revenue.get(plan_name, 0.0) + monthly_val
        print(f'  Zoo {s.zoo_id}: plan={plan_name}, plan_price={plan_price}, payment_amount={payment_amount}, monthly_val={monthly_val}')

mrr_total = sum(sub_monthly_by_zoo.values())
print(f'MRR Total: {mrr_total}')
print(f'Tier counts: {tier_counts}')
print(f'Tier revenue: {tier_revenue}')
