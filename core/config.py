"""
core/config.py — Central configuration for OnboardingBuddy
============================================================
Loads environment variables, declares all model names, phase definitions,
and shared constants used across every module in the system.

All other modules import from here — no magic strings scattered around the codebase.
"""

import os
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional

# Load .env file if present (for local development)
load_dotenv()


# ─────────────────────────────────────────────
# API Keys (read from environment)
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY: str = os.environ.get("VOYAGE_API_KEY", "")
HF_TOKEN: str = os.environ.get("HF_TOKEN", "")

# Optional integration keys — system runs in simulated mode if blank
SLACK_BOT_TOKEN: Optional[str] = os.environ.get("SLACK_BOT_TOKEN") or None
GOOGLE_CALENDAR_TOKEN: Optional[str] = os.environ.get("GOOGLE_CALENDAR_TOKEN") or None
LMS_API_KEY: Optional[str] = os.environ.get("LMS_API_KEY") or None
IT_PROVISIONING_API_KEY: Optional[str] = os.environ.get("IT_PROVISIONING_API_KEY") or None


# ─────────────────────────────────────────────
# Model Routing
# ─────────────────────────────────────────────
# Cost strategy:
#   - Haiku  → fast/cheap → KB retrieval answers, nudge generation, routing decisions
#   - Sonnet → higher quality → buddy coaching letters, sentiment analysis, phase summaries

MODEL_FAST: str = "claude-haiku-4-5"         # KB Q&A, nudges, classification
MODEL_SMART: str = "claude-sonnet-4-5"       # Buddy messages, feedback analysis
EMBEDDING_MODEL: str = "voyage-3-lite"        # Free-tier embeddings


# ─────────────────────────────────────────────
# RAG / Knowledge Base Settings
# ─────────────────────────────────────────────

CHUNK_SIZE: int = 400          # tokens per chunk
CHUNK_OVERLAP: int = 80        # overlap between consecutive chunks
TOP_K_RESULTS: int = 5         # number of KB chunks to retrieve per query
KB_DOCS_PATH: str = "data/kb_documents"   # where raw .txt/.docx files live
FAISS_INDEX_PATH: str = "data/faiss_index.pkl"  # persisted vector index


# ─────────────────────────────────────────────
# Phase Definitions
# ─────────────────────────────────────────────
# Each phase has: id, name, day range, objectives, checklist items, feedback questions,
# and whether completion requires a system gate (LMS) or is joiner-controlled.

@dataclass
class PhaseDefinition:
    phase_id: int
    name: str
    day_start: int
    day_end: int
    objective: str
    checklist: list[str]
    feedback_questions: list[str]
    system_gated: bool = False   # True only for Phase 3 (LMS confirmation required)
    nudge_after_days: int = 3    # Send nudge if not completed within N days of window


PHASES: list[PhaseDefinition] = [
    PhaseDefinition(
        phase_id=1,
        name="Welcome",
        day_start=1,
        day_end=2,
        objective="Get set up, meet your buddy, and feel at home on Day 1.",
        checklist=[
            "Workstation set up and logged in",
            "IT access credentials received",
            "Buddy intro call completed",
            "Office / remote workspace tour done",
            "First hello from OnboardingBuddy read",
            "Team Slack channel joined",
        ],
        feedback_questions=[
            "Did you feel genuinely welcomed on your first day?",
            "Was your workstation setup smooth and ready when you arrived?",
            "Did you connect with your buddy and feel supported?",
        ],
    ),
    PhaseDefinition(
        phase_id=2,
        name="Bearings",
        day_start=3,
        day_end=5,
        objective="Understand where your team fits, meet key stakeholders, and learn the company story.",
        checklist=[
            "Read the company mission, values, and OKRs",
            "Reviewed your team charter and department structure",
            "Understood how your role connects to company growth",
            "Completed the stakeholder map (3+ introductions)",
            "Attended first team stand-up or meeting",
            "Read the culture & ways-of-working guide",
        ],
        feedback_questions=[
            "Do you understand where your team fits within Nexora?",
            "Is the company context and strategy clear to you?",
            "Do you feel you know who your key stakeholders are?",
        ],
    ),
    PhaseDefinition(
        phase_id=3,
        name="Learning",
        day_start=5,
        day_end=29,
        objective="Complete mandatory compliance training and role-specific tool courses.",
        checklist=[
            "GDPR & Data Privacy course completed (LMS)",
            "Information Security Awareness completed (LMS)",
            "Code of Conduct & Ethics completed (LMS)",
            "Role-specific tool training completed (LMS)",
            "Department-specific mandatory module completed (LMS)",
        ],
        feedback_questions=[
            "Were the mandatory courses relevant and well-structured?",
            "Were there any gaps in the training content for your role?",
            "Do you feel confident using the tools covered in training?",
        ],
        system_gated=True,   # LMS confirmation required before marking complete
    ),
    PhaseDefinition(
        phase_id=4,
        name="Hands Dirty",
        day_start=15,
        day_end=60,
        objective="Shadow your buddy, join team meetings, and take on your first real work.",
        checklist=[
            "Shadowed buddy in at least 2 team meetings",
            "Scheduled 1:1s with 3+ colleagues",
            "Reviewed the team roadmap with your manager",
            "Contributed to at least one team deliverable",
            "Understood current team priorities and blockers",
            "Completed your 30-day check-in with your manager",
        ],
        feedback_questions=[
            "Are you getting meaningful exposure to real work?",
            "Do you feel included and part of the team?",
            "Is there anything blocking your ability to contribute?",
        ],
    ),
    PhaseDefinition(
        phase_id=5,
        name="Ready to Own",
        day_start=60,
        day_end=90,
        objective="Take full ownership of your role and prepare your 90-day insights.",
        checklist=[
            "Completed the 60-day manager check-in",
            "Taken full ownership of at least one end-to-end workstream",
            "Drafted your 90-day insight and learning presentation",
            "Identified 2–3 areas for personal development",
            "Set initial goals for the next quarter",
        ],
        feedback_questions=[
            "Do you feel ready to fully own your role?",
            "What support do you still need to be fully effective?",
            "Are your goals and expectations clearly aligned with your manager?",
        ],
    ),
    PhaseDefinition(
        phase_id=6,
        name="Finish Line",
        day_start=90,
        day_end=90,
        objective="Celebrate completing onboarding, set yearly goals, and submit your final feedback.",
        checklist=[
            "Delivered your 90-day insight presentation",
            "Set yearly goals with your manager",
            "Completed the final onboarding feedback survey",
        ],
        feedback_questions=[
            "Overall, how would you rate your onboarding experience? (1–10)",
            "What worked really well during your onboarding?",
            "What would you improve or change for the next cohort?",
            "Any additional comments or suggestions?",
        ],
    ),
]

# Quick lookup: phase_id → PhaseDefinition
PHASE_BY_ID: dict[int, PhaseDefinition] = {p.phase_id: p for p in PHASES}


# ─────────────────────────────────────────────
# Departments & Roles (derived from KB documents)
# ─────────────────────────────────────────────

DEPARTMENTS: list[str] = [
    "IT",
    "Commercial Excellence & Quality (CE&Q)",
    "HR & People Analytics",
    "R&D / Product Discovery",
    "Customer Success",
    "Finance / FP&A",
    "Operations / Supply Chain",
    "Sales Enablement",
    "Cloud Engineering",
    "TCP (Technology & Commercial Products)",
]

SENIORITY_LEVELS: list[str] = [
    "Analyst / Associate",
    "Senior Analyst / Senior Associate",
    "Manager",
    "Senior Manager",
    "Director",
    "Senior Director / VP",
    "C-Suite / Executive",
]


# ─────────────────────────────────────────────
# Progress & Nudge Settings
# ─────────────────────────────────────────────

NUDGE_POLL_INTERVAL_SECONDS: int = 60 * 60 * 6   # Check every 6 hours in production
MANAGER_SUMMARY_INTERVAL_DAYS: int = 7            # Weekly manager digest
SENTIMENT_ESCALATION_THRESHOLD: float = 3.0       # Average score below this triggers alert


# ─────────────────────────────────────────────
# UI Settings
# ─────────────────────────────────────────────

APP_TITLE: str = "OnboardingBuddy"
APP_TAGLINE: str = "Your AI-powered guide through your first 90 days at Nexora"
ADMIN_APP_TITLE: str = "OnboardingBuddy — Admin Portal"
JOINER_APP_TITLE: str = "OnboardingBuddy — Your Onboarding Journey"

# Brand colours (teal primary)
COLOR_PRIMARY: str = "#00897B"       # Teal
COLOR_SECONDARY: str = "#26A69A"
COLOR_ACCENT: str = "#FF7043"        # Coral / warm accent
COLOR_SURFACE: str = "#F5F5F5"
COLOR_TEXT: str = "#212121"
