"""学期目标 ↔ 导师名额的结对编排。

目标页按「起始学期」检索导师名额，青年教师按指导方向筛选后发起结对。
名额以 rosters 的「导师 + 学期」为边界：秋季目标只能占秋季名额，
春季同名导师的名额再空也不能替代。

同一剩余席位采用先占先得：发起即占位（候选资格=待确认），导师受理后
转成有效结对。第二个目标再选中同一席位时会被判定为候选失效，并写回
「需更换导师」的待办；回看任意一张目标都能看到自己手上的候选资格。
"""
from __future__ import annotations

from typing import Any

from app.services.mentor_roster import (
    CONFIRMED_QUALIFICATION,
    PENDING_QUALIFICATION,
    PENDING_PAIR_STATUS,
    PAIRED_STATUS,
    RELEASED_STATUS,
    INVALID_QUALIFICATION,
    refresh_roster,
    remaining_slots,
    roster_by_mentor,
    valid_instances,
)
from app.services.mentor_pair import MentorPairService
from app.store import store

UNPAIRED = "未结对"
PENDING_PAIR = PENDING_PAIR_STATUS
PAIRED = PAIRED_STATUS
RELEASED = RELEASED_STATUS


class PairingError(ValueError):
    """结对编排中的可预期业务错误，路由层转成 ok=false 的提示。"""


def _goal(goal_id: int) -> dict[str, Any]:
    goal = store.find("semester_goal", goal_id)
    if goal is None:
        raise PairingError(f"学期目标 {goal_id} 不存在或已归档")
    return goal


def _semester(goal: dict[str, Any]) -> str:
    semester = str(goal.get("起始学期", "") or "").strip()
    if not semester:
        raise PairingError(
            f"学期目标 {goal.get('目标编号') or goal.get('id')} 未填写起始学期，无法按学期检索导师"
        )
    return semester


def goal_semester(goal: dict[str, Any]) -> str:
    return str(goal.get("起始学期", "") or "").strip()


def _pair(goal: dict[str, Any]) -> dict[str, Any] | None:
    pair_id = goal.get("结对记录编号")
    if pair_id in (None, ""):
        return None
    try:
        return store.find("mentor_pair", int(pair_id))
    except (TypeError, ValueError):
        return None


def _roster(goal: dict[str, Any]) -> dict[str, Any] | None:
    roster_id = goal.get("候选名额编号")
    if roster_id in (None, ""):
        return None
    try:
        return store.find("mentor_roster", int(roster_id))
    except (TypeError, ValueError):
        return None


def _next_candidate_seq() -> int:
    return max(
        (int(row.get("候选序号") or 0) for row in store.rows("semester_goal")),
        default=0,
    ) + 1


def _clear_candidate(goal: dict[str, Any]) -> None:
    goal["结对状态"] = UNPAIRED
    goal["候选资格"] = ""
    goal["候选导师"] = ""
    goal["候选学期"] = ""
    goal["候选名额编号"] = None
    goal["结对记录编号"] = None
    goal["待办状态"] = ""
    goal["待办事项"] = ""


def _release_pending(goal: dict[str, Any], reason: str) -> None:
    """释放目标此前尚未受理的占位，让目标可以改选其他导师。"""
    pair = _pair(goal)
    if pair is not None and pair.get("status") == "草稿":
        pair["status"] = "已结项"
        pair["pending"] = False
        pair["终期评价"] = reason
    _clear_candidate(goal)


def _mark_invalid(goal: dict[str, Any], roster: dict[str, Any], semester: str) -> None:
    # 失效的候选不能再挂着一条待受理的结对记录，否则会继续占住名额。
    dangling = _pair(goal)
    if dangling is not None and dangling.get("status") == "草稿":
        dangling["status"] = "已结项"
        dangling["pending"] = False
        dangling["终期评价"] = "候选失效，占位撤销"
    goal["结对状态"] = UNPAIRED
    goal["候选资格"] = INVALID_QUALIFICATION
    goal["候选导师"] = roster.get("导师姓名", "")
    goal["候选学期"] = semester
    goal["候选名额编号"] = roster.get("id")
    goal["结对记录编号"] = None
    goal["候选序号"] = _next_candidate_seq()
    goal["待办状态"] = "需更换导师"
    goal["待办事项"] = (
        f"{roster.get('导师姓名')} 在 {semester} 的剩余可指导名额已被占用，"
        f"手上的候选不具备本次确认资格，请更换导师后重新发起结对"
    )


def search_mentors(
    goal_id: int,
    *,
    direction: str | None = None,
    include_full: bool = False,
) -> dict[str, Any]:
    """按目标所属学期检索可接收指导的导师，可按指导方向筛选。"""
    goal = _goal(goal_id)
    semester = _semester(goal)
    direction = str(direction or "").strip()
    items: list[dict[str, Any]] = []
    for roster in store.rows("mentor_roster"):
        if str(roster.get("学期", "")).strip() != semester:
            continue
        if roster.get("status") == "已停用":
            continue
        if direction and direction.casefold() not in str(roster.get("指导方向", "")).casefold():
            continue
        refresh_roster(roster)
        free = remaining_slots(roster)
        if not include_full and free <= 0:
            continue
        items.append({
            **roster,
            "剩余名额": free,
            "可用名额": free,
            "已占名额": int(roster.get("可指导名额") or 0) - free,
            "学期目标": goal.get("目标编号") or f"#{goal.get('id')}",
        })
    items.sort(key=lambda row: (
        str(row.get("指导方向", "")), str(row.get("导师姓名", "")), int(row.get("id") or 0)
    ))
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "size": len(items),
        "学期": semester,
        "目标编号": goal.get("目标编号") or f"#{goal.get('id')}",
        "责任教师": goal.get("责任教师", ""),
    }


def _resolve_roster(
    goal: dict[str, Any], semester: str, roster_id: int | None, mentor: str | None,
) -> dict[str, Any]:
    roster: dict[str, Any] | None = None
    if roster_id not in (None, ""):
        try:
            roster = store.find("mentor_roster", int(roster_id))
        except (TypeError, ValueError):
            roster = None
        if roster is None:
            raise PairingError(f"导师名额 {roster_id} 不存在")
        if str(roster.get("学期", "")).strip() != semester:
            raise PairingError(
                f"目标 {goal.get('目标编号') or goal.get('id')} 属于 {semester}，"
                f"只能使用 {semester} 的可指导名额；"
                f"{roster.get('导师姓名')} 的 {roster.get('学期')} 名额不能替代"
            )
        return roster

    name = str(mentor or "").strip()
    if not name:
        raise PairingError("请选择要发起结对的导师")
    roster = roster_by_mentor(semester, name)
    if roster is None:
        other = next(
            (
                row for row in store.rows("mentor_roster")
                if str(row.get("导师姓名", "")).strip() == name
                and str(row.get("学期", "")).strip() != semester
            ),
            None,
        )
        if other is not None:
            raise PairingError(
                f"目标 {goal.get('目标编号') or goal.get('id')} 属于 {semester}，"
                f"只能使用 {semester} 的可指导名额；"
                f"{name} 的 {other.get('学期')} 名额不能替代"
            )
        raise PairingError(f"{semester} 没有名为 {name} 的可指导导师")
    return roster


def initiate_pairing(
    goal_id: int,
    *,
    roster_id: int | None = None,
    mentor: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """从检索结果发起结对；同一目标重复提交保持幂等并取回原结对编号。"""
    goal = _goal(goal_id)
    semester = _semester(goal)
    current_status = str(goal.get("结对状态") or UNPAIRED)

    # 已经受理的结对：断线重提仍取回原编号，不改动目标的原学期和负责人。
    if current_status == PAIRED and goal.get("结对记录编号"):
        pair = _pair(goal)
        return {
            "ok": True,
            "message": f"该目标已完成结对，取回原结对记录 #{goal.get('结对记录编号')}",
            "pair": pair,
            "goal": goal,
            "idempotent": True,
        }

    roster = _resolve_roster(goal, semester, roster_id, mentor)
    if direction and str(direction).strip():
        if str(direction).strip().casefold() not in str(roster.get("指导方向", "")).casefold():
            raise PairingError(
                f"导师 {roster.get('导师姓名')} 的指导方向为 {roster.get('指导方向')}，"
                f"与筛选方向 {direction} 不一致"
            )

    # 同一目标、同一名额重复提交：直接取回上次生成的结对编号。
    if (current_status == PENDING_PAIR
            and int(goal.get("候选名额编号") or 0) == int(roster.get("id") or 0)
            and goal.get("结对记录编号")):
        pair = _pair(goal)
        return {
            "ok": True,
            "message": f"已取回原结对记录 #{goal.get('结对记录编号')}，等待导师受理",
            "pair": pair,
            "goal": goal,
            "idempotent": True,
        }

    # 改选导师：先释放此前尚未受理的占位，再为新名额排队。
    if current_status == PENDING_PAIR and goal.get("结对记录编号"):
        _release_pending(goal, "候选改选其他导师，原占位释放")

    refresh_roster(roster)
    if remaining_slots(roster) <= 0:
        _mark_invalid(goal, roster, semester)
        raise PairingError(
            f"导师 {roster.get('导师姓名')} 在 {semester} 的剩余可指导名额已被占用，"
            f"当前候选不具备本次确认资格，请更换导师"
        )

    seq = _next_candidate_seq()
    pair, missing = MentorPairService().create_entry({
        "指导教师": roster.get("导师姓名", ""),
        "青年教师": goal.get("责任教师", ""),
        "结对目标": goal.get("目标描述", ""),
        "起止日期": f"{semester}学期",
        "指导计划": f"围绕学期目标 {goal.get('目标编号') or goal.get('id')} 制定指导计划",
        "阶段产出": "",
        "终期评价": "",
        "备注说明": (
            f"由学期目标 {goal.get('目标编号') or goal.get('id')} 发起，"
            f"占用 {roster.get('导师姓名')} {semester} 的指导名额"
        ),
    })
    if pair is None:
        raise PairingError(f"结对记录创建失败：缺少字段 {'、'.join(missing)}")

    pair["关联目标"] = goal.get("id")
    pair["名额编号"] = roster.get("id")
    pair["指导方向"] = roster.get("指导方向", "")
    pair["学期"] = semester
    pair["候选序号"] = seq
    pair["青年教师"] = goal.get("责任教师", "")
    pair["结对目标"] = goal.get("目标描述", "")

    goal["结对状态"] = PENDING_PAIR
    goal["候选资格"] = PENDING_QUALIFICATION
    goal["候选导师"] = roster.get("导师姓名", "")
    goal["候选学期"] = semester
    goal["候选名额编号"] = roster.get("id")
    goal["候选序号"] = seq
    goal["结对记录编号"] = pair["id"]
    goal["待办状态"] = "待受理"
    goal["待办事项"] = (
        f"已向导师 {roster.get('导师姓名')} 发起结对，等待受理；"
        f"结对记录 #{pair['id']}，指导方向 {roster.get('指导方向')}"
    )
    refresh_roster(roster)
    return {
        "ok": True,
        "message": (
            f"已占住 {roster.get('导师姓名')} 在 {semester} 的一个指导席位，"
            f"结对记录 #{pair['id']}，等待导师受理"
        ),
        "pair": pair,
        "goal": goal,
        "idempotent": False,
    }


def _active_pair(goal: dict[str, Any]) -> dict[str, Any] | None:
    pair = _pair(goal)
    if pair is None or pair.get("status") not in ("草稿", "进行中", "待验收"):
        return None
    return pair


def _qualification(goal: dict[str, Any]) -> tuple[bool, bool, str]:
    """返回 (候选是否仍有本次确认资格, 是否需要更换导师, 说明)。"""
    status = str(goal.get("结对状态") or UNPAIRED)
    qualification = str(goal.get("候选资格") or "")
    if status in (PENDING_PAIR, PAIRED) and _active_pair(goal) is None:
        # 通过师徒结对直接验收/终止后，目标上的候选不再有效。
        goal["结对状态"] = RELEASED
        goal["候选资格"] = RELEASED
        goal["待办状态"] = "需更换导师"
        goal["待办事项"] = "原结对已结项或终止，指导名额已释放，可重新检索导师"
        return False, True, "原结对已结束，请重新检索导师"
    if status == PAIRED and qualification == CONFIRMED_QUALIFICATION:
        return True, False, "候选已受理，结对有效"
    if status == PENDING_PAIR and qualification == PENDING_QUALIFICATION:
        roster = _roster(goal)
        if roster is not None and goal in valid_instances(roster):
            return True, False, "候选仍占着该剩余席位，等待导师受理"
        if roster is not None:
            # 读的时候才发现失效：同时撤销这条已无席位的待受理结对。
            _mark_invalid(goal, roster, goal_semester(goal))
            return False, True, "候选已失效，请更换导师"
        return False, True, "候选对应的导师名额不存在，请更换导师"
    if qualification == INVALID_QUALIFICATION:
        return False, True, str(goal.get("待办事项") or "候选已失效，请更换导师")
    if qualification == RELEASED:
        return False, True, "原结对已解除，请重新检索导师"
    return False, False, "尚未发起结对"


def pairing_status(goal_id: int) -> dict[str, Any]:
    """回看单张目标：手上的候选是否具备本次确认资格。"""
    goal = _goal(goal_id)
    roster = _roster(goal)
    if roster is not None:
        refresh_roster(roster)
    qualified, needs_new_mentor, explanation = _qualification(goal)
    pair = _pair(goal)
    return {
        "目标": goal.get("目标编号") or f"#{goal.get('id')}",
        "目标编号": goal.get("目标编号") or f"#{goal.get('id')}",
        "目标id": goal.get("id"),
        "责任教师": goal.get("责任教师", ""),
        "学期": goal_semester(goal),
        "结对状态": goal.get("结对状态") or UNPAIRED,
        "候选资格": goal.get("候选资格") or "",
        "候选导师": goal.get("候选导师") or "",
        "候选学期": goal.get("候选学期") or "",
        "候选名额编号": goal.get("候选名额编号"),
        "结对记录编号": goal.get("结对记录编号"),
        "待办状态": goal.get("待办状态") or "",
        "待办事项": goal.get("待办事项") or "",
        "已具备确认资格": qualified,
        "需更换导师": needs_new_mentor,
        "available_slots": remaining_slots(roster) if roster is not None else None,
        "说明": explanation,
        "pair": pair,
    }


def _confirmed_others(roster: dict[str, Any], goal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in valid_instances(roster)
        if row is not goal
        and row.get("结对状态") == PAIRED
        and str(row.get("候选资格", "")) == CONFIRMED_QUALIFICATION
    ]


def accept_pair(pair_id: int) -> tuple[dict[str, Any] | None, str]:
    """导师受理结对，并把受理结果写回学期目标的待办。"""
    pair = store.find("mentor_pair", pair_id)
    if pair is None:
        return None, f"结对记录 {pair_id} 不存在或已归档"

    goal_id = pair.get("关联目标")
    if goal_id in (None, ""):
        return None, f"结对记录 {pair_id} 未关联学期目标，无法受理"
    goal = store.find("semester_goal", int(goal_id))
    if goal is None:
        return None, f"结对记录 {pair_id} 关联的学期目标不存在或已归档"

    if goal.get("结对状态") == PAIRED and int(goal.get("结对记录编号") or 0) == pair_id:
        return pair, f"结对记录 #{pair_id} 已受理，无需重复受理"

    if goal.get("候选资格") != PENDING_QUALIFICATION or goal.get("结对状态") != PENDING_PAIR:
        return None, (
            f"学期目标 {goal.get('目标编号') or goal.get('id')} 当前候选资格为"
            f"'{goal.get('候选资格') or '无'}'，不可受理"
        )

    roster = store.find("mentor_roster", int(pair.get("名额编号") or 0))
    if roster is None:
        return None, f"结对记录 #{pair_id} 对应的导师名额不存在"
    semester = goal_semester(goal)
    if str(roster.get("学期", "")).strip() != semester:
        return None, (
            f"结对记录 #{pair_id} 占用的 {roster.get('学期')} 名额不能用于 {semester} 的学期目标"
        )

    baseline = int(roster.get("初始占用") or 0)
    capacity = max(int(roster.get("可指导名额") or 0) - baseline, 0)
    if len(_confirmed_others(roster, goal)) >= capacity:
        _mark_invalid(goal, roster, semester)
        return None, (
            f"导师 {roster.get('导师姓名')} 在 {semester} 的剩余名额已被确认，"
            f"当前候选不具备本次确认资格，请更换导师"
        )
    # 先到先得：超出容量的待确认候选不能抢先受理，否则会挤掉更早的占位。
    if goal not in valid_instances(roster):
        _mark_invalid(goal, roster, semester)
        return None, (
            f"导师 {roster.get('导师姓名')} 在 {semester} 的剩余席位已由更早的候选占住，"
            f"当前候选不具备本次确认资格，请更换导师"
        )

    pair["status"] = "进行中"
    pair["pending"] = True
    pair["abnormal"] = False
    goal["结对状态"] = PAIRED
    goal["候选资格"] = CONFIRMED_QUALIFICATION
    goal["待办状态"] = "已受理"
    goal["待办事项"] = (
        f"导师 {roster.get('导师姓名')} 已受理结对（{semester}，指导方向 "
        f"{roster.get('指导方向')}），结对记录 #{pair_id}，可到师徒结对中查看进度"
    )
    refresh_roster(roster)
    return pair, f"结对记录 #{pair_id} 已受理，并已写回学期目标待办"


def close_pair(pair_id: int, reason: str = "结对已终止") -> None:
    """终止或撤销结对外释放名额占位，目标保留原学期和负责人。"""
    pair = store.find("mentor_pair", pair_id)
    if pair is None or pair.get("关联目标") in (None, ""):
        return
    goal = store.find("semester_goal", int(pair.get("关联目标") or 0))
    if goal is None:
        return
    goal["结对状态"] = RELEASED
    goal["候选资格"] = RELEASED
    goal["待办状态"] = "需更换导师"
    goal["待办事项"] = f"{reason}，原指导名额已释放，可重新检索导师"
    roster = _roster(goal)
    if roster is not None:
        refresh_roster(roster)
