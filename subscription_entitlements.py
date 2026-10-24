"""Additive subscription entitlement map for Skillvaya.

This module deliberately has no database, HTTP, or UI side effects. It is safe to
import while existing routes are migrated to explicit plan checks. Unknown plans
receive no paid-feature entitlements (fail closed).
"""
from __future__ import annotations

from typing import FrozenSet

# Keep these IDs aligned with app.py PLANS. Existing lower-tier IDs are preserved.
FEATURES: dict[str, FrozenSet[str]] = {
    "local": frozenset(),
    "priority": frozenset({"performance_insights"}),
    "plus": frozenset({
        "performance_insights",
        "lead_pipeline",
        "customer_booking_calendar",
        "crm",
        "quotation_followups",
        "invoice_payment_tracking",
        "customer_service_packages",
        "advanced_analytics",
    }),
    "spotlight": frozenset({
        "performance_insights",
        "lead_pipeline",
        "customer_booking_calendar",
        "crm",
        "quotation_followups",
        "invoice_payment_tracking",
        "customer_service_packages",
        "advanced_analytics",
        "featured_placement",
        "campaign_management",
        "promotional_offers",
        "vouchers",
        "branded_provider_page",
        "team_management",
        "lead_source_analytics",
        "priority_automation",
        "customer_announcements",
    }),
}


def normalize_plan(plan: object) -> str:
    """Return a known plan ID; never grant access for unknown or malformed values."""
    value = str(plan or "").strip().lower()
    aliases = {
        "business_plus": "plus",
        "business plus": "plus",
        "business_spotlight": "spotlight",
        "business spotlight": "spotlight",
    }
    value = aliases.get(value, value)
    return value if value in FEATURES else ""


def has_feature(plan: object, feature: str) -> bool:
    """Fail-closed entitlement check for a single feature."""
    plan_id = normalize_plan(plan)
    return bool(plan_id and feature in FEATURES[plan_id])


def features_for(plan: object) -> FrozenSet[str]:
    """Return immutable feature names for a known plan, or an empty set."""
    plan_id = normalize_plan(plan)
    return FEATURES.get(plan_id, frozenset())
