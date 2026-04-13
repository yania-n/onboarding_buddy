"""
agents/progress_tracker.py — Progress Tracker Agent
====================================================
Monitors all active joiners' state stores and:
  1. Sends a friendly nudge if a phase is overdue by 3+ days
  2. Pushes weekly summaries to managers (simulated via print / Slack)
  3. Escalates to manager if sentiment drops below threshold

Runs on a schedule (every 6 hours in production via APScheduler).
Also callable manually from the orchestrator.

Model: Claude Haiku (nudge message generation — short, warm, contextual).
"""

import uuid
from datetime import date, datetime, timedelta

import anthropic

from core.config import (
    ANTHROPIC_API_KEY, MODEL_FAST,
    PHASE_BY_ID, SENTIMENT_ESCALATION_THRESHOLD,
)
from core.models import JoinerState, PhaseStatus, NudgeRecord, SentimentLevel
from core.state_store import StateStore


_NUDGE_SYSTEM_PROMPT = """You are OnboardingBuddy writing a friendly, encouraging nudge
to a new joiner who hasn't yet completed their current onboarding phase checklist.
The nudge should be:
- 2-3 sentences maximum
- Warm and supportive — never critical or pushy
- Mention the specific phase by name
- Suggest one concrete next step from the checklist
- End with encouragement
Do not use placeholders.
"""


class ProgressTracker:
    """Monitors joiner progress and sends timely nudges."""

    def __init__(self, store: StateStore):
        self.store = store
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    def check_all_joiners(self) -> int:
        """
        Check every active joiner for overdue phases.
        Returns the number of nudges sent.
        """
        states = self.store.list_states()
        nudge_count = 0
        for state in states:
            if not state.onboarding_complete:
                if self._check_and_nudge(state):
                    nudge_count += 1
        return nudge_count

    def _check_and_nudge(self, state: JoinerState) -> bool:
        """Send a nudge if the current phase is overdue. Returns True if nudge was sent."""
        current_phase_id = state.current_phase
        phase_def = PHASE_BY_ID.get(current_phase_id)
        if not phase_def:
            return False

        status = state.phase_statuses.get(current_phase_id)
        if status != PhaseStatus.ACTIVE:
            return False

        # Calculate days since phase started
        phase_start = state.phase_start_dates.get(current_phase_id)
        if not phase_start:
            return False

        # phase_start may be a string (from JSON) or a date object
        if isinstance(phase_start, str):
            phase_start = date.fromisoformat(phase_start)

        days_in_phase = (date.today() - phase_start).days
        nudge_threshold = phase_def.nudge_after_days + (
            phase_def.day_end - phase_def.day_start
        )

        if days_in_phase < nudge_threshold:
            return False

        # Check if we already nudged recently (avoid spam — 1 per 48h)
        recent_nudges = [
            n for n in state.nudge_log
            if n.phase_id == current_phase_id
            and (datetime.utcnow() - n.sent_at).total_seconds() < 48 * 3600
        ]
        if recent_nudges:
            return False

        # Find first incomplete checklist item for the current phase
        incomplete = [
            c for c in state.get_checklist_for_phase(current_phase_id)
            if not c.completed
        ]
        next_step = incomplete[0].label if incomplete else "reviewing your checklist"

        # Generate nudge message
        msg = self._generate_nudge(
            phase_name=phase_def.name,
            days_overdue=days_in_phase - nudge_threshold,
            next_step=next_step,
        )

        # Post to app
        profile = self.store.get_profile(state.joiner_id)
        name = profile.full_name.split()[0] if profile else "there"
        full_msg = f"⏰ Gentle reminder, {name}!\n\n{msg}"
        state.app_notifications.insert(0, full_msg)

        # Log the nudge
        nudge = NudgeRecord(
            nudge_id=str(uuid.uuid4()),
            joiner_id=state.joiner_id,
            channel="app",
            recipient="joiner",
            phase_id=current_phase_id,
            message=full_msg,
        )
        state.nudge_log.append(nudge)
        self.store.save_state(state)
        return True

    def _generate_nudge(self, phase_name: str, days_overdue: int, next_step: str) -> str:
        if self._client is None:
            return (
                f"You're still working through Phase '{phase_name}'. "
                f"A good next step would be: {next_step}. "
                f"You've got this — take it one item at a time! 💪"
            )
        try:
            prompt = (
                f"Phase: {phase_name}\n"
                f"Days overdue: {days_overdue}\n"
                f"Suggested next step from checklist: {next_step}\n"
            )
            response = self._client.messages.create(
                model=MODEL_FAST,
                max_tokens=120,
                system=_NUDGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[ProgressTracker] Nudge LLM error: {e}")
            return (
                f"Don't forget about Phase '{phase_name}'! "
                f"Try tackling: {next_step}. You're doing great — keep going! 🌟"
            )

    def build_manager_summary(self, manager_email: str) -> str:
        """
        Build a weekly progress summary for a manager covering all their joiners.
        In production: send via Slack or email. Currently: returns formatted string.
        """
        profiles = self.store.list_profiles()
        managed = [p for p in profiles if p.manager_email == manager_email]

        if not managed:
            return "No active joiners found for this manager."

        lines = [f"📊 Weekly Onboarding Summary — {date.today().strftime('%d %b %Y')}\n"]
        for profile in managed:
            state = self.store.get_state(profile.joiner_id)
            if not state:
                continue
            phase_def = PHASE_BY_ID.get(state.current_phase)
            phase_name = phase_def.name if phase_def else "Unknown"

            # Sentiment signal
            recent_feedback = [
                f for f in state.feedback_responses
                if f.sentiment == SentimentLevel.CONCERNING
            ]
            sentiment_flag = " ⚠️ Sentiment alert" if recent_feedback else ""

            items_done = sum(1 for c in state.checklist_items if c.completed)
            items_total = len(state.checklist_items)

            lines.append(
                f"• {profile.full_name} ({profile.job_title})\n"
                f"  Phase: {state.current_phase} — {phase_name}{sentiment_flag}\n"
                f"  Checklist: {items_done}/{items_total} items complete\n"
            )

        return "\n".join(lines)
