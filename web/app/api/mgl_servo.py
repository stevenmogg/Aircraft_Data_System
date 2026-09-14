"""MGL Autopilot servo install REST API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web.app.services import mgl_servo_install as inst
from web.app.services.mgl_servo.control import OFFSET_MAX, OFFSET_MIN

router = APIRouter(prefix="/api/mgl-servo", tags=["mgl-servo"])


class AxisBody(BaseModel):
    axis: str


class StepBody(BaseModel):
    step: str


class PositionBody(BaseModel):
    position: int = Field(ge=OFFSET_MIN, le=OFFSET_MAX)


class LimitBody(BaseModel):
    which: str


class CanTxBody(BaseModel):
    enable: bool


class OffsetBody(BaseModel):
    axis: str
    offset: int = Field(ge=OFFSET_MIN, le=OFFSET_MAX)


@router.get("/snapshot")
def snapshot():
    return inst.snapshot()


@router.post("/install")
def install(body: AxisBody):
    try:
        return inst.start_install(body.axis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/step")
def step(body: StepBody):
    try:
        return inst.set_step(body.step)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/position")
def position(body: PositionBody):
    try:
        return inst.set_position(body.position)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/limit")
def limit(body: LimitBody):
    try:
        return inst.capture_limit(body.which)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/offset")
def offset(body: OffsetBody):
    try:
        return inst.set_offset(body.axis, body.offset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/abort")
def abort():
    return inst.abort_install()


@router.post("/can-tx")
def can_tx(body: CanTxBody):
    return inst.set_can_tx(body.enable)
