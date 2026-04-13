"""
ui/joiner_app.py — New Joiner Onboarding Experience (Gradio UI)
================================================================
The joiner's primary interface throughout their 90-day onboarding.

Tab structure:
  ├── 🏠 My Journey      (phase timeline + current phase card + checklist)
  ├── 💬 Ask Anything    (KB-grounded Q&A chatbot)
  ├── 📚 My Training     (LMS course plan + completion tracking)
  ├── 🔐 My Access       (IT provisioning status)
  ├── 📝 Feedback        (phase-end pulse survey)
  └── 🔔 Notifications   (all agent messages and nudges)

Design principles:
  - Joiner owns their progress — phases advance only when THEY mark complete
  - Warm, encouraging tone — feels like a wellness/habit app, not HR admin
  - Every view is live-rendered from state store — no stale data
  - Q&A chat maintains conversation history within the session
"""

from datetime import date
from typing import Optional

import gradio as gr

from core.config import (
    PHASES, PHASE_BY_ID, APP_TITLE,
    COLOR_PRIMARY, COLOR_ACCENT,
)
from core.models import PhaseStatus
from core.state_store import StateStore


# ─────────────────────────────────────────────
# CSS — Joiner App Styles
# ─────────────────────────────────────────────

JOINER_CSS = """
/* OnboardingBuddy Joiner App — styles */
:root {
    --ob-primary: #00897B;
    --ob-accent:  #FF7043;
    --ob-surface: #F5F5F5;
    --ob-card:    #FFFFFF;
    --ob-text:    #212121;
    --ob-muted:   #757575;
    --ob-border:  #E0E0E0;
    --ob-success: #43A047;
    --ob-locked:  #BDBDBD;
    --ob-pending: #FB8C00;
}

/* ── Journey timeline ─────────── */
.journey-header {
    background: linear-gradient(135deg, #00897B 0%, #26A69A 60%, #FF7043 100%);
    color: white;
    padding: 28px 32px;
    border-radius: 14px;
    margin-bottom: 20px;
}
.journey-header h2 { margin: 0 0 4px; font-size: 1.5rem; }
.journey-header p  { margin: 0; opacity: 0.9; font-size: 0.95rem; }

.phase-timeline {
    display: flex;
    gap: 0;
    margin-bottom: 24px;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--ob-border);
}
.phase-node {
    flex: 1;
    padding: 12px 8px;
    text-align: center;
    font-size: 0.78rem;
    font-weight: 600;
    position: relative;
    cursor: default;
    transition: background 0.2s;
}
.phase-node.active {
    background: var(--ob-primary);
    color: white;
}
.phase-node.complete {
    background: #E8F5E9;
    color: var(--ob-success);
}
.phase-node.locked {
    background: #F5F5F5;
    color: var(--ob-locked);
}
.phase-node.pending_lms {
    background: #FFF3E0;
    color: var(--ob-pending);
}

/* ── Phase card ───────────────── */
.phase-card {
    background: var(--ob-card);
    border: 2px solid var(--ob-primary);
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 20px;
}
.phase-card-title {
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--ob-primary);
    margin-bottom: 6px;
}
.phase-card-objective {
    color: var(--ob-muted);
    font-size: 0.92rem;
    margin-bottom: 18px;
    line-height: 1.5;
}

/* ── Progress ring ────────────── */
.progress-ring-wrap {
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 20px;
}
.progress-stats {
    font-size: 0.9rem;
    color: var(--ob-muted);
}
.progress-stats strong {
    font-size: 1.4rem;
    color: var(--ob-primary);
    display: block;
}

/* ── Checklist ────────────────── */
.checklist-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 6px;
    background: var(--ob-surface);
    font-size: 0.9rem;
    transition: background 0.15s;
}
.checklist-item.done { background: #E8F5E9; }
.checklist-item .check-icon { font-size: 1.1rem; }

/* ── Notifications ────────────── */
.notif-item {
    background: var(--ob-card);
    border: 1px solid var(--ob-border);
    border-left: 4px solid var(--ob-primary);
    border-radius: 0 10px 10px 0;
    padding: 14px 18px;
    margin-bottom: 10px;
    font-size: 0.92rem;
    white-space: pre-wrap;
    line-height: 1.55;
}

/* ── Training card ────────────── */
.course-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-radius: 8px;
    margin-bottom: 6px;
    background: var(--ob-surface);
    font-size: 0.9rem;
}
.course-item.done { background: #E8F5E9; }
.course-badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 12px;
    background: var(--ob-primary);
    color: white;
    font-weight: 600;
}
.course-badge.mandatory { background: var(--ob-accent); }

/* ── Access status ────────────── */
.access-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 16px;
    border-radius: 8px;
    margin-bottom: 6px;
    background: var(--ob-surface);
    font-size: 0.9rem;
}
.status-pill {
    font-size: 0.78rem;
    padding: 3px 10px;
    border-radius: 12px;
    font-weight: 600;
}
.status-pill.pending { background: #FFF3E0; color: var(--ob-pending); }
.status-pill.provisioned { background: #E8F5E9; color: var(--ob-success); }
.status-pill.blocked { background: #FFEBEE; color: #E53935; }

/* ── Chat ─────────────────────── */
.buddy-intro {
    background: linear-gradient(135deg, #E0F2F1, #E8F5E9);
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 16px;
    font-size: 0.93rem;
    line-height: 1.6;
}

/* ── General ──────────────────── */
.section-label {
    font-size: 1rem;
    font-weight: 700;
    color: var(--ob-primary);
    margin: 16px 0 10px;
    padding-bottom: 4px;
    border-bottom: 2px solid var(--ob-primary);
}
.gate-warning {
    background: #FFF3E0;
    border: 1px solid #FFB74D;
    border-radius: 8px;
    padding: 14px 18px;
    font-size: 0.92rem;
    color: #E65100;
    margin-top: 12px;
}
.complete-banner {
    background: linear-gradient(135deg, #E8F5E9, #F1F8E9);
    border: 2px solid #43A047;
    border-radius: 14px;
    padding: 24px;
    text-align: center;
    font-size: 1.1rem;
    color: #1B5E20;
    margin-top: 16px;
}
"""


# ─────────────────────────────────────────────
# HTML rendering helpers
# ─────────────────────────────────────────────

def _phase_timeline_html(state) -> str:
    """Render the 6-phase horizontal timeline strip."""
    nodes = []
    for phase in PHASES:
        status = state.phase_statuses.get(phase.phase_id, PhaseStatus.LOCKED).value
        icon = {"active": "▶", "complete": "✓", "locked": "○", "pending_lms": "⏳"}.get(status, "○")
        nodes.append(
            f'<div class="phase-node {status}">'
            f'{icon} {phase.phase_id}. {phase.name}'
            f'<br><span style="font-size:0.7rem;opacity:0.8">Day {phase.day_start}–{phase.day_end}</span>'
            f'</div>'
        )
    return f'<div class="phase-timeline">{"".join(nodes)}</div>'


def _progress_ring_svg(done: int, total: int) -> str:
    """Generate an SVG progress ring showing checklist completion %."""
    pct = done / total if total else 0
    r = 30
    circumference = 2 * 3.14159 * r
    dash = circumference * pct
    return f"""
    <svg width="80" height="80" viewBox="0 0 80 80" style="transform:rotate(-90deg)">
      <circle cx="40" cy="40" r="{r}" fill="none" stroke="#E0E0E0" stroke-width="8"/>
      <circle cx="40" cy="40" r="{r}" fill="none" stroke="#00897B" stroke-width="8"
              stroke-dasharray="{dash:.1f} {circumference:.1f}"
              stroke-linecap="round"/>
      <text x="40" y="47" text-anchor="middle" fill="#00897B" font-size="16"
            font-weight="bold" style="transform:rotate(90deg) translate(0,-80px)">
        {int(pct*100)}%
      </text>
    </svg>
    """


def _render_phase_card(state, phase_id: int) -> str:
    """Render the active phase card with checklist items."""
    phase_def = PHASE_BY_ID.get(phase_id)
    if not phase_def:
        return "<p>Phase not found.</p>"

    status = state.phase_statuses.get(phase_id, PhaseStatus.LOCKED)
    checklist = state.get_checklist_for_phase(phase_id)
    done = sum(1 for c in checklist if c.completed)
    total = len(checklist)

    ring = _progress_ring_svg(done, total)
    checklist_html = "".join(
        f'<div class="checklist-item {"done" if c.completed else ""}">'
        f'<span class="check-icon">{"✅" if c.completed else "⬜"}</span>'
        f'<span>{c.label}</span>'
        f'</div>'
        for c in checklist
    )

    gate_warning = ""
    if phase_def.system_gated and not state.lms_mandatory_confirmed:
        gate_warning = (
            '<div class="gate-warning">'
            '⏳ <strong>Phase 3 gate:</strong> This phase requires LMS confirmation of all mandatory '
            'courses before you can mark it complete. Check your training tab — completion is tracked automatically.'
            '</div>'
        )

    return f"""
    <div class="phase-card">
        <div class="phase-card-title">Phase {phase_id}: {phase_def.name}</div>
        <div class="phase-card-objective">{phase_def.objective}</div>
        <div class="progress-ring-wrap">
            {ring}
            <div class="progress-stats">
                <strong>{done}/{total}</strong>
                checklist items complete
            </div>
        </div>
        <div class="section-label">Your Checklist</div>
        {checklist_html}
        {gate_warning}
    </div>
    """


def _render_notifications(state) -> str:
    """Render all in-app notifications, newest first."""
    notifs = state.app_notifications
    if not notifs:
        return '<p style="color:#757575;padding:16px">No notifications yet — they\'ll appear here as your onboarding progresses.</p>'

    items = []
    for msg in reversed(notifs):
        # Convert **bold** markdown to HTML
        import re
        msg_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(msg))
        items.append(f'<div class="notif-item">{msg_html}</div>')
    return "".join(items)


def _render_training(store: StateStore, joiner_id: str, training_agent) -> str:
    """Render the training plan dashboard."""
    plan = training_agent.get_course_plan(joiner_id)

    def course_row(c: dict, badge_class: str = "") -> str:
        done = c.get("completed", False)
        return (
            f'<div class="course-item {"done" if done else ""}">'
            f'<span>{"✅" if done else "📖"} [{c["id"]}] {c["title"]} '
            f'<span style="color:#757575;font-size:0.82rem">({c.get("duration_mins", 0)} min)</span></span>'
            f'<span class="course-badge {badge_class}">{"Complete" if done else ("Mandatory" if badge_class == "mandatory" else "Optional")}</span>'
            f'</div>'
        )

    mandatory_html = "".join(course_row(c, "mandatory") for c in plan["mandatory"])
    role_html = "".join(course_row(c) for c in plan["role_specific"] + plan["tools"]) or \
                '<p style="color:#757575;font-size:0.9rem">No role-specific courses configured yet.</p>'

    gate_status = (
        '<span style="color:#43A047;font-weight:600">✅ LMS confirmed — Phase 3 gate is open</span>'
        if plan["lms_gate_confirmed"] else
        '<span style="color:#FB8C00;font-weight:600">⏳ Awaiting LMS confirmation</span>'
    )

    return f"""
    <div style="margin-bottom:8px">{gate_status}</div>
    <div class="section-label">Mandatory Courses (required for Phase 3)</div>
    {mandatory_html}
    <div class="section-label">Role-Specific & Tool Courses</div>
    {role_html}
    <p style="color:#757575;font-size:0.82rem;margin-top:12px">
        Access your courses via the LMS dashboard link in your welcome email.
        Completions sync automatically.
    </p>
    """


def _render_access(store: StateStore, joiner_id: str, access_agent) -> str:
    """Render the IT access status panel."""
    requests = access_agent.get_access_summary(joiner_id)
    if not requests:
        return '<p style="color:#757575;padding:16px">No access requests found. Your manager may not have configured tool access yet.</p>'

    rows = []
    for r in requests:
        status_cls = r["status"]
        icon = {"pending": "⏳", "provisioned": "✅", "blocked": "❌"}.get(status_cls, "❓")
        rows.append(
            f'<div class="access-item">'
            f'<div><strong>{r["tool"]}</strong> <span style="color:#757575;font-size:0.85rem">({r["level"]})</span>'
            f'<br><span style="font-size:0.78rem;color:#9E9E9E">Ticket: {r["ticket"]}</span></div>'
            f'<span class="status-pill {status_cls}">{icon} {status_cls.title()}</span>'
            f'</div>'
        )
    return "".join(rows)


# ─────────────────────────────────────────────
# Build the Joiner Gradio App
# ─────────────────────────────────────────────

def build_joiner_app(orchestrator, store: StateStore) -> gr.Blocks:
    """
    Construct and return the full Joiner Gradio Blocks app.
    Joiner selects themselves from a dropdown (no auth for PoC).
    All views are re-rendered on tab switch and after actions.
    """

    def get_joiner_choices() -> list[str]:
        profiles = store.list_profiles()
        return [f"{p.full_name} — {p.job_title} ({p.joiner_id[:8]}...)" for p in profiles]

    def parse_joiner_id(choice: str) -> Optional[str]:
        """Extract the joiner_id from a dropdown display string."""
        if not choice:
            return None
        # Find the profile whose id starts with the prefix shown
        prefix = choice.split("(")[-1].replace("...)", "").strip()
        for p in store.list_profiles():
            if p.joiner_id.startswith(prefix):
                return p.joiner_id
        return None

    with gr.Blocks(
        title="OnboardingBuddy — Your Journey",
        css=JOINER_CSS,
        theme=gr.themes.Soft(primary_hue="teal", secondary_hue="orange"),
    ) as joiner_app:

        # ── Joiner selector ────────────────────
        with gr.Row():
            joiner_dropdown = gr.Dropdown(
                label="👤 Select Your Profile",
                choices=get_joiner_choices(),
                value=None,
                scale=3,
                info="Your manager will have set this up — select your name to begin.",
            )
            refresh_selector = gr.Button("🔄 Refresh", scale=1)

        refresh_selector.click(
            fn=lambda: gr.Dropdown(choices=get_joiner_choices()),
            outputs=[joiner_dropdown],
        )

        # ── Dynamic header ─────────────────────
        header_html = gr.HTML(value="""
        <div class="journey-header">
            <h2>👋 Welcome to OnboardingBuddy</h2>
            <p>Select your profile above to begin your onboarding journey at Nexora.</p>
        </div>
        """)

        # ── Tabs ───────────────────────────────
        with gr.Tabs() as tabs:

            # ══════════════════════════════════
            # TAB 1 — My Journey (Phase view)
            # ══════════════════════════════════
            with gr.Tab("🏠 My Journey"):

                timeline_html = gr.HTML()
                phase_card_html = gr.HTML()

                with gr.Row():
                    with gr.Column(scale=2):
                        gr.HTML('<div class="section-label">Checklist Actions</div>')
                        item_id_input = gr.Textbox(
                            label="Checklist Item ID",
                            placeholder="phase1_item0",
                            info="Copy the item_id from the checklist (shown in the phase card source)"
                        )
                        with gr.Row():
                            mark_done_btn = gr.Button("✅ Mark Item Complete", variant="primary")
                            mark_undone_btn = gr.Button("↩ Mark Incomplete", variant="secondary")

                    with gr.Column(scale=1):
                        gr.HTML('<div class="section-label">Phase Control</div>')
                        complete_phase_btn = gr.Button(
                            "🏁 Mark Phase Complete",
                            variant="primary",
                            size="lg",
                        )

                action_result = gr.HTML(visible=False)

                def load_journey(choice):
                    """Render the full journey view for the selected joiner."""
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return (
                            """<div class="journey-header"><h2>👋 Select your profile above</h2>
                            <p>Your manager should have created your record — refresh the list if you don't see your name.</p></div>""",
                            "", "", gr.HTML(visible=False),
                        )
                    state = store.get_state(jid)
                    profile = store.get_profile(jid)
                    if not state or not profile:
                        return "Error loading profile.", "", "", gr.HTML(visible=False)

                    first_name = profile.full_name.split()[0]
                    phase_def = PHASE_BY_ID.get(state.current_phase)
                    phase_name = phase_def.name if phase_def else "—"

                    header = f"""
                    <div class="journey-header">
                        <h2>Hi {first_name}! 👋 You're on Phase {state.current_phase}: {phase_name}</h2>
                        <p>{profile.job_title} · {profile.department} · Started {profile.start_date}</p>
                    </div>
                    """
                    if state.onboarding_complete:
                        header += '<div class="complete-banner">🎉 Congratulations! You\'ve completed your 90-day onboarding journey at Nexora!</div>'

                    timeline = _phase_timeline_html(state)
                    card = _render_phase_card(state, state.current_phase)
                    return header, timeline, card, gr.HTML(visible=False)

                joiner_dropdown.change(
                    fn=load_journey,
                    inputs=[joiner_dropdown],
                    outputs=[header_html, timeline_html, phase_card_html, action_result],
                )

                def toggle_item(choice, item_id, completed: bool):
                    jid = parse_joiner_id(choice)
                    if not jid or not item_id.strip():
                        return gr.HTML(
                            value='<div style="color:#E53935;padding:8px;background:#FFEBEE;border-radius:8px">Please select a joiner and enter an item ID.</div>',
                            visible=True,
                        ), "", ""
                    success = orchestrator.toggle_checklist_item(jid, item_id.strip(), completed)
                    state = store.get_state(jid)
                    if success and state:
                        return (
                            gr.HTML(visible=False),
                            _phase_timeline_html(state),
                            _render_phase_card(state, state.current_phase),
                        )
                    return gr.HTML(
                        value='<div style="color:#E53935;padding:8px;background:#FFEBEE;border-radius:8px">Item ID not found.</div>',
                        visible=True,
                    ), "", ""

                mark_done_btn.click(
                    fn=lambda c, i: toggle_item(c, i, True),
                    inputs=[joiner_dropdown, item_id_input],
                    outputs=[action_result, timeline_html, phase_card_html],
                )
                mark_undone_btn.click(
                    fn=lambda c, i: toggle_item(c, i, False),
                    inputs=[joiner_dropdown, item_id_input],
                    outputs=[action_result, timeline_html, phase_card_html],
                )

                def advance_phase(choice):
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return (
                            gr.HTML(
                                value='<div style="color:#E53935;padding:8px;background:#FFEBEE;border-radius:8px">Please select your profile first.</div>',
                                visible=True,
                            ), "", "",
                        )
                    success, msg = orchestrator.advance_phase(jid)
                    state = store.get_state(jid)
                    result_color = "#E8F5E9" if success else "#FFEBEE"
                    text_color = "#1B5E20" if success else "#E53935"
                    return (
                        gr.HTML(
                            value=f'<div style="padding:12px;background:{result_color};border-radius:8px;color:{text_color};font-weight:500">{"✅" if success else "⚠️"} {msg}</div>',
                            visible=True,
                        ),
                        _phase_timeline_html(state) if state else "",
                        _render_phase_card(state, state.current_phase) if state else "",
                    )

                complete_phase_btn.click(
                    fn=advance_phase,
                    inputs=[joiner_dropdown],
                    outputs=[action_result, timeline_html, phase_card_html],
                )

            # ══════════════════════════════════
            # TAB 2 — Q&A Chatbot
            # ══════════════════════════════════
            with gr.Tab("💬 Ask Anything"):
                gr.HTML("""
                <div class="buddy-intro">
                    <strong>🤖 OnboardingBuddy knows your company inside out.</strong><br>
                    Ask me anything about Nexora — policies, tools, culture, your team structure,
                    expenses, how to get things done. I'll always tell you where to look for more.
                    <br><br>
                    <em>Note: I only answer from the official knowledge base. If I don't know something,
                    I'll flag it and you'll get an answer soon.</em>
                </div>
                """)

                chatbot = gr.Chatbot(
                    label="Chat with OnboardingBuddy",
                    height=450,
                    bubble_full_width=False,
                    show_label=False,
                )
                with gr.Row():
                    chat_input = gr.Textbox(
                        placeholder="Ask me anything about Nexora...",
                        label="",
                        scale=5,
                        container=False,
                    )
                    send_btn = gr.Button("Send →", variant="primary", scale=1)
                clear_chat_btn = gr.Button("🗑 Clear Chat", variant="secondary", size="sm")

                def chat(user_msg: str, history: list, choice: str):
                    jid = parse_joiner_id(choice) or "anonymous"
                    if not user_msg.strip():
                        return history, ""
                    answer = orchestrator.answer_question(jid, user_msg.strip())
                    history = history or []
                    history.append((user_msg, answer))
                    return history, ""

                send_btn.click(
                    fn=chat,
                    inputs=[chat_input, chatbot, joiner_dropdown],
                    outputs=[chatbot, chat_input],
                )
                chat_input.submit(
                    fn=chat,
                    inputs=[chat_input, chatbot, joiner_dropdown],
                    outputs=[chatbot, chat_input],
                )
                clear_chat_btn.click(fn=lambda: [], outputs=[chatbot])

            # ══════════════════════════════════
            # TAB 3 — Training
            # ══════════════════════════════════
            with gr.Tab("📚 My Training"):
                training_html = gr.HTML(
                    value='<p style="color:#757575">Select your profile to see your training plan.</p>'
                )
                training_refresh = gr.Button("🔄 Refresh Training Status", variant="secondary")

                def load_training(choice):
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return '<p style="color:#757575">Select your profile first.</p>'
                    return _render_training(store, jid, orchestrator.training_agent)

                joiner_dropdown.change(fn=load_training, inputs=[joiner_dropdown], outputs=[training_html])
                training_refresh.click(fn=load_training, inputs=[joiner_dropdown], outputs=[training_html])

            # ══════════════════════════════════
            # TAB 4 — Access Status
            # ══════════════════════════════════
            with gr.Tab("🔐 My Access"):
                gr.HTML("""
                <p style="color:#757575;font-size:0.9rem">
                Your IT access requests were raised on Day 1. Provisioning typically takes 1–2 business days.
                Contact IT Support if any access is blocked.
                </p>
                """)
                access_html = gr.HTML(
                    value='<p style="color:#757575">Select your profile to see access status.</p>'
                )
                access_refresh = gr.Button("🔄 Refresh Access Status", variant="secondary")

                def load_access(choice):
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return '<p style="color:#757575">Select your profile first.</p>'
                    return _render_access(store, jid, orchestrator.access_agent)

                joiner_dropdown.change(fn=load_access, inputs=[joiner_dropdown], outputs=[access_html])
                access_refresh.click(fn=load_access, inputs=[joiner_dropdown], outputs=[access_html])

            # ══════════════════════════════════
            # TAB 5 — Feedback
            # ══════════════════════════════════
            with gr.Tab("📝 Feedback"):
                gr.HTML("""
                <div class="buddy-intro">
                    <strong>💬 Your voice shapes the onboarding experience.</strong><br>
                    At the end of each phase, share how it felt. Your answers are read by HR
                    and used to improve the experience for future joiners.
                    Responses are confidential — they are never shared with your direct manager verbatim.
                </div>
                """)

                fb_phase_display = gr.HTML(
                    value='<p style="color:#757575">Select your profile and submit a phase to see feedback questions.</p>'
                )

                with gr.Row():
                    fb_phase_select = gr.Dropdown(
                        label="Submit feedback for phase",
                        choices=[f"Phase {p.phase_id} — {p.name}" for p in PHASES],
                        value=None,
                    )

                fb_q1 = gr.Textbox(label="Question 1", visible=False)
                fb_a1 = gr.Textbox(label="Your answer", placeholder="Write your honest thoughts...", lines=2, visible=False)
                fb_q2 = gr.Textbox(label="Question 2", visible=False)
                fb_a2 = gr.Textbox(label="Your answer", placeholder="Write your honest thoughts...", lines=2, visible=False)
                fb_q3 = gr.Textbox(label="Question 3", visible=False)
                fb_a3 = gr.Textbox(label="Your answer", placeholder="Write your honest thoughts...", lines=2, visible=False)

                fb_submit_btn = gr.Button("Submit Feedback", variant="primary", visible=False)
                fb_result = gr.HTML(visible=False)

                def load_feedback_questions(phase_choice):
                    if not phase_choice:
                        return [gr.HTML(visible=False)] + [gr.update(visible=False)] * 7
                    phase_id = int(phase_choice.split(" ")[1])
                    phase_def = PHASE_BY_ID.get(phase_id)
                    if not phase_def:
                        return [gr.HTML(visible=False)] + [gr.update(visible=False)] * 7
                    qs = phase_def.feedback_questions
                    q_updates = []
                    for i in range(3):
                        if i < len(qs):
                            q_updates.extend([gr.Textbox(label=f"Q{i+1}", value=qs[i], visible=True, interactive=False),
                                              gr.Textbox(visible=True)])
                        else:
                            q_updates.extend([gr.Textbox(visible=False), gr.Textbox(visible=False)])
                    return [gr.HTML(visible=False)] + q_updates + [gr.Button(visible=True)]

                fb_phase_select.change(
                    fn=load_feedback_questions,
                    inputs=[fb_phase_select],
                    outputs=[fb_phase_display, fb_q1, fb_a1, fb_q2, fb_a2, fb_q3, fb_a3, fb_submit_btn],
                )

                def submit_feedback(choice, phase_choice, a1, a2, a3):
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return gr.HTML(
                            value='<div style="color:#E53935;padding:8px;background:#FFEBEE;border-radius:8px">Please select your profile first.</div>',
                            visible=True,
                        )
                    if not phase_choice:
                        return gr.HTML(
                            value='<div style="color:#E53935;padding:8px">Please select a phase.</div>',
                            visible=True,
                        )
                    phase_id = int(phase_choice.split(" ")[1])
                    phase_def = PHASE_BY_ID.get(phase_id)
                    qs = phase_def.feedback_questions if phase_def else []
                    answers = {}
                    for q, a in zip(qs, [a1, a2, a3]):
                        if a and a.strip():
                            answers[q] = a.strip()

                    if not answers:
                        return gr.HTML(
                            value='<div style="color:#E53935;padding:8px">Please answer at least one question.</div>',
                            visible=True,
                        )

                    orchestrator.feedback_agent.record_feedback(jid, phase_id, answers)
                    return gr.HTML(
                        value='<div style="padding:14px;background:#E8F5E9;border-radius:8px;color:#1B5E20;font-weight:500">✅ Thank you for your feedback! Your responses have been recorded.</div>',
                        visible=True,
                    )

                fb_submit_btn.click(
                    fn=submit_feedback,
                    inputs=[joiner_dropdown, fb_phase_select, fb_a1, fb_a2, fb_a3],
                    outputs=[fb_result],
                )

            # ══════════════════════════════════
            # TAB 6 — Notifications
            # ══════════════════════════════════
            with gr.Tab("🔔 Notifications"):
                notif_html = gr.HTML(
                    value='<p style="color:#757575">Select your profile to see your notifications.</p>'
                )
                notif_refresh = gr.Button("🔄 Refresh", variant="secondary")

                def load_notifs(choice):
                    jid = parse_joiner_id(choice)
                    if not jid:
                        return '<p style="color:#757575">Select your profile first.</p>'
                    state = store.get_state(jid)
                    if not state:
                        return '<p style="color:#757575">Profile state not found.</p>'
                    return _render_notifications(state)

                joiner_dropdown.change(fn=load_notifs, inputs=[joiner_dropdown], outputs=[notif_html])
                notif_refresh.click(fn=load_notifs, inputs=[joiner_dropdown], outputs=[notif_html])

        # ── Peer connections sidebar ───────────
        with gr.Accordion("👥 Recommended Connections for This Phase", open=False):
            connections_html = gr.HTML(
                value='<p style="color:#757575">Select your profile to see recommendations.</p>'
            )

            def load_connections(choice):
                jid = parse_joiner_id(choice)
                if not jid:
                    return '<p style="color:#757575">Select your profile first.</p>'
                state = store.get_state(jid)
                if not state:
                    return ""
                recs = orchestrator.buddy_agent.recommend_connections(jid, state.current_phase)
                rows = "".join(
                    f'<div style="padding:10px 14px;background:#F5F5F5;border-radius:8px;margin-bottom:6px">'
                    f'<strong>{r["name"]}</strong><br>'
                    f'<span style="color:#757575;font-size:0.88rem">{r["reason"]}</span>'
                    f'</div>'
                    for r in recs
                )
                return rows or '<p style="color:#757575">No specific recommendations for this phase.</p>'

            joiner_dropdown.change(fn=load_connections, inputs=[joiner_dropdown], outputs=[connections_html])

    return joiner_app
