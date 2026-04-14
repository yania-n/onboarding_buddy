"""
agents/integration_agent.py — Integration Agent (Layer 4 Added Agent)
======================================================================
Acts as the connector layer between the AI agents and the organisation's
existing tools. Makes the system produce outcomes rather than to-do lists.

Per the updated system design (April 2026):
  - Executes real actions in connected systems
  - Creates/suggests calendar invites (PoC: directs joiner to book directly)
  - Raises IT access tickets (PoC: simulated, logged to state store)
  - Reads LMS completion data (PoC: simulated, admin confirms manually)
  - Routes notifications to the right channel (PoC: in-app only)

PoC constraints applied here:
  - No HRIS, no MS Teams, no Outlook calendar API
  - Calendar booking → direct joiner to contact the person with email/link
  - IT tickets → simulated (written to state store, visible in My Access tab)
  - LMS → simulated (admin confirms completion in admin portal)
  - All external integration calls are no-ops that log their intent clearly

This agent is called once at activation to handle integration actions
that fall outside the scope of the core agents.
"""

import uuid
from datetime import datetime

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import ANTHROPIC_API_KEY, MODEL_FAST, LMS_API_KEY, IT_PROVISIONING_API_KEY
from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore


class IntegrationAgent:
    """
    Connector layer between OnboardingBuddy and external org systems.

    In PoC mode:
      - All external actions are simulated and logged
      - In-app notifications explain what would happen in production
      - Calendar booking is replaced with direct contact instructions
    """

    def __init__(self, store: StateStore):
        self.store   = store
        self._client = (
            anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run_activation_integrations(
        self, profile: JoinerProfile, state: JoinerState
    ) -> None:
        """
        Execute all integration actions on joiner activation (Day 1).
        Called in parallel with other core agents by the orchestrator.

        Actions performed:
          1. Buddy intro contact details (directs joiner to reach out)
          2. IT provisioning confirmation (simulated)
          3. LMS account setup confirmation (simulated)
        """
        print(f"[IntegrationAgent] Running activation integrations for {profile.full_name}")

        # Action 1: Buddy contact — direct the joiner to reach out themselves
        self._notify_buddy_contact(profile)

        # Action 2: Simulate IT provisioning acknowledgement
        self._confirm_it_provisioning(profile)

        # Action 3: Simulate LMS account setup
        self._confirm_lms_setup(profile)

        print(f"[IntegrationAgent] Activation integrations complete for {profile.full_name}")

    def check_lms_completion(self, joiner_id: str) -> bool:
        """
        Check whether all mandatory LMS courses are complete.

        PoC: simulated — always returns False until admin manually confirms.
        Production: would call the LMS API with the joiner's employee ID.
        """
        if LMS_API_KEY:
            # TODO (production): call LMS API to check course completion status
            # e.g.: lms_client.get_completion_status(joiner_id)
            pass

        # In PoC, LMS completion is confirmed manually by admin in the portal
        state = self.store.get_state(joiner_id)
        if state:
            return state.lms_mandatory_confirmed
        return False

    # ── Integration actions ───────────────────────────────────────────────────

    def _notify_buddy_contact(self, profile: JoinerProfile) -> None:
        """
        Generate clear instructions for the joiner to arrange their buddy intro.

        PoC: no Outlook/calendar API. Instead, surface the buddy's contact
        details prominently so the joiner can reach out themselves.
        """
        calendar_line = (
            f"\n📅 **Book via calendar:** {profile.buddy_calendar_link}"
            if profile.buddy_calendar_link
            else ""
        )

        message = (
            f"📞 **Arrange Your Buddy Intro Call**\n\n"
            f"Your buddy is **{profile.buddy_name}** — reach out directly to arrange "
            f"your intro call at a time that works for both of you:\n\n"
            f"✉️ **Email:** {profile.buddy_email}"
            f"{calendar_line}\n\n"
            f"Suggested agenda for your first call:\n"
            f"- Quick intro and background\n"
            f"- What does a typical week look like in {profile.department}?\n"
            f"- Top 3 things to know as a new joiner\n"
            f"- Any questions you have so far\n\n"
            f"Aim to connect within your first 2 days — it will make a big difference! 🤝"
        )

        self.store.append_to_state(
            joiner_id=profile.joiner_id,
            notifications=[message],
        )

    def _confirm_it_provisioning(self, profile: JoinerProfile) -> None:
        """
        Simulate IT provisioning confirmation.

        PoC: logs a simulated confirmation. In production this would
        call the IT provisioning API to trigger ticket creation.
        """
        if IT_PROVISIONING_API_KEY:
            # TODO (production): call IT provisioning API here
            # e.g.: it_client.create_access_batch(profile.joiner_id, profile.tool_access)
            pass

        tool_count = len(profile.tool_access)
        if tool_count == 0:
            return

        self.store.append_to_state(
            joiner_id=profile.joiner_id,
            notifications=[
                f"✅ **IT Access — {tool_count} request(s) queued**\n\n"
                f"Your IT access requests have been submitted. Most access is "
                f"provisioned within 1–3 business days. Track progress in **My Access** tab.\n\n"
                f"If anything isn't ready by Day 3, contact your manager "
                f"**{profile.manager_name}** ({profile.manager_email})."
            ],
        )

    def _confirm_lms_setup(self, profile: JoinerProfile) -> None:
        """
        Simulate LMS account setup confirmation.

        PoC: generates a notification directing the joiner to the LMS.
        In production this would call the LMS API to trigger account creation.
        """
        message = (
            f"🎓 **Your Learning Account**\n\n"
            f"Your LMS (Learning Management System) account is being set up for you.\n\n"
            f"**When ready, log in with your company email:** {profile.email}\n\n"
            f"Your mandatory courses (Phase 3) will be pre-assigned. Contact your manager "
            f"**{profile.manager_name}** ({profile.manager_email}) if you need help "
            f"accessing the LMS or finding your assigned courses."
        )

        self.store.append_to_state(
            joiner_id=profile.joiner_id,
            notifications=[message],
        )
