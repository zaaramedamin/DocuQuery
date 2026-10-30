"""
Subscription plans: what each plan allows, and which plan a user is on.

Limits are read from ``config`` when asked for (not when this module is
imported), so changing them in the environment — or in a test — takes effect
immediately.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
from services import db_service

FREE = "free"
PRO = "pro"

# A Pro period that ended longer ago than this is treated as over.
_GRACE = timedelta(days=3)
_ACTIVE_STATUSES = {"active", "trialing", "past_due"}


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    max_upload_bytes: int
    max_documents: int
    max_storage_bytes: int
    daily_questions: int
    max_ocr_pages: int


def limits_for(plan: str) -> PlanLimits:
    if plan == PRO:
        return PlanLimits(
            plan=PRO,
            max_upload_bytes=config.PRO_MAX_UPLOAD_BYTES,
            max_documents=config.PRO_MAX_DOCS_PER_USER,
            max_storage_bytes=config.PRO_MAX_STORAGE_BYTES_PER_USER,
            daily_questions=config.PRO_DAILY_QUERY_LIMIT,
            max_ocr_pages=config.PRO_MAX_OCR_PAGES,
        )
    return PlanLimits(
        plan=FREE,
        max_upload_bytes=config.MAX_UPLOAD_BYTES,
        max_documents=config.MAX_DOCS_PER_USER,
        max_storage_bytes=config.MAX_STORAGE_BYTES_PER_USER,
        daily_questions=config.DAILY_QUERY_LIMIT,
        max_ocr_pages=config.MAX_OCR_PAGES,
    )


def largest_upload_bytes() -> int:
    """The biggest file any plan accepts (the server-wide ceiling)."""
    return max(config.MAX_UPLOAD_BYTES, config.PRO_MAX_UPLOAD_BYTES)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def plan_of(profile: dict | None, now: datetime | None = None) -> str:
    """The plan a profile row is entitled to right now."""
    if not profile or profile.get("plan") != PRO:
        return FREE
    status = profile.get("subscription_status")
    if status and status not in _ACTIVE_STATUSES:
        return FREE
    ends = _parse_time(profile.get("current_period_end"))
    if ends and ends + _GRACE < (now or datetime.now(timezone.utc)):
        return FREE
    return PRO


def plan_for_user(user_id: str) -> PlanLimits:
    """The limits that apply to this user."""
    return limits_for(plan_of(db_service.get_profile(user_id)))


def upgrade_hint(limits: PlanLimits) -> bool:
    """True when hitting a limit should offer the Pro plan (it can't help someone already on it)."""
    return limits.plan == FREE


def limit_error(limits: PlanLimits, message: str, code: str) -> dict:
    """The body of a "you've hit a plan limit" error: the message, a code, and whether Pro would help."""
    return {
        "message": message,
        "code": code,
        "upgrade": upgrade_hint(limits),
        "plan": limits.plan,
    }
