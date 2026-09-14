"""REST: pilot MARK and related events."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.app.services import historian as hist_svc

router = APIRouter(prefix="/api/events", tags=["events"])


class MarkBody(BaseModel):
    text: str | None = None
    label: str | None = None


@router.post("/mark")
def create_mark(body: MarkBody | None = None):
    body = body or MarkBody()
    text = body.text or body.label
    resp = hist_svc.mark_event(text=text)
    if not resp.get("ok"):
        raise HTTPException(status_code=409, detail=resp.get("error") or resp)
    return resp
