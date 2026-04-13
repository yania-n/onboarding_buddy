"""
agents/access_agent.py — IT Access & Tools Provisioning Agent
=============================================================
Reads the tool list assigned by the manager and raises access tickets
on Day 1. Tracks provisioning status and surfaces blocked/delayed
requests to the joiner and manager.

In production: connects to the IT provisioning API.
Current mode: simulated (creates tickets with PENDING status + logs them).
"""

import uuid
from datetime import datetime

from core.models import JoinerProfile, JoinerState, AccessRequest, AccessStatus
from core.state_store import StateStore


class AccessAgent:
    """Raises IT provisioning tickets and tracks their status."""

    def __init__(self, store: StateStore):
        self.store = store

    def raise_access_tickets(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Create an AccessRequest for every tool in the joiner's tool list.
        In production: submit to IT provisioning API.
        Currently: creates PENDING records in state.
        """
        if not profile.tool_access:
            self.store.append_to_state(
                profile.joiner_id,
                notifications=["🔧 No tool access requests were configured by your manager. "
                               "Reach out to your manager or IT if you need system access."],
            )
            return

        new_requests = []
        requests_raised = []
        for tool_name, permission_level in profile.tool_access.items():
            ticket_id = f"IT-{uuid.uuid4().hex[:8].upper()}"
            req = AccessRequest(
                tool_name=tool_name,
                permission_level=permission_level,
                status=AccessStatus.PENDING,
                ticket_id=ticket_id,
                raised_at=datetime.utcnow(),
            )
            new_requests.append(req)
            requests_raised.append(f"• {tool_name} ({permission_level}) — Ticket {ticket_id}")

        notification = (
            f"🔐 IT Access Requests Raised on Day 1\n\n"
            f"The following access tickets have been submitted:\n\n"
            + "\n".join(requests_raised)
            + "\n\nExpect provisioning within 1–2 business days. "
            "You'll be notified here when each one is ready."
        )
        # Use atomic append to avoid race condition with other agents
        self.store.append_to_state(
            profile.joiner_id,
            notifications=[notification],
            access_requests=new_requests,
        )

    def update_ticket_status(
        self, joiner_id: str, ticket_id: str, new_status: AccessStatus, notes: str = ""
    ) -> bool:
        """Update the status of an access ticket (called by IT system callback or admin)."""
        state = self.store.get_state(joiner_id)
        if not state:
            return False

        for req in state.access_requests:
            if req.ticket_id == ticket_id:
                req.status = new_status
                req.notes = notes
                if new_status == AccessStatus.PROVISIONED:
                    req.provisioned_at = datetime.utcnow()
                    state.app_notifications.append(
                        f"✅ Access granted: {req.tool_name} ({req.permission_level}) is ready to use!"
                    )
                elif new_status == AccessStatus.BLOCKED:
                    state.app_notifications.append(
                        f"⚠️ Access blocked for {req.tool_name}: {notes}. "
                        "Please contact IT or your manager."
                    )
                self.store.save_state(state)
                return True

        return False

    def get_access_summary(self, joiner_id: str) -> list[dict]:
        """Return a summary of all access requests for the UI."""
        state = self.store.get_state(joiner_id)
        if not state:
            return []
        return [
            {
                "tool": r.tool_name,
                "level": r.permission_level,
                "status": r.status.value,
                "ticket": r.ticket_id,
            }
            for r in state.access_requests
        ]
