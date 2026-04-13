"""
agents/qa_agent.py — Knowledge Base Q&A Chatbot Agent
======================================================
Answers joiner questions strictly from the knowledge base.
Never speculates, never answers outside the KB.

Model routing:
  - KB retrieval: no LLM (pure vector search)
  - Answer generation: Claude Haiku (fast, cheap — most questions are factual)
  - If answer is complex or multi-document: stays with Haiku (KB-grounded answers
    don't need Sonnet's reasoning depth)

On failure: returns "I don't have that yet" and logs the question as a KB gap.
"""

import anthropic

from core.config import ANTHROPIC_API_KEY, MODEL_FAST, TOP_K_RESULTS
from core.state_store import StateStore
from core.knowledge_base import KnowledgeBase


# System prompt for the QA chatbot
_QA_SYSTEM_PROMPT = """You are OnboardingBuddy's Q&A assistant for Nexora Global Corporation.
Your ONLY source of truth is the context provided below from the company knowledge base.
Rules you must follow:
1. Answer ONLY from the provided context — never use external knowledge.
2. If the context does not contain the answer, reply exactly: "I don't have that information in the knowledge base yet."
3. Always cite the source document name (e.g. "According to the Employee Handbook...").
4. Be concise and friendly. Format answers clearly — use bullet points for lists.
5. Never make up policies, names, dates, or procedures.
"""


class QAAgent:
    """
    KB-grounded question answering.
    Called by the orchestrator on every joiner chat message.
    """

    def __init__(self, store: StateStore, kb: KnowledgeBase):
        self.store = store
        self.kb = kb
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

    def answer(self, joiner_id: str, question: str) -> str:
        """
        Retrieve relevant KB chunks, then generate a grounded answer with Haiku.
        Logs unanswered questions as knowledge gaps.
        """
        # 1. Retrieve relevant chunks
        chunks = self.kb.retrieve(question, top_k=TOP_K_RESULTS)

        if not chunks:
            self._log_gap(joiner_id, question)
            return (
                "I don't have that information in the knowledge base yet. "
                "I've flagged this question so the team can add it — "
                "check back soon or ask your buddy or manager directly."
            )

        # 2. Build context string
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[Source: {chunk['source']}]\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)

        # 3. Generate answer via Haiku
        if self._client is None:
            return self._keyword_fallback(question, chunks)

        try:
            user_message = (
                f"Context from the Nexora knowledge base:\n\n{context}\n\n"
                f"Question: {question}"
            )
            response = self._client.messages.create(
                model=MODEL_FAST,
                max_tokens=512,
                system=_QA_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            answer = response.content[0].text.strip()

            # Log as gap if the model signals it couldn't answer
            if "don't have that information" in answer.lower():
                self._log_gap(joiner_id, question)

            return answer

        except Exception as e:
            print(f"[QAAgent] LLM error: {e}")
            return self._keyword_fallback(question, chunks)

    def _keyword_fallback(self, question: str, chunks: list[dict]) -> str:
        """Return the best-matching chunk text directly when LLM is unavailable."""
        if not chunks:
            return "I couldn't find relevant information right now. Please try again later."
        best = chunks[0]
        return (
            f"Here's what I found in '{best['source']}':\n\n"
            f"{best['text'][:600]}\n\n"
            f"_(Full answer generation is temporarily unavailable — showing raw KB content.)_"
        )

    def _log_gap(self, joiner_id: str, question: str) -> None:
        """Record an unanswered question as a knowledge gap for admin review."""
        try:
            self.store.log_knowledge_gap(joiner_id=joiner_id, question=question)
        except Exception as e:
            print(f"[QAAgent] Gap logging error: {e}")
