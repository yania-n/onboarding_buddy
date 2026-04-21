"""
core/knowledge_base.py — RAG Pipeline: Ingestion + Retrieval
=============================================================
Reads all knowledge documents, chunks them, embeds with Voyage AI,
stores in a FAISS flat cosine-similarity index, and exposes retrieve().

Two document sources (in priority order):
  1. Google Drive folder — synced on startup if GOOGLE_API_KEY is set.
     Supports: Google Docs (exported as plain text), .txt, .pdf files.
  2. Local data/kb_documents/ — always available as fallback / seed content.

Architecture:
  ingest()   → read docs → chunk → embed → save FAISS index to disk
  retrieve() → embed query → cosine search → return top-K chunks

Models:
  Embedding: voyage-3-lite (1024-dim, free tier, fast)
  No LLM here — this module is purely retrieval.

The KB is loaded once at startup and shared by all agents via the Orchestrator.
Thread-safe for reads; ingest() is called once only.
"""

import os
import pickle
import re
from pathlib import Path
from typing import Optional

import numpy as np
import requests

from core.config import (
    VOYAGE_API_KEY,
    GOOGLE_API_KEY,
    GOOGLE_DRIVE_FOLDER_ID,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K_RESULTS,
    KB_DOCS_PATH,
    FAISS_INDEX_PATH,
)

# ── Optional dependency guards ────────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# Text cleaning & chunking helpers
# ─────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """
    Strip repeated whitespace and very short lines (page numbers, headers).
    Preserves paragraph structure.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= 4:
            cleaned.append(stripped)
    return "\n".join(cleaned)


def _chunk_text(text: str, source: str) -> list[dict]:
    """
    Split a document into overlapping word-level chunks.

    Each chunk is a dict:
        { text: str, source: str, chunk_index: int }

    Uses simple word-level windowing — no tokenizer dependency.
    CHUNK_SIZE and CHUNK_OVERLAP are defined in config.
    """
    text = _clean_text(text)
    words = text.split()
    chunks: list[dict] = []
    start = 0
    idx = 0

    while start < len(words):
        end = min(start + CHUNK_SIZE, len(words))
        chunk_text = " ".join(words[start:end]).strip()

        # Skip near-empty chunks
        if len(chunk_text) > 60:
            chunks.append({
                "text":        chunk_text,
                "source":      source,
                "chunk_index": idx,
            })
            idx += 1

        if end == len(words):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


# ─────────────────────────────────────────────
# Google Drive sync helpers
# ─────────────────────────────────────────────

def _extract_pdf_text(pdf_bytes: bytes, filename: str) -> Optional[str]:
    """Extract plain text from a PDF byte stream using pdfplumber."""
    try:
        import io
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return "\n\n".join(parts) if parts else None
    except Exception as e:
        print(f"[KB] PDF extraction failed for {filename}: {e}")
        return None


def _sync_from_google_drive(folder_id: str, api_key: str, dest_dir: Path) -> int:
    """
    List and download all supported files from a public Google Drive folder.

    Supported MIME types:
      - application/vnd.google-apps.document → exported as plain text
      - text/plain                            → downloaded directly
      - application/pdf                       → text extracted via pdfplumber

    Files already present in dest_dir are skipped (idempotent).
    Returns the number of new files downloaded.

    Requires a free Google API key with the Drive API enabled.
    Setup: https://console.cloud.google.com → APIs → Drive API → Credentials
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    # Step 1: List files in the folder
    try:
        list_resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q":        f"'{folder_id}' in parents and trashed=false",
                "key":      api_key,
                "fields":   "files(id,name,mimeType)",
                "pageSize": 200,
            },
            timeout=20,
        )
        list_resp.raise_for_status()
    except Exception as e:
        print(f"[KB] Google Drive listing failed: {e}")
        return 0

    files = list_resp.json().get("files", [])
    print(f"[KB] Drive folder contains {len(files)} file(s).")

    # Step 2: Download each supported file
    for f in files:
        # Sanitise filename so it's safe to write on any OS
        fname = re.sub(r'[\\/*?:"<>|]', "_", f["name"])
        fid   = f["id"]
        mime  = f["mimeType"]

        dest_file = dest_dir / f"{fname}.txt"
        if dest_file.exists():
            continue  # Already synced

        try:
            if mime == "application/vnd.google-apps.document":
                # Export Google Doc as plain text
                resp = requests.get(
                    f"https://www.googleapis.com/drive/v3/files/{fid}/export",
                    params={"mimeType": "text/plain", "key": api_key},
                    timeout=30,
                )
                if resp.status_code == 200:
                    dest_file.write_text(resp.text, encoding="utf-8")
                    downloaded += 1
                    print(f"[KB]   Downloaded (Doc): {fname}")

            elif mime == "text/plain":
                resp = requests.get(
                    f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media",
                    params={"key": api_key},
                    timeout=30,
                )
                if resp.status_code == 200:
                    dest_file.write_text(resp.text, encoding="utf-8")
                    downloaded += 1
                    print(f"[KB]   Downloaded (txt): {fname}")

            elif mime == "application/pdf":
                resp = requests.get(
                    f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media",
                    params={"key": api_key},
                    timeout=60,
                )
                if resp.status_code == 200:
                    text = _extract_pdf_text(resp.content, fname)
                    if text:
                        dest_file.write_text(text, encoding="utf-8")
                        downloaded += 1
                        print(f"[KB]   Downloaded (PDF): {fname}")
            # Other types (images, spreadsheets) are skipped

        except Exception as e:
            print(f"[KB]   Failed to download '{fname}': {e}")

    return downloaded


# ─────────────────────────────────────────────
# KnowledgeBase class
# ─────────────────────────────────────────────

class KnowledgeBase:
    """
    Shared RAG knowledge base — loaded once at startup, injected into all agents.

    Internally holds:
      _chunks  : list of { text, source, chunk_index } dicts
      _index   : FAISS IndexFlatIP (cosine after L2 normalisation)
      _vectors : np.ndarray (N, 1024) — kept for future re-ranking

    If Voyage AI / FAISS are unavailable, falls back to keyword overlap search.
    """

    def __init__(self):
        self._chunks:  list[dict]           = []
        self._index:   Optional[object]     = None  # faiss.Index
        self._vectors: Optional[np.ndarray] = None
        self._voyage:  Optional[object]     = None  # voyageai.Client

        if VOYAGE_AVAILABLE and VOYAGE_API_KEY:
            self._voyage = voyageai.Client(api_key=VOYAGE_API_KEY)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_or_ingest(self) -> None:
        """
        Entry point called once at app startup.

        1. Sync new docs from Google Drive (if GOOGLE_API_KEY is set)
        2. Try to load cached FAISS index from disk
        3. If no cache → ingest from local documents and build index
        """
        docs_path = Path(KB_DOCS_PATH)
        docs_path.mkdir(parents=True, exist_ok=True)

        # 1. Google Drive sync (optional)
        if GOOGLE_API_KEY and GOOGLE_DRIVE_FOLDER_ID:
            print(f"[KB] Syncing from Google Drive: {GOOGLE_DRIVE_FOLDER_ID}")
            n = _sync_from_google_drive(GOOGLE_DRIVE_FOLDER_ID, GOOGLE_API_KEY, docs_path)
            print(f"[KB] Drive sync: {n} new file(s) added.")
        else:
            print("[KB] No GOOGLE_API_KEY set — using local kb_documents only.")

        # 2. Try loading cached index
        index_path = Path(FAISS_INDEX_PATH)
        if index_path.exists():
            try:
                self._load_index(index_path)
                print(f"[KB] Loaded cached index — {len(self._chunks)} chunks ready.")
                return
            except Exception as e:
                print(f"[KB] Cache load failed ({e}) — rebuilding index.")

        # 3. Ingest and build fresh index
        self._ingest(docs_path)
        self._save_index(index_path)
        print(f"[KB] Ready — {len(self._chunks)} chunks indexed.")

    def retrieve(self, query: str, top_k: int = TOP_K_RESULTS) -> list[dict]:
        """
        Return the top_k most relevant chunks for the given query string.

        Result dicts include: { text, source, chunk_index, score }

        Falls back to keyword search when Voyage / FAISS are unavailable.
        """
        if not self._chunks:
            return []
        if self._index is not None and self._voyage is not None:
            return self._semantic_search(query, top_k)
        return self._keyword_search(query, top_k)

    def chunk_count(self) -> int:
        """Return total indexed chunks — used in health/status displays."""
        return len(self._chunks)

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def _ingest(self, docs_path: Path) -> None:
        """
        Read all .txt and .md files from docs_path, chunk them, and
        optionally build a FAISS vector index.
        """
        all_chunks: list[dict] = []
        txt_files = sorted(
            list(docs_path.glob("*.txt")) + list(docs_path.glob("*.md"))
        )

        if not txt_files:
            print("[KB] Warning: no documents found in kb_documents/ — KB will be empty.")
            return

        for fpath in txt_files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").strip()
                if not text:
                    continue
                source = fpath.stem  # filename without extension as source label
                chunks = _chunk_text(text, source)
                all_chunks.extend(chunks)
                print(f"[KB]   {source}: {len(chunks)} chunk(s)")
            except Exception as e:
                print(f"[KB]   Skipped {fpath.name}: {e}")

        self._chunks = all_chunks
        print(f"[KB] Total chunks to embed: {len(all_chunks)}")

        if VOYAGE_AVAILABLE and FAISS_AVAILABLE and self._voyage and all_chunks:
            self._build_faiss_index(all_chunks)
        else:
            print("[KB] Voyage/FAISS unavailable — will use keyword search fallback.")

    def _build_faiss_index(self, chunks: list[dict]) -> None:
        """
        Embed all chunks via Voyage AI and build a FAISS IndexFlatIP.
        Batches of 128 are used to stay within API rate limits.
        Vectors are L2-normalised so inner-product = cosine similarity.

        Robustness rules:
          - The embedding dimension is detected from the first successful batch.
          - Failed batches use zero-vectors of the SAME detected dimension
            (not a hardcoded 1024 which differs from voyage-3-lite's 512-dim output).
          - If no batch succeeds at all, the index is not built and keyword search
            is used as fallback.
        """
        texts = [c["text"] for c in chunks]
        BATCH = 128
        all_vecs   = []
        embed_dim  = None   # determined from the first successful batch
        total_batches = (len(texts) - 1) // BATCH + 1

        for i in range(0, len(texts), BATCH):
            batch      = texts[i : i + BATCH]
            batch_num  = i // BATCH + 1
            try:
                result = self._voyage.embed(batch, model=EMBEDDING_MODEL, input_type="document")
                vecs   = result.embeddings            # list of lists
                if vecs and embed_dim is None:
                    embed_dim = len(vecs[0])          # detect dim from first real result
                all_vecs.extend(vecs)
                print(f"[KB]   Embedded batch {batch_num}/{total_batches} (dim={embed_dim})")
            except Exception as e:
                print(f"[KB]   Embedding batch {batch_num} failed: {e}")
                if embed_dim is not None:
                    # Use detected dimension for zero-vector placeholder
                    all_vecs.extend([[0.0] * embed_dim] * len(batch))
                else:
                    # Dimension still unknown — defer; will be filled after loop
                    all_vecs.extend([None] * len(batch))

        if embed_dim is None:
            print("[KB] No successful embedding batch — skipping FAISS build; using keyword search.")
            return

        # Replace any None placeholders (batches that failed before dim was known)
        all_vecs = [v if v is not None else [0.0] * embed_dim for v in all_vecs]

        vectors = np.array(all_vecs, dtype="float32")

        # L2-normalise for cosine similarity via inner product
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vectors /= norms

        dim   = vectors.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)

        self._index   = index
        self._vectors = vectors
        print(f"[KB] FAISS index built: {index.ntotal} vectors, dim={dim}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_index(self, path: Path) -> None:
        """Pickle chunks + vectors to disk; save FAISS index in native format."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"chunks": self._chunks, "vectors": self._vectors}, f)
        if self._index is not None and FAISS_AVAILABLE:
            faiss.write_index(self._index, str(path) + ".faiss")

    def _load_index(self, path: Path) -> None:
        """Load chunks, vectors, and FAISS index from disk."""
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._chunks  = data["chunks"]
        self._vectors = data.get("vectors")

        faiss_path = str(path) + ".faiss"
        if FAISS_AVAILABLE and os.path.exists(faiss_path):
            self._index = faiss.read_index(faiss_path)

    # ── Search ────────────────────────────────────────────────────────────────

    def _semantic_search(self, query: str, top_k: int) -> list[dict]:
        """Embed the query and search FAISS for the nearest chunk vectors."""
        try:
            result = self._voyage.embed([query], model=EMBEDDING_MODEL, input_type="query")
            qvec   = np.array(result.embeddings, dtype="float32")
            norm   = np.linalg.norm(qvec)
            if norm > 0:
                qvec /= norm

            scores, indices = self._index.search(qvec, min(top_k, len(self._chunks)))
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                chunk = dict(self._chunks[idx])
                chunk["score"] = float(score)
                results.append(chunk)
            return results

        except Exception as e:
            print(f"[KB] Semantic search error: {e} — using keyword fallback.")
            return self._keyword_search(query, top_k)

    # Common English stop words — excluded from keyword matching so they
    # don't inflate scores for irrelevant chunks.
    _STOP_WORDS: set = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "its", "this", "that", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may", "might", "can", "not",
        "no", "so", "if", "as", "up", "out", "how", "what", "when", "where",
        "who", "which", "about", "into", "than", "then", "them", "they", "their",
        "your", "our", "we", "you", "i", "me", "he", "she", "his", "her", "my",
        "any", "all", "also", "more", "new", "some", "there", "these", "those",
        "get", "got", "use", "used", "see", "know", "need", "go", "make", "just",
    }

    @staticmethod
    def _normalise_query(text: str) -> set[str]:
        """
        Normalise a query string into a set of meaningful keywords.

        Steps:
          1. Lower-case
          2. Strip possessives ("nexora's" → "nexora", "company's" → "company")
          3. Remove remaining punctuation
          4. Split into words
          5. Remove stop words and very short tokens (len < 3)
        """
        # Step 2: strip possessives before removing punctuation
        text = re.sub(r"'s\b", "", text.lower())
        # Step 3: strip remaining punctuation
        text = re.sub(r"[^\w\s]", " ", text)
        words = text.split()
        return {
            w for w in words
            if len(w) >= 3 and w not in KnowledgeBase._STOP_WORDS
        }

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """
        Improved keyword search — stop-word-free, possessive-normalised.

        Scoring:
          - Primary : fraction of meaningful query words found in the chunk
          - Tie-break: source name bonus when a query word appears in the filename

        This produces far better results than naive word overlap when semantic
        search (Voyage) is unavailable.
        """
        query_words = self._normalise_query(query)
        if not query_words:
            # Fallback: if all words were stop words, use raw split (avoids empty result)
            query_words = set(re.sub(r"[^\w\s]", "", query.lower()).split()) - {""}

        if not query_words:
            return []

        scored = []
        for chunk in self._chunks:
            # Normalise chunk text the same way
            chunk_text_lower = re.sub(r"'s\b", "", chunk["text"].lower())
            chunk_words = set(re.sub(r"[^\w\s]", " ", chunk_text_lower).split())

            overlap = len(query_words & chunk_words) / max(len(query_words), 1)
            if overlap == 0:
                continue

            # Small bonus when query words appear in the source document name
            source_words = set(re.sub(r"[_\-]", " ", chunk["source"].lower()).split())
            source_bonus = 0.1 * len(query_words & source_words) / max(len(query_words), 1)

            scored.append((overlap + source_bonus, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            c = dict(chunk)
            c["score"] = score
            results.append(c)
        return results
