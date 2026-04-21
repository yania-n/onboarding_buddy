"""
agents/orchestrator.py — Central Onboarding Orchestrator
=========================================================
The nerve centre of OnboardingBuddy. Receives all inputs from both
apps, reads the joiner's profile and current state, determines which
phase the joiner is in, and dispatches tasks to the right sub-agents.

Architecture (6-layer system design):
  Layer 1: Apps        → admin_app.py, joiner_app.py
  Layer 2: Orchestrator → THIS FILE
  Layer 3: Core agents  → org_agent, access_agent, training_agent, qa_agent
  Layer 4: Added agents → progress_tracker, feedback_agent, integration_agent
  Layer 5: Infrastructure → KnowledgeBase, StateStore
  Layer 6: Integrations → PoC: simulated; production: LMS, IT, Calendar

Design principle: orchestrator decides WHAT and WHEN — agents decide HOW.
All Day 1 agents run in parallel threads (Steps 4a–4c execute simultaneously).
"""

import asyncio
import threading
from datetime import date, datetime
from typing import Optional

from core.models import JoinerProfile, JoinerState, PhaseStatus, AccessRequest, AccessStatus
from core.state_store import StateStore
from core.config import PHASE_BY_ID, PHASES
from core.knowledge_base import KnowledgeBase

from agents.qa_agent import QAAgent
from agents.feedback_agent import FeedbackAgent
from agents.org_agent import OrgAgent
from agents.access_agent import AccessAgent
from agents.training_agent import TrainingAgent
from agents.buddy_agent import BuddyAgent
from agents.integration_agent import IntegrationAgent
from agents.progress_tracker import ProgressTracker


class Orchestrator:
    """
    Singleton-style orchestrator shared across the entire app session.

    Thread safety: each Day 1 agent runs in its own daemon thread.
    The StateStore uses a threading.Lock internally for safe concurrent writes.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store = store
        self.kb    = kb

        # ── Core agents (Layer 3) ──────────────────────────────────────────
        self.qa_agent       = QAAgent(store=store, kb=kb)
        self.org_agent      = OrgAgent(store=store, kb=kb)
        self.access_agent   = AccessAgent(store=store, kb=kb)
        self.training_agent = TrainingAgent(store=store, kb=kb)

        # ── Added agents (Layer 4) ─────────────────────────────────────────
        self.buddy_agent       = BuddyAgent(store=store)
        self.integration_agent = IntegrationAgent(store=store)
        self.feedback_agent    = FeedbackAgent(store=store)
        self.progress_tracker  = ProgressTracker(store=store)

    # ─────────────────────────────────────────────
    # New Joiner Activation — Day 1
    # ─────────────────────────────────────────────

    async def activate_new_joiner(self, profile: JoinerProfile) -> JoinerState:
        """
        Called by the admin app when a manager submits the new joiner form.

        Data flow (per spec):
          Step 1: Persist profile to state store
          Step 2: Create fresh JoinerState (Phase 1 active)
          Step 3: Orchestrator activates
          Steps 4a–4e: All agents fire as async tasks (non-blocking, run concurrently)
            4a → org_agent.build_org_brief()
            4b → access_agent.raise_access_tickets()
            4c → training_agent.build_course_plan()
            4d → buddy_agent.send_buddy_intro()
            4e → integration_agent.run_activation_integrations()
          Step 5: Welcome notification → joiner app is live

        Returns the initialised JoinerState immediately — agents continue in background.
        """
        print(f"[Orchestrator] Activating new joiner: {profile.full_name}")

        # Steps 1 & 2: Persist and initialise state (sync — fast in-memory + JSON)
        self.store.create_profile(profile)
        state = self.store.create_state(profile.joiner_id, profile)

        # Steps 4a–4e: Fire all agents as concurrent async tasks (fire-and-forget).
        # create_task schedules them on the current event loop and returns immediately,
        # so the admin form responds instantly while agents run in the background.
        agent_tasks = [
            ("org_agent",         self.org_agent.build_org_brief),
            ("access_agent",      self.access_agent.raise_access_tickets),
            ("training_agent",    self.training_agent.build_course_plan),
            ("buddy_agent",       self.buddy_agent.send_buddy_intro),
            ("integration_agent", self.integration_agent.run_activation_integrations),
        ]

        for name, fn in agent_tasks:
            asyncio.create_task(
                self._run_agent_safe(name, fn, profile, state),
                name=f"onboarding-{name}-{profile.joiner_id[:8]}",
            )

        # Step 5: Welcome notification written synchronously before returning.
        # Agents will append their own notifications asynchronously afterward.
        welcome = (
            f"👋 **Welcome to the team, {profile.full_name}!**\n\n"
            f"I'm OnboardingBuddy — your AI companion for the next 90 days at "
            f"{profile.business_unit}.\n\n"
            f"Your **Phase 1: Welcome** checklist is ready. I'm preparing your "
            f"org brief, training plan, and access requests right now — they'll "
            f"appear in your notifications shortly.\n\n"
            f"Your buddy is **{profile.buddy_name}** ({profile.buddy_email}). "
            f"Reach out to arrange your intro call — it's one of the most valuable "
            f"things you can do in your first week!\n\n"
            f"Let's make these 90 days count! 🚀"
        )
        self.store.append_to_state(profile.joiner_id, notifications=[welcome])

        return self.store.get_state(profile.joiner_id) or state

    async def _run_agent_safe(
        self,
        name: str,
        fn,
        profile: JoinerProfile,
        state: JoinerState,
    ) -> None:
        """
        Async wrapper for agent coroutine calls.
        Catches all exceptions so one agent failure doesn't cancel the others.
        """
        try:
            await fn(profile, state)
        except Exception as e:
            print(f"[Orchestrator] Agent '{name}' raised an error: {e}")

    # ─────────────────────────────────────────────
    # Phase Advancement
    # ─────────────────────────────────────────────

    async def advance_phase(self, joiner_id: str) -> tuple[bool, str]:
        """
        Attempt to advance the joiner to the next phase.

        Validation:
          - All checklist items in current phase must be ticked
          - Phase 3 requires LMS gate (admin confirms mandatory courses done)

        Returns (success: bool, message: str).
        """
        state   = self.store.get_state(joiner_id)
        profile = self.store.get_profile(joiner_id)
        if not state or not profile:
            return False, "Joiner record not found."

        current   = state.current_phase
        phase_def = PHASE_BY_ID.get(current)
        if not phase_def:
            return False, "Invalid phase."

        # Guard: all checklist items must be complete
        if not state.phase_checklist_complete(current):
            incomplete = [
                c.label for c in state.get_checklist_for_phase(current)
                if not c.completed
            ]
            items_str = ", ".join(incomplete[:3])
            suffix = " and more" if len(incomplete) > 3 else ""
            return False, (
                f"Please complete all checklist items before marking Phase {current} done. "
                f"Remaining: {items_str}{suffix}."
            )

        # Guard: Phase 3 LMS gate
        if phase_def.system_gated and not state.lms_mandatory_confirmed:
            return False, (
                "Phase 3 requires LMS confirmation that all mandatory courses are complete. "
                "This unlocks automatically once your admin confirms your LMS completion — "
                "check with your manager if this hasn't happened yet."
            )

        # Mark current phase complete
        state.phase_statuses[current]      = PhaseStatus.COMPLETE
        state.phase_complete_dates[current] = date.today()

        # Trigger feedback pulse as a background async task (only at 50% and 100% per spec)
        asyncio.create_task(
            self._run_feedback_pulse(joiner_id, current),
            name=f"feedback-pulse-phase{current}-{joiner_id[:8]}",
        )

        # Advance to next phase (or mark onboarding complete at Phase 6)
        next_phase = current + 1
        if next_phase > 6:
            state.onboarding_complete = True
            state.app_notifications.insert(
                0,
                "🎉 **Congratulations — Onboarding Complete!**\n\n"
                "You've completed all 6 phases of your onboarding journey at "
                f"{profile.business_unit}. What an achievement — welcome fully aboard! "
                "Your final feedback form is in the **Feedback** tab.",
            )
            msg = "Onboarding journey complete! 🎉"
        else:
            state.current_phase               = next_phase
            state.phase_statuses[next_phase]  = PhaseStatus.ACTIVE
            state.phase_start_dates[next_phase] = date.today()
            next_def = PHASE_BY_ID[next_phase]
            state.app_notifications.insert(
                0,
                f"✅ **Phase {current} — '{phase_def.name}' Complete!**\n\n"
                f"You've unlocked **Phase {next_phase}: {next_def.name}**.\n"
                f"Objective: {next_def.objective}",
            )
            msg = f"Phase {next_phase} '{next_def.name}' is now active."

        self.store.save_state(state)
        return True, f"Phase {current} marked complete. {msg}"

    async def _run_feedback_pulse(self, joiner_id: str, phase_id: int) -> None:
        """Safely trigger the feedback prompt in a background async task."""
        try:
            self.feedback_agent.prompt_phase_feedback(joiner_id, phase_id)
        except Exception as e:
            print(f"[Orchestrator] Feedback pulse error: {e}")

    # ─────────────────────────────────────────────
    # Checklist Management
    # ─────────────────────────────────────────────

    def toggle_checklist_item(
        self, joiner_id: str, item_id: str, completed: bool
    ) -> bool:
        """
        Mark a single checklist item as complete or incomplete.
        Returns True if the item was found and updated.
        """
        state = self.store.get_state(joiner_id)
        if not state:
            return False

        for item in state.checklist_items:
            if item.item_id == item_id:
                item.completed    = completed
                item.completed_at = datetime.utcnow() if completed else None
                self.store.save_state(state)
                return True
        return False

    # ─────────────────────────────────────────────
    # Q&A Routing
    # ─────────────────────────────────────────────

    async def answer_question(self, joiner_id: str, question: str) -> str:
        """Route a joiner question to the QA agent and return the answer (async)."""
        return await self.qa_agent.answer(joiner_id=joiner_id, question=question)

    # ─────────────────────────────────────────────
    # LMS Gate Confirmation (Phase 3)
    # ─────────────────────────────────────────────

    def confirm_lms_complete(self, joiner_id: str) -> None:
        """
        Called from the admin portal when the admin confirms LMS completion.
        Unlocks the Phase 3 gate so the joiner can mark it done.
        """
        state = self.store.get_state(joiner_id)
        if not state:
            return

        state.lms_mandatory_confirmed = True

        if state.phase_statuses.get(3) == PhaseStatus.ACTIVE:
            state.app_notifications.insert(
                0,
                "✅ **LMS Training Confirmed!**\n\n"
                "Your admin has confirmed your mandatory training is complete. "
                "You can now tick all Phase 3 items and mark the phase as done. "
                "Great work — the Learning phase is your foundation for everything ahead!",
            )
        self.store.save_state(state)

    # ─────────────────────────────────────────────
    # Feedback
    # ─────────────────────────────────────────────

    async def store_feedback(
        self, joiner_id: str, phase_id: int, answers: dict[str, str]
    ) -> str:
        """Route feedback submission to the feedback agent (async). Returns thank-you message."""
        return await self.feedback_agent.store_feedback(
            joiner_id=joiner_id,
            phase_id=phase_id,
            answers=answers,
        )

    # ─────────────────────────────────────────────
    # Scheduled Progress Check
    # ─────────────────────────────────────────────

    def run_progress_check(self) -> int:
        """
        Called every 6 hours by the background scheduler (APScheduler).
        Delegates to progress tracker to send nudges where needed.
        Returns the number of nudges sent.
        """
        return self.progress_tracker.check_all_joiners()
