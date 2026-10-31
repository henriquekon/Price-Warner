"""Pure price-cycle evaluation rules, independent of persistence and SMTP."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from engine.alert_rules import ADDITIONAL_DROP_PERCENT, LOOKBACK_DAYS, percentile

RECOVERY_CONFIRMATIONS = 2
RECOVERY_PERCENT = 5.0


@dataclass(frozen=True)
class CycleSnapshot:
    first_price: float | None = None
    last_price: float | None = None
    candidate_high: float | None = None
    candidate_count: int = 0
    confirmed_high: float | None = None
    confirmed_at: datetime | None = None
    last_alert_price: float | None = None
    last_alert_at: datetime | None = None
    recovered_since_alert: bool = False


@dataclass(frozen=True)
class CycleDecision:
    snapshot: CycleSnapshot
    reasons: tuple[str, ...]
    should_send: bool
    reference: float | None


def evaluate_cycle(snapshot: CycleSnapshot, recent_prices: list[float], current: float,
                   threshold: float, now: datetime) -> CycleDecision:
    """Evaluate a new observation without treating a single high reading as a recovery."""
    if not isfinite(current) or current <= 0 or not 0 < threshold <= 100:
        return CycleDecision(snapshot, (), False, None)

    prices = [p for p in recent_prices if p is not None and isfinite(p) and p > 0]
    confirmed_high = snapshot.confirmed_high
    confirmed_at = snapshot.confirmed_at
    if confirmed_at is None or now - confirmed_at > timedelta(days=LOOKBACK_DAYS):
        confirmed_high = None
        confirmed_at = None

    candidate = snapshot.candidate_high
    count = snapshot.candidate_count
    last_price = snapshot.last_price
    # Confirm a rising reference only after two consistent observations.
    if last_price is None or current >= last_price * 1.05 or (candidate is not None and current >= candidate * 0.95):
        if candidate is not None and current >= candidate * 0.95:
            count += 1
            candidate = max(candidate, current)
        else:
            candidate, count = current, 1
    elif current < (candidate or current) * 0.95:
        candidate, count = None, 0

    if count >= RECOVERY_CONFIRMATIONS:
        if confirmed_high is None or candidate >= confirmed_high * 0.95:
            confirmed_high, confirmed_at = max(confirmed_high or 0, candidate), now
        candidate, count = None, 0

    if len(prices) >= 3:
        median = percentile(prices, 0.5)
        robust_prices = [p for p in prices if p <= median * 2]
        if confirmed_high is not None:
            robust_prices = [p for p in robust_prices if p <= confirmed_high * 1.05]
        rolling_reference = percentile(robust_prices, 0.75) if len(robust_prices) >= 3 else None
    else:
        rolling_reference = None
    references = [r for r in (rolling_reference, confirmed_high) if r is not None]
    reference = max(references) if references else None
    meets_threshold = reference is not None and current <= reference * (1 - threshold / 100)

    recovered = snapshot.recovered_since_alert
    if snapshot.last_alert_price is not None and confirmed_high is not None:
        if (confirmed_at is not None and snapshot.last_alert_at is not None
                and confirmed_at > snapshot.last_alert_at
                and confirmed_high >= snapshot.last_alert_price * (1 + RECOVERY_PERCENT / 100)):
            recovered = True

    reasons = ()
    if meets_threshold:
        reasons = (f"Price dropped at least {threshold:g}% from reference (R$ {reference:.2f} -> R$ {current:.2f})",)

    alert_price = snapshot.last_alert_price
    first_alert = alert_price is None
    further_drop = alert_price is not None and current <= alert_price * (1 - ADDITIONAL_DROP_PERCENT / 100)
    new_cycle = alert_price is not None and recovered and current <= alert_price
    should_send = meets_threshold and (first_alert or further_drop or new_cycle)

    updated = CycleSnapshot(
        first_price=snapshot.first_price if snapshot.first_price is not None else current,
        last_price=current,
        candidate_high=candidate,
        candidate_count=count,
        confirmed_high=confirmed_high,
        confirmed_at=confirmed_at,
        last_alert_price=alert_price,
        last_alert_at=snapshot.last_alert_at,
        recovered_since_alert=recovered,
    )
    return CycleDecision(updated, reasons, should_send, reference)


def mark_delivered(snapshot: CycleSnapshot, price: float, sent_at: datetime) -> CycleSnapshot:
    """Only mark notification state after successful SMTP delivery."""
    return CycleSnapshot(
        first_price=snapshot.first_price,
        last_price=snapshot.last_price,
        candidate_high=snapshot.candidate_high,
        candidate_count=snapshot.candidate_count,
        confirmed_high=snapshot.confirmed_high,
        confirmed_at=snapshot.confirmed_at,
        last_alert_price=price,
        last_alert_at=sent_at,
        recovered_since_alert=False,
    )
