"""
app.py — OnboardingBuddy Main Launcher
=======================================
Entry point for the entire application. Wires together:
  1. Knowledge base  → loads or ingests on startup (Google Drive / local docs)
  2. State store     → JSON persistence for all joiner records
  3. Orchestrator    → wires all 8 agents
  4. Admin Gradio UI → manager portal (Add Joiner, Dashboard, Gaps, Reports)
  5. Joiner Gradio UI→ new joiner experience (Journey, Chat, Training, Access, Feedback)
  6. APScheduler     → background progress checks every 6 hours

Both UIs are merged into one gr.TabbedInterface so a single Hugging Face
Space URL serves both the admin portal and the new joiner app.

Local:  python app.py
Deploy: push to huggingface.co/spaces/yania-n/OnboardingBuddy (see README_HF.md)
"""

import sys
from pathlib import Path

# ── Ensure project root is on sys.path (required in HF Spaces) ──────────────
sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr

# ── Monkey-patch for Gradio 4.44.x + Python 3.13 compatibility ───────────────
# Bug: gradio_client.utils._json_schema_to_python_type() raises
#   APIInfoParseError: Cannot parse schema True
# when a Pydantic model emits additionalProperties: true (a bool, not a dict)
# in its JSON Schema.  This is valid JSON Schema but Gradio 4.44 doesn't handle
# it — the function assumes every schema it receives is a dict and passes the
# bool straight through until it hits the final `raise`.
#
# Fix: wrap _json_schema_to_python_type so any non-dict schema short-circuits
# to "any" before the function body runs.  Minimal, surgical, no side effects.
import gradio_client.utils as _gc_utils

_orig_j2p = _gc_utils._json_schema_to_python_type

def _safe_j2p(schema, defs=None):
    if not isinstance(schema, dict):
        return "any"
    return _orig_j2p(schema, defs)

_gc_utils._json_schema_to_python_type = _safe_j2p
# ─────────────────────────────────────────────────────────────────────────────

from apscheduler.schedulers.background import BackgroundScheduler

from core.config import (
    ANTHROPIC_API_KEY,
    VOYAGE_API_KEY,
    NUDGE_POLL_INTERVAL_SECONDS,
    APP_TITLE,
    COLOR_PRIMARY,
    COLOR_PRIMARY_DARK,
    GLOBAL_CSS_VARS,
)
from core.knowledge_base import KnowledgeBase
from core.state_store import StateStore
from agents.orchestrator import Orchestrator
from ui.admin_app import build_admin_app
from ui.joiner_app import build_joiner_app


# ─────────────────────────────────────────────
# Combined CSS for the top-level TabbedInterface
# ─────────────────────────────────────────────

TOP_LEVEL_CSS = GLOBAL_CSS_VARS + f"""
/* Outer tab bar — grass green accent */
.tab-nav button {{
    font-weight: 600;
    font-size: 0.95rem;
    padding: 10px 22px;
    color: var(--ob-text-muted);
    border: none;
    background: transparent;
    transition: color 0.2s;
}}
.tab-nav button.selected {{
    color: var(--ob-primary-darker);
    border-bottom: 3px solid var(--ob-primary);
    background: transparent;
}}
.tab-nav button:hover {{ color: var(--ob-primary); }}

body, .gradio-container {{ background: var(--ob-surface) !important; }}
"""


# ─────────────────────────────────────────────
# Startup checks
# ─────────────────────────────────────────────

def _check_env() -> list[str]:
    """
    Check for required API keys and warn (not crash) if any are missing.
    The app still starts in degraded mode so it can be tested without keys.
    """
    warnings = []
    if not ANTHROPIC_API_KEY:
        warnings.append(
            "ANTHROPIC_API_KEY not set — all LLM features disabled. "
            "Agents will fall back to templates."
        )
    if not VOYAGE_API_KEY:
        warnings.append(
            "VOYAGE_API_KEY not set — semantic search disabled. "
            "KB Q&A will use keyword fallback."
        )
    return warnings


# ─────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────

def _start_scheduler(orchestrator: Orchestrator) -> BackgroundScheduler:
    """
    Launch APScheduler in the background. Runs orchestrator.run_progress_check()
    every 6 hours to detect overdue phases and send in-app nudges.
    The daemon=True flag ensures it shuts down cleanly with the main process.
    """
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=orchestrator.run_progress_check,
        trigger="interval",
        seconds=NUDGE_POLL_INTERVAL_SECONDS,
        id="progress_check",
        replace_existing=True,
        misfire_grace_time=60,   # tolerate up to 60-second scheduler jitter
    )
    scheduler.start()
    hours = NUDGE_POLL_INTERVAL_SECONDS // 3600
    print(f"[App] ✅ Background scheduler started — nudge checks every {hours}h.")
    return scheduler


# ─────────────────────────────────────────────
# App builder
# ─────────────────────────────────────────────

def build_app() -> gr.Blocks:
    """
    Initialise all shared infrastructure, build both Gradio apps, and
    return a combined TabbedInterface ready for .launch().

    Shared objects (kb, store, orchestrator) are created once and injected
    into both UIs — no singletons, no global state outside this function.
    """
    print("=" * 60)
    print(f"  {APP_TITLE} — Starting Up")
    print("=" * 60)

    # 1. Warn on missing keys (never crash — graceful degradation)
    for w in _check_env():
        print(f"  ⚠️  {w}")

    # 2. Knowledge base — sync from Google Drive then build FAISS index
    print("[App] Initialising knowledge base...")
    kb = KnowledgeBase()
    kb.load_or_ingest()   # idempotent: skips re-indexing if index already exists

    # 3. State store — reads existing joiner records from data/state/
    store = StateStore()
    existing = len(store.list_profiles())
    print(f"[App] State store loaded — {existing} existing joiner record(s).")

    # 4. Orchestrator — wires all 8 agents around the shared store and KB
    orchestrator = Orchestrator(store=store, kb=kb)

    # 5. Background scheduler — progress nudges every 6 hours
    _start_scheduler(orchestrator)

    # 6. Build each Gradio Blocks app (CSS + event logic defined inside)
    print("[App] Building Admin Portal UI...")
    admin_ui  = build_admin_app(orchestrator=orchestrator, store=store)

    print("[App] Building Joiner Journey UI...")
    joiner_ui = build_joiner_app(orchestrator=orchestrator, store=store)

    # 7. Merge into a single tabbed root UI
    combined = gr.TabbedInterface(
        interface_list=[admin_ui, joiner_ui],
        tab_names=["🧭 Admin Portal", "🌱 My Onboarding Journey"],
        title=f"{APP_TITLE}",
        css=TOP_LEVEL_CSS,
    )

    print(f"[App] ✅ {APP_TITLE} is ready — visit http://0.0.0.0:7860")
    print("=" * 60)
    return combined


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

# HF Spaces runs this file directly with `python app.py`.
# We call launch() at module level (not inside __main__) so HF Spaces
# can also import and mount the app object if needed.
app = build_app()
app.launch(
    server_name="0.0.0.0",  # bind to all interfaces — required for HF Spaces
    server_port=7860,        # HF Spaces default port
    share=False,            # HF Spaces handles the public URL — no tunnel needed
    show_error=True,
)
 