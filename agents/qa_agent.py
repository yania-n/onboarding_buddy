"""
agents/qa_agent.py — "Ask Me Anything" KB-Grounded Chatbot Agent
================================================================
Answers every joiner question strictly from the knowledge base.
Never speculates. Never uses information outside the KB.

Rules (from system design):
  - Answers ONLY from KB content — no external knowledge, no speculation
  - If no KB match: returns 'I don't have that information yet' and logs a gap
  - Knowledge gap log is reviewed by admin to create missing documentation
  - Responses cite the source document so the joiner can read further

Model routing:
  - KB retrieval : Voyage embedding + FAISS (no LLM)
  - Answer gen   : Claude Haiku (fast, cheap — most KB answers are factual)
"""

import asyncio

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import ANTHROPIC_API_KEY, MODEL_FAST, TOP_K_RESULTS
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_QA_SYSTEM = """You are OnboardingBuddy's Q&A assistant.
Your ONLY source of truth is the context provided below from the company knowledge base.

Rules you must follow without exception:
1. Answer ONLY from the provided context — never use external knowledge or assumptions.
2. If the context does not contain a clear answer, reply EXACTLY with:
   "I don't have that information in the knowledge base yet. I've flagged your question so the team can add it — please ask your buddy or manager directly in the meantime."
3. Always cite the source document at the end of your answer, e.g. "Source: NexoraGlobal_EmployeeHandbook"
4. Be concise and friendly. Use bullet points for lists. Keep answers under 250 words unless the question genuinely requires more.
5. Never make up policies, names, dates, links, or procedures.
6. Warm, encouraging tone — remember this person is new and finding their feet."""


class QAAgent:
    """
    KB-grounded Q&A chatbot.
    Called by the Orchestrator for every joiner chat message.
    Logs unanswered questions as knowledge gaps for admin review.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store = store
        self.kb    = kb
        self._client = (
            anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            if ANTHROPIC_API_KEY else None
        )

    async def answer(self, joiner_id: str, question: str) -> str:
        """
        Main entry point.
        1. Retrieve relevant KB chunks via semantic search
        2. Generate a grounded answer with Claude Haiku
        3. Log as knowledge gap if the model cannot answer

        Returns the answer string to display in the joiner chat UI.
        """
        # Step 1: KB retrieval — no LLM, pure vector search
        chunks = self.kb.retrieve(question, top_k=TOP_K_RESULTS)

        if not chunks:
            # No relevant content found at all → log gap immediately
            self._log_gap(joiner_id, question)
            # DEBUG: surface KB state so we can diagnose HF deployment issues.
            # Remove this line once the chatbot is confirmed working.
            _kb_chunks = len(self.kb._chunks)
            _kb_mode   = "semantic" if self.kb._index is not None else "keyword"
            return (
                f"⚠️ _Debug: KB has {_kb_chunks} chunks · search mode: {_kb_mode}_\n\n"
                "I don't have that information in the knowledge base yet. "
                "I've flagged your question so the team can add it — "
                "please ask your buddy or manager directly in the meantime."
            )

        # Step 2: Build context string from retrieved chunks
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(f"[Source: {chunk['source']}]\n{chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)

        # Step 3: LLM answer generation
        if self._client is None:
            # No API key — return the best matching chunk directly
            return self._direct_chunk_response(chunks)

        try:
            answer = await self._call_llm(context, question)

            # If model signals it couldn't answer from the KB, log a gap
            if "don't have that information" in answer.lower():
                self._log_gap(joiner_id, question)

            return answer

        except Exception as e:
            print(f"[QAAgent] LLM call failed: {e}")
            return self._direct_chunk_response(chunks)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _call_llm(self, context: str, question: str) -> str:
        """Call Claude Haiku with KB context and the joiner's question (async). Retries on failure."""
        user_msg = (
            f"Context from the knowledge base:\n\n{context}\n\n"
            f"Joiner's question: {question}"
        )
        response = await self._client.messages.create(
            model=MODEL_FAST,
            max_tokens=600,
            system=_QA_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text.strip()

    def _direct_chunk_response(self, chunks: list[dict]) -> str:
        """
        Fallback when LLM is unavailable.
        Returns the top retrieved chunk directly with a note.
        """
        best = chunks[0]
        return (
            f"Here's what I found in '{best['source']}':\n\n"
            f"{best['text'][:700]}\n\n"
            f"_(Full AI-generated answer temporarily unavailable — showing raw KB content.)_"
        )

    def _log_gap(self, joiner_id: str, question: str) -> None:
        """Record an unanswered question as a knowledge gap for admin review."""
        try:
            self.store.log_knowledge_gap(joiner_id=joiner_id, question=question)
        except Exception as e:
            print(f"[QAAgent] Gap logging error: {e}")
