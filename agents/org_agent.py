"""
agents/org_agent.py — Org & Role Context Agent
===============================================
Surfaces organisational context relevant to the joiner:
  - Where their team sits in the company structure
  - Team mission and responsibilities
  - How the role connects to company OKRs and growth
  - Key stakeholders to know

Activates in parallel on Day 1.
Content is posted as an in-app notification available from Day 3 (per spec).

Model: Claude Haiku (retrieval-based — not high reasoning complexity).
"""

import anthropic

from core.config import ANTHROPIC_API_KEY, MODEL_FAST
from core.models import JoinerProfile, JoinerState
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


_ORG_SYSTEM_PROMPT = """You are OnboardingBuddy's org context specialist.
Using only the provided knowledge base content, write a warm and clear summary for a new joiner
that covers: (1) where their team sits in the company, (2) their department's mission,
(3) how their role connects to company goals, (4) 3–5 key people they should know.
Keep it under 350 words. Use a friendly, welcoming tone. Use bullet points where helpful.
Only use information from the context — do not invent names, titles, or facts.
"""


class OrgAgent:
    """Builds the org & role context brief for a new joiner."""

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store = store
        self.kb = kb
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    def build_org_brief(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Query the KB for org/team/role context, generate a brief, and
        post it as a Day-3-ready notification in the joiner's state.
        """
        # Retrieve relevant KB content
        queries = [
            f"{profile.department} department team structure mission",
            f"{profile.job_title} role responsibilities stakeholders",
            "company OKRs strategy how teams connect",
            f"{profile.team} team ways of working",
        ]

        chunks = []
        seen_sources = set()
        for q in queries:
            for chunk in self.kb.retrieve(q, top_k=3):
                if chunk["source"] not in seen_sources:
                    chunks.append(chunk)
                    seen_sources.add(chunk["source"])

        context = "\n\n---\n\n".join(
            f"[{c['source']}]\n{c['text']}" for c in chunks[:8]
        )

        # Generate brief
        brief = self._generate_brief(profile, context)

        # Post to joiner state atomically (avoid race with other Day-1 agents)
        self.store.append_to_state(
            profile.joiner_id,
            notifications=[f"🏢 Your Org Context Brief (available from Day 3)\n\n{brief}"],
        )

    def _generate_brief(self, profile: JoinerProfile, context: str) -> str:
        if self._client is None or not context.strip():
            return (
                f"Welcome to the {profile.department} department, {profile.full_name}! "
                f"Your manager {profile.manager_name} will walk you through your team's "
                f"structure and priorities in your first 1:1. "
                f"Check the Employee Directory and Culture Playbook for more context."
            )

        try:
            prompt = (
                f"New joiner profile:\n"
                f"- Name: {profile.full_name}\n"
                f"- Role: {profile.job_title} ({profile.seniority})\n"
                f"- Department: {profile.department}\n"
                f"- Team: {profile.team}\n"
                f"- Division: {profile.division}\n\n"
                f"Knowledge base context:\n\n{context}\n\n"
                f"Write the org context brief for this joiner."
            )
            response = self._client.messages.create(
                model=MODEL_FAST,
                max_tokens=512,
                system=_ORG_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[OrgAgent] LLM error: {e}")
            return f"Your org context is being prepared. Check back on Day 3 — your manager {profile.manager_name} can also walk you through it."
