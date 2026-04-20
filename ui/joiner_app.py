"""
ui/joiner_app.py — New Joiner App (Joiner-facing Gradio UI)
============================================================
The onboarding companion that guides a new employee through all 6 phases
of their 90-day onboarding journey.

Tab structure:
  ├── 🗺️ My Journey      (unified phase cards — current phase expanded with checklist)
  ├── 💬 Ask Anything    (KB-grounded chatbot)
  ├── 🎓 My Training     (course table with org brief first)
  ├── 🔑 My Access       (IT ticket status table)
  ├── 📝 Feedback        (pulse survey — phases 3 & 6)
  └── 🔔 Notifications   (welcome + buddy messages only)
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

/* ── Access status badges ────────────────────────── */
.badge-pending     { background: #EEEEEE !important; color: #424242 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
.badge-provisioned { background: #E8F5E9 !important; color: #2E7D32 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }
.badge-blocked     { background: #FFEBEE !important; color: #C62828 !important; padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; }

/* ── Chatbot tweaks ──────────────────────────────── */
.chatbot-wrap .message.bot  { background: #E8F5E9 !important; color: #000000 !important; }
.chatbot-wrap .message.user { background: #C8E6C9 !important; color: #000000 !important; }
"""


# ─────────────────────────────────────────────
# Joiner App Builder
# ─────────────────────────────────────────────

def build_joiner_app(orchestrator, store: StateStore) -> gr.Blocks:
    """
    Build and return the complete Gradio Blocks UI for the new joiner.
    Called by app.py; the orchestrator is injected at startup.
    """

    # ── Helper: build unified phase cards HTML ───────────────────────────────
    # All 6 phases displayed as cards:
    #   complete  → compact green card  (✅)
    #   active    → expanded card with inline checklist
    #   locked    → compact grey card   (🔒)

    def _build_phase_cards_html(state, profile) -> str:
        cards = []
        for ph in PHASES:
            ph_id   = ph.phase_id
            status  = state.phase_statuses.get(ph_id, PhaseStatus.LOCKED)
            is_complete = (status == PhaseStatus.COMPLETE)
            is_current  = (ph_id == state.current_phase and not is_complete)

            if is_complete:
                cards.append(
                    f'<div style="background:#E8F5E9;border:1px solid #A5D6A7;'
                    f'border-left:4px solid #4CAF50;border-radius:8px;padding:12px 16px;'
                    f'margin-bottom:8px;display:flex;align-items:flex-start;gap:12px">'
                    f'  <span style="font-size:1.2rem;margin-top:2px">✅</span>'
                    f'  <div>'
                    f'    <strong style="color:#2E7D32">Phase {ph_id}: {ph.name}</strong>'
                    f'    <span style="font-size:0.82rem;color:#666;margin-left:8px">'
                    f'      Days {ph.day_start}–{ph.day_end}</span>'
                    f'    <div style="font-size:0.83rem;color:#555;margin-top:2px">{ph.objective}</div>'
                    f'  </div>'
                    f'</div>'
                )

            elif is_current:
                items = [c for c in state.checklist_items if c.phase_id == ph_id]
                total = len(items)
                done  = sum(1 for c in items if c.completed)
                pct   = int(done / total * 100) if total else 0

                # Checklist rows
                rows_html = ""
                for item in items:
                    if item.completed:
                        rows_html += (
                            f'<div style="display:flex;align-items:center;gap:10px;'
                            f'padding:8px 12px;margin-bottom:6px;border-radius:6px;'
                            f'background:#E8F5E9;border:1px solid #A5D6A7">'
                            f'  <span style="color:#4CAF50;font-weight:700">✔</span>'
                            f'  <span style="color:#2E7D32;text-decoration:line-through">{item.label}</span>'
                            f'</div>'
                        )
                    else:
                        rows_html += (
                            f'<div style="display:flex;align-items:center;gap:10px;'
                            f'padding:8px 12px;margin-bottom:6px;border-radius:6px;'
                            f'background:#F1F8E9;border:1px solid #C8E6C9">'
                            f'  <span style="color:#A5D6A7">○</span>'
                            f'  <span style="color:#000">{item.label}</span>'
                            f'</div>'
                        )

                # LMS gate notice (green tint instead of orange)
                lms_note = ""
                if ph.system_gated and not state.lms_mandatory_confirmed:
                    lms_note = (
                        '<div style="background:#E8F5E9;border-radius:6px;padding:10px 14px;'
                        'margin-top:10px;font-size:0.88rem;color:#2E7D32;border:1px solid #A5D6A7">'
                        '⏳ <strong>Phase gate:</strong> Your admin must confirm LMS course completion '
                        'before you can mark this phase done. Reach out to your manager if needed.'
                        '</div>'
                    )

                cards.append(
                    f'<div style="background:#FFFFFF;border:1px solid #A5D6A7;'
                    f'border-left:5px solid #4CAF50;border-radius:10px;padding:18px 22px;margin-bottom:16px">'
                    f'  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
                    f'    <h3 style="margin:0;color:#2E7D32;font-size:1.1rem;font-weight:700">'
                    f'      🟢 Phase {ph_id}: {ph.name}'
                    f'      <span style="font-size:0.82rem;color:#777;font-weight:400;margin-left:6px">'
                    f'        Days {ph.day_start}–{ph.day_end}</span></h3>'
                    f'    <span style="font-size:0.88rem;font-weight:600;color:#4CAF50">{done}/{total} done</span>'
                    f'  </div>'
                    f'  <p style="color:#555;font-size:0.9rem;margin:0 0 10px">🎯 {ph.objective}</p>'
                    f'  <div style="background:#E0E0E0;border-radius:6px;height:8px;margin-bottom:14px">'
                    f'    <div style="background:#4CAF50;width:{pct}%;height:100%;border-radius:6px;'
                    f'         transition:width 0.4s"></div>'
                    f'  </div>'
                    f'  {rows_html}'
                    f'  {lms_note}'
                    f'</div>'
                )

            else:
                # Locked future phase
                cards.append(
                    f'<div style="background:#FAFAFA;border:1px solid #E0E0E0;'
                    f'border-left:4px solid #BDBDBD;border-radius:8px;padding:12px 16px;'
                    f'margin-bottom:8px;opacity:0.65;display:flex;align-items:flex-start;gap:12px">'
                    f'  <span style="font-size:1.2rem;margin-top:2px">🔒</span>'
                    f'  <div>'
                    f'    <strong style="color:#757575">Phase {ph_id}: {ph.name}</strong>'
                    f'    <span style="font-size:0.82rem;color:#999;margin-left:8px">'
                    f'      Days {ph.day_start}–{ph.day_end}</span>'
                    f'    <div style="font-size:0.83rem;color:#999;margin-top:2px">{ph.objective}</div>'
                    f'  </div>'
                    f'</div>'
                )

        # Completion banner
        if state.onboarding_complete:
            cards.append(
                '<div style="background:#E8F5E9;border-radius:10px;padding:22px;'
                'text-align:center;margin-top:16px;border:1px solid #A5D6A7">'
                '  <span style="font-size:2rem">🎉</span>'
                '  <h3 style="margin:8px 0 4px;color:#2E7D32">Onboarding Complete!</h3>'
                "  <p style=\"color:#555;margin:0\">You've finished all 6 phases. Welcome fully aboard!</p>"
                '</div>'
            )

        return "\n".join(cards)

    # ── Helper: checklist dropdown choices for current phase ─────────────────

    def _get_checklist_dropdown_choices(state) -> list[str]:
        """Return all checklist item labels for the current phase (for dropdown)."""
        items = [c for c in state.checklist_items if c.phase_id == state.current_phase]
        return [item.label for item in items]

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
                f"<tr style='border-bottom:1px solid #E0E0E0'>"
                f"  <td style='padding:8px 12px;color:#000'>{req.tool_name}</td>"
                f"  <td style='padding:8px 12px;color:#000'>{req.permission_level or '—'}</td>"
                f"  <td style='padding:8px 12px'><span class='{badge_cls}'>{status_label}</span></td>"
                f"  <td style='padding:8px 12px;font-size:0.82rem;color:#777'>{req.ticket_id}</td>"
                f"</tr>"
            )

        return (
            '<table style="width:100%;border-collapse:collapse;font-size:0.9rem">'
            '<thead><tr style="background:#E8F5E9;border-bottom:2px solid #4CAF50">'
            '  <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Tool</th>'
            '  <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Permission</th>'
            '  <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Status</th>'
            '  <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Ticket ID</th>'
            '</tr></thead>'
            '<tbody>' + "\n".join(rows) + "</tbody></table>"
        )

    # ── Helper: build training table HTML ────────────────────────────────────

    def _build_training_html(state) -> str:
        """
        Render the training plan as a Course Name | Status table.
        Org brief is always the first row. Courses are parsed from the
        training plan notification; falls back to Phase 3 checklist.
        """
        rows = []

        # Row 1: Org & Role Brief (always present — delivered via org_agent in Phase 1)
        rows.append((
            "🏢 Org & Role Brief — company vision, structure, and your role fit",
            "📖 Self-paced (see Notifications)",
        ))

        # Try to find training plan notification
        plan_notif = next(
            (n for n in state.app_notifications if "Training Plan" in n or "🎓" in n),
            None,
        )

        if plan_notif:
            # Parse bullet-point lines from the notification text
            for line in plan_notif.splitlines():
                stripped = line.strip()
                if stripped.startswith(("- ", "• ", "* ")):
                    course = stripped[2:].strip()
                    if not course:
                        continue
                    is_mandatory = any(
                        kw in course.lower()
                        for kw in ["gdpr", "security", "compliance", "code of conduct",
                                   "mandatory", "required", "data privacy", "ethics"]
                    )
                    status = "✅ Mandatory" if is_mandatory else "📘 Recommended"
                    rows.append((course, status))
        else:
            # Fallback: show Phase 3 checklist items as pending courses
            from core.config import PHASE_BY_ID as _PBY
            phase3 = _PBY.get(3)
            if phase3:
                for item in phase3.checklist:
                    rows.append((item, "⏳ Pending"))

        # Render table
        tbody = "\n".join(
            f"<tr style='border-bottom:1px solid #E0E0E0'>"
            f"  <td style='padding:10px 12px;color:#000'>{name}</td>"
            f"  <td style='padding:10px 12px;color:#000'>{status}</td>"
            f"</tr>"
            for name, status in rows
        )

        return (
            '<table style="width:100%;border-collapse:collapse;font-size:0.9rem">'
            '<thead>'
            '  <tr style="background:#E8F5E9;border-bottom:2px solid #4CAF50">'
            '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Course Name</th>'
            '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Status</th>'
            '  </tr>'
            '</thead>'
            f'<tbody>{tbody}</tbody>'
            '</table>'
        )

    # ── Helper: extract a short title from a notification string ─────────────

    def _extract_title(notif: str) -> str:
        m = re.search(r"\*\*([^*]+)\*\*", notif)
        if m:
            t = m.group(1).strip()
            return t[:90] + ("…" if len(t) > 90 else "")
        first = next((ln for ln in notif.splitlines() if ln.strip()), "").strip()
        if first:
            return first[:70] + ("…" if len(first) > 70 else "")
        return "Notification"

    def _markdown_to_html(txt: str) -> str:
        txt = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = txt.split("**")
        out = ""
        for i, part in enumerate(parts):
            out += ("<strong>" if i % 2 == 1 else "") + part
            if i % 2 == 1:
                out += "</strong>"
        return out.replace("\n\n", "<br><br>").replace("\n", "<br>")

    # ── Helper: build notifications list (welcome + buddy only) ──────────────

    def _build_notifications_html(state) -> str:
        """
        Render notifications as a collapsible list.
        Only shows welcome and buddy-related messages — training, IT access,
        and org brief have their own dedicated tabs.
        """
        if not state.app_notifications:
            return (
                "<p style='padding:20px;text-align:center;color:#616161'>"
                "No notifications yet. Your welcome message and buddy intro will appear here.</p>"
            )

        # Filter: show only welcome and buddy messages
        visible = [
            n for n in reversed(state.app_notifications)
            if any(kw in n.lower() for kw in ["welcome", "buddy", "👋", "🌱", "congratulations"])
        ]

        if not visible:
            return (
                "<p style='padding:20px;text-align:center;color:#616161'>"
                "Your welcome message and buddy intro will appear here once your onboarding is activated.</p>"
            )

        items = []
        for notif in visible:
            title = _extract_title(notif).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            body  = _markdown_to_html(notif)
            items.append(
                f'<details class="notif-item">'
                f'  <summary><span class="notif-title-text">{title}</span></summary>'
                f'  <div class="notif-body"'
                f'       style="background:#F1F8E9;border-radius:6px;padding:14px 16px;'
                f'              margin-top:10px;border:1px solid #C8E6C9;line-height:1.7;'
                f'              color:#000000 !important">'
                f'    {body}'
                f'  </div>'
                f'</details>'
            )
        return "\n".join(items)

    def _latest_notification_title(state) -> str | None:
        if not state or not state.app_notifications:
            return None
        return _extract_title(state.app_notifications[-1])

    # ────────────────────────────────────────────────────────────────────────
    # Gradio Blocks UI
    # ────────────────────────────────────────────────────────────────────────

    light_theme = gr.themes.Soft(
        primary_hue="green", secondary_hue="green", neutral_hue="gray",
    ).set(
        # Force white/light backgrounds even when OS is in dark mode
        body_background_fill="#F1F8E9",
        body_background_fill_dark="#F1F8E9",
        background_fill_primary="#FFFFFF",
        background_fill_primary_dark="#FFFFFF",
        background_fill_secondary="#F1F8E9",
        background_fill_secondary_dark="#F1F8E9",
        block_background_fill="#FFFFFF",
        block_background_fill_dark="#FFFFFF",
        panel_background_fill="#FFFFFF",
        panel_background_fill_dark="#FFFFFF",
        input_background_fill="#FFFFFF",
        input_background_fill_dark="#FFFFFF",
        input_background_fill_focus="#FFFFFF",
        input_background_fill_focus_dark="#FFFFFF",
        # Text
        body_text_color="#000000",
        body_text_color_dark="#000000",
        body_text_color_subdued="#616161",
        body_text_color_subdued_dark="#616161",
        block_label_text_color="#000000",
        block_label_text_color_dark="#000000",
        block_title_text_color="#2E7D32",
        block_title_text_color_dark="#2E7D32",
        # Borders
        border_color_primary="#A5D6A7",
        border_color_primary_dark="#A5D6A7",
        block_border_color="#A5D6A7",
        block_border_color_dark="#A5D6A7",
        input_border_color="#E0E0E0",
        input_border_color_dark="#E0E0E0",
        input_placeholder_color="#9E9E9E",
        input_placeholder_color_dark="#9E9E9E",
        # Primary button
        button_primary_background_fill="#4CAF50",
        button_primary_background_fill_dark="#4CAF50",
        button_primary_background_fill_hover="#388E3C",
        button_primary_background_fill_hover_dark="#388E3C",
        button_primary_text_color="#FFFFFF",
        button_primary_text_color_dark="#FFFFFF",
        # Secondary button
        button_secondary_background_fill="#FFFFFF",
        button_secondary_background_fill_dark="#FFFFFF",
        button_secondary_text_color="#000000",
        button_secondary_text_color_dark="#000000",
        button_secondary_border_color="#E0E0E0",
        button_secondary_border_color_dark="#E0E0E0",
        # Table
        table_even_background_fill="#FFFFFF",
        table_even_background_fill_dark="#FFFFFF",
        table_odd_background_fill="#F1F8E9",
        table_odd_background_fill_dark="#F1F8E9",
    )
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
                gr.Markdown(
                    "Your 6-phase onboarding journey. Your **current phase** is expanded "
                    "with an interactive checklist — tick items off as you complete them. "
                    "Completed and upcoming phases are shown as summary cards."
                )

                # Unified phase cards (current expanded, others compact)
                phase_cards_html = gr.HTML("")

                # Tick off a checklist item
                gr.HTML(
                    '<div style="font-size:1rem;font-weight:700;color:#2E7D32;'
                    'margin:20px 0 12px;padding:0 0 6px;border-bottom:2px solid #4CAF50;'
                    'background:transparent">Tick Off a Checklist Item</div>'
                )
                with gr.Row():
                    tick_item_dropdown = gr.Dropdown(
                        label="Select item",
                        choices=[],
                        scale=4,
                    )
                    tick_done_input = gr.Checkbox(label="Mark as complete", value=True, scale=1)
                    tick_btn = gr.Button("Update", size="sm", scale=1)
                tick_msg = gr.Markdown("")

                with gr.Row():
                    refresh_journey_btn = gr.Button("🔄 Refresh", size="sm")
                    mark_complete_btn   = gr.Button(
                        "✅ Mark Phase Complete", variant="primary", size="sm"
                    )
                advance_msg = gr.Markdown("")

            # ── TAB 2: Ask Anything ──────────────────────────────────────────
            with gr.Tab("💬 Ask Anything"):
                gr.Markdown(
                    "### Ask Me Anything\n"
                    "Ask any question about the company, your role, tools, processes, or anything "
                    "else you'd like to know. I'll search the knowledge base to help you."
                )
                chatbot = gr.Chatbot(
                    label="OnboardingBuddy Chat",
                    elem_classes=["chatbot-wrap"],
                    height=400,
                )
                with gr.Row():
                    chat_input = gr.Textbox(
                        label="Your question",
                        placeholder="How does the performance review process work?",
                        scale=5,
                        max_lines=2,
                    )
                    chat_send_btn = gr.Button("Send", variant="primary", scale=1)
                chat_clear_btn = gr.Button("🗑️ Clear Chat", size="sm")

            # ── TAB 3: My Training ───────────────────────────────────────────
            with gr.Tab("🎓 My Training"):
                gr.Markdown(
                    "### Your Learning Plan\n"
                    "Your personalised course list for the first 90 days. "
                    "The **Org & Role Brief** (first row) gives you strategic context about the company. "
                    "Mandatory LMS courses must be completed before Phase 3 can be marked done."
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
                    "### Personal Messages\n"
                    "Your welcome message and buddy intro from OnboardingBuddy. "
                    "**Click any row to expand its full content.** "
                    "Training and access information are available in their dedicated tabs."
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
                    "",              # phase_cards_html
                    gr.update(),     # tick_item_dropdown
                    "", "", "",      # training, access, notifications
                )

            ph_name = PHASE_BY_ID[state.current_phase].name
            status_html = (
                f'<p style="color:#2E7D32">✅ Welcome back, '
                f'<strong>{profile.full_name}</strong>! '
                f'Currently on Phase {state.current_phase}: {ph_name}</p>'
            )

            latest = _latest_notification_title(state)
            if latest:
                count  = len(state.app_notifications)
                plural = "notification" if count == 1 else "notifications"
                gr.Info(
                    f"{latest}  ·  ({count} {plural} — see the 🔔 Notifications tab)"
                )

            choices = _get_checklist_dropdown_choices(state)
            return (
                gr.update(value=status_html),
                gr.update(visible=True),
                joiner_id,
                _build_phase_cards_html(state, profile),
                gr.update(choices=choices, value=choices[0] if choices else None),
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
                phase_cards_html,
                tick_item_dropdown,
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
                return "", gr.update()
            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            if not state or not profile:
                return "", gr.update()
            choices = _get_checklist_dropdown_choices(state)
            return (
                _build_phase_cards_html(state, profile),
                gr.update(choices=choices, value=choices[0] if choices else None),
            )

        refresh_journey_btn.click(
            fn=refresh_journey,
            inputs=[active_joiner_id],
            outputs=[phase_cards_html, tick_item_dropdown],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Mark Phase Complete
        # ────────────────────────────────────────────────────────────────────

        def mark_phase_complete(joiner_id: str):
            if not joiner_id:
                gr.Warning("Please load your dashboard first.")
                return "Please load your dashboard first.", "", gr.update()

            success, msg = orchestrator.advance_phase(joiner_id)

            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            cards   = ""
            choices = []
            if state and profile:
                cards   = _build_phase_cards_html(state, profile)
                choices = _get_checklist_dropdown_choices(state)

            if success:
                gr.Info(msg)
            else:
                gr.Warning(msg)

            prefix = "✅ " if success else "⚠️ "
            return (
                prefix + msg,
                cards,
                gr.update(choices=choices, value=choices[0] if choices else None),
            )

        mark_complete_btn.click(
            fn=mark_phase_complete,
            inputs=[active_joiner_id],
            outputs=[advance_msg, phase_cards_html, tick_item_dropdown],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Tick Checklist Item
        # ────────────────────────────────────────────────────────────────────

        def tick_item(joiner_id: str, label: str, completed: bool):
            if not joiner_id or not label:
                return "Please load your dashboard and select a checklist item.", "", gr.update()

            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            if not state:
                return "Could not load your record. Try refreshing.", "", gr.update()

            # Exact match from dropdown
            matched = next(
                (item for item in state.checklist_items if item.label == label),
                None,
            )
            if not matched:
                return (
                    f"⚠️ Item not found. Please refresh and try again.",
                    _build_phase_cards_html(state, profile),
                    gr.update(),
                )

            updated = orchestrator.toggle_checklist_item(joiner_id, matched.item_id, completed)
            if not updated:
                return "❌ Could not update. Please try again.", _build_phase_cards_html(state, profile), gr.update()

            state   = store.get_state(joiner_id)
            profile = store.get_profile(joiner_id)
            action  = "marked complete ✅" if completed else "marked incomplete"
            choices = _get_checklist_dropdown_choices(state)
            return (
                f"'{matched.label}' {action}.",
                _build_phase_cards_html(state, profile),
                gr.update(choices=choices, value=choices[0] if choices else None),
            )

        tick_btn.click(
            fn=tick_item,
            inputs=[active_joiner_id, tick_item_dropdown, tick_done_input],
            outputs=[tick_msg, phase_cards_html, tick_item_dropdown],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Chat / Ask Anything
        # ────────────────────────────────────────────────────────────────────

        def send_question(joiner_id: str, question: str, history: list):
            # Gradio 6.12 Chatbot expects messages-dict format:
            # {"role": "user"|"assistant", "content": "..."}
            history = history or []
            if not joiner_id:
                history.append({"role": "assistant", "content": "Please load your dashboard first by entering your Joiner ID above."})
                return history, ""
            if not question.strip():
                return history, ""
            answer = orchestrator.answer_question(joiner_id, question.strip())
            history.append({"role": "user",      "content": question.strip()})
            history.append({"role": "assistant", "content": answer})
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
            fn=refresh_training, inputs=[active_joiner_id], outputs=[training_html],
        )
        refresh_access_btn.click(
            fn=refresh_access, inputs=[active_joiner_id], outputs=[access_html],
        )
        refresh_notif_btn.click(
            fn=refresh_notifications, inputs=[active_joiner_id], outputs=[notifications_html],
        )

        # ────────────────────────────────────────────────────────────────────
        # Event: Load Feedback Questions
        # ────────────────────────────────────────────────────────────────────

        def load_feedback_questions(joiner_id: str, phase_id: int):
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
                f'<div style="font-size:1rem;font-weight:700;color:#2E7D32;'
                f'margin:0 0 8px;padding:0 0 6px;border-bottom:2px solid #4CAF50">'
                f'Phase {phase_id} Feedback</div>'
                '<p style="font-size:0.9rem;color:#555;margin:0 0 12px">Please answer honestly — '
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
