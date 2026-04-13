"""
core/knowledge_base.py — RAG Pipeline: Ingestion + Retrieval
=============================================================
Reads all knowledge documents, chunks them, embeds with Voyage AI,
stores in a FAISS flat index, and exposes a retrieve() method.

Architecture:
  1. ingest()   → reads docs → chunks → embeds → saves FAISS index to disk
  2. retrieve() → embeds query → cosine search → returns top-K chunks

Models:
  - Embedding: voyage-3-lite (free tier, fast, 1024-dim)
  - No LLM here — this module is purely retrieval.

The KB is pre-loaded once at app startup and shared by all agents.
"""

import os
import pickle
import re
import textwrap
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import voyageai
    VOYAGE_AVAILABLE = True
except ImportError:
    VOYAGE_AVAILABLE = False

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

from core.config import (
    VOYAGE_API_KEY, EMBEDDING_MODEL,
    CHUNK_SIZE, CHUNK_OVERLAP, TOP_K_RESULTS,
    KB_DOCS_PATH, FAISS_INDEX_PATH,
)


# ─────────────────────────────────────────────
# Text chunking
# ─────────────────────────────────────────────

def _chunk_text(text: str, source: str) -> list[dict]:
    """
    Split a document into overlapping chunks.
    Returns list of dicts: {text, source, chunk_index}
    Uses simple word-level windowing (avoids tokenizer dependency).
    """
    # Estimate tokens as words (close enough for chunking)
    words = text.split()
    chunks = []
    start = 0
    idx = 0

    while start < len(words):
        end = min(start + CHUNK_SIZE, len(words))
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words).strip()

        if len(chunk_text) > 50:   # Skip near-empty chunks
            chunks.append({
                "text": chunk_text,
                "source": source,
                "chunk_index": idx,
            })
            idx += 1

        start += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


# ─────────────────────────────────────────────
# KnowledgeBase class
# ─────────────────────────────────────────────

class KnowledgeBase:
    """
    Singleton-style KB — build once, query many times.

    Usage:
        kb = KnowledgeBase()
        kb.load_or_ingest()   # at startup
        results = kb.retrieve("how do I request IT access?")
    """

    def __init__(self):
        self.chunks: list[dict] = []      # Raw text chunks with metadata
        self.index = None                  # FAISS index (or None if unavailable)
        self.embeddings: Optional[np.ndarray] = None
        self._voyage_client = None
        self._ready = False

    # ── Voyage AI client (lazy init) ─────────

    def _get_voyage(self):
        if self._voyage_client is None and VOYAGE_AVAILABLE and VOYAGE_API_KEY:
            self._voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)
        return self._voyage_client

    # ── Embedding helper ─────────────────────

    def _embed(self, texts: list[str]) -> Optional[np.ndarray]:
        """Return float32 numpy array of shape (N, dim), or None on failure."""
        voyage = self._get_voyage()
        if voyage is None:
            return None
        try:
            result = voyage.embed(texts, model=EMBEDDING_MODEL, input_type="document")
            return np.array(result.embeddings, dtype=np.float32)
        except Exception as e:
            print(f"[KB] Embedding error: {e}")
            return None

    def _embed_query(self, query: str) -> Optional[np.ndarray]:
        voyage = self._get_voyage()
        if voyage is None:
            return None
        try:
            result = voyage.embed([query], model=EMBEDDING_MODEL, input_type="query")
            return np.array(result.embeddings, dtype=np.float32)
        except Exception as e:
            print(f"[KB] Query embedding error: {e}")
            return None

    # ── Document loading ──────────────────────

    def _load_documents(self) -> list[tuple[str, str]]:
        """
        Load all text documents from KB_DOCS_PATH.
        Returns list of (source_name, content) tuples.
        Falls back to bundled /mnt/project files if data dir is empty.
        """
        docs = []
        kb_path = Path(KB_DOCS_PATH)
        project_path = Path("/mnt/project")

        # Try data/kb_documents first
        if kb_path.exists():
            for fpath in sorted(kb_path.glob("**/*")):
                if fpath.suffix.lower() in {".txt", ".md", ".docx"} and fpath.is_file():
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                        docs.append((fpath.stem, content))
                    except Exception as e:
                        print(f"[KB] Could not read {fpath}: {e}")

        # Always include project files (our canonical KB)
        if project_path.exists():
            for fpath in sorted(project_path.glob("*.docx")):
                if fpath.stem == "OnboardingBuddy_System_Design":
                    continue   # Internal design doc — not for joiner KB
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    # Clean markdown-style bold markers
                    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
                    content = re.sub(r'\*(.+?)\*', r'\1', content)
                    docs.append((fpath.stem, content))
                except Exception as e:
                    print(f"[KB] Could not read {fpath}: {e}")

        print(f"[KB] Loaded {len(docs)} documents.")
        return docs

    # ── Ingestion ─────────────────────────────

    def ingest(self) -> None:
        """
        Full ingestion pipeline:
          1. Load all documents
          2. Chunk each document
          3. Embed all chunks (batched to avoid rate limits)
          4. Build FAISS index
          5. Save index + chunks to disk
        """
        print("[KB] Starting ingestion...")
        documents = self._load_documents()

        if not documents:
            print("[KB] No documents found. KB will be empty.")
            self._ready = True
            return

        # Chunk all documents
        all_chunks: list[dict] = []
        for source, content in documents:
            all_chunks.extend(_chunk_text(content, source))
        print(f"[KB] Created {len(all_chunks)} chunks from {len(documents)} documents.")

        self.chunks = all_chunks
        texts = [c["text"] for c in all_chunks]

        # Embed (in batches of 128 to respect API limits)
        if not VOYAGE_AVAILABLE or not VOYAGE_API_KEY:
            print("[KB] Voyage AI not available — KB will use keyword fallback.")
            self._ready = True
            self._save_index()
            return

        print("[KB] Embedding chunks (this may take a moment)...")
        batch_size = 128
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            emb = self._embed(batch)
            if emb is not None:
                all_embeddings.append(emb)
            else:
                print(f"[KB] Embedding failed for batch {i}–{i+batch_size}")

        if all_embeddings:
            self.embeddings = np.vstack(all_embeddings)
            print(f"[KB] Embeddings shape: {self.embeddings.shape}")

            if FAISS_AVAILABLE:
                dim = self.embeddings.shape[1]
                # Normalise for cosine similarity via inner product
                norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1, norms)
                normed = self.embeddings / norms
                self.index = faiss.IndexFlatIP(dim)
                self.index.add(normed)
                print(f"[KB] FAISS index built with {self.index.ntotal} vectors.")
        else:
            print("[KB] No embeddings produced — falling back to keyword search.")

        self._ready = True
        self._save_index()

    # ── Persistence ───────────────────────────

    def _save_index(self) -> None:
        idx_path = Path(FAISS_INDEX_PATH)
        idx_path.parent.mkdir(exist_ok=True)
        with open(idx_path, "wb") as f:
            pickle.dump({
                "chunks": self.chunks,
                "embeddings": self.embeddings,
            }, f)
        if FAISS_AVAILABLE and self.index is not None:
            faiss.write_index(self.index, str(idx_path) + ".faiss")
        print(f"[KB] Index saved to {idx_path}")

    def load(self) -> bool:
        """Load a previously built index from disk. Returns True on success."""
        idx_path = Path(FAISS_INDEX_PATH)
        if not idx_path.exists():
            return False
        try:
            with open(idx_path, "rb") as f:
                saved = pickle.load(f)
            self.chunks = saved["chunks"]
            self.embeddings = saved.get("embeddings")

            faiss_path = str(idx_path) + ".faiss"
            if FAISS_AVAILABLE and Path(faiss_path).exists():
                self.index = faiss.read_index(faiss_path)

            self._ready = True
            print(f"[KB] Loaded {len(self.chunks)} chunks from disk.")
            return True
        except Exception as e:
            print(f"[KB] Load failed: {e}")
            return False

    def load_or_ingest(self) -> None:
        """Load from disk if available; otherwise run full ingestion."""
        if not self.load():
            self.ingest()

    # ── Retrieval ─────────────────────────────

    def retrieve(self, query: str, top_k: int = TOP_K_RESULTS) -> list[dict]:
        """
        Find the most relevant KB chunks for a query.
        Returns list of {text, source, score} dicts.
        Falls back to keyword matching if embeddings are unavailable.
        """
        if not self._ready or not self.chunks:
            return []

        # ── Semantic search (preferred) ───────
        if self.index is not None and FAISS_AVAILABLE:
            q_emb = self._embed_query(query)
            if q_emb is not None:
                norm = np.linalg.norm(q_emb)
                if norm > 0:
                    q_emb = q_emb / norm
                scores, indices = self.index.search(q_emb, min(top_k, len(self.chunks)))
                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx >= 0:
                        chunk = self.chunks[idx].copy()
                        chunk["score"] = float(score)
                        results.append(chunk)
                return results

        # ── Keyword fallback ──────────────────
        return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """Simple TF-style keyword overlap scoring — no external dependencies."""
        query_words = set(query.lower().split())
        scored = []
        for chunk in self.chunks:
            chunk_words = set(chunk["text"].lower().split())
            overlap = len(query_words & chunk_words)
            if overlap > 0:
                scored.append((overlap, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            c = chunk.copy()
            c["score"] = score
            results.append(c)
        return results
