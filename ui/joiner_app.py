"""
ui/joiner_app.py — New Joiner App (Joiner-facing Gradio UI)
============================================================
The onboarding companion that guides a new employee through all 6 phases
of their 90-day onboarding journey.

Tab structure:
  ├── 🗺️ My Journey      (phase timeline + interactive checklist)
  ├── 💬 Ask Anything    (KB-grounded chatbot)
  ├── 🎓 My Training     (course plan from training agent)
  ├── 🔑 My Access       (IT ticket status table)
  ├── 📝 Feedback        (pulse survey — phases 3 & 6)
  └── 🔔 Notifications   (all agent messages — titles only, click to expand)

Notification UX:
  - Newest agent messages fire a transient toast (gr.Info) with a close
    button. The full content is ALWAYS logged to the Notifications tab
    as a collapsible row (title visible, body hidden until clicked).

Access model: joiner enters their Joiner ID (UUID) to load their record.
The orchestrator handles all reads/writes — no direct store access from UI.
"""

import re
import gradio as gr

from core.config import PHASE_BY_ID, PHASES, GLOBAL_CSS_VARS
from core.models import PhaseStatus, AccessStatus
from core.state_store import StateStore


# ─────────────────────────────────────────────
# CSS Theme — Grass Green + Black + White
# ─────────────────────────────────────────────

JOINER_CSS = GLOBAL_CSS_VARS + """
/* ── Joiner header — green gradient, white text ── */
.joiner-header {
    background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%) !important;
    color: #FFFFFF !important;
    padding: 20px 28px;
    border-radius: 12px;
    margin-bottom: 20px;
    border: none !important;
}
.joiner-header h1 { margin: 0; font-size: 1.5rem; font-weight: 700; color: #FFFFFF !important; }
.joiner-header p  { margin: 4px 0 0; opacity: 0.9; font-size: 0.9rem; color: #FFFFFF !important; }

/* ── Phase timeline ──────────────────────── */
.phase-row {
    display: flex;
    align-items: flex-start;
    margin-bottom: 10px;
    gap: 14px;
    color: #000000 !important;
}
.phase-dot {
    width: 18px; height: 18px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 3px;
}
.phase-dot.complete { background: #4CAF50 !important; }
.phase-dot.active   { background: #4CAF50 !important; box-shadow: 0 0 0 3px rgba(76,175,80,0.3); }
.phase-dot.locked   { background: #A5D6A7 !important; }

/* ── Current phase card ──────────────────── */
.current-phase-card {
    background: #FFFFFF !important;
    border: 1px solid #A5D6A7 !important;
    border-left: 5px solid #4CAF50 !important;
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 16px;
    color: #000000 !important;
}
.current-phase-card * { color: #000000 !important; }
.current-phase-card h3 {
    margin: 0 0 4px;
    color: #2E7D32 !important;
    font-size: 1.1rem;
    font-weight: 700;
}
.current-phase-card .objective {
    color: #616161 !important;
    font-size: 0.9rem;
    margin: 0 0 12px;
}

/* ── Checklist items ─────────────────────── */
.checklist-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 6px;
    margin-bottom: 6px;
    background: #F1F8E9 !important;
    border: 1px solid #A5D6A7 !important;
    color: #000000 !important;
}
.checklist-item.done { border-color: #4CAF50 !important; background: #E8F5E9 !important; }
.checklist-tick.done { color: #4CAF50 !important; font-weight: 700; }
.checklist-tick.todo { color: #A5D6A7 !important; }

/* ── Progress bar ────────────────────────── */
.progress-bar-wrap {
    background: #E0E0E0 !important;
    border-radius: 6px;
    height: 10px;
    width: 100%;
    margin: 10px 0;
    overflow: hidden;
}
.progress-bar-fill {
    background: #4CAF50 !important;
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
}

/* ── Access status badges ────────────────── */
.badge-pending     { background: #FFF3E0 !important; color: #E65100 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
.badge-provisioned { background: #E8F5E9 !important; color: #2E7D32 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
.badge-blocked     { background: #FFEBEE !important; color: #C62828 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }

/* ── Chatbot tweaks ──────────────────────── */
.chatbot-wrap .message.bot     { background: #E8F5E9 !important; color: #000000 !important; }
.chatbot-wrap .message.user    { background: #C8E6C9 !important; color: #000000 !important; }
"""


# ─────────────────────────────────────────────
# Joiner App Builder
# ─────────────────────────────────────────────

def build_joiner_app(orchestrator, store: StateStore) -> gr.Blocks:
    """
    Build and return the complete Gradio Blocks UI for the new joiner.
    Called by app.py; the orchestrator is injected at startup.
    """

    # ── Helper: format phase status label ───────────────────────────────────

    def _phase_status_label(status: PhaseStatus, phase_id: int, current: int) -> str:
        """Return a short text badge for a phase status."""
        if status == PhaseStatus.COMPLETE:
            return "✅ Complete"
        if status == PhaseStatus.ACTIVE:
            return "🟢 In Progress"
        if phase_id == current + 1:
            return "⏳ Up Next"
        return "🔒 Locked"

    # ── Helper: build phase timeline HTML ───────────────────────────────────

    def _build_timeline_html(state) -> str:
        """Render a vertical timeline of all 6 phases as HTML."""
        rows = []
        for ph in PHASES:
            ph_id   = ph.phase_id
            status  = state.phase_statuses.get(ph_id, PhaseStatus.LOCKED)
            label   = _phase_status_label(status, ph_id, state.current_phase)
            dot_cls = (
                "complete" if status == PhaseStatus.COMPLETE
                else "active" if status == PhaseStatus.ACTIVE
                else "locked"
            )
            start = state.phase_start_dates.get(ph_id)
            end   = state.phase_complete_dates.get(ph_id)
            date_str = ""
            if end:
                date_str = f" · Completed {end}"
            elif start:
                date_str = f" · Started {start}"

            rows.append(
                f'<div class="phase-row">'
                f'  <div class="phase-dot {dot_cls}"></div>'
                f'  <div>'
                f'    <strong>Phase {ph_id}: {ph.name}</strong> '
                f'    <span style="font-size:0.82rem; color:#666">{label}{date_str}</span><br>'
                f'    <span style="font-size:0.85rem; color:#555">Days {ph.day_start}–{ph.day_end} · {ph.objective}</span>'
                f'  </div>'
                f'</div>'
            )

        return '<div style="padding:8px 0">' + "\n".join(rows) + "</div>"

    # ── Helper: build checklist HTML ─────────────────────────────────────────

    def _build_checklist_html(state) -> str:
        """Render the current phase checklist as styled HTML."""
        items = [c for c in state.checklist_items if c.phase_id == state.current_phase]
        if not items:
            return "<p style='color:#888'>No checklist items for this phase.</p>"

        total = len(items)
        done  = sum(1 for c in items if c.completed)
        pct   = int(done / total * 100) if total else 0

        rows = []
        for item in items:
            tick_cls = "done" if item.completed else "todo"
            tick_sym = "✔" if item.completed else "○"
            rows.append(
                f'<div class="checklist-item {"done" if item.completed else ""}">'
                f'  <span class="checklist-tick {tick_cls}">{tick_sym}</span>'
                f'  <span>{item.label}</span>'
                f'</div>'
            )

        return (
            f'<div class="progress-bar-wrap">'
            f'  <div class="progress-bar-fill" style="width:{pct}%"></div>'
            f'</div>'
            f'<p style="font-size:0.85rem;color:#555;margin:4px 0 12px">{done}/{total} items complete ({pct}%)</p>'
            + "\n".join(rows)
        )

    # ── Helper: build current phase card ─────────────────────────────────────

    def _build_phase_card(state, profile) -> str:
        """Render the current phase summary card."""
        ph_id  = state.current_phase
        ph_def = PHASE_BY_ID.get(ph_id)
        if not ph_def:
            return ""

        lms_note = ""
        if ph_def.system_gated and not state.lms_mandatory_confirmed:
            lms_note = (
                '<div style="background:#FFF3E0;border-radius:6px;padding:10px 14px;'
                'margin-top:10px;font-size:0.88rem;color:#E65100">'
                '⏳ <strong>Phase gate:</strong> Your admin must confirm LMS course completion before '
                'you can mark this phase done. Reach out to your manager if this is taking too long.'
                '</div>'
            )

        complete_note = ""
        if state.onboarding_complete:
            complete_note = (
                '<div style="background:#E8F5E9;border-radius:8px;padding:14px 18px;text-align:center">'
                '<span style="font-size:1.8rem">🎉</span>'
                '<h3 style="margin:6px 0;color:var(--ob-primary-darker)">Onboarding Complete!</h3>'
                '<p style="color:#555;margin:0">You\'ve finished all 6 phases. Welcome fully aboard!</p>'
                '</div>'
            )

        return (
            f'<div class="current-phase-card">'
            f'  <h3>Phase {ph_id}: {ph_def.name}</h3>'
            f'  <p class="objective">🎯 {ph_def.objective}</p>'
            f'  <span style="font-size:0.82rem;color:#777">Days {ph_def.day_start}–{ph_def.day_end}</span>'
            f'{lms_note}'
            f'</div>'
            f'{complete_note}'
        )

    # ── Helper: build access table HTML ─────────────────────────────────────

    def _build_access_html(state) -> str:
        """Render IT access request status as an HTML table."""
        if not state.access_requests:
            return "<p style='color:#888'>No access requests on record.</p>"

        rows = []
        for req in state.access_requests:
            badge_cls = {
                AccessStatus.PENDING:     "badge-pending",
                AccessStatus.PROVISIONED: "badge-provisioned",
                AccessStatus.BLOCKED:     "badge-blocked",
            }.get(req.status, "badge-pending")
            status_label = req.status.value.title()
            rows.append(
                f"<tr>"
                f"  <td style='padding:8px 12px'>{req.tool_name}</td>"
                f"  <td style='padding:8px 12px'>{req.permission_level or '—'}</td>"
                f"  <td style='padding:8px 12px'><span class='{badge_cls}'>{status_label}</span></td>"
                f"  <td style='padding:8px 12px;font-size:0.82rem;color:#777'>{req.ticket_id}</td>"
                f"</tr>"
            )

        return (
            '<table style="width:100%;border-collapse:collapse;font-size:0.9rem">'
            '<thead><tr style="background:#E8F5E9">'
            '  <th style="padding:10px 12px;text-align:left">Tool</th>'
            '  <th style="padding:10px 12px;text-align:left">Permission</th>'
            '  <th style="padding:10px 12px;text-align:left">Status</th>'
            '  <th style="padding:10px 12px;text-align:left">Ticket ID</th>'
            '</tr></thead>'
            '<tbody>' + "\n".join(rows) + "</tbody></table>"
        )

    # ── Helper: extract training content from notifications ──────────────────

    def _build_training_html(state) -> str:
        """
        Pull the training plan notification from state.
        The training agent writes this as a notification containing 'Training Plan'.
        """
        plan_notif = next(
            (n for n in state.app_notifications if "Training Plan" in n or "🎓" in n),
            None,
        )
        if not plan_notif:
            return (
                "<p style='color:#888'>Your training plan is being prepared — "
                "check back shortly or refresh the page.</p>"
            )
        # Convert markdown-style bold to HTML
        txt = plan_notif.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = txt.split("**")
        html = ""
        for i, part in enumerate(parts):
            html += ("<strong>" if i % 2 == 1 else "") + part
            if i % 2 == 1:
                html += "</strong>"
        html = html.replace("\n\n", "<br><br>").replace("\n", "<br>")
        return f'<div style="line-height:1.7">{html}</div>'

    # ── Helper: extract a short title from a notification string ─────────────

    def _extract_title(notif: str) -> str:
        """Return a short one-line title suitable for a collapsed list row.

        Strategy (in order):
          1. First **bold** phrase (agents usually lead with one).
          2. First non-empty line, truncated to 70 chars.
          3. Fallback: "Notification".
        """
        m = re.search(r"\*\*([^*]+)\*\*", notif)
        if m:
            t = m.group(1).strip()
            return t[:90] + ("…" if len(t) > 90 else "")
        first = next((ln for ln in notif.splitlines() if ln.strip()), "").strip()
        if first:
            return first[:70] + ("…" if len(first) > 70 else "")
        return "Notification"

    def _markdown_to_html(txt: str) -> str:
        """Minimal safe conversion: escape HTML, then convert **bold** and newlines."""
        txt = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = txt.split("**")
        out = ""
        for i, part in enumerate(parts):
            out += ("<strong>" if i % 2 == 1 else "") + part
            if i % 2 == 1:
                out += "</strong>"
        return out.replace("\n\n", "<br><br>").replace("\n", "<br>")

    # ── Helper: build notifications list ─────────────────────────────────────

    def _build_notifications_html(state) -> str:
        """Render notifications as a collapsible list.

        Each row shows only a short title; clicking expands to reveal the
        full body. This matches the "event list shouldn't display the
        entire content, only on clicking the event" requirement.
        """
        if not state.app_notifications:
            return (
                "<p class='ob-muted' style='padding:20px;text-align:center'>"
                "No notifications yet. Agent messages (org brief, training plan, "
                "buddy intro, access updates) will appear here as they arrive.</p>"
            )

        items = []
        # Newest first — most recent agent messages are at the end of the list,
        # so reverse for display.
        for notif in reversed(state.app_notifications):
            title = _extract_title(notif).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            body  = _markdown_to_html(notif)
            items.append(
                f'<details class="notif-item">'
                f'  <summary>'
                f'    <span class="notif-title-text">{title}</span>'
                f'  </summary>'
                f'  <div class="notif-body">{body}</div>'
                f'</details>'
            )
        return "\n".join(items)

    def _latest_notification_title(state) -> str | None:
        """Return the short title of the most recent notification, if any."""
        if not state or not state.app_notifications:
            return None
        return _extract_title(state.app_notifications[-1])

    # ────────────────────────────────────────────────────────────────────────
    # Gradio Blocks UI
    # ────────────────────────────────────────────────────────────────────────

    light_theme = gr.themes.Soft(primary_hue="green", secondary_hue="green", neutral_hue="gray")
    with gr.Blocks(css=JOINER_CSS, title="OnboardingBuddy — My Journey", theme=light_theme) as joiner_ui:

        # ── Header ──────────────────────────────────────────────────────────
        gr.HTML(
            '<div style="background:linear-gradient(135deg,#2E7D32 0%,#4CAF50 100%);'
            'color:#FFFFFF;padding:20px 28px;border-radius:10px;margin-bottom:16px;">'
            '  <div style="font-size:1.5rem;font-weight:700;color:#FFFFFF;margin:0 0 4px">'
            '    &#127807; OnboardingBuddy'
            '  </div>'
            '  <div style="font-size:0.9rem;color:#C8E6C9;margin:0">'
            '    Your 90-day onboarding companion &mdash; welcome aboard!'
            '  </div>'
            '</div>'
        )

        # ── Joiner ID login ──────────────────────────────────────────────────
        with gr.Row():
            joiner_id_input = gr.Textbox(
                label="Your Joiner ID",
                placeholder="Paste your Joiner ID here (you received it in your welcome email)…",
                max_lines=1,
                scale=5,
            )
            load_btn = gr.Button("Load My Dashboard", variant="primary", scale=1)

        login_status = gr.HTML("")

        # ── Tabs (hidden until logged in) ────────────────────────────────────
        with gr.Tabs(visible=False) as main_tabs:

            # ── TAB 1: My Journey ────────────────────────────────────────────
            with gr.Tab("🗺️ My Journey"):
                phase_card_html   = gr.HTML("")
                timeline_html     = gr.HTML("")

                gr.HTML('<div class="section-title">Current Phase Checklist</div>')
                checklist_html    = gr.HTML("")

                with gr.Row():
                    refresh_journey_btn   = gr.Button("🔄 Refresh", size="sm")
                    mark_complete_btn     = gr.Button(
                        "✅ Mark Phase Complete", variant="primary", size="sm"
                    )

                advance_msg = gr.Markdown("")

                # Checklist tick controls
                gr.HTML('<div class="section-title" style="margin-top:20px">Tick Off Items</div>')
                gr.Markdown(
                    "_Enter part of the item label to mark it complete or incomplete._"
                )
                with gr.Row():
                    tick_label_input = gr.Textbox(
                        label="Checklist item label",
                        placeholder="e.g. Complete IT security induction",
                        scale=4,
                    )
                    tick_done_input  = gr.Checkbox(label="Mark as complete", value=True, scale=1)
                    tick_btn         = gr.Button("Update", size="sm", scale=1)
                tick_msg = gr.Markdown("")

            # ── TAB 2: Ask Anything ──────────────────────────────────────────
            with gr.Tab("💬 Ask Anything"):
                gr.Markdown(
                    "### Ask Me Anything\n"
                    "Ask any question about the company, your role, tools, processes, or anything "
                    "else you'd like to know. I'll search the knowledge base to help you."
                )
                # Gradio 6.x uses (user_msg, bot_msg) tuple pairs by default
                chatbot = gr.Chatbot(
                    label="OnboardingBuddy Chat",
                    elem_classes=["chatbot-wrap"],
                    height=400,
                )
                with gr.Row():
                    chat_input = gr.Textbox(
                        label="Your question",
                        placeholder="What is the expense policy?",
                        scale=5,
                        max_lines=2,
                    )
                    chat_send_btn = gr.Button("Send", variant="primary", scale=1)
                chat_clear_btn = gr.Button("🗑️ Clear Chat", size="sm")

            # ── TAB 3: My Training ───────────────────────────────────────────
            with gr.Tab("🎓 My Training"):
                gr.Markdown(
                    "### Your Learning Plan\n"
                    "Here is the personalised course plan prepared for your role. "
                    "Mandatory courses must be completed before Phase 3 can be marked done."
                )
                training_html        = gr.HTML("")
                refresh_training_btn = gr.Button("🔄 Refresh", size="sm")

            # ── TAB 4: My Access ─────────────────────────────────────────────
            with gr.Tab("🔑 My Access"):
                gr.Markdown(
                    "### IT Access Requests\n"
                    "Access requests were raised on your first day. "
                    "Most tools are provisioned within 1–3 business days. "
                    "If anything is still **Pending** after Day 3, contact your manager."
                )
                access_html        = gr.HTML("")
                refresh_access_btn = gr.Button("🔄 Refresh", size="sm")

            # ── TAB 5: Feedback ──────────────────────────────────────────────
            with gr.Tab("📝 Feedback"):
                gr.Markdown(
                    "### Pulse Survey\n"
                    "Please share your honest feedback at two key milestones: "
                    "**Phase 3** (50% journey) and **Phase 6** (finish line). "
                    "Your answers are shared with your manager only in summary form."
                )
                feedback_phase_selector = gr.Dropdown(
                    choices=[3, 6],
                    value=3,
                    label="Which phase is this feedback for?",
                )
                load_questions_btn      = gr.Button("Load Questions", size="sm")
                feedback_questions_html = gr.HTML("")

                fb_q1 = gr.Textbox(label="Q1", visible=False, lines=2)
                fb_q2 = gr.Textbox(label="Q2", visible=False, lines=2)
                fb_q3 = gr.Textbox(label="Q3", visible=False, lines=2)

                submit_feedback_btn = gr.Button(
                    "Submit Feedback", variant="primary", visible=False
                )
                feedback_result_msg = gr.Markdown("")

            # ── TAB 6: Notifications ─────────────────────────────────────────
            with gr.Tab("🔔 Notifications"):
                gr.Markdown(
                    "### Your Notifications\n"
                    "Messages from OnboardingBuddy agents — org brief, training plan, "
                    "buddy intro, access updates, and progress nudges. "
                    "**Click any row to expand its full content.** "
                    "New events also appear briefly as a popup in the top-right "
                    "corner of the screen — close the popup to dismiss it."
                )
                notifications_html = gr.HTML("")
                refresh_notif_btn  = gr.Button("🔄 Refresh", size="sm")

        # ── State: validated joiner ID + cached feedback questions ───────────
        active_joiner_id = gr.State("")
        active_questions = gr.State([])

        # ────────────────────────────────────────────────────────────────────
        # Event: Load Dashboard
        # ────────────────────────────────────────────────────────────────────

        def load_dashboard(joiner_id_raw: str):
            """
            Validate joiner ID, load state, and populate all tab content.
            Returns updates for every dependent component.

            Also fires a toast popup (gr.Info) with the latest notification
            title — the popup has a built-in close button; full detail is
            available in the 🔔 Notifications tab.
            """
            joiner_id = joiner_id_raw.strip()
            state     = store.get_state(joiner_id)
            profile   = store.get_profile(joiner_id)

            if not state or not profile:
                gr.Warning("Joiner ID not found. Please check your welcome email.")
                return (
                    gr.update(value=(
                        '<p style="color:#C62828">❌ Joiner ID not found. '
                        'Please check your welcome email and try again.</p>'
                    )),
                    gr.update(visible=False),
                    "",
                    "", "", "", "", "", "",
                )

            ph_name = PHASE_BY_ID[state.current_phase].name
            status_html = (
                f'<p style="color:var(--ob-primary-darker)">✅ Welcome back, '
                f'<strong>{profile.full_name}</strong>! '
                f'Currently on Phase {state.current_phase}: {ph_name}</p>'
            )

            # Pop a toast for the most recent notification (if any)
            latest = _latest_notification_title(state)
            if latest:
                count = len(state.app_notifications)
                plural = "notification" if count == 1 else "notifications"
                gr.Info(
                    f"{latest}  ·  ({count} {plural} — see the 🔔 Notifications tab for details)"
                )

            return (
                gr.update(value=status_html),
                gr.update(visible=True),
                joiner_id,
                _build_phase_card(state, profile),
                _build_timeline_html(state),
                _build_checklist_html(state),
                _build_training_html(state),
                _build_access_html(state),
                _build_notifications_html(state),
            )

        load_btn.click(
            fn=load_dashboard,
            inputs=[joiner_id_input],
            outputs=[
                login_status,
                main_tabs,
                active_joiner_id,
                phase_card_html,
                timeline_html,
                checklist_html,
                training_html,
                access_html,
                notifications_html,
            ],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Refresh Journey Tab
        # ────────────────────────────────────────────────────────────────────

        def refresh_journey(joiner_id: str):
            if not joiner_id:
                return "", "", ""
            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            if not state or not profile:
                return "", "", ""
            return (
                _build_phase_card(state, profile),
                _build_timeline_html(state),
                _build_checklist_html(state),
            )

        refresh_journey_btn.click(
            fn=refresh_journey,
            inputs=[active_joiner_id],
            outputs=[phase_card_html, timeline_html, checklist_html],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Mark Phase Complete
        # ────────────────────────────────────────────────────────────────────

        def mark_phase_complete(joiner_id: str):
            """Ask the orchestrator to advance the phase; refresh all journey components."""
            if not joiner_id:
                gr.Warning("Please load your dashboard first.")
                return "Please load your dashboard first.", "", "", ""

            success, msg = orchestrator.advance_phase(joiner_id)

            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            card = timeline = checklist = ""
            if state and profile:
                card      = _build_phase_card(state, profile)
                timeline  = _build_timeline_html(state)
                checklist = _build_checklist_html(state)

            # Fire a popup toast — success or warning — so the joiner sees
            # the outcome without a full page-filling banner.
            if success:
                gr.Info(msg)
            else:
                gr.Warning(msg)

            prefix = "✅ " if success else "⚠️ "
            return prefix + msg, card, timeline, checklist

        mark_complete_btn.click(
            fn=mark_phase_complete,
            inputs=[active_joiner_id],
            outputs=[advance_msg, phase_card_html, timeline_html, checklist_html],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Tick Checklist Item
        # ────────────────────────────────────────────────────────────────────

        def tick_item(joiner_id: str, label: str, completed: bool):
            """Find checklist item by partial label match and toggle its status."""
            if not joiner_id or not label.strip():
                return "Please load your dashboard and enter a checklist item label.", ""

            state = store.get_state(joiner_id)
            if not state:
                return "Could not load your record. Try refreshing.", ""

            matched = next(
                (
                    item for item in state.checklist_items
                    if label.strip().lower() in item.label.lower()
                ),
                None,
            )
            if not matched:
                return (
                    f"⚠️ No item matching '{label}' found. Copy the exact label from the checklist.",
                    _build_checklist_html(state),
                )

            updated = orchestrator.toggle_checklist_item(joiner_id, matched.item_id, completed)
            if not updated:
                return "❌ Could not update the item. Please try again.", _build_checklist_html(state)

            state  = store.get_state(joiner_id)
            action = "marked complete ✅" if completed else "marked incomplete"
            return f"'{matched.label}' {action}.", _build_checklist_html(state)

        tick_btn.click(
            fn=tick_item,
            inputs=[active_joiner_id, tick_label_input, tick_done_input],
            outputs=[tick_msg, checklist_html],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Chat / Ask Anything
        # ────────────────────────────────────────────────────────────────────

        def send_question(joiner_id: str, question: str, history: list):
            """Route question to QA agent and append both turns to chat history."""
            history = history or []

            if not joiner_id:
                history.append((None, "Please load your dashboard first by entering your Joiner ID above."))
                return history, ""

            if not question.strip():
                return history, ""

            answer = orchestrator.answer_question(joiner_id, question.strip())
            history.append((question.strip(), answer))
            return history, ""

        chat_send_btn.click(
            fn=send_question,
            inputs=[active_joiner_id, chat_input, chatbot],
            outputs=[chatbot, chat_input],
        )
        chat_input.submit(
            fn=send_question,
            inputs=[active_joiner_id, chat_input, chatbot],
            outputs=[chatbot, chat_input],
        )
        chat_clear_btn.click(fn=lambda: [], outputs=[chatbot])

        # ────────────────────────────────────────────────────────────────────
        # Event: Refresh Training / Access / Notifications
        # ────────────────────────────────────────────────────────────────────

        def refresh_training(joiner_id: str):
            if not joiner_id:
                return ""
            state = store.get_state(joiner_id)
            return _build_training_html(state) if state else ""

        def refresh_access(joiner_id: str):
            if not joiner_id:
                return ""
            state = store.get_state(joiner_id)
            return _build_access_html(state) if state else ""

        def refresh_notifications(joiner_id: str):
            if not joiner_id:
                return ""
            state = store.get_state(joiner_id)
            if not state:
                return ""
            latest = _latest_notification_title(state)
            if latest:
                gr.Info(latest)
            return _build_notifications_html(state)

        refresh_training_btn.click(
            fn=refresh_training,
            inputs=[active_joiner_id],
            outputs=[training_html],
        )
        refresh_access_btn.click(
            fn=refresh_access,
            inputs=[active_joiner_id],
            outputs=[access_html],
        )
        refresh_notif_btn.click(
            fn=refresh_notifications,
            inputs=[active_joiner_id],
            outputs=[notifications_html],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Load Feedback Questions
        # ────────────────────────────────────────────────────────────────────

        def load_feedback_questions(joiner_id: str, phase_id: int):
            """
            Fetch questions for the chosen phase from the feedback agent.
            Returns updates for the three answer textboxes and the submit button.
            """
            if not joiner_id:
                return (
                    "<p style='color:#C62828'>Load your dashboard first.</p>",
                    gr.update(visible=False, label="Q1"),
                    gr.update(visible=False, label="Q2"),
                    gr.update(visible=False, label="Q3"),
                    gr.update(visible=False),
                    [],
                )

            questions = orchestrator.feedback_agent.get_feedback_questions(int(phase_id))

            q_updates = []
            for i in range(3):
                if i < len(questions):
                    q_updates.append(gr.update(label=questions[i], value="", visible=True))
                else:
                    q_updates.append(gr.update(visible=False))

            header = (
                f'<div class="section-title">Phase {phase_id} Feedback</div>'
                '<p style="font-size:0.9rem;color:#555">Please answer honestly — '
                'your feedback is kept confidential.</p>'
            )
            return header, q_updates[0], q_updates[1], q_updates[2], gr.update(visible=True), questions

        load_questions_btn.click(
            fn=load_feedback_questions,
            inputs=[active_joiner_id, feedback_phase_selector],
            outputs=[
                feedback_questions_html,
                fb_q1, fb_q2, fb_q3,
                submit_feedback_btn,
                active_questions,
            ],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Submit Feedback
        # ────────────────────────────────────────────────────────────────────

        def submit_feedback(
            joiner_id: str,
            phase_id: int,
            questions: list,
            a1: str, a2: str, a3: str,
        ):
            """Pair answers with question labels and route to the feedback agent."""
            if not joiner_id:
                gr.Warning("Please load your dashboard first.")
                return "Please load your dashboard first."

            answers_raw = [a1, a2, a3]
            answers = {
                q: a.strip()
                for q, a in zip(questions, answers_raw)
                if a and a.strip()
            }

            if not answers:
                gr.Warning("Please fill in at least one answer before submitting.")
                return "⚠️ Please fill in at least one answer before submitting."

            result = orchestrator.store_feedback(
                joiner_id=joiner_id,
                phase_id=int(phase_id),
                answers=answers,
            )
            gr.Info("Feedback submitted — thank you! See the 🔔 Notifications tab.")
            return result

        submit_feedback_btn.click(
            fn=submit_feedback,
            inputs=[
                active_joiner_id,
                feedback_phase_selector,
                active_questions,
                fb_q1, fb_q2, fb_q3,
            ],
            outputs=[feedback_result_msg],
        )

    return joiner_ui
