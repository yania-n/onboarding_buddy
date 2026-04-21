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

Gradio 6.0 note: css= and theme= are no longer accepted by gr.Blocks() or
gr.TabbedInterface() constructors — they must be passed to app.launch().
The js= parameter IS still accepted by the TabbedInterface constructor.

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
    COLOR_PRIMARY, COLOR_PRIMARY_DARK, COLOR_PRIMARY_DARKER,
    COLOR_PRIMARY_LIGHT, COLOR_SURFACE, COLOR_CARD, COLOR_TEXT,
    COLOR_TEXT_SECONDARY, COLOR_MUTED, COLOR_BORDER,
)
from core.knowledge_base import KnowledgeBase
from core.state_store import StateStore
from agents.orchestrator import Orchestrator
from ui.admin_app import build_admin_app, ADMIN_CSS
from ui.joiner_app import build_joiner_app, JOINER_CSS


# ── Gradio theme — Grass Green + Black + White ────────────────────────────────
# Defined here (once) and passed to launch() per Gradio 6.0 requirements.

LIGHT_THEME = gr.themes.Soft(
    primary_hue="green",
    secondary_hue="green",
    neutral_hue="gray",
).set(
    # Force white/light backgrounds even when OS is in dark mode
    body_background_fill=COLOR_SURFACE,
    body_background_fill_dark=COLOR_SURFACE,
    background_fill_primary=COLOR_CARD,
    background_fill_primary_dark=COLOR_CARD,
    background_fill_secondary=COLOR_SURFACE,
    background_fill_secondary_dark=COLOR_SURFACE,
    block_background_fill=COLOR_CARD,
    block_background_fill_dark=COLOR_CARD,
    panel_background_fill=COLOR_CARD,
    panel_background_fill_dark=COLOR_CARD,
    input_background_fill=COLOR_CARD,
    input_background_fill_dark=COLOR_CARD,
    input_background_fill_focus=COLOR_CARD,
    input_background_fill_focus_dark=COLOR_CARD,
    # Text
    body_text_color=COLOR_TEXT,
    body_text_color_dark=COLOR_TEXT,
    body_text_color_subdued=COLOR_MUTED,
    body_text_color_subdued_dark=COLOR_MUTED,
    block_label_text_color=COLOR_TEXT,
    block_label_text_color_dark=COLOR_TEXT,
    block_title_text_color=COLOR_PRIMARY_DARKER,
    block_title_text_color_dark=COLOR_PRIMARY_DARKER,
    # Borders
    border_color_primary=COLOR_BORDER,
    border_color_primary_dark=COLOR_BORDER,
    block_border_color=COLOR_BORDER,
    block_border_color_dark=COLOR_BORDER,
    input_border_color="#E0E0E0",
    input_border_color_dark="#E0E0E0",
    input_placeholder_color=COLOR_MUTED,
    input_placeholder_color_dark=COLOR_MUTED,
    # Primary button
    button_primary_background_fill=COLOR_PRIMARY,
    button_primary_background_fill_dark=COLOR_PRIMARY,
    button_primary_background_fill_hover=COLOR_PRIMARY_DARK,
    button_primary_background_fill_hover_dark=COLOR_PRIMARY_DARK,
    button_primary_text_color="#FFFFFF",
    button_primary_text_color_dark="#FFFFFF",
    # Secondary button
    button_secondary_background_fill=COLOR_CARD,
    button_secondary_background_fill_dark=COLOR_CARD,
    button_secondary_text_color=COLOR_TEXT,
    button_secondary_text_color_dark=COLOR_TEXT,
    button_secondary_border_color="#E0E0E0",
    button_secondary_border_color_dark="#E0E0E0",
    # Table
    table_even_background_fill=COLOR_CARD,
    table_even_background_fill_dark=COLOR_CARD,
    table_odd_background_fill=COLOR_SURFACE,
    table_odd_background_fill_dark=COLOR_SURFACE,
)

# Combined CSS: GLOBAL_CSS_VARS (shared) + per-app extras.
# Both JOINER_CSS and ADMIN_CSS already include GLOBAL_CSS_VARS; combining
# them simply duplicates that shared block, which is harmless for CSS.
COMBINED_CSS = JOINER_CSS + "\n" + ADMIN_CSS

# JavaScript: runs on page load to strip Gradio's html.dark class and prevent
# it from being re-added via MutationObserver. Passed directly to
# gr.TabbedInterface(js=...) — the only js= that Gradio 6.0 honours at the
# outer page level.
_FORCE_LIGHT_JS = """
() => {
    var h = document.documentElement;
    h.classList.remove('dark');
    h.style.colorScheme = 'light';
    new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            if (m.attributeName === 'class' && h.classList.contains('dark')) {
                h.classList.remove('dark');
                h.style.colorScheme = 'light';
            }
        });
    }).observe(h, { attributes: true, attributeFilter: ['class'] });
    return [];
}
"""


# ── Startup checks ────────────────────────────────────────────────────────────

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


# ── Scheduler ─────────────────────────────────────────────────────────────────

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


# ── App builder ───────────────────────────────────────────────────────────────

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

    # Gradio 6.0: TabbedInterface does NOT accept js=, css=, or theme=.
    # css= and theme= go to launch() — see below.
    # JS must be wired inside a Blocks context via .load().
    combined = gr.TabbedInterface(
        interface_list=[admin_ui, joiner_ui],
        tab_names=["Admin Portal", "My Onboarding Journey"],
        title=APP_TITLE,
    )

    # Re-open the TabbedInterface context to register the load event.
    # .load() cannot be called outside a gr.Blocks context in Gradio 6.x.
    with combined:
        combined.load(fn=None, js=_FORCE_LIGHT_JS)

    print("[App] {} is ready -- visit http://0.0.0.0:7860".format(APP_TITLE))
    print("=" * 60)
    return combined


# ── Entry point ───────────────────────────────────────────────────────────────
# css= and theme= MUST be passed to launch() in Gradio 6.0.
# Setting them on the Blocks/TabbedInterface object is silently ignored.

app = build_app()
app.launch(
    server_name="0.0.0.0",
    server_port=7860,
    share=False,
    show_error=True,
    css=COMBINED_CSS,
    theme=LIGHT_THEME,
)
