from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from models import BookingBundle, LoyaltyAccount, LoyaltySetting, Promotion, Service, User, db
from services.loyalty import get_settings


class PricingError(ValueError):
    pass


@dataclass(frozen=True)
class PriceLine:
    name: str
    quantity: int
    unit_price: float
    discount: float
    total: float


@dataclass(frozen=True)
class PriceBreakdown:
    lines: tuple[PriceLine, ...]
    subtotal: float
    discount: float
    loyalty_discount: float
    total: float
    currency: str = "PHP"

    def as_dict(self) -> dict:
        return {
            "lines": [asdict(line) for line in self.lines],
            "subtotal": self.subtotal,
            "discount": self.discount,
            "loyalty_discount": self.loyalty_discount,
            "total": self.total,
            "currency": self.currency,
        }


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _discount(amount: Decimal, discount_type: str, value: float) -> Decimal:
    if value < 0:
        raise PricingError("Discount cannot be negative.")
    if discount_type == "percent":
        if value > 100:
            raise PricingError("Percentage discount cannot exceed 100.")
        return amount * Decimal(str(value)) / Decimal("100")
    if discount_type == "fixed":
        return min(amount, Decimal(str(value)))
    if discount_type in {"none", ""}:
        return Decimal("0")
    raise PricingError("Unsupported discount type.")


def calculate_booking_price(
    *,
    service: Service,
    guests: int,
    bundle: BookingBundle | None = None,
    promotion: Promotion | None = None,
    add_ons: list[Service] | None = None,
    loyalty_points: int = 0,
    user: User | None = None,
    visit_date: date | None = None,
) -> PriceBreakdown:
    if not service or service.price is None or float(service.price) < 0:
        raise PricingError("Service price is invalid.")
    if guests < 1:
        raise PricingError("Guests must be at least one.")
    if bundle:
        if not bundle.is_active or bundle.zoo_id != service.zoo_id:
            raise PricingError("The selected bundle is unavailable for this service.")
        if getattr(bundle, "service_id", None) and bundle.service_id != service.id:
            raise PricingError("The selected bundle is not available for this service.")
        if guests < bundle.min_guests or guests > bundle.max_guests:
            raise PricingError("Guest quantity is outside the selected bundle limits.")
        today = visit_date or date.today()
        if bundle.valid_from and today < bundle.valid_from:
            raise PricingError("The selected bundle is not active yet.")
        if bundle.valid_until and today > bundle.valid_until:
            raise PricingError("The selected bundle has expired.")

    lines: list[PriceLine] = []
    base_unit = Decimal(str(bundle.price if bundle else service.price))
    base_amount = base_unit * guests
    bundle_discount = _discount(base_amount, bundle.discount_type, bundle.discount_value) if bundle else Decimal("0")
    lines.append(PriceLine(bundle.name if bundle else service.name, guests, _money(base_unit), _money(bundle_discount), _money(base_amount - bundle_discount)))

    subtotal = base_amount - bundle_discount
    discount = bundle_discount
    for add_on in add_ons or []:
        if (
            not add_on
            or add_on.id == service.id
            or add_on.zoo_id != service.zoo_id
            or add_on.price is None
            or float(add_on.price) < 0
        ):
            raise PricingError("An add-on service is invalid.")
        amount = Decimal(str(add_on.price)) * guests
        subtotal += amount
        lines.append(PriceLine(add_on.name, guests, _money(Decimal(str(add_on.price))), 0.0, _money(amount)))

    if promotion:
        if promotion.zoo_id not in {None, service.zoo_id}:
            raise PricingError("Promotion does not belong to the selected zoo.")
        if not getattr(promotion, "is_active", True):
            raise PricingError("The selected promotion is inactive.")
        if promotion.valid_until:
            try:
                if (visit_date or date.today()) > date.fromisoformat(str(promotion.valid_until)):
                    raise PricingError("The selected promotion has expired.")
            except ValueError as exc:
                raise PricingError("Promotion expiry is invalid.") from exc
        promo_discount = _discount(subtotal, promotion.discount_type or "percent", float(promotion.discount_value or 0))
        discount += promo_discount
        subtotal -= promo_discount

    loyalty_discount = Decimal("0")
    if loyalty_points:
        if loyalty_points < 0:
            raise PricingError("Loyalty points cannot be negative.")
        if not user:
            raise PricingError("A visitor account is required to redeem points.")
        account = LoyaltyAccount.query.filter_by(user_id=user.id).first()
        setting = get_settings()
        if not account or loyalty_points > account.balance:
            raise PricingError("Insufficient loyalty points.")
        if loyalty_points < setting.minimum_redemption_points:
            raise PricingError("The selected points amount is below the redemption minimum.")
        loyalty_discount = Decimal(str(loyalty_points)) * Decimal(str(setting.currency_per_point))
        max_discount = subtotal * Decimal(str(setting.maximum_redemption_percent)) / Decimal("100")
        loyalty_discount = min(loyalty_discount, max_discount)

    total = subtotal - loyalty_discount
    if total < 0:
        raise PricingError("Final price cannot be negative.")
    pre_promotion_subtotal = sum(Decimal(str(line.total)) for line in lines)
    return PriceBreakdown(tuple(lines), _money(pre_promotion_subtotal), _money(discount), _money(loyalty_discount), _money(total))
