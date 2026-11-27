"""目标页导师检索与结对编排接口。

与通用资源路由不同，这里把「按学期查导师 → 发起结对 → 回看候选资格」
串成一条面向学期目标的业务链路，路由层只做参数解析，规则都在
`app.services.pairing` 和 `app.services.mentor_roster` 里。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import pairing

router = APIRouter(prefix="/api", tags=["导师结对"])


class PairingPayload(BaseModel):
    """发起结对：可以传名额编号，也可以直接传导师姓名。"""

    roster_id: int | None = None
    mentor: str | None = None
    direction: str | None = None


def _business_error(error: ValueError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(error))


def _not_found(error: ValueError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error))


@router.get("/semester_goal/{goal_id}/mentors")
def search_mentors(
    goal_id: int,
    direction: str | None = Query(default=None),
    include_full: bool = Query(default=False),
) -> dict[str, Any]:
    """从目标页按起始学期检索可接收指导的导师，可按指导方向筛选。"""
    try:
        return pairing.search_mentors(goal_id, direction=direction, include_full=include_full)
    except pairing.PairingError as error:
        raise _not_found(error) from error


@router.get("/semester_goal/{goal_id}/pairing")
def pairing_status(goal_id: int) -> dict[str, Any]:
    """回看目标：候选是否仍有本次确认资格，还是需要更换导师。"""
    try:
        return pairing.pairing_status(goal_id)
    except pairing.PairingError as error:
        raise _not_found(error) from error


@router.post("/semester_goal/{goal_id}/pairing")
def initiate_pairing(goal_id: int, payload: PairingPayload) -> dict[str, Any]:
    """从检索结果发起结对，占住该学期的剩余席位并写入待办。"""
    try:
        return pairing.initiate_pairing(
            goal_id,
            roster_id=payload.roster_id,
            mentor=payload.mentor,
            direction=payload.direction,
        )
    except pairing.PairingError as error:
        raise _business_error(error) from error


@router.post("/mentor_pair/{pair_id}/accept")
def accept_pair(pair_id: int) -> dict[str, Any]:
    """导师受理结对，并把结果写回学期目标的待办。"""
    pair, message = pairing.accept_pair(pair_id)
    if pair is None:
        raise HTTPException(status_code=409, detail=message)
    return {
        "ok": True,
        "message": message,
        "pair": pair,
        "goal": pairing.pairing_status(int(pair.get("关联目标") or 0)),
    }
