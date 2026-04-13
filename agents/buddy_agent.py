"""
agents/buddy_agent.py — Buddy Matcher & Intro Booking Agent
============================================================
Sends an intro message to the assigned buddy and books the Day 1-2 call.
As onboarding progresses, recommends additional peer connections aligned
to the current phase objectives.

Production mode: integrates with Google Calendar / Outlook API.
Current mode: simulated — posts confirmation notifications to the joiner app.

Model: Claude Haiku (generates the intro message text).
"""

import anthropic
from datetime import datetime

from core.config import ANTHROPIC_API_KEY, MODEL_FAST
from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore


_INTRO_SYSTEM_PROMPT = """You are OnboardingBuddy. Write a short, warm intro message
from the OnboardingBuddy system to a new joiner's assigned buddy.
The message should:
- Be 3-4 sentences max
- Mention the new joiner's name, role, and start date
- Ask the buddy to reach out and book an intro call in the first 2 days
- Be friendly and professional
Do not use placeholders — use the actual values provided.
"""


class BuddyAgent:
    """Books buddy intro calls and recommends peer connections."""

    def __init__(self, store: StateStore):
        self.store = store
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    def book_intro_call(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Generate an intro message for the buddy and confirm the booking
        in the joiner's notification feed.
        In production: send via email/Slack and create calendar invite.
        """
        intro_msg = self._generate_intro_message(profile)
        notification = (
            f"👋 Buddy Intro Arranged!\n\n"
            f"Your onboarding buddy is **{profile.buddy_name}**.\n\n"
            f"A message has been sent to {profile.buddy_name} to reach out and book "
            f"your intro call within your first 2 days.\n\n"
            f"📅 Buddy calendar link: {profile.buddy_calendar_link or 'Your buddy will share their calendar link directly.'}\n\n"
            f"_Message sent to your buddy:_\n\"{intro_msg}\""
        )
        # Use atomic append to avoid race with other Day-1 agents
        self.store.append_to_state(profile.joiner_id, notifications=[notification])

    def recommend_connections(self, joiner_id: str, phase_id: int) -> list[dict]:
        """
        Return a list of recommended people to meet for the current phase.
        In production: reads org chart + KB stakeholder maps.
        Current mode: returns phase-contextual generic recommendations.
        """
        phase_recommendations = {
            1: [
                {"name": "Your manager", "reason": "First 1:1 — set expectations and priorities"},
                {"name": "Your buddy", "reason": "Day 1-2 intro call — your guide to all things Nexora"},
                {"name": "Your direct teammates", "reason": "Get to know your immediate team"},
            ],
            2: [
                {"name": "Department head", "reason": "Understand the department mission"},
                {"name": "Cross-team stakeholders", "reason": "Map how your role connects to others"},
                {"name": "HR Business Partner", "reason": "Benefits, policies, and support resources"},
            ],
            3: [
                {"name": "L&D coordinator", "reason": "Help navigate the LMS and training resources"},
                {"name": "Tool power users in your team", "reason": "Tips and shortcuts for the tools you use"},
            ],
            4: [
                {"name": "Key project stakeholders", "reason": "Understand current priorities firsthand"},
                {"name": "IT support", "reason": "Resolve any lingering access or tool issues"},
            ],
            5: [
                {"name": "Manager", "reason": "60-day check-in — progress and feedback"},
                {"name": "Skip-level manager", "reason": "Broader context on team direction"},
            ],
            6: [
                {"name": "Manager", "reason": "90-day review and goal-setting session"},
                {"name": "Buddy", "reason": "Wrap-up conversation — reflect on the journey"},
            ],
        }
        return phase_recommendations.get(phase_id, [])

    def _generate_intro_message(self, profile: JoinerProfile) -> str:
        if self._client is None:
            return (
                f"Hi {profile.buddy_name}! {profile.full_name} is joining Nexora as "
                f"{profile.job_title} on {profile.start_date.strftime('%d %B %Y')}. "
                f"As their onboarding buddy, could you reach out and book an intro call "
                f"within their first two days? They're looking forward to meeting you!"
            )
        try:
            prompt = (
                f"New joiner: {profile.full_name}\n"
                f"Role: {profile.job_title}\n"
                f"Start date: {profile.start_date.strftime('%d %B %Y')}\n"
                f"Buddy name: {profile.buddy_name}\n"
                f"Department: {profile.department}\n"
            )
            response = self._client.messages.create(
                model=MODEL_FAST,
                max_tokens=200,
                system=_INTRO_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[BuddyAgent] LLM error: {e}")
            return (
                f"Hi {profile.buddy_name}! {profile.full_name} joins us as "
                f"{profile.job_title} on {profile.start_date.strftime('%d %B %Y')}. "
                f"Please reach out to book your intro call in the first 2 days — they're excited to meet you!"
            )
