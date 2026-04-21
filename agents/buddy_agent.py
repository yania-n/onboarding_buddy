"""
agents/buddy_agent.py — Buddy Introduction Agent
=================================================
Generates a warm welcome message from the buddy and provides the joiner
with clear instructions on how to arrange their intro call.

PoC constraint: no calendar integration.
Instead of booking a calendar invite, this agent:
  1. Generates a personalised welcome note from the buddy (via Claude Haiku)
  2. Directs the joiner to contact the buddy directly using their email
     or calendar link (if provided by the manager at setup)

The joiner owns the action of reaching out — the agent makes it easy
by surfacing all contact details prominently.

Model routing:
  - Welcome note: Claude Haiku (warm, personalised, short)
  - KB retrieval: used to provide onboarding buddy programme context
"""

import asyncio

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import ANTHROPIC_API_KEY, MODEL_FAST
from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_BUDDY_SYSTEM = """You are OnboardingBuddy writing a short, warm welcome note
on behalf of the assigned buddy to a new joiner.

The note should:
- Be warm and personal (written as if FROM the buddy)
- Be 80–120 words maximum
- Reference the joiner's role briefly so it feels personalised
- Tell the joiner exactly how to reach out to arrange their intro call
  (do NOT reference calendar booking — just email or the calendar link if provided)
- End with genuine enthusiasm

Sign off as: "[Buddy Name], your OnboardingBuddy 👋"

Do NOT invent information. If no calendar link is provided, just give the email."""


class BuddyAgent:
    """
    Generates the buddy introduction message for a new joiner.
    Called at activation alongside other agents (parallel).
    Directs joiner to contact buddy directly — no calendar booking.
    """

    def __init__(self, store: StateStore):
        self.store   = store
        self._client = (
            anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def send_buddy_intro(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Generate and store the buddy welcome message.

        1. Generate a personalised welcome note with Claude Haiku
        2. Include clear contact instructions (email / calendar link)
        3. Store as an in-app notification in the joiner's state
        """
        print(f"[BuddyAgent] Creating buddy intro for {profile.full_name} → {profile.buddy_name}")

        if self._client:
            note = await self._generate_note(profile)
        else:
            note = self._template_note(profile)

        self.store.append_to_state(
            joiner_id     = profile.joiner_id,
            notifications = [note],
        )
        print(f"[BuddyAgent] Buddy intro stored for {profile.full_name}")

    # ── Private helpers ───────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _generate_note(self, profile: JoinerProfile) -> str:
        """Generate personalised welcome note from buddy using Claude Haiku (async)."""
        calendar_line = (
            f"You can also grab time directly via my calendar: {profile.buddy_calendar_link}"
            if profile.buddy_calendar_link
            else f"Drop me an email and we'll find a time that works for you."
        )
        user_msg = (
            f"New joiner: {profile.full_name}\n"
            f"Role: {profile.job_title} in {profile.department}\n"
            f"Buddy name: {profile.buddy_name}\n"
            f"Buddy email: {profile.buddy_email}\n"
            f"How to arrange intro: {calendar_line}"
        )
        resp = await self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=200,
            system=_BUDDY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return f"👋 **Message from your Buddy**\n\n{resp.content[0].text.strip()}"

    def _template_note(self, profile: JoinerProfile) -> str:
        """Structured fallback when LLM is unavailable."""
        contact_line = (
            f"📅 Book intro call: {profile.buddy_calendar_link}"
            if profile.buddy_calendar_link
            else f"✉️ Email me: {profile.buddy_email}"
        )
        return (
            f"👋 **Message from your Buddy, {profile.buddy_name}**\n\n"
            f"Hi {profile.full_name}! Welcome to {profile.department} — "
            f"so excited to have you on board as our new {profile.job_title}. "
            f"I'm here to help you settle in and answer any questions.\n\n"
            f"**Let's connect!** Reach out directly and we'll arrange our intro call:\n"
            f"✉️ Email: {profile.buddy_email}\n"
            f"{contact_line if profile.buddy_calendar_link else ''}\n\n"
            f"Looking forward to meeting you! — {profile.buddy_name} 👋"
        )
