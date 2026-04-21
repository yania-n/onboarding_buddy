"""
agents/org_agent.py — Org & Role Context Agent
===============================================
Surfaces organisational context relevant to the new joiner:
  - Where their team sits in the company structure
  - Company mission, values, and OKRs
  - How the role connects to company growth
  - Key stakeholders they should know and why (with contact details)

Data source: knowledge base ONLY (no HRIS — PoC constraint).
The KB contains org charts, team charters, department missions, and
role wikis ingested from the company's Google Drive.

Activation: called on Day 1 by the orchestrator in parallel with other agents.
Output is stored as an in-app notification viewable in "My Journey" tab.

Model routing:
  - KB retrieval  : Voyage + FAISS (no LLM)
  - Brief writing : Claude Haiku (cheap, fast, factual summary)
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

_ORG_SYSTEM = """You are OnboardingBuddy's Org & Role agent.
Write a personalised "Your Team & Organisation" brief for a new joiner.
Use ONLY the knowledge base context provided — no external knowledge or invented details.

Structure your brief with these headings:
## Your Team
## Where You Fit in the Company
## Key People to Know  (list 3–5, each with a one-line reason why)
## Culture Highlights  (2–3 key culture points)

Style:
- Warm and direct — write TO the joiner ("you", "your team")
- 300–400 words total
- End with one encouraging sentence
- If KB context is thin for this team/role, say so honestly instead of inventing content."""


class OrgAgent:
    """
    Builds a personalised org & role context brief for each new joiner.
    Called once at activation. Output stored as an in-app notification.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store   = store
        self.kb      = kb
        self._client = (
            anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def build_org_brief(self, profile: JoinerProfile, state: JoinerState) -> None:
        """
        Build and store the org context brief.

        1. Retrieve KB chunks for department, team, role, and culture (sync — local FAISS)
        2. Generate the personalised brief with Claude Haiku (async — non-blocking LLM call)
        3. Append the brief as an in-app notification to the state store
        """
        print(f"[OrgAgent] Building brief for {profile.full_name} / {profile.department}")

        # Targeted queries covering the four brief sections
        queries = [
            f"{profile.department} {profile.team} team charter mission responsibilities",
            f"{profile.job_title} {profile.seniority} role stakeholders key contacts",
            f"company OKRs strategy growth {profile.business_unit} {profile.division}",
            f"culture values ways of working communication norms rituals",
        ]

        # Collect and deduplicate retrieved chunks (sync — local CPU FAISS, no I/O)
        seen:       set[str]  = set()
        all_chunks: list[dict] = []
        for query in queries:
            for chunk in self.kb.retrieve(query, top_k=3):
                key = f"{chunk['source']}:{chunk['chunk_index']}"
                if key not in seen:
                    seen.add(key)
                    all_chunks.append(chunk)

        # Generate brief (async LLM or structured fallback)
        if self._client and all_chunks:
            brief = await self._generate_with_llm(profile, all_chunks)
        elif all_chunks:
            brief = self._template_brief(profile, all_chunks)
        else:
            brief = self._fallback_brief(profile)

        # Store as in-app notification (sync — fast in-memory + JSON write)
        self.store.append_to_state(
            joiner_id=profile.joiner_id,
            notifications=[f"🏢 **Your Team & Organisation Brief**\n\n{brief}"],
        )
        print(f"[OrgAgent] Brief stored for {profile.full_name}")

    # ── Private helpers ───────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _generate_with_llm(self, profile: JoinerProfile, chunks: list[dict]) -> str:
        """Call Claude Haiku with KB context to produce the personalised brief (async)."""
        context = "\n\n---\n\n".join(
            f"[Source: {c['source']}]\n{c['text']}" for c in chunks[:10]
        )
        user_msg = (
            f"New joiner details:\n"
            f"  Name: {profile.full_name}\n"
            f"  Role: {profile.job_title} ({profile.seniority})\n"
            f"  Department: {profile.department} · Team: {profile.team}\n"
            f"  Business Unit: {profile.business_unit} · Division: {profile.division}\n"
            f"  Manager: {profile.manager_name} <{profile.manager_email}>\n"
            f"  Buddy: {profile.buddy_name} <{profile.buddy_email}>\n\n"
            f"Knowledge base context:\n\n{context}\n\n"
            f"Write the personalised org & role brief for {profile.full_name}."
        )
        resp = await self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=700,
            system=_ORG_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()

    def _template_brief(self, profile: JoinerProfile, chunks: list[dict]) -> str:
        """Structured fallback when LLM is unavailable — surfaces top KB chunk."""
        top = chunks[0]["text"][:600]
        return (
            f"## Your Team — {profile.department}\n\n"
            f"**Role:** {profile.job_title} · **Manager:** {profile.manager_name} "
            f"({profile.manager_email})\n\n"
            f"From the knowledge base:\n\n{top}\n\n"
            f"Use **Ask Me Anything** to explore more about your team and role."
        )

    def _fallback_brief(self, profile: JoinerProfile) -> str:
        """Minimal brief when KB has no relevant content for this team/role."""
        return (
            f"## Welcome to {profile.department}, {profile.full_name}!\n\n"
            f"You're joining as **{profile.job_title}**.\n\n"
            f"Your manager **{profile.manager_name}** ({profile.manager_email}) "
            f"and buddy **{profile.buddy_name}** ({profile.buddy_email}) are your "
            f"primary sources of team context.\n\n"
            f"**To arrange your buddy intro call:** reach out to {profile.buddy_name} "
            f"directly at {profile.buddy_email}"
            + (f" or via their calendar link: {profile.buddy_calendar_link}"
               if profile.buddy_calendar_link else "")
            + ".\n\n"
            f"Use **Ask Me Anything** to query the knowledge base — any gaps you "
            f"find will be flagged for the admin team to fill in."
        )
