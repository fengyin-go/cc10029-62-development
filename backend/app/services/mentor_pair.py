"""师徒结对领域服务：结对登记、验收、结项，含跨模块教师冲突检测和学期目标关联。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class MentorPairService(BaseModuleService):
    MODULE = "mentor_pair"
    ENTITY = "结对记录"
    OPERATION_TERM = "验收结对"
    LIST_FIELDS = ["指导教师", "青年教师", "结对目标", "起止日期", "指导计划", "阶段产出", "终期评价", "备注说明"]
    REQUIRED_FIELDS = ["指导教师", "青年教师", "结对目标"]
    STATUS_ORDER = ["草稿", "进行中", "待验收", "已结项"]
    ACTION_RULES = {"验收结对": "已结项", "调整计划": "进行中", "终止结对": "已结项"}
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """创建结对记录：同一指导教师不能同时被多个结对占用同一时段。"""
        mentor = str(values.get("指导教师", "") or "").strip()
        date_range = str(values.get("起止日期", "") or "").strip()
        teacher = str(values.get("青年教师", "") or "").strip()

        if mentor and teacher and mentor == teacher:
            raise ValueError("指导教师和青年教师不能是同一个人")

        if mentor and date_range and values.get("名额编号") in (None, ""):
            # 由导师名额发起的结对按名额容量控制，多条结对可以属于同一时段；
            # 手工登记的结对仍沿用「同一时段只能有一段进行中」的旧约束。
            existing = store.rows("mentor_pair")
            for row in existing:
                if (str(row.get("指导教师", "")).strip() == mentor
                        and str(row.get("起止日期", "")).strip() == date_range
                        and row.get("status") in ("进行中", "待验收")):
                    raise ValueError(
                        f"结对冲突：指导教师 {mentor} 在 {date_range} 时段已有进行中的结对，"
                        f"不能同时被多个结对占用"
                    )

        entry, missing = super().create_entry(values)
        if entry is not None:
            entry["关联目标"] = values.get("关联目标")
            entry["名额编号"] = values.get("名额编号")
            entry["指导方向"] = values.get("指导方向", "")
            entry["学期"] = values.get("学期", "")
            entry["候选序号"] = values.get("候选序号", 0)
        return entry, missing

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行动作，含业务约束和跨模块关联。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        # 验收结对：必须在进行中或待验收状态
        if action == "验收结对":
            if entry.get("status") not in ("进行中", "待验收"):
                return None, f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，不可验收"

        # 调整计划：已结项的不可调整
        if action == "终止结对":
            if entry.get("status") not in ("进行中", "待验收"):
                return None, f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，不可终止"

        result, message = super().run_action(entry_id, action)
        if result is not None and action in ("验收结对", "终止结对"):
            # 延迟导入，避免与 pairing 的结对编排形成模块级循环依赖。
            from app.services.pairing import close_pair

            reason = "结对已验收结项" if action == "验收结对" else "结对已终止"
            close_pair(entry_id, reason)
            # close_pair 会释放目标上的名额占位并写回待办，回填最新状态。
            if result.get("关联目标") not in (None, ""):
                goal = store.find("semester_goal", int(result["关联目标"]))
                if goal is not None:
                    result["关联目标待办"] = goal.get("待办事项", "")
        return result, message