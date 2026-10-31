"""Evaluate price opportunities independently of transport and persistence."""
from math import ceil, isfinite

LOOKBACK_DAYS = 30
MIN_HISTORY_SAMPLES = 3
NEW_LOW_DROP_PERCENT = 5.0
ADDITIONAL_DROP_PERCENT = 5.0
RECOVERY_PERCENT = 5.0


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = ceil((len(ordered) - 1) * fraction)
    return ordered[index]


def opportunity_reasons(prices: list[float], current_price: float, threshold_percent: float) -> list[str]:
    """Require evidence from recent observations before reporting a drop."""
    if not isfinite(current_price) or current_price <= 0 or not 0 < threshold_percent <= 100 or len(prices) < MIN_HISTORY_SAMPLES:
        return []
    prices = [value for value in prices if value is not None and isfinite(value) and value > 0]
    if len(prices) < MIN_HISTORY_SAMPLES:
        return []
    reference = percentile(prices, 0.75)
    previous_low = min(prices)
    reasons = []
    if current_price <= reference * (1 - threshold_percent / 100):
        reasons.append(f"Drop of at least {threshold_percent:g}% from recent reference (R$ {reference:.2f} -> R$ {current_price:.2f})")
    if reasons and current_price <= previous_low * (1 - NEW_LOW_DROP_PERCENT / 100):
        reasons.append(f"New 30-day low by at least {NEW_LOW_DROP_PERCENT:g}% (R$ {previous_low:.2f} -> R$ {current_price:.2f})")
    return reasons


def should_notify(current_price: float, last_sent_price: float | None,
                  prices_since_last_sent: list[float]) -> bool:
    """Alert on first opportunity, further significant drops, or recovered promotions."""
    if last_sent_price is None:
        return True
    if current_price <= last_sent_price * (1 - ADDITIONAL_DROP_PERCENT / 100):
        return True
    recovered = any(price >= last_sent_price * (1 + RECOVERY_PERCENT / 100)
                    for price in prices_since_last_sent)
    return recovered and current_price <= last_sent_price
