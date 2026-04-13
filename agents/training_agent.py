"""
agents/training_agent.py — Training Planner Agent
==================================================
Builds a personalised course plan based on role, seniority, department,
and assigned tools. Separates mandatory company-wide courses from
role-specific courses. Surfaces the plan in the joiner app.

Phase 3 Gate: monitors lms_mandatory_confirmed on the state record.
In production: syncs with the LMS API to read completion status.
Current mode: simulated course list with a manual admin confirm button.

Model: None (rule-based course selection from KB content).
"""

from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


# ─────────────────────────────────────────────
# Mandatory courses — all joiners, all departments
# ─────────────────────────────────────────────
MANDATORY_COURSES = [
    {"id": "COMP-001", "title": "GDPR & Data Privacy", "duration_mins": 45, "lms_link": "#lms-gdpr"},
    {"id": "COMP-002", "title": "Information Security Awareness", "duration_mins": 60, "lms_link": "#lms-security"},
    {"id": "COMP-003", "title": "Code of Conduct & Ethics", "duration_mins": 30, "lms_link": "#lms-ethics"},
    {"id": "COMP-004", "title": "Anti-Bribery & Corruption", "duration_mins": 30, "lms_link": "#lms-abc"},
    {"id": "COMP-005", "title": "Health & Safety Fundamentals", "duration_mins": 20, "lms_link": "#lms-hns"},
]

# Department-specific required courses
DEPT_COURSES = {
    "IT": [
        {"id": "IT-001", "title": "Cloud Security Essentials", "duration_mins": 90, "lms_link": "#lms-cloud-sec"},
        {"id": "IT-002", "title": "Nexora Infrastructure Overview", "duration_mins": 60, "lms_link": "#lms-infra"},
        {"id": "IT-003", "title": "Incident Response Procedures", "duration_mins": 45, "lms_link": "#lms-incident"},
    ],
    "Commercial Excellence & Quality (CE&Q)": [
        {"id": "CEQ-001", "title": "Quality Management System (QMS) Overview", "duration_mins": 60, "lms_link": "#lms-qms"},
        {"id": "CEQ-002", "title": "Commercial Excellence Framework", "duration_mins": 45, "lms_link": "#lms-cex"},
    ],
    "Finance / FP&A": [
        {"id": "FIN-001", "title": "Financial Controls & SOX Compliance", "duration_mins": 60, "lms_link": "#lms-sox"},
        {"id": "FIN-002", "title": "Nexora Chart of Accounts", "duration_mins": 30, "lms_link": "#lms-coa"},
    ],
    "HR & People Analytics": [
        {"id": "HR-001", "title": "People Data Privacy & Ethics", "duration_mins": 45, "lms_link": "#lms-people-data"},
    ],
}

# Generic role-type courses (assigned based on seniority)
LEADERSHIP_COURSES = [
    {"id": "LEAD-001", "title": "Leading at Nexora — Manager Essentials", "duration_mins": 120, "lms_link": "#lms-lead"},
    {"id": "LEAD-002", "title": "Performance Conversations Framework", "duration_mins": 60, "lms_link": "#lms-perf"},
]

SENIORITY_TRIGGERS_LEADERSHIP = {"Manager", "Senior Manager", "Director", "Senior Director / VP", "C-Suite / Executive"}


class TrainingAgent:
    """Builds and surfaces the personalised training plan for a joiner."""

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store = store
        self.kb = kb

    def build_course_plan(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Assemble the course plan and post it to the joiner's notifications.
        Stores course list in the state for later LMS tracking.
        """
        mandatory = list(MANDATORY_COURSES)
        role_specific = list(DEPT_COURSES.get(profile.department, []))

        if profile.seniority in SENIORITY_TRIGGERS_LEADERSHIP:
            role_specific.extend(LEADERSHIP_COURSES)

        # Tool-specific training (generic — in production, pull from LMS)
        tool_courses = []
        for tool in profile.tool_access:
            tool_courses.append({
                "id": f"TOOL-{tool[:3].upper()}",
                "title": f"{tool} — Getting Started",
                "duration_mins": 30,
                "lms_link": f"#lms-{tool.lower().replace(' ', '-')}",
            })

        all_courses = mandatory + role_specific + tool_courses

        # Build notification
        mandatory_lines = "\n".join(
            f"  • [{c['id']}] {c['title']} ({c['duration_mins']} min)"
            for c in mandatory
        )
        role_lines = "\n".join(
            f"  • [{c['id']}] {c['title']} ({c['duration_mins']} min)"
            for c in role_specific + tool_courses
        ) or "  • No additional role-specific courses identified."

        total_mins = sum(c["duration_mins"] for c in all_courses)
        notification = (
            f"📚 Your Training Plan — Phase 3 (Days 5–29)\n\n"
            f"Mandatory courses (required for Phase 3 gate):\n{mandatory_lines}\n\n"
            f"Role-specific courses:\n{role_lines}\n\n"
            f"Total estimated time: {total_mins // 60}h {total_mins % 60}min\n\n"
            f"Access all courses via your LMS dashboard. Phase 3 unlocks automatically "
            f"once the LMS confirms all mandatory courses are complete."
        )

        # Post atomically to avoid race with other Day-1 agents
        self.store.append_to_state(
            profile.joiner_id,
            notifications=[notification],
        )

    def get_course_plan(self, joiner_id: str) -> dict:
        """Return structured course plan for the UI training dashboard."""
        state = self.store.get_state(joiner_id)
        profile = self.store.get_profile(joiner_id)
        if not state or not profile:
            return {"mandatory": [], "role_specific": [], "tools": []}

        mandatory = list(MANDATORY_COURSES)
        role_specific = list(DEPT_COURSES.get(profile.department, []))
        if profile.seniority in SENIORITY_TRIGGERS_LEADERSHIP:
            role_specific.extend(LEADERSHIP_COURSES)

        tool_courses = [
            {
                "id": f"TOOL-{t[:3].upper()}",
                "title": f"{t} — Getting Started",
                "duration_mins": 30,
                "completed": t in state.lms_courses_completed,
            }
            for t in profile.tool_access
        ]

        # Add completion status from state
        completed_ids = set(state.lms_courses_completed)
        for c in mandatory:
            c["completed"] = c["id"] in completed_ids
        for c in role_specific:
            c["completed"] = c["id"] in completed_ids

        return {
            "mandatory": mandatory,
            "role_specific": role_specific,
            "tools": tool_courses,
            "lms_gate_confirmed": state.lms_mandatory_confirmed,
        }
