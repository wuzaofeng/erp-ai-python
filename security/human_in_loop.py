from dataclasses import dataclass
from datetime import datetime
from typing import Literal
import uuid


DANGEROUS_KEYWORDS = ["删除", "批量删除", "删除所有", "清空", "drop", "truncate", "delete all"]

AFFECTED_ROWS_THRESHOLD = 10


@dataclass
class PendingApproval:
    approval_id: str
    user_id: str
    action: str
    details: dict
    created_at: datetime
    status: Literal["pending", "approved", "rejected"]


class HumanInLoop:
    def __init__(self):
        self._pending: dict[str, PendingApproval] = {}

    def needs_approval(self, action: str, details: dict) -> bool:
        is_dangerous = any(kw in action for kw in DANGEROUS_KEYWORDS)
        too_many_rows = (details.get("affected_rows") or 0) > AFFECTED_ROWS_THRESHOLD
        return is_dangerous or too_many_rows

    def request_approval(self, user_id: str, action: str, details: dict) -> PendingApproval:
        approval_id = f"apr_{uuid.uuid4().hex[:8]}"
        approval = PendingApproval(
            approval_id=approval_id,
            user_id=user_id,
            action=action,
            details=details,
            created_at=datetime.now(),
            status="pending",
        )
        self._pending[approval_id] = approval
        return approval

    def process(self, approval_id: str, decision: str, user_id: str) -> bool:
        approval = self._pending.get(approval_id)
        if not approval:
            raise ValueError("审批记录不存在")
        if approval.user_id != user_id:
            raise ValueError("无权限处理此审批")
        approval.status = "approved" if decision == "approve" else "rejected"
        return approval.status == "approved"

    def get_pending(self, user_id: str) -> list[PendingApproval]:
        return [a for a in self._pending.values() if a.user_id == user_id and a.status == "pending"]


human_in_loop = HumanInLoop()
