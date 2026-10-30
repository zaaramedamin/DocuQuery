"""
Pro plan (demo): switch your own account between Free and Pro with no payment.

There is no payment provider behind this, so it is a demonstration of the Pro
experience (bigger files, more sources, more questions). Set BILLING_DEMO_MODE=false
to switch it off; "Upgrade to Pro" then says that upgrading isn't available.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config
from security import AuthUser, get_current_user, limited_user
from services import db_service, plans

router = APIRouter(prefix="/api/billing", tags=["billing"])

demo_user = limited_user("billing", (30, 3600))


class DemoBody(BaseModel):
    plan: str = Field(pattern="^(free|pro)$")


@router.post("/demo")
def switch_plan(body: DemoBody, user: AuthUser = Depends(demo_user)):
    if not config.BILLING_DEMO_MODE:
        raise HTTPException(status_code=404, detail="Not found.")
    if body.plan == plans.PRO:
        fields = {
            "plan": plans.PRO,
            "subscription_status": "active",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "cancel_at_period_end": False,
        }
    else:
        fields = {"plan": plans.FREE, "subscription_status": "canceled", "cancel_at_period_end": False}
    db_service.update_profile(user.id, fields)
    return {"plan": body.plan}
