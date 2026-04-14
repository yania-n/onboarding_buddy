"""
agents/feedback_agent.py — Feedback & Sentiment Agent
======================================================
Collects lightweight pulse surveys at two key moments:
  - 50% onboarding completion (after Phase 3 completion)
  - 100% onboarding completion (Phase 6 finish line)

Responsibilities:
  1. Prompt the joiner with 2–3 tailored questions at the right moment
  2. Store the answers in the joiner's state record
  3. Analyse sentiment using Claude Sonnet (quality matters here)
  4. Flag concerning sentiment to the admin (in-app, no external push)

Design: feedback is triggered by the orchestrator after phase completion.
The UI collects the answers and calls store_feedback(); this agent
then does the sentiment analysis and any follow-up actions.

Model routing:
  - Sentiment analysis: Claude Sonnet (nuanced, important signal)
  - Feedback prompts: static from config (no LLM needed)
"""

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from datetime import datetime

from core.config import ANTHROPIC_API_KEY, MODEL_SMART, PHASE_BY_ID, SENTIMENT_ESCALATION_THRESHOLD
from core.models import JoinerState, FeedbackResponse, SentimentLevel
from core.state_store import StateStore


# ─────────────────────────────────────────────
# System prompt for sentiment analysis
# ─────────────────────────────────────────────

_SENTIMENT_SYSTEM = """You are OnboardingBuddy's Feedback & Sentiment agent.
Analyse the new joiner's phase-end survey answers and produce a sentiment assessment.

You must return ONLY a JSON object with exactly these fields (no markdown, no extra text):
{
  "sentiment": "positive" | "neutral" | "concerning",
  "score": <float 1.0–5.0>,
  "summary": "<one sentence summary of the feedback>",
  "flag_manager": <true | false>
}

Scoring guide:
  5.0 = Extremely positive, joiner is thriving
  4.0 = Positive with minor concerns
  3.0 = Mixed — neutral overall
  2.0 = Some real concerns worth noting
  1.0 = Concerning — joiner struggling or disengaged

Set flag_manager = true if score < 3.0 or if any answer suggests the joiner
is blocked, excluded, overwhelmed, or considering leaving."""


class FeedbackAgent:
    """
    Collects and analyses joiner pulse survey responses.
    Called by the orchestrator after each phase completion.
    """

    def __init__(self, store: StateStore):
        self.store   = store
        self._client = (
            anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def get_feedback_questions(self, phase_id: int) -> list[str]:
        """
        Return the feedback questions for a given phase.
        Used by the joiner UI to render the feedback form.
        """
        phase_def = PHASE_BY_ID.get(phase_id)
        if phase_def:
            return phase_def.feedback_questions
        return ["How is your onboarding going so far?"]

    def store_feedback(
        self,
        joiner_id: str,
        phase_id:  int,
        answers:   dict[str, str],
    ) -> str:
        """
        Store the feedback answers and run sentiment analysis.

        Called by the joiner UI after the user submits the feedback form.
        Returns a thank-you message to display in the UI.
        """
        print(f"[FeedbackAgent] Storing feedback for {joiner_id}, phase {phase_id}")

        # Build FeedbackResponse with placeholder sentiment
        feedback = FeedbackResponse(
            phase_id     = phase_id,
            submitted_at = datetime.utcnow(),
            answers      = answers,
        )

        # Run sentiment analysis
        if self._client and answers:
            sentiment, score, summary, flag = self._analyse_sentiment(phase_id, answers)
        else:
            sentiment, score, summary, flag = SentimentLevel.NEUTRAL, 3.0, "", False

        feedback.sentiment       = sentiment
        feedback.sentiment_score = score

        # Persist to state store
        state = self.store.get_state(joiner_id)
        if state:
            state.feedback_responses.append(feedback)

            # If manager flag is triggered, add an admin-visible notification
            if flag:
                state.app_notifications.insert(
                    0,
                    f"⚠️ **Manager Attention Needed** — Phase {phase_id} feedback for "
                    f"this joiner indicates concerns (score {score:.1f}/5). "
                    f"Summary: {summary} Please check in with them directly."
                )
            self.store.save_state(state)
            print(f"[FeedbackAgent] Feedback stored — sentiment: {sentiment.value}, score: {score}")

        # Return thank-you message
        if sentiment == SentimentLevel.CONCERNING:
            return (
                "Thank you for your honest feedback 🙏 — it's really valuable. "
                "Your manager will be in touch to support you. "
                "In the meantime, don't hesitate to use Ask Me Anything or reach out directly."
            )
        elif sentiment == SentimentLevel.POSITIVE:
            return (
                "That's wonderful to hear! 🎉 Thank you for the feedback — "
                "keep up the great momentum!"
            )
        else:
            return (
                "Thank you for your feedback! 🙏 We'll use this to keep improving "
                "the onboarding experience. Keep going — you're doing great!"
            )

    def prompt_phase_feedback(self, joiner_id: str, phase_id: int) -> None:
        """
        Triggered by the orchestrator after a phase is marked complete.
        Adds an in-app prompt nudging the joiner to complete their feedback form.
        Only fires at 50% (phase 3) and 100% (phase 6) per the spec.
        """
        # Per spec: feedback fires at 50% (≈ Phase 3) and 100% (Phase 6)
        if phase_id not in (3, 6):
            return

        phase_def = PHASE_BY_ID.get(phase_id)
        phase_name = phase_def.name if phase_def else f"Phase {phase_id}"

        prompt = (
            f"📝 **Phase {phase_id} — {phase_name} Complete!**\n\n"
            f"You've reached a milestone — please take 2 minutes to share your feedback. "
            f"Your answers help us improve the onboarding experience for everyone.\n\n"
            f"Head to the **Feedback** tab to answer {len(self.get_feedback_questions(phase_id))} quick questions."
        )
        self.store.append_to_state(
            joiner_id=joiner_id,
            notifications=[prompt],
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _analyse_sentiment(
        self,
        phase_id: int,
        answers: dict[str, str],
    ) -> tuple[SentimentLevel, float, str, bool]:
        """
        Analyse feedback answers with Claude Sonnet.
        Returns (sentiment, score, summary, flag_manager).
        """
        import json

        answers_text = "\n".join(
            f"Q: {q}\nA: {a}" for q, a in answers.items()
        )
        user_msg = (
            f"Phase {phase_id} feedback answers:\n\n{answers_text}"
        )

        resp = self._client.messages.create(
            model=MODEL_SMART,
            max_tokens=200,
            system=_SENTIMENT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        try:
            raw = resp.content[0].text.strip()
            # Strip any accidental markdown code fences
            raw = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)

            sentiment_map = {
                "positive":   SentimentLevel.POSITIVE,
                "neutral":    SentimentLevel.NEUTRAL,
                "concerning": SentimentLevel.CONCERNING,
            }
            sentiment = sentiment_map.get(data.get("sentiment", "neutral"), SentimentLevel.NEUTRAL)
            score     = float(data.get("score", 3.0))
            summary   = str(data.get("summary", ""))
            flag      = bool(data.get("flag_manager", False))
            return sentiment, score, summary, flag

        except Exception as e:
            print(f"[FeedbackAgent] Sentiment parse error: {e}")
            return SentimentLevel.NEUTRAL, 3.0, "", False
