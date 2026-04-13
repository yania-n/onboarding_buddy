"""
agents/feedback_agent.py — Feedback & Sentiment Agent
======================================================
Fires a lightweight 2-3 question pulse survey when a joiner marks
a phase complete. Analyses sentiment and escalates to the manager
if scores fall below threshold.

Model routing:
  - Sentiment analysis: Claude Haiku (simple classification)
  - Manager escalation messages: Claude Sonnet (higher stakes communication)
"""

import uuid
import anthropic
from datetime import datetime

from core.config import (
    ANTHROPIC_API_KEY, MODEL_FAST, MODEL_SMART,
    PHASE_BY_ID, SENTIMENT_ESCALATION_THRESHOLD,
)
from core.models import FeedbackResponse, SentimentLevel
from core.state_store import StateStore


_SENTIMENT_SYSTEM_PROMPT = """You are an HR sentiment analyst.
Given a set of pulse survey answers from a new employee at the end of an onboarding phase,
respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{"sentiment": "positive|neutral|concerning", "score": 4.2, "summary": "one sentence summary"}
Score is 1-5 where 5 is very positive. Be accurate — do not round up.
If answers suggest confusion, frustration, or feeling unsupported, score low.
"""

_ESCALATION_SYSTEM_PROMPT = """You are OnboardingBuddy writing a sensitive message to a manager.
A new joiner has completed a phase but their feedback suggests they may be struggling.
Write a brief, professional, empathetic message to the manager (3-4 sentences) that:
- Flags that the joiner's feedback warrants a check-in
- Does NOT quote the joiner's exact words
- Suggests the manager proactively reaches out
- Keeps the joiner's confidence (no judgement)
Tone: warm, professional, not alarmist.
"""


class FeedbackAgent:
    """Collects phase-end feedback and analyses sentiment."""

    def __init__(self, store: StateStore):
        self.store = store
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    def prompt_phase_feedback(self, joiner_id: str, phase_id: int) -> None:
        """
        Post a feedback prompt notification to the joiner app.
        The actual answers are collected via the UI and passed to record_feedback().
        """
        phase_def = PHASE_BY_ID.get(phase_id)
        if not phase_def:
            return

        state = self.store.get_state(joiner_id)
        if not state:
            return

        questions_text = "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(phase_def.feedback_questions)
        )
        notification = (
            f"📝 Phase {phase_id} Feedback — {phase_def.name}\n\n"
            f"Brilliant work completing Phase {phase_id}! Take 2 minutes to "
            f"share how it felt — your feedback helps us improve onboarding for everyone.\n\n"
            f"{questions_text}\n\n"
            f"_Use the Feedback tab to submit your answers._"
        )
        state.app_notifications.insert(0, notification)
        self.store.save_state(state)

    def record_feedback(
        self, joiner_id: str, phase_id: int, answers: dict[str, str]
    ) -> FeedbackResponse:
        """
        Store feedback answers, analyse sentiment, and escalate if needed.
        Returns the saved FeedbackResponse.
        """
        state = self.store.get_state(joiner_id)
        profile = self.store.get_profile(joiner_id)
        if not state:
            raise ValueError(f"No state found for joiner {joiner_id}")

        # Analyse sentiment
        sentiment, score, summary = self._analyse_sentiment(phase_id, answers)

        response = FeedbackResponse(
            phase_id=phase_id,
            answers=answers,
            sentiment=sentiment,
            sentiment_score=score,
        )

        state.feedback_responses.append(response)
        state.app_notifications.insert(
            0,
            f"✅ Thanks for your Phase {phase_id} feedback! "
            f"Your insights help make Nexora's onboarding better for everyone. 🙏"
        )
        self.store.save_state(state)

        # Escalate if sentiment is concerning
        if sentiment == SentimentLevel.CONCERNING and profile:
            self._escalate_to_manager(profile, phase_id, summary)

        return response

    def get_feedback_summary(self, joiner_id: str) -> list[dict]:
        """Return all feedback responses for the admin dashboard."""
        state = self.store.get_state(joiner_id)
        if not state:
            return []
        return [
            {
                "phase_id": r.phase_id,
                "phase_name": PHASE_BY_ID[r.phase_id].name if r.phase_id in PHASE_BY_ID else str(r.phase_id),
                "sentiment": r.sentiment.value if r.sentiment else "unknown",
                "score": r.sentiment_score,
                "submitted_at": r.submitted_at.strftime("%Y-%m-%d %H:%M") if r.submitted_at else "",
                "answers": r.answers,
            }
            for r in state.feedback_responses
        ]

    # ── Private helpers ───────────────────────

    def _analyse_sentiment(
        self, phase_id: int, answers: dict[str, str]
    ) -> tuple[SentimentLevel, float, str]:
        """Run Haiku sentiment classification. Returns (level, score, summary)."""
        if self._client is None:
            return SentimentLevel.NEUTRAL, 3.0, "Sentiment analysis unavailable."

        answers_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items())
        try:
            response = self._client.messages.create(
                model=MODEL_FAST,
                max_tokens=150,
                system=_SENTIMENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Phase {phase_id} feedback:\n{answers_text}"}],
            )
            import json
            raw = response.content[0].text.strip()
            parsed = json.loads(raw)
            sentiment_str = parsed.get("sentiment", "neutral")
            sentiment = SentimentLevel(sentiment_str) if sentiment_str in SentimentLevel._value2member_map_ else SentimentLevel.NEUTRAL
            score = float(parsed.get("score", 3.0))
            summary = parsed.get("summary", "")
            return sentiment, score, summary
        except Exception as e:
            print(f"[FeedbackAgent] Sentiment error: {e}")
            return SentimentLevel.NEUTRAL, 3.0, "Could not analyse sentiment."

    def _escalate_to_manager(self, profile, phase_id: int, summary: str) -> None:
        """Generate and simulate sending an escalation message to the manager."""
        if self._client is None:
            print(f"[FeedbackAgent] Escalation needed for {profile.full_name} after Phase {phase_id}")
            return

        phase_name = PHASE_BY_ID[phase_id].name if phase_id in PHASE_BY_ID else str(phase_id)
        try:
            prompt = (
                f"Joiner: {profile.full_name} ({profile.job_title})\n"
                f"Phase just completed: Phase {phase_id} — {phase_name}\n"
                f"Sentiment summary: {summary}\n"
                f"Manager: {profile.manager_name}\n"
            )
            response = self._client.messages.create(
                model=MODEL_SMART,
                max_tokens=200,
                system=_ESCALATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            msg = response.content[0].text.strip()
            # In production: send via Slack/email to manager
            print(
                f"[FeedbackAgent] ESCALATION → {profile.manager_name} "
                f"re {profile.full_name} Phase {phase_id}:\n{msg}"
            )
        except Exception as e:
            print(f"[FeedbackAgent] Escalation LLM error: {e}")
