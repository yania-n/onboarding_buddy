"""
core/config.py — Central configuration for OnboardingBuddy
============================================================
Single source of truth for every constant, colour, model name, phase
definition, and dropdown list used across the system.

All other modules import from here — no magic strings elsewhere.

PoC constraints applied:
  - No HRIS integration → org data sourced from knowledge base only
  - No MS Teams → all notifications are in-app only
  - No calendar booking → system directs joiner to contact the person directly
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# Load .env file for local development (no-op in HF Spaces)
load_dotenv()


# ─────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY: str    = os.environ.get("VOYAGE_API_KEY", "")
HF_TOKEN: str          = os.environ.get("HF_TOKEN", "")

# Google Drive — optional; if set, KB is synced from Drive on startup
GOOGLE_API_KEY: str        = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_DRIVE_FOLDER_ID: str = os.environ.get(
    "GOOGLE_DRIVE_FOLDER_ID",
    "1DZvjvJBErSrMIWKy90O8fBjcFgsTtQrl",   # default: the shared company Drive folder
)

# PoC: no LMS, IT-provisioning, MS Teams, or calendar tokens needed
LMS_API_KEY: Optional[str]             = os.environ.get("LMS_API_KEY") or None
IT_PROVISIONING_API_KEY: Optional[str] = os.environ.get("IT_PROVISIONING_API_KEY") or None


# ─────────────────────────────────────────────
# Model Routing — cost-effective tiering
# ─────────────────────────────────────────────
# Haiku  → fast & cheap  → KB Q&A, nudges, access briefs, training plans
# Sonnet → higher quality → buddy context, feedback analysis, org summaries

MODEL_FAST:  str = "claude-haiku-4-5-20251001"   # Fast tasks
MODEL_SMART: str = "claude-sonnet-4-6"            # Complex tasks
EMBEDDING_MODEL: str = "voyage-3-lite"            # Free-tier Voyage embeddings


# ─────────────────────────────────────────────
# RAG / Knowledge Base Settings
# ─────────────────────────────────────────────

CHUNK_SIZE: int        = 400             # ~words per chunk
CHUNK_OVERLAP: int     = 80             # overlap between consecutive chunks
TOP_K_RESULTS: int     = 5              # KB chunks retrieved per query
KB_DOCS_PATH: str      = "data/kb_documents"
FAISS_INDEX_PATH: str  = "data/faiss_index.pkl"


# ─────────────────────────────────────────────
# Phase Definitions
# ─────────────────────────────────────────────

@dataclass
class PhaseDefinition:
    """All metadata for a single onboarding phase."""
    phase_id:           int
    name:               str
    day_start:          int
    day_end:            int
    objective:          str
    checklist:          list[str]
    feedback_questions: list[str]
    system_gated:       bool = False   # Phase 3 only — LMS gate
    nudge_after_days:   int  = 3       # Nudge if not done within N days


PHASES: list[PhaseDefinition] = [
    PhaseDefinition(
        phase_id=1,
        name="Welcome",
        day_start=1, day_end=2,
        objective="Get set up, meet your buddy, and feel at home on Day 1.",
        checklist=[
            "Workstation set up and logged in",
            "IT access credentials received",
            "Intro call with buddy arranged (contact details in My Journey)",
            "Office or remote workspace tour done",
            "First welcome message from OnboardingBuddy read",
            "Team communication channel joined",
        ],
        feedback_questions=[
            "Did you feel genuinely welcomed on your first day?",
            "Was your workstation setup smooth and ready when you arrived?",
            "Did you connect with your buddy?",
        ],
    ),
    PhaseDefinition(
        phase_id=2,
        name="Bearings",
        day_start=3, day_end=5,
        objective="Understand where your team fits, meet key stakeholders, and learn the company story.",
        checklist=[
            "Read the company mission, values, and OKRs",
            "Reviewed your team charter and department structure",
            "Understood how your role connects to company growth",
            "Identified 3+ key stakeholders to connect with",
            "Attended first team stand-up or team meeting",
            "Read the culture and ways-of-working guide",
        ],
        feedback_questions=[
            "Do you understand where your team fits within the organisation?",
            "Is the company context and strategy clear to you?",
            "Do you feel you know who your key stakeholders are?",
        ],
    ),
    PhaseDefinition(
        phase_id=3,
        name="Learning",
        day_start=5, day_end=29,
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
        system_gated=True,  # LMS confirmation required before marking complete
    ),
    PhaseDefinition(
        phase_id=4,
        name="Hands Dirty",
        day_start=15, day_end=60,
        objective="Shadow your buddy, join team meetings, and take on your first real work.",
        checklist=[
            "Shadowed buddy in at least 2 team meetings",
            "Scheduled 1:1s with 3 or more colleagues",
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
        day_start=60, day_end=90,
        objective="Take full ownership of your role and prepare your 90-day insights.",
        checklist=[
            "Completed the 60-day manager check-in",
            "Taken full ownership of at least one end-to-end workstream",
            "Drafted your 90-day insight and learning summary",
            "Identified 2 to 3 areas for personal development",
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
        day_start=90, day_end=90,
        objective="Celebrate completing onboarding, set yearly goals, and submit final feedback.",
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

# Fast lookup: phase_id → PhaseDefinition
PHASE_BY_ID: dict[int, PhaseDefinition] = {p.phase_id: p for p in PHASES}


# ─────────────────────────────────────────────
# Org Structure Library  (Admin form dropdowns)
# ─────────────────────────────────────────────
# These are used to populate dropdowns in the admin new-joiner form.
# In production these would be pulled from HRIS; for this PoC they are
# maintained as static lists reflecting the company's actual structure.

BUSINESS_UNITS: list[str] = [
    "Technology & Products",
    "Commercial",
    "Operations",
    "People & Culture",
    "Finance",
    "Research & Development",
    "Customer",
]

DIVISIONS: list[str] = [
    "Digital Products",
    "Platform Engineering",
    "Cloud Infrastructure",
    "Data & Analytics",
    "Sales Enablement",
    "Commercial Excellence",
    "Supply Chain & Visibility",
    "HR & People Analytics",
    "Finance & FP&A",
    "Product Discovery",
    "Customer Success",
    "TCP (Technology & Commercial Products)",
]

DEPARTMENTS: list[str] = [
    "IT",
    "Cloud Engineering",
    "HR & People Analytics",
    "R&D / Product Discovery",
    "Customer Success",
    "Finance / FP&A",
    "Operations / Supply Chain",
    "Sales Enablement",
    "Commercial Excellence & Quality",
    "TCP (Technology & Commercial Products)",
    "Legal & Compliance",
    "Marketing",
]

TEAMS: list[str] = [
    "Platform Engineering",
    "Site Reliability",
    "Data Engineering",
    "ML & AI",
    "Security",
    "People Operations",
    "Talent Acquisition",
    "Financial Planning",
    "Revenue Operations",
    "Product Management",
    "UX & Design",
    "Customer Onboarding",
    "Account Management",
    "Procurement",
    "Logistics",
    "Compliance & Risk",
]

ROLES: list[str] = [
    "Software Engineer",
    "Senior Software Engineer",
    "Staff Engineer",
    "Data Analyst",
    "Senior Data Analyst",
    "Data Scientist",
    "ML Engineer",
    "Product Manager",
    "Senior Product Manager",
    "UX Designer",
    "DevOps / SRE Engineer",
    "Cloud Architect",
    "IT Support Specialist",
    "HR Business Partner",
    "Talent Acquisition Specialist",
    "Financial Analyst",
    "FP&A Manager",
    "Account Executive",
    "Customer Success Manager",
    "Sales Engineer",
    "Supply Chain Analyst",
    "Operations Manager",
    "Compliance Officer",
    "Legal Counsel",
    "Marketing Manager",
    "Content Strategist",
    "Other / Custom",
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
# Tools Library  (Admin form multi-select)
# ─────────────────────────────────────────────
# Format: "Tool Name" → list of permission levels available for that tool.
# The admin selects which tools the joiner needs and at what level.

TOOLS_CATALOGUE: dict[str, list[str]] = {
    # Productivity & Communication
    "Microsoft 365 (Outlook, Word, Excel, PowerPoint)": ["Standard User", "Full Access"],
    "Microsoft Teams":            ["Standard User", "Full Access"],
    "SharePoint":                 ["View Only", "Contributor", "Full Access"],
    "Zoom":                       ["Standard User", "Host / Full Access"],

    # Project & Work Management
    "Jira":                       ["View Only", "Standard User", "Project Admin"],
    "Confluence":                 ["View Only", "Contributor", "Space Admin"],
    "Asana":                      ["View Only", "Standard User", "Admin"],
    "Monday.com":                 ["View Only", "Member", "Admin"],

    # Engineering & Dev
    "GitHub":                     ["Read Only", "Contributor", "Maintainer", "Admin"],
    "GitLab":                     ["Reporter", "Developer", "Maintainer", "Owner"],
    "Azure DevOps":               ["Stakeholder", "Basic", "Admin"],
    "VS Code / Codespaces":       ["Standard User"],

    # Cloud & Infrastructure
    "AWS":                        ["Read Only", "Developer", "Power User", "Admin"],
    "Azure":                      ["Reader", "Contributor", "Owner"],
    "GCP":                        ["Viewer", "Editor", "Owner"],

    # Data & Analytics
    "Tableau":                    ["Viewer", "Explorer", "Creator", "Admin"],
    "Power BI":                   ["Viewer", "Contributor", "Admin"],
    "Databricks":                 ["User", "Can Restart", "Can Manage"],
    "Snowflake":                  ["Read Only", "Read/Write", "Account Admin"],

    # CRM & Sales
    "Salesforce":                 ["Read Only", "Standard User", "Full Access", "Admin"],
    "HubSpot":                    ["View Only", "Standard User", "Super Admin"],

    # ITSM & Support
    "ServiceNow":                 ["Requester", "Fulfiller", "Admin"],

    # HR & Finance
    "Workday":                    ["Employee Self-Service", "HR Partner", "Admin"],
    "Netsuite / SAP":             ["Read Only", "Standard User", "Power User"],

    # Security
    "1Password / LastPass":       ["Standard User", "Admin"],
    "Okta / SSO":                 ["Standard User", "Admin"],
    "CrowdStrike / Defender":     ["View Only", "Admin"],
}

# Flat list of tool names for dropdown rendering
ALL_TOOLS: list[str] = sorted(TOOLS_CATALOGUE.keys())

# Permission levels (union across all tools — used in simple text fallback)
ALL_PERMISSION_LEVELS: list[str] = [
    "View Only",
    "Read Only",
    "Standard User",
    "Contributor / Editor",
    "Full Access",
    "Admin",
]


# ─────────────────────────────────────────────
# Progress & Nudge Settings
# ─────────────────────────────────────────────

NUDGE_POLL_INTERVAL_SECONDS: int   = 60 * 60 * 6   # Every 6 hours
MANAGER_SUMMARY_INTERVAL_DAYS: int = 7              # Weekly digest
SENTIMENT_ESCALATION_THRESHOLD: float = 3.0         # Avg score below → flag


# ─────────────────────────────────────────────
# UI / Brand Settings — Grass Green + Black + White
# ─────────────────────────────────────────────

APP_TITLE: str        = "OnboardingBuddy"
APP_TAGLINE: str      = "Your AI-powered guide through your first 90 days"
ADMIN_APP_TITLE: str  = "OnboardingBuddy — Admin Portal"
JOINER_APP_TITLE: str = "OnboardingBuddy — Your Onboarding Journey"

# Brand palette: grass green, black, white
COLOR_PRIMARY:        str = "#4CAF50"   # Grass green
COLOR_PRIMARY_DARK:   str = "#388E3C"   # Dark green (hover, borders)
COLOR_PRIMARY_DARKER: str = "#2E7D32"   # Very dark green (headers)
COLOR_PRIMARY_LIGHT:  str = "#81C784"   # Light green (accents)
COLOR_SURFACE:        str = "#F1F8E9"   # Near-white green tint (page bg)
COLOR_CARD:           str = "#FFFFFF"   # White (card backgrounds)
COLOR_TEXT:           str = "#000000"   # Black (primary text)
COLOR_TEXT_SECONDARY: str = "#212121"   # Near-black (secondary text)
COLOR_MUTED:          str = "#616161"   # Dark grey (placeholder, meta)
COLOR_BORDER:         str = "#A5D6A7"   # Green-tinted border
COLOR_SUCCESS:        str = "#2E7D32"   # Dark green (success state)
COLOR_WARNING:        str = "#F57F17"   # Amber (warning)
COLOR_DANGER:         str = "#C62828"   # Red (error / danger)
COLOR_WHITE:          str = "#FFFFFF"
COLOR_BLACK:          str = "#000000"

# Shared CSS variables block — injected once via app.py
GLOBAL_CSS_VARS = f"""
:root {{
    /* ── Our brand tokens ─────────────────────────────── */
    --ob-primary:         {COLOR_PRIMARY};
    --ob-primary-dark:    {COLOR_PRIMARY_DARK};
    --ob-primary-darker:  {COLOR_PRIMARY_DARKER};
    --ob-primary-light:   {COLOR_PRIMARY_LIGHT};
    --ob-surface:         {COLOR_SURFACE};
    --ob-card:            {COLOR_CARD};
    --ob-text:            {COLOR_TEXT};
    --ob-text-sec:        {COLOR_TEXT_SECONDARY};
    --ob-muted:           {COLOR_MUTED};
    --ob-text-muted:      {COLOR_MUTED};
    --ob-border:          {COLOR_BORDER};
    --ob-success:         {COLOR_SUCCESS};
    --ob-success-bg:      #E8F5E9;
    --ob-success-text:    #1B5E20;
    --ob-warning:         {COLOR_WARNING};
    --ob-warning-bg:      #FFF8E1;
    --ob-warning-text:    #E65100;
    --ob-danger:          {COLOR_DANGER};
    --ob-error-bg:        #FFEBEE;
    --ob-error-text:      #B71C1C;
    --ob-gap-bg:          #F9FBE7;
    --ob-locked:          #BDBDBD;
    --ob-progress-track:  #E0E0E0;

    /* ── Override Gradio 4.44 internal theme variables ── */
    /* Forces light mode regardless of system/browser preference */
    --body-background-fill:            {COLOR_SURFACE};
    --body-text-color:                 {COLOR_TEXT};
    --body-text-color-subdued:         {COLOR_MUTED};
    --block-background-fill:           {COLOR_CARD};
    --block-border-color:              {COLOR_BORDER};
    --block-label-background-fill:     {COLOR_CARD};
    --block-label-text-color:          {COLOR_TEXT_SECONDARY};
    --block-title-text-color:          {COLOR_TEXT};
    --input-background-fill:           {COLOR_CARD};
    --input-border-color:              {COLOR_BORDER};
    --input-text-color:                {COLOR_TEXT};
    --input-placeholder-color:         {COLOR_MUTED};
    --prose-text-color:                {COLOR_TEXT};
    --prose-header-text-color:         {COLOR_TEXT};
    --checkbox-label-text-color:       {COLOR_TEXT};
    --radio-circle-color:              {COLOR_PRIMARY};
    --button-primary-background-fill:  {COLOR_PRIMARY};
    --button-primary-text-color:       #FFFFFF;
    --button-secondary-background-fill: {COLOR_CARD};
    --button-secondary-text-color:     {COLOR_TEXT};
    --table-text-color:                {COLOR_TEXT};
    --table-even-background-fill:      {COLOR_SURFACE};
    --table-odd-background-fill:       {COLOR_CARD};
    --panel-background-fill:           {COLOR_SURFACE};
    --tab-nav-background-fill:         {COLOR_SURFACE};
    --tab-nav-text-color:              {COLOR_MUTED};
    --tab-nav-selected-text-color:     {COLOR_PRIMARY_DARKER};
    --border-color-primary:            {COLOR_BORDER};
    --color-accent:                    {COLOR_PRIMARY};
    --color-accent-soft:               {COLOR_PRIMARY_LIGHT};
    --link-text-color:                 {COLOR_PRIMARY_DARK};
    --link-text-color-hover:           {COLOR_PRIMARY_DARKER};
    --link-text-color-visited:         {COLOR_PRIMARY_DARK};
    --shadow-drop:                     0 1px 3px rgba(0,0,0,0.08);
}}

/* Gradio scopes styles so also add direct element overrides */
.gradio-container, .gradio-container * {{
    color: {COLOR_TEXT};
}}
/* Restore white text on coloured buttons/badges */
button.primary, .btn-primary, .svelte-1gfkn6j,
[data-testid="primary-btn"] {{
    color: #FFFFFF !important;
}}
/* Labels */
label, .label-wrap span, .block-label span {{
    color: {COLOR_TEXT_SECONDARY} !important;
}}
/* Markdown prose */
.prose, .prose p, .prose li, .prose h1, .prose h2, .prose h3 {{
    color: {COLOR_TEXT} !important;
}}
/* Tabs */
.tab-nav button {{
    color: {COLOR_MUTED} !important;
}}
.tab-nav button.selected {{
    color: {COLOR_PRIMARY_DARKER} !important;
}}
"""
