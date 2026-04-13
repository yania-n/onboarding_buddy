"""
agents/orchestrator.py — Central Onboarding Orchestrator
=========================================================
The orchestrator is the nerve centre of OnboardingBuddy.
It receives all inputs from both apps, reads the joiner's profile and
current state, determines which phase the joiner is in, and dispatches
tasks to the appropriate sub-agents — all in parallel on Day 1.

Responsibilities:
  1. Activate when a new joiner record is created → trigger all core agents
  2. Advance phases when the joiner marks them complete
  3. Route incoming Q&A queries to the QA agent
  4. Hand off feedback collection to the Feedback agent
  5. Check phase overdue status and delegate nudges to the Progress Tracker

Design principle: the orchestrator decides WHAT to do and WHEN — the
individual agents decide HOW. The orchestrator never calls an LLM directly.
"""

import threading
from datetime import date, datetime
from typing import Optional

from core.models import JoinerProfile, JoinerState, PhaseStatus, AccessRequest, AccessStatus
from core.state_store import StateStore
from core.config import PHASE_BY_ID, PHASES
from agents.qa_agent import QAAgent
from agents.feedback_agent import FeedbackAgent
from agents.org_agent import OrgAgent
from agents.access_agent import AccessAgent
from agents.training_agent import TrainingAgent
from agents.buddy_agent import BuddyAgent
from agents.progress_tracker import ProgressTracker


class Orchestrator:
    """
    One orchestrator instance is shared across the entire app session.
    Thread-safe: each agent activation spawns its own thread.
    """

    def __init__(self, store: StateStore, kb):
        self.store = store
        self.kb = kb

        # Initialise all agents (they share the same store and KB)
        self.qa_agent = QAAgent(store=store, kb=kb)
        self.feedback_agent = FeedbackAgent(store=store)
        self.org_agent = OrgAgent(store=store, kb=kb)
        self.access_agent = AccessAgent(store=store)
        self.training_agent = TrainingAgent(store=store, kb=kb)
        self.buddy_agent = BuddyAgent(store=store)
        self.progress_tracker = ProgressTracker(store=store)

    # ─────────────────────────────────────────
    # New Joiner Activation (Day 1)
    # ─────────────────────────────────────────

    def activate_new_joiner(self, profile: JoinerProfile) -> JoinerState:
        """
        Called by the admin app when a manager submits a new joiner form.
        Steps:
          1. Persist the profile
          2. Create a fresh JoinerState
          3. Trigger all core agents in parallel (Steps 4a–4d from the spec)
          4. Post a welcome notification to the joiner app
        Returns the initialised JoinerState.
        """
        print(f"[Orchestrator] Activating new joiner: {profile.full_name}")

        # 1 + 2: Persist profile and create state
        self.store.create_profile(profile)
        state = self.store.create_state(profile.joiner_id, profile)

        # 3: Dispatch agents in parallel — nothing waits on anything else
        threads = [
            threading.Thread(
                target=self._run_agent,
                args=("org_agent", self.org_agent.build_org_brief, profile, state),
                daemon=True,
            ),
            threading.Thread(
                target=self._run_agent,
                args=("access_agent", self.access_agent.raise_access_tickets, profile, state),
                daemon=True,
            ),
            threading.Thread(
                target=self._run_agent,
                args=("training_agent", self.training_agent.build_course_plan, profile, state),
                daemon=True,
            ),
            threading.Thread(
                target=self._run_agent,
                args=("buddy_agent", self.buddy_agent.book_intro_call, profile, state),
                daemon=True,
            ),
        ]

        for t in threads:
            t.start()

        # 4: Welcome notification — use atomic append so we don't race with agent threads
        welcome = (
            f"👋 Welcome to Nexora, {profile.full_name}! "
            f"I'm OnboardingBuddy — your AI companion for the next 90 days. "
            f"Your Phase 1 checklist is ready. Your buddy {profile.buddy_name} "
            f"has been notified and will reach out to book your intro call. "
            f"Let's make these 90 days count! 🚀"
        )
        self.store.append_to_state(profile.joiner_id, notifications=[welcome])

        return self.store.get_state(profile.joiner_id) or state

    def _run_agent(self, name: str, fn, profile: JoinerProfile, state: JoinerState) -> None:
        """Thread wrapper — catches exceptions so one agent failure doesn't kill others."""
        try:
            fn(profile, state)
        except Exception as e:
            print(f"[Orchestrator] Agent '{name}' error: {e}")

    # ─────────────────────────────────────────
    # Phase Advancement
    # ─────────────────────────────────────────

    def advance_phase(self, joiner_id: str) -> tuple[bool, str]:
        """
        Attempt to advance the joiner to the next phase.
        Validates: checklist complete, and LMS gate if Phase 3.
        Returns (success, message).
        """
        state = self.store.get_state(joiner_id)
        profile = self.store.get_profile(joiner_id)
        if not state or not profile:
            return False, "Joiner record not found."

        current = state.current_phase
        phase_def = PHASE_BY_ID.get(current)
        if not phase_def:
            return False, "Invalid phase."

        # Check checklist completion
        if not state.phase_checklist_complete(current):
            incomplete = [
                c.label for c in state.get_checklist_for_phase(current)
                if not c.completed
            ]
            return False, (
                f"Please complete all checklist items before marking Phase {current} done. "
                f"Remaining: {', '.join(incomplete[:3])}"
                + (" and more." if len(incomplete) > 3 else ".")
            )

        # Phase 3 LMS gate
        if phase_def.system_gated and not state.lms_mandatory_confirmed:
            return False, (
                "Phase 3 requires confirmation from the LMS that all mandatory "
                "courses are complete. Please check your training dashboard — "
                "this unlocks automatically once the LMS reports completion."
            )

        # Mark current phase complete
        state.phase_statuses[current] = PhaseStatus.COMPLETE
        state.phase_complete_dates[current] = date.today()

        # Trigger feedback pulse
        threading.Thread(
            target=self._safe_feedback,
            args=(joiner_id, current),
            daemon=True,
        ).start()

        # Advance to next phase (if one exists)
        next_phase = current + 1
        if next_phase > 6:
            state.onboarding_complete = True
            state.app_notifications.insert(
                0,
                "🎉 Congratulations! You've completed your onboarding journey at Nexora. "
                "What an achievement — welcome fully aboard!",
            )
        else:
            state.current_phase = next_phase
            state.phase_statuses[next_phase] = PhaseStatus.ACTIVE
            state.phase_start_dates[next_phase] = date.today()
            next_def = PHASE_BY_ID[next_phase]
            state.app_notifications.insert(
                0,
                f"✅ Phase {current} — '{phase_def.name}' complete! "
                f"You've unlocked Phase {next_phase}: '{next_def.name}'. "
                f"Objective: {next_def.objective}",
            )

        self.store.save_state(state)
        return True, f"Phase {current} marked complete. " + (
            "Onboarding journey complete! 🎉" if next_phase > 6
            else f"Phase {next_phase} '{PHASE_BY_ID[next_phase].name}' is now active."
        )

    def _safe_feedback(self, joiner_id: str, phase_id: int) -> None:
        try:
            self.feedback_agent.prompt_phase_feedback(joiner_id, phase_id)
        except Exception as e:
            print(f"[Orchestrator] Feedback agent error: {e}")

    # ─────────────────────────────────────────
    # Q&A Routing
    # ─────────────────────────────────────────

    def answer_question(self, joiner_id: str, question: str) -> str:
        """Route a joiner question to the QA agent and return the answer."""
        return self.qa_agent.answer(joiner_id=joiner_id, question=question)

    # ─────────────────────────────────────────
    # Checklist Updates
    # ─────────────────────────────────────────

    def toggle_checklist_item(
        self, joiner_id: str, item_id: str, completed: bool
    ) -> bool:
        """Mark a checklist item complete or incomplete. Returns True on success."""
        state = self.store.get_state(joiner_id)
        if not state:
            return False
        for item in state.checklist_items:
            if item.item_id == item_id:
                item.completed = completed
                item.completed_at = datetime.utcnow() if completed else None
                self.store.save_state(state)
                return True
        return False

    # ─────────────────────────────────────────
    # LMS Gate Confirmation (Phase 3)
    # ─────────────────────────────────────────

    def confirm_lms_complete(self, joiner_id: str) -> None:
        """Called when the LMS reports mandatory courses are complete."""
        state = self.store.get_state(joiner_id)
        if not state:
            return
        state.lms_mandatory_confirmed = True
        if state.phase_statuses.get(3) == PhaseStatus.PENDING_LMS:
            state.phase_statuses[3] = PhaseStatus.ACTIVE
            state.app_notifications.insert(
                0,
                "✅ Great news! The LMS has confirmed your mandatory training is complete. "
                "You can now mark Phase 3 as done and move forward.",
            )
        self.store.save_state(state)

    # ─────────────────────────────────────────
    # Progress Check (called by scheduled job)
    # ─────────────────────────────────────────

    def run_progress_check(self) -> int:
        """Delegate to the progress tracker to send nudges where needed. Returns nudge count."""
        return self.progress_tracker.check_all_joiners()
