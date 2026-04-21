"""
agents/training_agent.py — Training Planner Agent
==================================================
Builds a personalised course plan for the new joiner.

Separates two course tracks:
  - Mandatory company-wide: GDPR, Info Security, Code of Conduct, etc.
  - Role-specific: tools training, department processes, technical skills

Sources: knowledge base only (no LMS API in PoC).
The KB contains per-tool onboarding guides, training matrices, learning
paths, and compliance training links from the company's Google Drive.

Phase 3 gate: all mandatory courses must be confirmed complete in the LMS
before the joiner can mark Phase 3 done. Admins confirm via the admin portal.

Output: stored as in-app notification; displayed in "My Training" tab.

Model routing:
  - KB retrieval  : Voyage + FAISS
  - Plan writing  : Claude Haiku (structured, factual output)
"""

import asyncio

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import ANTHROPIC_API_KEY, MODEL_FAST
from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_TRAINING_SYSTEM = """You are OnboardingBuddy's Training Planner agent.
Build a personalised training plan for a new joiner based on their role, seniority,
department, and assigned tools.

Use ONLY the knowledge base context provided — no invented course names or links.

Structure your output as:

## Mandatory Company-Wide Training (Phase 3 — must complete for gate)
List each course on a new line: **Course Name** — brief description

## Role-Specific Training
List each course/resource on a new line: **Name** — brief description

## Recommended Resources
2–3 additional KB documents or reading materials relevant to this role

Keep each description to one sentence. Total length: 250–350 words.
Do NOT invent LMS links or course codes — only reference what the KB confirms exists."""


class TrainingAgent:
    """
    Builds a personalised training plan for a new joiner.
    Called at activation alongside other agents (parallel).
    Output stored as in-app notification and shown in the My Training tab.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store   = store
        self.kb      = kb
        self._client = (
            anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def build_course_plan(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Build and store the personalised training plan.

        1. Retrieve KB chunks for compliance training, tool guides, role learning paths
        2. Generate the plan with Claude Haiku
        3. Append as in-app notification and update state store
        """
        print(f"[TrainingAgent] Building training plan for {profile.full_name}")

        # Queries targeting compliance, tools, and role-specific learning
        tools_list = ", ".join(profile.tool_access.keys()) if profile.tool_access else "standard tools"
        queries = [
            f"mandatory compliance training GDPR security code of conduct",
            f"role-specific training {profile.job_title} {profile.department} learning path",
            f"tool onboarding guide training {tools_list}",
            f"LMS courses mandatory {profile.seniority} {profile.business_unit}",
        ]

        seen:       set[str]  = set()
        all_chunks: list[dict] = []
        for query in queries:
            for chunk in self.kb.retrieve(query, top_k=3):
                key = f"{chunk['source']}:{chunk['chunk_index']}"
                if key not in seen:
                    seen.add(key)
                    all_chunks.append(chunk)

        if self._client and all_chunks:
            plan = await self._generate_with_llm(profile, all_chunks)
        elif all_chunks:
            plan = self._template_plan(profile, all_chunks)
        else:
            plan = self._fallback_plan(profile)

        # Store as in-app notification
        self.store.append_to_state(
            joiner_id=profile.joiner_id,
            notifications=[f"📚 **Your Training Plan**\n\n{plan}"],
        )
        print(f"[TrainingAgent] Training plan stored for {profile.full_name}")

    # ── Private helpers ───────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _generate_with_llm(self, profile: JoinerProfile, chunks: list[dict]) -> str:
        """Generate the personalised training plan via Claude Haiku + KB context (async)."""
        context = "\n\n---\n\n".join(
            f"[Source: {c['source']}]\n{c['text']}" for c in chunks[:10]
        )
        tools_str = (
            "\n".join(f"  - {t}: {lvl}" for t, lvl in profile.tool_access.items())
            if profile.tool_access else "  No specific tools assigned"
        )
        user_msg = (
            f"New joiner details:\n"
            f"  Name: {profile.full_name}\n"
            f"  Role: {profile.job_title} ({profile.seniority})\n"
            f"  Department: {profile.department} · Team: {profile.team}\n"
            f"  Assigned tools:\n{tools_str}\n\n"
            f"Knowledge base context:\n\n{context}\n\n"
            f"Write the personalised training plan for {profile.full_name}."
        )
        resp = await self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=600,
            system=_TRAINING_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()

    def _template_plan(self, profile: JoinerProfile, chunks: list[dict]) -> str:
        """Structured fallback when LLM is unavailable."""
        top = chunks[0]["text"][:500]
        tools = list(profile.tool_access.keys()) if profile.tool_access else []
        tool_lines = "\n".join(f"- {t} ({profile.tool_access[t]})" for t in tools) or "- No tools assigned"
        return (
            f"## Mandatory Company-Wide Training (Phase 3)\n"
            f"- **GDPR & Data Privacy** — complete in your LMS\n"
            f"- **Information Security Awareness** — complete in your LMS\n"
            f"- **Code of Conduct & Ethics** — complete in your LMS\n\n"
            f"## Your Assigned Tools\n{tool_lines}\n\n"
            f"## From the Knowledge Base\n{top}\n\n"
            f"Ask your manager for direct LMS links to each course."
        )

    def _fallback_plan(self, profile: JoinerProfile) -> str:
        """Minimal plan when KB has no training content."""
        tools = list(profile.tool_access.keys()) if profile.tool_access else []
        tool_lines = "\n".join(f"- {t}" for t in tools) or "- Check with your manager"
        return (
            f"## Your Training Plan — {profile.job_title}\n\n"
            f"**Mandatory (Phase 3 gate):**\n"
            f"- GDPR & Data Privacy (LMS)\n"
            f"- Information Security Awareness (LMS)\n"
            f"- Code of Conduct & Ethics (LMS)\n"
            f"- Department-specific compliance module (LMS)\n\n"
            f"**Your Tool Access to Set Up:**\n{tool_lines}\n\n"
            f"Please contact your manager **{profile.manager_name}** "
            f"({profile.manager_email}) for LMS login details and specific course links."
        )
