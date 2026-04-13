"""
core/models.py — Pydantic data models for OnboardingBuddy
==========================================================
Defines all data structures used across the system:
  - JoinerProfile      → created by the manager in the admin app
  - JoinerState        → live progress record, updated throughout onboarding
  - ChecklistItem      → single task within a phase
  - FeedbackResponse   → pulse survey answers at each phase end
  - KnowledgeGapEntry  → unanswered Q&A chatbot queries logged for admin review
  - NudgeRecord        → log of every nudge / notification sent
  - AccessRequest      → IT provisioning ticket raised on Day 1

All state is JSON-serialisable so it can be persisted to disk or a DB later.
"""

from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────

class PhaseStatus(str, Enum):
    """Lifecycle of a single onboarding phase."""
    LOCKED = "locked"           # Not yet reached
    ACTIVE = "active"           # Currently in progress
    PENDING_LMS = "pending_lms" # Phase 3 only — waiting for LMS gate
    COMPLETE = "complete"        # Joiner marked it done


class AccessStatus(str, Enum):
    PENDING = "pending"
    PROVISIONED = "provisioned"
    BLOCKED = "blocked"


class SentimentLevel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    CONCERNING = "concerning"   # Triggers manager alert


# ─────────────────────────────────────────────
# Joiner Profile (set once by the manager)
# ─────────────────────────────────────────────

class JoinerProfile(BaseModel):
    """
    Everything the manager provides at onboarding setup.
    Immutable after creation (use JoinerState for mutable progress).
    """
    # Identity
    joiner_id: str              # UUID, auto-generated
    full_name: str
    email: str
    start_date: date
    job_title: str
    seniority: str

    # Org placement
    business_unit: str
    division: str
    department: str
    team: str
    role_description: str

    # Manager & buddy
    manager_name: str
    manager_email: str
    buddy_name: str
    buddy_email: str
    buddy_calendar_link: Optional[str] = None

    # Tool access list (tool name → permission level)
    tool_access: dict[str, str] = Field(default_factory=dict)

    # Phase customisations (phase_id → extra days granted)
    phase_extensions: dict[int, int] = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = ""   # manager email


# ─────────────────────────────────────────────
# Checklist Item
# ─────────────────────────────────────────────

class ChecklistItem(BaseModel):
    """A single task within a phase checklist."""
    item_id: str
    phase_id: int
    label: str
    completed: bool = False
    completed_at: Optional[datetime] = None


# ─────────────────────────────────────────────
# Feedback / Pulse Response
# ─────────────────────────────────────────────

class FeedbackResponse(BaseModel):
    """Pulse survey answers collected at the end of each phase."""
    phase_id: int
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    answers: dict[str, str]        # question → answer
    sentiment: Optional[SentimentLevel] = None   # set by feedback agent
    sentiment_score: Optional[float] = None      # 1–5 scale


# ─────────────────────────────────────────────
# Access / IT Provisioning Request
# ─────────────────────────────────────────────

class AccessRequest(BaseModel):
    """One tool provisioning ticket raised on Day 1 by the Access & Tools agent."""
    tool_name: str
    permission_level: str
    status: AccessStatus = AccessStatus.PENDING
    ticket_id: Optional[str] = None
    raised_at: datetime = Field(default_factory=datetime.utcnow)
    provisioned_at: Optional[datetime] = None
    notes: str = ""


# ─────────────────────────────────────────────
# Knowledge Gap Entry
# ─────────────────────────────────────────────

class KnowledgeGapEntry(BaseModel):
    """
    Logged when the Q&A chatbot cannot find an answer in the KB.
    Admins review this to identify missing documentation.
    """
    gap_id: str
    joiner_id: str
    question: str
    asked_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution_note: str = ""


# ─────────────────────────────────────────────
# Nudge Record
# ─────────────────────────────────────────────

class NudgeRecord(BaseModel):
    """Log of every nudge or notification sent to the joiner or manager."""
    nudge_id: str
    joiner_id: str
    channel: str          # "app" | "slack" | "email"
    recipient: str        # "joiner" | "manager"
    phase_id: int
    message: str
    sent_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────
# Live Joiner State (mutable progress record)
# ─────────────────────────────────────────────

class JoinerState(BaseModel):
    """
    The live state record for a single joiner.
    Everything that changes during onboarding lives here.
    Updated by agents and saved to disk as JSON.
    """
    # Link to immutable profile
    joiner_id: str

    # Phase progress
    current_phase: int = 1
    phase_statuses: dict[int, PhaseStatus] = Field(
        default_factory=lambda: {
            1: PhaseStatus.ACTIVE,
            2: PhaseStatus.LOCKED,
            3: PhaseStatus.LOCKED,
            4: PhaseStatus.LOCKED,
            5: PhaseStatus.LOCKED,
            6: PhaseStatus.LOCKED,
        }
    )
    phase_start_dates: dict[int, Optional[date]] = Field(
        default_factory=lambda: {i: None for i in range(1, 7)}
    )
    phase_complete_dates: dict[int, Optional[date]] = Field(
        default_factory=lambda: {i: None for i in range(1, 7)}
    )

    # Checklist state
    checklist_items: list[ChecklistItem] = Field(default_factory=list)

    # Training / LMS
    lms_mandatory_confirmed: bool = False   # Phase 3 gate
    lms_courses_completed: list[str] = Field(default_factory=list)

    # Tool access
    access_requests: list[AccessRequest] = Field(default_factory=list)

    # Feedback
    feedback_responses: list[FeedbackResponse] = Field(default_factory=list)

    # In-app notifications (unread messages from agents)
    app_notifications: list[str] = Field(default_factory=list)

    # Nudge log
    nudge_log: list[NudgeRecord] = Field(default_factory=list)

    # Knowledge gaps this joiner triggered
    knowledge_gaps: list[KnowledgeGapEntry] = Field(default_factory=list)

    # Metadata
    onboarding_complete: bool = False
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def get_checklist_for_phase(self, phase_id: int) -> list[ChecklistItem]:
        return [c for c in self.checklist_items if c.phase_id == phase_id]

    def phase_checklist_complete(self, phase_id: int) -> bool:
        items = self.get_checklist_for_phase(phase_id)
        return bool(items) and all(c.completed for c in items)
