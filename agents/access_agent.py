"""
agents/access_agent.py — IT Access & Tools Provisioning Agent
=============================================================
Reads the tool access list assigned by the manager and raises
provisioning tickets in the IT system on Day 1.

PoC mode: no live IT provisioning API. All tickets are simulated —
they are logged to the state store with PENDING status.
The integration agent / admin can mark them provisioned manually.

The agent also writes an in-app notification to the joiner listing:
  - Which tools are being provisioned and at what permission level
  - Expected timelines (SLA from KB if available, otherwise generic)
  - Who to contact if access is delayed

Data source: knowledge base for SLA and access procedure information.

Model routing:
  - KB retrieval: Voyage + FAISS (for SLA/procedure info)
  - Notification writing: Claude Haiku (brief, action-oriented)
"""

import uuid
from datetime import datetime

import asyncio

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import ANTHROPIC_API_KEY, MODEL_FAST
from core.models import JoinerProfile, JoinerState, AccessRequest, AccessStatus
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_ACCESS_SYSTEM = """You are OnboardingBuddy's Access & Tools agent.
Write a friendly in-app message telling a new joiner which IT access requests
have just been raised on their behalf.

Use ONLY the knowledge base context for SLA timelines and procedures.
If KB has no SLA data for a tool, say "typically 1–3 business days".

Format:
## Your IT Access Requests — Raised Today

Then list each tool:
**Tool Name** (Permission Level) — short note on what this gives access to

Then add:
## What to Expect
One paragraph: expected timelines and who to contact if delayed.
Direct them to email IT support or their manager — NO calendar booking.

Keep it under 200 words. Warm, reassuring tone."""


class AccessAgent:
    """
    Raises IT access provisioning tickets for a new joiner.
    Called at activation alongside other agents.

    In PoC mode all tickets are simulated (no live IT API).
    Tickets are written to the state store with PENDING status.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase = None):
        self.store   = store
        self.kb      = kb
        self._client = (
            anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def raise_access_tickets(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Simulate raising IT access tickets for every tool in the joiner's access list.

        1. Create an AccessRequest record for each tool (status=PENDING)
        2. Write all requests to the state store in a single atomic update
        3. Write an in-app notification summarising what was raised
        """
        print(f"[AccessAgent] Raising access tickets for {profile.full_name}")

        if not profile.tool_access:
            self.store.append_to_state(
                joiner_id=profile.joiner_id,
                notifications=["🔐 No tool access requests configured — check with your manager."],
            )
            return


        # Step 1: Build AccessRequest objects for each tool
        requests_to_raise: list[AccessRequest] = []
        for tool_name, permission_level in profile.tool_access.items():
            ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
            req = AccessRequest(
                tool_name        = tool_name,
                permission_level = permission_level,
                status           = AccessStatus.PENDING,
                ticket_id        = ticket_id,
                raised_at        = datetime.utcnow(),
                notes            = f"Auto-raised by OnboardingBuddy for {profile.full_name}",
            )
            requests_to_raise.append(req)
            print(f"[AccessAgent]   Raised ticket {ticket_id}: {tool_name} ({permission_level})")

        # Step 2: Write all tickets to state store atomically
        self.store.append_to_state(
            joiner_id       = profile.joiner_id,
            access_requests = requests_to_raise,
        )

        # Step 3: Generate and store the joiner notification (async LLM call)
        notification = await self._build_notification(profile, requests_to_raise)
        self.store.append_to_state(
            joiner_id     = profile.joiner_id,
            notifications = [notification],
        )
        print(f"[AccessAgent] {len(requests_to_raise)} ticket(s) raised for {profile.full_name}")

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _build_notification(
        self,
        profile: JoinerProfile,
        requests: list[AccessRequest],
    ) -> str:
        """
        Build the in-app access summary notification.
        Uses async LLM if available, otherwise produces a structured template.
        """
        # Retrieve any SLA / procedure info from KB (sync — local FAISS)
        sla_context = ""
        if self.kb:
            chunks = self.kb.retrieve(
                "IT access provisioning SLA timelines tool access request procedure",
                top_k=3,
            )
            if chunks:
                sla_context = "\n\n".join(c["text"] for c in chunks[:3])

        tool_lines = "\n".join(
            f"  - {r.tool_name} ({r.permission_level}) — Ticket {r.ticket_id}"
            for r in requests
        )

        if self._client and sla_context:
            return await self._generate_with_llm(profile, requests, sla_context)

        # Structured fallback
        return (
            f"🔐 **Your IT Access Requests — Raised Today**\n\n"
            f"The following access requests have been raised on your behalf:\n\n"
            f"{tool_lines}\n\n"
            f"**What to Expect:**\n"
            f"Most access requests are fulfilled within 1–3 business days. "
            f"If any tool isn't set up within 3 days of your start date, "
            f"contact IT support or your manager "
            f"**{profile.manager_name}** ({profile.manager_email}) directly.\n\n"
            f"You can track the status of each request in the **My Access** tab."
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _generate_with_llm(
        self,
        profile: JoinerProfile,
        requests: list[AccessRequest],
        sla_context: str,
    ) -> str:
        """Generate the access notification via Claude Haiku (async)."""
        tool_list = "\n".join(
            f"- {r.tool_name} ({r.permission_level})" for r in requests
        )
        user_msg = (
            f"New joiner: {profile.full_name}\n"
            f"Manager: {profile.manager_name} ({profile.manager_email})\n\n"
            f"Tools requested:\n{tool_list}\n\n"
            f"KB context on SLAs/procedures:\n{sla_context}"
        )
        resp = await self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=400,
            system=_ACCESS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return f"🔐 {resp.content[0].text.strip()}"
