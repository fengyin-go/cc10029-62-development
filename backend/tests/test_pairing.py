"""学期目标按学期检索导师、发起结对与名额占位的业务约束测试。"""
import pytest

from app.seed import SEED_ROWS
from app.services import pairing
from app.services.mentor_pair import MentorPairService
from app.services.mentor_roster import remaining_slots
from app.services.semester_goal import SemesterGoalService
from app.store import store


def reset_modules():
    for module in ("semester_goal", "mentor_pair", "mentor_roster"):
        store.rows(module).clear()
        store.rows(module).extend(dict(row) for row in SEED_ROWS[module])


def make_goal(teacher: str, semester: str, title: str = "目标") -> dict:
    goal, missing = SemesterGoalService().create_entry({
        "目标描述": title,
        "量化指标": "完成 N 项",
        "责任教师": teacher,
        "起始学期": semester,
    })
    assert goal is not None and missing == []
    return goal


class TestMentorSearch:
    """目标页按学期检索导师"""

    def setup_method(self):
        reset_modules()

    def test_autumn_goal_only_sees_autumn_rosters(self):
        goal = store.find("semester_goal", 22)  # G-22，2026-秋季
        result = pairing.search_mentors(goal["id"])
        assert result["学期"] == "2026-秋季"
        assert {row["学期"] for row in result["items"]} == {"2026-秋季"}
        assert all(row["剩余名额"] > 0 for row in result["items"])

    def test_spring_slot_is_not_offered_to_autumn_goal(self):
        goal = store.find("semester_goal", 22)
        result = pairing.search_mentors(goal["id"], direction="课堂教学")
        # 林可春季还有名额，但秋季目标只应看到秋季那一行。
        assert [(row["导师姓名"], row["学期"]) for row in result["items"]] == [("林可", "2026-秋季")]

    def test_direction_filter(self):
        goal = store.find("semester_goal", 22)
        result = pairing.search_mentors(goal["id"], direction="课堂诊断")
        assert [row["导师姓名"] for row in result["items"]] == ["沈舟"]

    def test_full_roster_hidden_by_default(self):
        goal = store.find("semester_goal", 22)
        names = [row["导师姓名"] for row in pairing.search_mentors(goal["id"])["items"]]
        assert "程雪" not in names
        with_full = pairing.search_mentors(goal["id"], include_full=True)["items"]
        assert "程雪" in [row["导师姓名"] for row in with_full]


class TestSemesterIsolation:
    """秋季目标不能借用春季同名导师的名额"""

    def setup_method(self):
        reset_modules()

    def test_autumn_goal_cannot_take_spring_roster(self):
        goal = store.find("semester_goal", 22)
        spring_roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "林可" and row["学期"] == "2027-春季"
        )
        with pytest.raises(pairing.PairingError, match="不能替代"):
            pairing.initiate_pairing(goal["id"], roster_id=spring_roster["id"])
        assert goal["结对状态"] == "未结对"
        assert spring_roster["剩余名额"] == 1

    def test_autumn_goal_cannot_take_spring_by_name(self):
        goal = make_goal("周青", "2027-春季")
        # 只有秋季名额的导师不能给春季目标使用。
        with pytest.raises(pairing.PairingError, match="没有名为|不能替代"):
            pairing.initiate_pairing(goal["id"], mentor="沈舟")


class TestSlotContention:
    """同一剩余席位只允许一份有效结对"""

    def setup_method(self):
        reset_modules()
        self.goal_a = store.find("semester_goal", 22)   # G-22 秋季
        self.goal_b = store.find("semester_goal", 23)   # G-23 秋季
        self.roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "林可" and row["学期"] == "2026-秋季"
        )

    def test_first_candidate_holds_slot_second_is_invalid(self):
        first = pairing.initiate_pairing(self.goal_a["id"], roster_id=self.roster["id"])
        assert first["pair"]["id"]
        assert remaining_slots(self.roster) == 0

        with pytest.raises(pairing.PairingError, match="不具备本次确认资格"):
            pairing.initiate_pairing(self.goal_b["id"], roster_id=self.roster["id"])

    def test_two_goals_can_tell_whose_candidate_is_still_valid(self):
        pairing.initiate_pairing(self.goal_a["id"], roster_id=self.roster["id"])
        with pytest.raises(pairing.PairingError):
            pairing.initiate_pairing(self.goal_b["id"], roster_id=self.roster["id"])

        view_a = pairing.pairing_status(self.goal_a["id"])
        view_b = pairing.pairing_status(self.goal_b["id"])
        assert view_a["已具备确认资格"] is True
        assert view_a["候选资格"] == "待确认"
        assert view_b["已具备确认资格"] is False
        assert view_b["需更换导师"] is True
        assert view_b["待办状态"] == "需更换导师"

    def test_second_confirmed_cannot_squeeze_first_pending(self):
        """两个人各自打开候选、第二个人也选同一席位时，第一人的占位不能被顶掉。"""
        first = pairing.initiate_pairing(self.goal_a["id"], roster_id=self.roster["id"])
        # 第二个浏览器看到的仍是「剩余 1」，此时才点选。
        assert first["pair"]["id"]
        with pytest.raises(pairing.PairingError):
            pairing.initiate_pairing(self.goal_b["id"], roster_id=self.roster["id"])

        # 第一人的候选仍是该席位唯一有效占位，受理不受第二人影响。
        assert pairing.pairing_status(self.goal_a["id"])["已具备确认资格"] is True
        accepted, message = pairing.accept_pair(first["pair"]["id"])
        assert accepted is not None, message
        assert pairing.pairing_status(self.goal_a["id"])["候选资格"] == "资格有效"

    def test_only_one_effective_pairing_for_same_slot(self):
        first = pairing.initiate_pairing(self.goal_a["id"], roster_id=self.roster["id"])
        with pytest.raises(pairing.PairingError):
            pairing.initiate_pairing(self.goal_b["id"], roster_id=self.roster["id"])

        pair_id = first["pair"]["id"]
        pairing.accept_pair(pair_id)
        effective = [
            row for row in store.rows("mentor_pair")
            if row.get("名额编号") == self.roster["id"]
            and row.get("status") in ("草稿", "进行中", "待验收")
        ]
        assert [row["id"] for row in effective] == [pair_id]

    def test_capacity_two_accepts_two_goals(self):
        roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "沈舟" and row["学期"] == "2026-秋季"
        )
        third = make_goal("郑青", "2026-秋季")
        one = pairing.initiate_pairing(self.goal_a["id"], roster_id=roster["id"])
        two = pairing.initiate_pairing(self.goal_b["id"], roster_id=roster["id"])
        assert remaining_slots(roster) == 0

        with pytest.raises(pairing.PairingError, match="不具备本次确认资格"):
            pairing.initiate_pairing(third["id"], roster_id=roster["id"])

        assert pairing.accept_pair(one["pair"]["id"])[0] is not None
        assert pairing.accept_pair(two["pair"]["id"])[0] is not None
        assert remaining_slots(roster) == 0

    def test_capacity_two_third_goal_gets_todo_to_change_mentor(self):
        roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "沈舟" and row["学期"] == "2026-秋季"
        )
        pairing.initiate_pairing(self.goal_a["id"], roster_id=roster["id"])
        pairing.initiate_pairing(self.goal_b["id"], roster_id=roster["id"])
        third = make_goal("郑青", "2026-秋季")

        with pytest.raises(pairing.PairingError):
            pairing.initiate_pairing(third["id"], roster_id=roster["id"])
        view = pairing.pairing_status(third["id"])
        assert view["已具备确认资格"] is False
        assert view["需更换导师"] is True
        assert view["待办状态"] == "需更换导师"


class TestResubmission:
    """已确认后的断线重提"""

    def setup_method(self):
        reset_modules()
        self.goal = store.find("semester_goal", 22)
        self.roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "林可" and row["学期"] == "2026-秋季"
        )

    def test_resubmit_pending_returns_same_pair(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        again = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        assert again["idempotent"] is True
        assert again["pair"]["id"] == first["pair"]["id"]

    def test_resubmit_after_confirm_returns_same_pair_and_keeps_goal_fields(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        pairing.accept_pair(first["pair"]["id"])

        again = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        assert again["idempotent"] is True
        assert again["pair"]["id"] == first["pair"]["id"]
        assert self.goal["起始学期"] == "2026-秋季"
        assert self.goal["责任教师"] == "周青"
        assert self.goal["结对记录编号"] == first["pair"]["id"]

    def test_accept_writes_back_todo_and_hides_mentor(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        pairing.accept_pair(first["pair"]["id"])

        view = pairing.pairing_status(self.goal["id"])
        assert view["结对状态"] == "已结对"
        assert view["候选资格"] == "资格有效"
        assert view["已具备确认资格"] is True
        assert view["待办状态"] == "已受理"
        assert "已受理" in view["待办事项"]
        # 名额占满后，其他目标在同一学期检索不到这位导师。
        other = store.find("semester_goal", 23)
        assert "林可" not in [row["导师姓名"] for row in pairing.search_mentors(other["id"])["items"]]


class TestReleaseSlot:
    """终止结对或废止目标后名额回到名录"""

    def setup_method(self):
        reset_modules()
        self.goal = store.find("semester_goal", 22)
        self.roster = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "林可" and row["学期"] == "2026-秋季"
        )

    def test_terminate_pair_releases_slot(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        pairing.accept_pair(first["pair"]["id"])
        assert remaining_slots(self.roster) == 0

        MentorPairService().run_action(first["pair"]["id"], "终止结对")
        assert remaining_slots(self.roster) == 1
        view = pairing.pairing_status(self.goal["id"])
        assert view["需更换导师"] is True
        assert view["结对状态"] == "已解除"
        assert self.goal["起始学期"] == "2026-秋季"

    def test_abolish_goal_releases_slot(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        pairing.accept_pair(first["pair"]["id"])
        assert remaining_slots(self.roster) == 0

        SemesterGoalService().run_action(self.goal["id"], "废止目标")
        assert remaining_slots(self.roster) == 1

    def test_switch_mentor_releases_previous_pending_slot(self):
        first = pairing.initiate_pairing(self.goal["id"], roster_id=self.roster["id"])
        spring_free = next(
            row for row in store.rows("mentor_roster")
            if row["导师姓名"] == "顾远" and row["学期"] == "2026-秋季"
        )
        pairing.initiate_pairing(self.goal["id"], roster_id=spring_free["id"])
        assert remaining_slots(self.roster) == 1
        assert remaining_slots(spring_free) == 0
        assert first["pair"]["id"] != self.goal["结对记录编号"]
