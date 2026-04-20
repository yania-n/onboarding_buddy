"""
app.py -- OnboardingBuddy Main Launcher
=======================================
Entry point for the entire application. Wires together:
  1. Knowledge base  -> loads or ingests on startup (Google Drive / local docs)
  2. State store     -> JSON persistence for all joiner records
  3. Orchestrator    -> wires all 8 agents
  4. Admin Gradio UI -> manager portal (Add Joiner, Dashboard, Gaps, Reports)
  5. Joiner Gradio UI-> new joiner experience (Journey, Chat, Training, Access, Feedback)
  6. APScheduler     -> background progress checks every 6 hours

Both UIs are merged into one gr.TabbedInterface so a single Hugging Face
Space URL serves both the admin portal and the new joiner app.

Local:  python app.py
Deploy: push to huggingface.co/spaces/yania-n/OnboardingBuddy (see README_HF.md)
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path (required in HF Spaces)
sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from core.config import (
    ANTHROPIC_API_KEY,
    VOYAGE_API_KEY,
    NUDGE_POLL_INTERVAL_SECONDS,
    APP_TITLE,
    GLOBAL_CSS_VARS,
)
from core.knowledge_base import KnowledgeBase
from core.state_store import StateStore
from agents.orchestrator import Orchestrator
from ui.admin_app import build_admin_app
from ui.joiner_app import build_joiner_app


# Startup checks

def _check_env():
    warnings = []
    if not ANTHROPIC_API_KEY:
        warnings.append(
            "ANTHROPIC_API_KEY not set -- all LLM features disabled. "
            "Agents will fall back to templates."
        )
    if not VOYAGE_API_KEY:
        warnings.append(
            "VOYAGE_API_KEY not set -- semantic search disabled. "
            "KB Q&A will use keyword fallback."
        )
    return warnings


# Scheduler

def _start_scheduler(orchestrator):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=orchestrator.run_progress_check,
        trigger="interval",
        seconds=NUDGE_POLL_INTERVAL_SECONDS,
        id="progress_check",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    hours = NUDGE_POLL_INTERVAL_SECONDS // 3600
    print("[App] Background scheduler started -- nudge checks every {}h.".format(hours))
    return scheduler


# App builder

def build_app():
    print("=" * 60)
    print("  {} -- Starting Up".format(APP_TITLE))
    print("=" * 60)

    for w in _check_env():
        print("  WARNING: {}".format(w))

    print("[App] Initialising knowledge base...")
    kb = KnowledgeBase()
    kb.load_or_ingest()

    store = StateStore()
    existing = len(store.list_profiles())
    print("[App] State store loaded -- {} existing joiner record(s).".format(existing))

    orchestrator = Orchestrator(store=store, kb=kb)
    _start_scheduler(orchestrator)

    print("[App] Building Admin Portal UI...")
    admin_ui = build_admin_app(orchestrator=orchestrator, store=store)

    print("[App] Building Joiner Journey UI...")
    joiner_ui = build_joiner_app(orchestrator=orchestrator, store=store)

    # Gradio 6.x: css removed from TabbedInterface — each sub-Blocks
    # already carries its own CSS (ADMIN_CSS / JOINER_CSS include GLOBAL_CSS_VARS)
    combined = gr.TabbedInterface(
        interface_list=[admin_ui, joiner_ui],
        tab_names=["Admin Portal", "My Onboarding Journey"],
        title=APP_TITLE,
    )

    print("[App] {} is ready -- visit http://0.0.0.0:7860".format(APP_TITLE))
    print("=" * 60)
    return combined


# Entry point
app = build_app()
app.launch(
    server_name="0.0.0.0",
    server_port=7860,
    share=False,
    show_error=True,
)
