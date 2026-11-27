"""导师名录领域服务：按学期维护可接收指导的导师名额，并承接目标页的候选占位。

名额以「导师 + 学期」为边界，春季和秋季各算各的：秋季目标只能占秋季名额。
同一个剩余席位用「占位实例」（学期目标上的候选 + 结对记录）先到先得：
先提交的候选先占住，后来基于同一剩余席位的选择会判定为名额已满，
回看目标时能看到自己的候选是否仍然具备本次确认资格。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store

PENDING_PAIR_STATUS = "待确认"
PAIRED_STATUS = "已结对"
RELEASED_STATUS = "已解除"
# 尚未受理的占位和已经受理的有效结对都会占住席位。
HOLDING_GOAL_STATUSES = (PENDING_PAIR_STATUS, PAIRED_STATUS)
PENDING_QUALIFICATION = "待确认"
CONFIRMED_QUALIFICATION = "资格有效"
INVALID_QUALIFICATION = "候选失效"


def roster_rows_for(semester: str, direction: str | None = None) -> list[dict[str, Any]]:
    """返回指定学期（可按指导方向过滤）的导师名录行。"""
    rows = [
        row for row in store.rows("mentor_roster")
        if str(row.get("学期", "")).strip() == semester.strip()
    ]
    if direction:
        rows = [row for row in rows if str(row.get("指导方向", "")).strip() == direction.strip()]
    return rows


def roster_by_mentor(semester: str, mentor: str) -> dict[str, Any] | None:
    """按导师 + 学期精确查名录，春季名额不会命中秋季检索。"""
    for row in store.rows("mentor_roster"):
        if (str(row.get("学期", "")).strip() == semester.strip()
                and str(row.get("导师姓名", "")).strip() == mentor.strip()):
            return row
    return None


def _pair_holds(goal: dict[str, Any]) -> bool:
    """结对尚未结项时才继续占着名额；已结项/已终止的名额自动释放。"""
    pair_id = goal.get("结对记录编号")
    if pair_id in (None, ""):
        return False
    try:
        pair = store.find("mentor_pair", int(pair_id))
    except (TypeError, ValueError):
        return False
    # 尚未受理的结对是「草稿」状态，同样占住席位；结项/终止后释放。
    return pair is not None and pair.get("status") in ("草稿", "进行中", "待验收")


def valid_instances(roster: dict[str, Any]) -> list[dict[str, Any]]:
    """按名额容量算出真正占住席位的学期目标。

    已确认的结对优先保留；剩余席位按占位先后（候选序号）分配给待确认候选。
    超出容量的候选属于后来者，不能因为先点了按钮就继续有效。
    """
    roster_id = int(roster.get("id") or 0)
    capacity = max(int(roster.get("可指导名额") or 0) - int(roster.get("初始占用") or 0), 0)
    holding = [
        row for row in store.rows("semester_goal")
        if int(row.get("候选名额编号") or 0) == roster_id
        and row.get("结对状态") in HOLDING_GOAL_STATUSES
        and str(row.get("候选资格", "")) in (PENDING_QUALIFICATION, CONFIRMED_QUALIFICATION)
        and _pair_holds(row)
    ]
    confirmed = [
        row for row in holding
        if row.get("结对状态") == PAIRED_STATUS
        and str(row.get("候选资格", "")) == CONFIRMED_QUALIFICATION
    ]
    confirmed.sort(key=lambda row: int(row.get("候选序号") or 0))
    valid = confirmed[:capacity]
    free_slots = max(capacity - len(valid), 0)
    pending = [
        row for row in holding
        if row.get("结对状态") == PENDING_PAIR_STATUS
        and str(row.get("候选资格", "")) == PENDING_QUALIFICATION
    ]
    pending.sort(key=lambda row: int(row.get("候选序号") or 0))
    return valid + pending[:free_slots]


def remaining_slots(roster: dict[str, Any]) -> int:
    capacity = max(int(roster.get("可指导名额") or 0) - int(roster.get("初始占用") or 0), 0)
    return max(capacity - len(valid_instances(roster)), 0)


def refresh_roster(roster: dict[str, Any]) -> None:
    """按有效占位重算已占 / 剩余名额，占位释放后名额能回到名录。

    `初始占用` 是名录上线前已经形成的线下结对（不计入学期目标占位），
    保留它才能让示例里已满的导师继续显示为已满。
    """
    total = int(roster.get("可指导名额") or 0)
    baseline = int(roster.get("初始占用") or 0)
    valid = len(valid_instances(roster))
    roster["已占名额"] = min(baseline + valid, total)
    roster["剩余名额"] = max(total - baseline - valid, 0)
    roster["status"] = "开放" if roster["剩余名额"] > 0 else "已满"


class MentorRosterService(BaseModuleService):
    MODULE = "mentor_roster"
    ENTITY = "导师名额"
    OPERATION_TERM = "检索导师"
    LIST_FIELDS = ["导师姓名", "指导方向", "学期", "职称", "所在教研室", "备注说明"]
    REQUIRED_FIELDS = ["导师姓名", "指导方向", "学期"]
    STATUS_ORDER = ["开放", "已满", "已停用"]
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS = []

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(self.MODULE))
        # 列表展示的剩余席位始终从有效占位实时计算。
        for row in rows:
            refresh_roster(row)
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword and self.LIST_FIELDS:
            field = self.LIST_FIELDS[0]
            rows = [row for row in rows if keyword.casefold() in str(row.get(field, "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry, missing = super().create_entry(values)
        if entry is None:
            return entry, missing
        entry["可指导名额"] = int(values.get("可指导名额") or 1)
        entry["已占名额"] = int(values.get("已占名额") or 0)
        entry["剩余名额"] = max(entry["可指导名额"] - entry["已占名额"], 0)
        entry["初始占用"] = entry["已占名额"]
        entry["名额版本"] = 0
        return entry, missing
