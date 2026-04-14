"""
app.py — OnboardingBuddy Main Launcher
=======================================
Entry point for the application. Wires together:
  1. Knowledge base (load or ingest on startup)
  2. State store (JSON persistence)
  3. Orchestrator + all agents
  4. Admin Gradio app
  5. Joiner Gradio app
  6. APScheduler for periodic progress checks

Both apps are merged into a single Gradio server using gr.TabbedInterface
so one Hugging Face Space link serves both admin and joiner views.

Production deployment: Hugging Face Spaces (app.py at root, requirements.txt adjacent).
Local development: python app.py
"""

import os
import sys
import threading
from pathlib import Path

# ── Ensure the project root is on sys.path ──
sys.path.insert(0, str(Path(__file__).parent))

import gradio as gr
from apscheduler.schedulers.background import BackgroundScheduler

from core.config import (
    ANTHROPIC_API_KEY, VOYAGE_API_KEY,
    NUDGE_POLL_INTERVAL_SECONDS, APP_TITLE,
)
from core.knowledge_base import KnowledgeBase
from core.state_store import StateStore
from agents.orchestrator import Orchestrator
from ui.admin_app import build_admin_app, ADMIN_CSS
from ui.joiner_app import build_joiner_app, JOINER_CSS


# ─────────────────────────────────────────────
# Startup validation
# ─────────────────────────────────────────────

def _check_env() -> list[str]:
    """Warn about missing API keys — app still starts but with degraded functionality."""
    warnings = []
    if not ANTHROPIC_API_KEY:
        warnings.append("ANTHROPIC_API_KEY not set — LLM features will be unavailable.")
    if not VOYAGE_API_KEY:
        warnings.append("VOYAGE_API_KEY not set — semantic search disabled, using keyword fallback.")
    return warnings


# ─────────────────────────────────────────────
# Copy KB documents from /mnt/project to data/
# ─────────────────────────────────────────────

def _copy_kb_documents() -> None:
    """
    On first run, copy the knowledge base .docx (plain-text) files
    from /mnt/project (Colab / HF Spaces project directory) to data/kb_documents/.
    This makes them available to the ingestion pipeline.
    Skips the system design doc (internal only).
    """
    src = Path("/mnt/project")
    dst = Path("data/kb_documents")
    dst.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        # Running locally — check for docs in same directory as app.py
        src = Path(__file__).parent / "docs"
        if not src.exists():
            print("[App] No /mnt/project or docs/ folder found — KB will be empty.")
            return

    SKIP = {"OnboardingBuddy_System_Design"}
    copied = 0
    for fpath in sorted(src.glob("*.docx")):
        if fpath.stem in SKIP:
            continue
        dest_file = dst / fpath.name
        if not dest_file.exists():
            dest_file.write_bytes(fpath.read_bytes())
            copied += 1

    if copied:
        print(f"[App] Copied {copied} KB documents to data/kb_documents/")


# ─────────────────────────────────────────────
# Scheduler setup
# ─────────────────────────────────────────────

def _start_scheduler(orchestrator: Orchestrator) -> BackgroundScheduler:
    """
    Start a background scheduler that:
    - Checks for overdue phases and sends nudges every 6 hours
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=orchestrator.run_progress_check,
        trigger="interval",
        seconds=NUDGE_POLL_INTERVAL_SECONDS,
        id="progress_check",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[App] Scheduler started — progress checks every {NUDGE_POLL_INTERVAL_SECONDS // 3600}h.")
    return scheduler


# ─────────────────────────────────────────────
# Main build function
# ─────────────────────────────────────────────

def build_app() -> gr.Blocks:
    """
    Initialise all shared infrastructure and build the combined Gradio app.
    Returns a gr.Blocks instance ready for .launch().
    """
    print("=" * 60)
    print("  OnboardingBuddy — Starting Up")
    print("=" * 60)

    # 1. Environment check
    for warning in _check_env():
        print(f"  ⚠️  {warning}")

    # 2. Copy KB documents (idempotent)
    _copy_kb_documents()

    # 3. Knowledge base
    print("[App] Initialising knowledge base...")
    kb = KnowledgeBase()
    kb.load_or_ingest()

    # 4. State store
    store = StateStore()

    # 5. Orchestrator (wires all agents)
    orchestrator = Orchestrator(store=store, kb=kb)

    # 6. Background scheduler
    _start_scheduler(orchestrator)

    # 7. Build both Gradio apps
    print("[App] Building Admin app...")
    admin_app = build_admin_app(orchestrator=orchestrator, store=store)

    print("[App] Building Joiner app...")
    joiner_app = build_joiner_app(orchestrator=orchestrator, store=store)

    # 8. Combine into a single tabbed interface
    combined = gr.TabbedInterface(
        interface_list=[admin_app, joiner_app],
        tab_names=["🧭 Admin Portal", "🌱 My Onboarding Journey"],
        title=f"{APP_TITLE} — Nexora Global Corporation",
        css=ADMIN_CSS + JOINER_CSS + """
        /* Global tab bar styling */
        .tab-nav button {
            font-weight: 600;
            font-size: 0.95rem;
            padding: 10px 20px;
        }
        .tab-nav button.selected {
            border-bottom: 3px solid #00897B;
            color: #00897B;
        }
        """,
    )

    print("[App] ✅ OnboardingBuddy is ready!")
    print("=" * 60)
    return combined


# ─────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = build_app()
    app.launch(
        server_name="0.0.0.0",   # Required for HF Spaces
        server_port=7860,         # Default HF Spaces port
        share=False,              # Set True for local share link
        show_error=True,
        theme=gr.themes.Soft(primary_hue="teal", secondary_hue="orange"),
    )
