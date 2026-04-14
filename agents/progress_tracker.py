"""
agents/progress_tracker.py — Progress Tracker Agent
====================================================
Monitors the state store continuously and sends friendly nudges when
a phase has not been marked complete within 3 days of its expected window.

Per the spec:
  - Checks all active joiners every 6 hours (via APScheduler in app.py)
  - Sends nudge if phase is overdue by 3+ days
  - Nudge is in-app only (PoC — no MS Teams or email)
  - Managers receive an in-app notification if significantly overdue (7+ days)
  - Manager cannot block or force-advance phases — nudge only

Also provides:
  - build_manager_summary() → weekly digest of all joiners for the admin Reports tab
"""

from datetime import date, timedelta
from typing import Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import (
    ANTHROPIC_API_KEY, MODEL_FAST,
    PHASE_BY_ID, PHASES,
    NUDGE_POLL_INTERVAL_SECONDS,
)
from core.models import JoinerState, PhaseStatus, NudgeRecord
from core.state_store import StateStore

import uuid


class ProgressTracker:
    """
    Monitors all active joiners and sends in-app nudges for overdue phases.
    Called on a schedule by APScheduler; also provides manager summaries.
    """

    def __init__(self, store: StateStore):
        self.store   = store
        self._client = (
            anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def check_all_joiners(self) -> int:
        """
        Check every active joiner for overdue phases and send nudges as needed.
        Called every 6 hours by the background scheduler.
        Returns the number of nudges sent.
        """
        nudges_sent = 0
        states = self.store.list_states()

        for state in states:
            if state.onboarding_complete:
                continue

            profile = self.store.get_profile(state.joiner_id)
            if not profile:
                continue

            overdue_days = self._get_phase_overdue_days(state)
            if overdue_days is None:
                continue

            phase_def = PHASE_BY_ID.get(state.current_phase)
            if not phase_def:
                continue

            # Nudge thresholds
            nudge_threshold  = phase_def.nudge_after_days     # typically 3 days
            manager_threshold = nudge_threshold + 4            # 7 days → manager alert

            if overdue_days >= nudge_threshold:
                self._send_joiner_nudge(state, profile, overdue_days)
                nudges_sent += 1

            if overdue_days >= manager_threshold:
                self._send_manager_alert(state, profile, overdue_days)

        if nudges_sent:
            print(f"[ProgressTracker] Sent {nudges_sent} nudge(s)")
        return nudges_sent

    def build_manager_summary(self, manager_email: str) -> str:
        """
        Build a plain-text weekly digest for a specific manager.
        Shows all joiners the manager is responsible for and their current status.
        Called from the admin Reports tab.
        """
        profiles = self.store.list_profiles()
        my_joiners = [
            p for p in profiles if p.manager_email.lower() == manager_email.lower()
        ]

        if not my_joiners:
            return f"No active joiners found for manager: {manager_email}"

        lines = [
            f"OnboardingBuddy — Weekly Manager Summary",
            f"Manager: {manager_email}",
            f"Generated: {date.today().isoformat()}",
            "=" * 50,
            "",
        ]

        for profile in my_joiners:
            state = self.store.get_state(profile.joiner_id)
            if not state:
                continue

            phase_def = PHASE_BY_ID.get(state.current_phase)
            phase_name = phase_def.name if phase_def else "Unknown"

            # Checklist progress
            total = len(state.checklist_items)
            done  = sum(1 for c in state.checklist_items if c.completed)
            pct   = int(done / total * 100) if total else 0

            # Access status
            pending_access = [r.tool_name for r in state.access_requests
                              if r.status.value == "pending"]

            # Latest sentiment
            sentiment_str = "No feedback yet"
            if state.feedback_responses:
                latest = state.feedback_responses[-1]
                if latest.sentiment:
                    sentiment_str = latest.sentiment.value.title()
                    if latest.sentiment_score:
                        sentiment_str += f" ({latest.sentiment_score:.1f}/5)"

            # Overdue check
            overdue = self._get_phase_overdue_days(state)
            overdue_str = f"⚠️ {overdue} day(s) overdue" if overdue and overdue >= 3 else "On track"

            lines += [
                f"Joiner: {profile.full_name}",
                f"  Role: {profile.job_title} ({profile.department})",
                f"  Start date: {profile.start_date}",
                f"  Current phase: {state.current_phase} — {phase_name}",
                f"  Checklist: {done}/{total} items ({pct}%)",
                f"  Phase status: {overdue_str}",
                f"  Sentiment: {sentiment_str}",
                f"  Pending access: {', '.join(pending_access) if pending_access else 'None'}",
                "",
            ]

        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_phase_overdue_days(self, state: JoinerState) -> Optional[int]:
        """
        Calculate how many days a joiner is overdue on their current phase.
        Returns None if the phase start date is unknown or phase is not active.
        """
        current = state.current_phase
        phase_status = state.phase_statuses.get(current)

        if phase_status != PhaseStatus.ACTIVE:
            return None

        start_date = state.phase_start_dates.get(current)
        if start_date is None:
            return None

        phase_def = PHASE_BY_ID.get(current)
        if not phase_def:
            return None

        # Expected completion date = phase start + phase window duration
        expected_days = phase_def.day_end - phase_def.day_start
        expected_completion = start_date + timedelta(days=expected_days)
        today = date.today()

        if today > expected_completion:
            return (today - expected_completion).days
        return None

    def _send_joiner_nudge(self, state: JoinerState, profile, overdue_days: int) -> None:
        """
        Send a friendly in-app nudge to the joiner for an overdue phase.
        Uses Claude Haiku for a warm, personalised message.
        """
        phase_def = PHASE_BY_ID.get(state.current_phase)
        phase_name = phase_def.name if phase_def else f"Phase {state.current_phase}"

        # Check how many items remain
        incomplete = [
            c.label for c in state.checklist_items
            if c.phase_id == state.current_phase and not c.completed
        ]

        message = self._generate_nudge(
            profile.full_name, state.current_phase, phase_name,
            overdue_days, incomplete
        )

        # Log nudge
        nudge = NudgeRecord(
            nudge_id  = str(uuid.uuid4()),
            joiner_id = state.joiner_id,
            channel   = "app",
            recipient = "joiner",
            phase_id  = state.current_phase,
            message   = message,
        )
        state.nudge_log.append(nudge)
        state.app_notifications.insert(0, f"🔔 {message}")
        self.store.save_state(state)

    def _send_manager_alert(self, state: JoinerState, profile, overdue_days: int) -> None:
        """
        Notify the admin dashboard when a joiner is significantly overdue.
        Stored as an in-app notification (no email/Teams in PoC).
        """
        phase_def = PHASE_BY_ID.get(state.current_phase)
        phase_name = phase_def.name if phase_def else f"Phase {state.current_phase}"

        alert = (
            f"⚠️ **Manager Alert — {profile.full_name}**\n"
            f"Phase {state.current_phase} ({phase_name}) is {overdue_days} day(s) overdue. "
            f"Consider reaching out to check if they need support."
        )
        state.app_notifications.insert(0, alert)
        self.store.save_state(state)

    def _generate_nudge(
        self,
        name: str,
        phase_id: int,
        phase_name: str,
        overdue_days: int,
        incomplete: list[str],
    ) -> str:
        """Generate a warm, personalised nudge message with Claude Haiku if available."""
        if self._client:
            try:
                return self._llm_nudge(name, phase_id, phase_name, overdue_days, incomplete)
            except Exception as e:
                print(f"[ProgressTracker] Nudge LLM error: {e}")

        # Template fallback
        remaining_str = (
            f" You have {len(incomplete)} item(s) left: {', '.join(incomplete[:2])}"
            + (" and more." if len(incomplete) > 2 else ".")
            if incomplete else ""
        )
        return (
            f"Hey {name.split()[0]}! 👋 Just checking in — Phase {phase_id} ({phase_name}) "
            f"is {overdue_days} day(s) past its expected window.{remaining_str} "
            f"You've got this — tick off the remaining items when you get a chance!"
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    def _llm_nudge(
        self,
        name: str,
        phase_id: int,
        phase_name: str,
        overdue_days: int,
        incomplete: list[str],
    ) -> str:
        """Generate nudge via Claude Haiku — warm, encouraging, brief."""
        incomplete_str = ", ".join(incomplete[:3]) if incomplete else "a few items"
        user_msg = (
            f"Write a brief (60–80 word), warm, encouraging nudge for a new joiner:\n"
            f"  Name: {name}\n"
            f"  Phase: {phase_id} — {phase_name}\n"
            f"  Overdue by: {overdue_days} day(s)\n"
            f"  Remaining checklist items: {incomplete_str}\n\n"
            f"Tone: friendly, not nagging. Remind them the checklist is there to help, "
            f"not pressure them. Use their first name. No emojis except one at the start."
        )
        resp = self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=150,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()
