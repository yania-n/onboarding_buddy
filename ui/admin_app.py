"""
ui/admin_app.py — Admin Portal (Manager-facing Gradio UI)
==========================================================
The manager's interface for:
  1. Creating new joiner records → triggers the full onboarding pipeline
  2. Monitoring all active joiners (phase, sentiment, access status)
  3. Reviewing the knowledge gap backlog
  4. Confirming LMS completion (Phase 3 gate unlock)
  5. Manager weekly summary reports

Tab structure:
  ├── ➕ Add New Joiner     (form with dropdowns from config library)
  ├── 📋 Active Joiners     (progress dashboard)
  ├── 🔍 Knowledge Gaps     (unanswered Q&A log)
  └── 📊 Reports            (weekly summary + sentiment overview)

Colour theme: grass green (#4CAF50), black, white.
All state changes go through the Orchestrator — the UI never writes to
the store directly.
"""

import uuid
from datetime import date, datetime

import gradio as gr

from core.config import (
    BUSINESS_UNITS, DIVISIONS, DEPARTMENTS, TEAMS, ROLES,
    SENIORITY_LEVELS, ALL_TOOLS, ALL_PERMISSION_LEVELS,
    PHASE_BY_ID, GLOBAL_CSS_VARS,
)
from core.models import JoinerProfile, PhaseStatus
from core.state_store import StateStore


# ─────────────────────────────────────────────
# Admin activity log (in-memory, session-scoped)
# ─────────────────────────────────────────────
# Each entry: dict with keys: ts (ISO), title (short), body (full html/text).
# Rendered in the 🔔 Notifications tab as a click-to-expand list.
_ADMIN_NOTIFICATIONS: list[dict] = []


def _push_admin_notification(title: str, body: str) -> None:
    """Append an admin activity record to the session log."""
    _ADMIN_NOTIFICATIONS.insert(0, {
        "ts":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": title,
        "body":  body,
    })


def _render_admin_notifications() -> str:
    """Render the admin notification log as collapsible <details> items."""
    if not _ADMIN_NOTIFICATIONS:
        return (
            '<p class="ob-muted" style="padding:20px;text-align:center">'
            'No activity yet. Notifications will appear here as you create joiners, '
            'resolve knowledge gaps, and confirm LMS completions.</p>'
        )
    items = []
    for n in _ADMIN_NOTIFICATIONS:
        items.append(
            f'<details class="notif-item">'
            f'  <summary>'
            f'    <span class="notif-title-text">{n["title"]}</span>'
            f'    <span class="notif-time">{n["ts"]}</span>'
            f'  </summary>'
            f'  <div class="notif-body">{n["body"]}</div>'
            f'</details>'
        )
    return "\n".join(items)


# ─────────────────────────────────────────────
# Shared CSS — Grass Green + Black + White theme
# ─────────────────────────────────────────────

ADMIN_CSS = GLOBAL_CSS_VARS + """
/* ── Admin header — green gradient, white text ── */
.admin-header {
    background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%) !important;
    color: #FFFFFF !important;
    padding: 24px 32px;
    border-radius: 12px;
    margin-bottom: 20px;
    border: none !important;
}
.admin-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; color: #FFFFFF !important; }
.admin-header p  { margin: 4px 0 0; opacity: 0.9; font-size: 0.95rem; color: #FFFFFF !important; }

/* Admin-only utility rows — transparent so they don't show as white bands */
.admin-util-row { background: transparent !important; padding: 0 !important; }

/* ── Joiner cards ────────────────────────── */
.joiner-card {
    background: #FFFFFF !important;
    border: 1px solid #A5D6A7 !important;
    border-left: 4px solid #4CAF50 !important;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.07);
    color: #000000 !important;
}
.joiner-card * { color: #000000 !important; }
.phase-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    background: #4CAF50 !important;
    color: #FFFFFF !important;
}
.phase-complete { background: #2E7D32 !important; color: #FFFFFF !important; }

/* ── Sentiment ───────────────────────────── */
.sentiment-positive   { color: #2E7D32 !important; font-weight: 600; }
.sentiment-neutral    { color: #616161 !important; }
.sentiment-concerning { color: #C62828 !important; font-weight: 600; }

/* ── Status messages ─────────────────────── */
.ob-success {
    background: #E8F5E9 !important;
    border: 1px solid #4CAF50 !important;
    border-radius: 8px;
    padding: 14px 18px;
    color: #1B5E20 !important;
    font-weight: 500;
}
.ob-error {
    background: #FFEBEE !important;
    border: 1px solid #C62828 !important;
    border-radius: 8px;
    padding: 10px 14px;
    color: #B71C1C !important;
}
.ob-muted { color: #616161 !important; }

/* ── Knowledge gap items ─────────────────── */
.gap-item {
    background: #F1F8E9 !important;
    border-left: 4px solid #4CAF50 !important;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    color: #000000 !important;
    margin-bottom: 8px;
    font-size: 0.9rem;
}

/* ── Tool tags ───────────────────────────── */
.tool-tag {
    display: inline-block;
    background: #81C784 !important;
    color: #1B5E20 !important;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.8rem;
    margin: 2px;
    font-weight: 600;
}

/* ── Buttons ─────────────────────────────── */
.gr-button-primary { background: #4CAF50 !important; color: #FFFFFF !important; }
.gr-button-primary:hover { background: #388E3C !important; }

/* ── Report / summary blocks ─────────────── */
.report-block {
    background: #FFFFFF !important;
    border: 1px solid #A5D6A7 !important;
    border-radius: 10px;
    padding: 20px 24px;
    color: #000000 !important;
}
.report-block * { color: #000000 !important; }
.report-block h2, .report-block h3 { color: #2E7D32 !important; }
"""


# ─────────────────────────────────────────────
# HTML rendering helpers
# ─────────────────────────────────────────────

def _render_dashboard(store: StateStore) -> str:
    """Render the active joiners progress dashboard as an HTML table."""
    profiles = store.list_profiles()
    if not profiles:
        return (
            '<p class="ob-muted" style="padding:20px;text-align:center">'
            'No joiners registered yet. Use the <strong>Add New Joiner</strong> tab to get started.</p>'
        )

    rows = []
    for profile in profiles:
        state = store.get_state(profile.joiner_id)
        if not state:
            continue

        phase_def  = PHASE_BY_ID.get(state.current_phase)
        phase_name = phase_def.name if phase_def else "Unknown"
        complete   = state.onboarding_complete

        # Checklist progress
        total = len(state.checklist_items)
        done  = sum(1 for c in state.checklist_items if c.completed)
        pct   = int(done / total * 100) if total else 0

        # Access summary
        pending      = sum(1 for r in state.access_requests if r.status.value == "pending")
        provisioned  = sum(1 for r in state.access_requests if r.status.value == "provisioned")

        # Latest sentiment
        sentiment_label = "No feedback yet"
        if state.feedback_responses:
            latest = state.feedback_responses[-1]
            if latest.sentiment:
                s = latest.sentiment.value
                sentiment_label = {
                    "positive":   "😊 Positive",
                    "neutral":    "😐 Neutral",
                    "concerning": "⚠️ Needs attention",
                }.get(s, s)

        phase_badge  = "✅ Complete" if complete else f"Phase {state.current_phase}: {phase_name}"
        badge_color  = "#2E7D32" if complete else "#4CAF50"

        TD = "padding:10px 12px;color:#000000;background-color:#FFFFFF"
        rows.append(
            f"<tr style='border-bottom:1px solid #E0E0E0;background-color:#FFFFFF'>"
            f"  <td style='{TD}'>"
            f"    <strong style='color:#000000'>{profile.full_name}</strong><br>"
            f"    <span style='font-size:0.8rem;color:#616161'>{profile.job_title}</span>"
            f"  </td>"
            f"  <td style='{TD}'>{profile.department}</td>"
            f"  <td style='{TD}'>{profile.team}</td>"
            f"  <td style='{TD}'>{profile.manager_name}</td>"
            f"  <td style='{TD}'>"
            f"    <span style='background:{badge_color};color:#ffffff;padding:3px 10px;"
            f"           border-radius:12px;font-size:0.82rem;font-weight:600'>"
            f"      {phase_badge}"
            f"    </span>"
            f"  </td>"
            f"  <td style='{TD}'>{done}/{total} ({pct}%)</td>"
            f"  <td style='{TD}'>✅ {provisioned} · ⏳ {pending}</td>"
            f"  <td style='{TD}'>{sentiment_label}</td>"
            f"  <td style='{TD}'>"
            f"    <code style='font-size:0.75rem;color:#616161;background:#F1F8E9'>{profile.joiner_id[:8]}…</code>"
            f"  </td>"
            f"</tr>"
        )

    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.9rem">'
        '<thead>'
        '  <tr style="background:#E8F5E9;border-bottom:2px solid #4CAF50">'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Name</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Dept</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Team</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Manager</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Phase</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Progress</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Access</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Sentiment</th>'
        '    <th style="padding:10px 12px;text-align:left;color:#2E7D32;font-weight:700;background:#E8F5E9">Joiner ID</th>'
        '  </tr>'
        '</thead>'
        '<tbody>' + "\n".join(rows) + '</tbody>'
        '</table>'
    )


def _render_gaps(store: StateStore) -> str:
    """Render the knowledge gaps list as HTML."""
    gaps = store.list_knowledge_gaps(resolved=False)
    if not gaps:
        return (
            '<p style="color:var(--ob-success);padding:20px;text-align:center">'
            '✅ No open knowledge gaps — the KB is covering all questions!</p>'
        )

    items = []
    for g in sorted(gaps, key=lambda x: x.get("asked_at", ""), reverse=True):
        jid_short = g.get("joiner_id", "")[:8]
        items.append(f"""
        <div class="gap-item">
          <div style="font-weight:600;margin-bottom:2px;color:var(--ob-text)">{g['question']}</div>
          <div class="ob-muted" style="font-size:0.8rem">
            Gap ID: <code>{g['gap_id'][:8]}…</code> ·
            Joiner: {jid_short}… ·
            Asked: {g.get('asked_at','')[:16]}
          </div>
        </div>
        """)

    return (
        f'<p class="ob-muted" style="font-size:0.9rem;margin-bottom:12px">'
        f'{len(gaps)} open gap(s) — review and add missing docs to the KB.</p>'
        + "\n".join(items)
    )


# ─────────────────────────────────────────────
# Main build function
# ─────────────────────────────────────────────

def build_admin_app(orchestrator, store: StateStore) -> gr.Blocks:
    """
    Build and return the Admin Gradio Blocks app.
    Injected dependencies: orchestrator (shared), store (shared).
    """

    # NOTE (Gradio 6.0): css= and theme= are no longer accepted by gr.Blocks().
    # They are passed to launch() in app.py via LIGHT_THEME and COMBINED_CSS.
    with gr.Blocks(title="OnboardingBuddy — Admin Portal") as admin_app:

        # ── Header ────────────────────────────────────────────────────────────
        gr.HTML("""
        <div style="background:linear-gradient(135deg,#2E7D32 0%,#4CAF50 100%);
                    color:#FFFFFF;padding:22px 28px;border-radius:10px;
                    margin-bottom:16px;display:flex;align-items:center;gap:16px;">
          <div style="font-size:2.4rem;line-height:1">🧭</div>
          <div>
            <div style="font-size:1.5rem;font-weight:700;color:#FFFFFF;margin:0 0 4px">
              OnboardingBuddy &mdash; Admin Portal
            </div>
            <div style="font-size:0.9rem;color:#C8E6C9;margin:0">
              Manager &amp; HR view &middot; Create joiners, track progress, review knowledge gaps
            </div>
          </div>
        </div>
        """)

        with gr.Tabs():

            # ══════════════════════════════════════════════════════════════════
            # TAB 1 — Add New Joiner
            # ══════════════════════════════════════════════════════════════════
            with gr.Tab("➕ Add New Joiner"):
                gr.Markdown(
                    "Fill in all details below. Submitting this form activates the full "
                    "onboarding pipeline — org brief, access tickets, training plan, "
                    "and buddy intro all fire in parallel."
                )

                # ── Section: Personal details ────────────────────────────────
                with gr.Group(elem_classes=["form-section"]):
                    gr.HTML('<div class="section-title">Personal Details</div>')
                    with gr.Row():
                        nj_name  = gr.Textbox(label="Full Name *", placeholder="e.g. Priya Sharma")
                        nj_email = gr.Textbox(label="Work Email *", placeholder="priya.sharma@company.com")
                        nj_start = gr.Textbox(
                            label="Start Date * (YYYY-MM-DD)",
                            value=str(date.today()),
                        )

                # ── Section: Role & placement ────────────────────────────────
                with gr.Group(elem_classes=["form-section"]):
                    gr.HTML('<div class="section-title">Role & Placement</div>')
                    with gr.Row():
                        nj_bu       = gr.Dropdown(label="Business Unit *", choices=BUSINESS_UNITS,
                                                  value=BUSINESS_UNITS[0])
                        nj_division = gr.Dropdown(label="Division *", choices=DIVISIONS,
                                                  value=DIVISIONS[0])
                        nj_dept     = gr.Dropdown(label="Department *", choices=DEPARTMENTS,
                                                  value=DEPARTMENTS[0])
                        nj_team     = gr.Dropdown(label="Team *", choices=TEAMS,
                                                  value=TEAMS[0])

                    with gr.Row():
                        nj_role      = gr.Dropdown(label="Role *", choices=ROLES, value=ROLES[0])
                        nj_seniority = gr.Dropdown(label="Seniority *", choices=SENIORITY_LEVELS,
                                                   value=SENIORITY_LEVELS[0])
                        nj_role_desc = gr.Textbox(
                            label="Role Description (optional)",
                            placeholder="Brief description of responsibilities…",
                            lines=2,
                        )

                # ── Section: Manager & Buddy ─────────────────────────────────
                with gr.Group(elem_classes=["form-section"]):
                    gr.HTML('<div class="section-title">Manager & Buddy</div>')
                    with gr.Row():
                        nj_mgr_name  = gr.Textbox(label="Manager Name *", placeholder="e.g. David Chen")
                        nj_mgr_email = gr.Textbox(label="Manager Email *",
                                                  placeholder="d.chen@company.com")
                    with gr.Row():
                        nj_buddy_name  = gr.Textbox(label="Buddy Name *", placeholder="e.g. Sara Okonkwo")
                        nj_buddy_email = gr.Textbox(label="Buddy Email *",
                                                    placeholder="s.okonkwo@company.com")
                        nj_buddy_cal   = gr.Textbox(
                            label="Buddy Calendar Link (optional)",
                            placeholder="https://calendly.com/sara-okonkwo",
                        )

                # ── Section: Tool Access ─────────────────────────────────────
                with gr.Group(elem_classes=["form-section"]):
                    gr.HTML('<div class="section-title">Tool & System Access</div>')
                    gr.Markdown(
                        "Select the tools this joiner needs. Then specify the permission level "
                        "for each in the box below (one per line: `Tool Name: Permission Level`)."
                    )
                    with gr.Row():
                        nj_tools_select = gr.Dropdown(
                            label="Select Tools",
                            choices=ALL_TOOLS,
                            multiselect=True,
                            value=[],
                            scale=2,
                        )
                    nj_tools_text = gr.Textbox(
                        label="Tool Access List (auto-filled — edit permission levels as needed)",
                        placeholder="Microsoft 365 (Outlook, Word, Excel, PowerPoint): Standard User\nJira: Standard User",
                        lines=5,
                    )

                    # Auto-fill the text box when tools are selected from dropdown
                    def _fill_tool_text(selected_tools: list[str]) -> str:
                        return "\n".join(f"{t}: Standard User" for t in selected_tools)

                    nj_tools_select.change(
                        fn=_fill_tool_text,
                        inputs=[nj_tools_select],
                        outputs=[nj_tools_text],
                    )

                # ── Section: Phase customisations ────────────────────────────
                with gr.Group(elem_classes=["form-section"]):
                    gr.HTML('<div class="section-title">Phase Customisations (optional)</div>')
                    nj_phase_ext = gr.Textbox(
                        label="Phase extensions (format: phase_id:extra_days, comma-separated)",
                        placeholder="e.g. 3:5  → extend Phase 3 by 5 days",
                        lines=1,
                    )

                # ── Submit row ───────────────────────────────────────────────
                with gr.Row(elem_classes=["admin-util-row"]):
                    nj_submit = gr.Button(
                        "🚀 Create Joiner & Activate Onboarding",
                        variant="primary", scale=2,
                    )
                    nj_clear = gr.Button("Clear Form", variant="secondary", scale=1)

                # Inline status line (just one line of confirmation — the rich
                # detail now goes into a toast popup AND the Notifications tab).
                nj_status = gr.Markdown("")

                # ── Submit handler ───────────────────────────────────────────
                async def submit_new_joiner(
                    name, email, start,
                    bu, division, dept, team, role, seniority, role_desc,
                    mgr_name, mgr_email,
                    buddy_name, buddy_email, buddy_cal,
                    tools_text, phase_ext_text,
                ):
                    # Validate required fields
                    required = {
                        "Full Name": name, "Work Email": email, "Start Date": start,
                        "Business Unit": bu, "Division": division, "Department": dept,
                        "Team": team, "Role": role,
                        "Manager Name": mgr_name, "Manager Email": mgr_email,
                        "Buddy Name": buddy_name, "Buddy Email": buddy_email,
                    }
                    missing = [k for k, v in required.items() if not str(v).strip()]
                    if missing:
                        gr.Warning("Missing required fields: " + ", ".join(missing))
                        return "", _render_admin_notifications()

                    # Parse start date
                    try:
                        start_date = date.fromisoformat(start.strip())
                    except ValueError:
                        gr.Warning("Start date must be in YYYY-MM-DD format.")
                        return "", _render_admin_notifications()

                    # Parse tool access (one per line: "Tool: Permission")
                    tool_access: dict[str, str] = {}
                    for line in tools_text.strip().splitlines():
                        if ":" in line:
                            parts = line.split(":", 1)
                            tool_access[parts[0].strip()] = parts[1].strip()

                    # Parse phase extensions (e.g. "3:5,4:3")
                    phase_extensions: dict[int, int] = {}
                    if phase_ext_text.strip():
                        for part in phase_ext_text.split(","):
                            part = part.strip()
                            if ":" in part:
                                try:
                                    pid, days = part.split(":", 1)
                                    phase_extensions[int(pid.strip())] = int(days.strip())
                                except ValueError:
                                    pass

                    # Build the JoinerProfile
                    profile = JoinerProfile(
                        joiner_id         = store.new_joiner_id(),
                        full_name         = name.strip(),
                        email             = email.strip(),
                        start_date        = start_date,
                        job_title         = role.strip(),
                        seniority         = seniority,
                        business_unit     = bu,
                        division          = division,
                        department        = dept,
                        team              = team,
                        role_description  = role_desc.strip(),
                        manager_name      = mgr_name.strip(),
                        manager_email     = mgr_email.strip(),
                        buddy_name        = buddy_name.strip(),
                        buddy_email       = buddy_email.strip(),
                        buddy_calendar_link = buddy_cal.strip() or None,
                        tool_access       = tool_access,
                        phase_extensions  = phase_extensions,
                        created_by        = mgr_email.strip(),
                    )

                    # Activate — fires all agents as concurrent async tasks (non-blocking)
                    await orchestrator.activate_new_joiner(profile)

                    # Build the long-form body (goes into the Notification tab only)
                    tool_lines = "".join(
                        f"<li>{t} — {v}</li>" for t, v in tool_access.items()
                    ) or "<li>No tools configured</li>"

                    body = f"""
                        <p><strong>Joiner ID:</strong> <code>{profile.joiner_id}</code></p>
                        <p><strong>Role:</strong> {role} · {dept} · {team}</p>
                        <p><strong>Start Date:</strong> {start}</p>
                        <p><strong>Phase 1: Welcome</strong> is now active.</p>
                        <p style="margin-top:10px"><strong>Actions triggered in parallel:</strong></p>
                        <ul>
                          <li>🏢 Org &amp; role context brief (for joiner's Day 1)</li>
                          <li>🔐 IT access tickets raised: <ul>{tool_lines}</ul></li>
                          <li>📚 Training plan built (Phase 3 ready)</li>
                          <li>👋 Buddy intro message sent to {buddy_name}</li>
                        </ul>
                        <p style="margin-top:10px;font-size:0.88rem;opacity:0.85">
                          Share the <strong>My Onboarding Journey</strong> tab with {name}
                          and have them enter their Joiner ID to access their experience.
                        </p>
                    """

                    # Log to Notifications tab (short title + full body)
                    _push_admin_notification(
                        title=f"✅ Onboarding activated for {name} ({role})",
                        body=body,
                    )

                    # Fire the popup (toast) with a message + built-in close
                    gr.Info(
                        f"Onboarding activated for {name}. "
                        f"Joiner ID: {profile.joiner_id}. "
                        f"See the Notifications tab for full details."
                    )

                    # Inline one-liner on the form itself
                    inline_status = (
                        f"✅ **{name}** is now onboarding. "
                        f"Joiner ID: `{profile.joiner_id}` — full details in the "
                        "🔔 Notifications tab."
                    )
                    return inline_status, _render_admin_notifications()

                def clear_form():
                    return (
                        "", "", str(date.today()),           # name, email, start
                        BUSINESS_UNITS[0], DIVISIONS[0],    # bu, division
                        DEPARTMENTS[0], TEAMS[0], ROLES[0], # dept, team, role
                        SENIORITY_LEVELS[0], "",             # seniority, role_desc
                        "", "", "", "", "",                  # manager, buddy fields
                        [], "",                              # tools select, tools text
                        "",                                  # phase ext
                        "",                                  # status markdown
                    )

                nj_clear.click(
                    fn=clear_form,
                    outputs=[
                        nj_name, nj_email, nj_start,
                        nj_bu, nj_division, nj_dept, nj_team, nj_role,
                        nj_seniority, nj_role_desc,
                        nj_mgr_name, nj_mgr_email,
                        nj_buddy_name, nj_buddy_email, nj_buddy_cal,
                        nj_tools_select, nj_tools_text,
                        nj_phase_ext,
                        nj_status,
                    ],
                )

            # ══════════════════════════════════════════════════════════════════
            # TAB 2 — Active Joiners Dashboard
            # ══════════════════════════════════════════════════════════════════
            with gr.Tab("📋 Active Joiners"):
                gr.HTML('<div class="section-title">Joiner Progress Dashboard</div>')

                with gr.Row():
                    dash_refresh = gr.Button("🔄 Refresh", variant="secondary", scale=1)
                    lms_id_input = gr.Textbox(
                        label="Confirm LMS completion — paste Joiner ID",
                        placeholder="joiner-uuid…",
                        scale=2,
                    )
                    lms_btn = gr.Button("✅ Confirm LMS Complete", variant="primary", scale=1)

                lms_status     = gr.Markdown("")
                dashboard_html = gr.HTML(value=_render_dashboard(store))

                def refresh_dash():
                    return _render_dashboard(store)

                def confirm_lms(jid: str):
                    jid = jid.strip()
                    if not jid:
                        gr.Warning("Please enter a Joiner ID.")
                        return "", _render_admin_notifications()
                    orchestrator.confirm_lms_complete(jid)
                    _push_admin_notification(
                        title=f"✅ LMS confirmed — Phase 3 gate unlocked",
                        body=(
                            f"<p><strong>Joiner ID:</strong> <code>{jid}</code></p>"
                            f"<p>The joiner can now advance past Phase 3.</p>"
                        ),
                    )
                    gr.Info(f"LMS confirmed for {jid[:8]}… — Phase 3 gate unlocked.")
                    return (
                        f"✅ LMS confirmed for `{jid}` — Phase 3 gate unlocked.",
                        _render_admin_notifications(),
                    )

                dash_refresh.click(fn=refresh_dash, outputs=[dashboard_html])
                # lms_btn wiring happens after notifications_html is declared

            # ══════════════════════════════════════════════════════════════════
            # TAB 3 — Knowledge Gaps
            # ══════════════════════════════════════════════════════════════════
            with gr.Tab("🔍 Knowledge Gaps"):
                gr.HTML('<div class="section-title">Unanswered Joiner Questions</div>')
                gr.Markdown(
                    "These questions were asked in the chatbot but couldn't be answered from "
                    "the knowledge base. Add the missing content to your Google Drive KB "
                    "and sync — the next nightly ingest will close the gap."
                )

                with gr.Row():
                    gaps_refresh = gr.Button("🔄 Refresh", variant="secondary", scale=1)
                    gap_id_input = gr.Textbox(label="Gap ID to resolve", placeholder="gap-uuid…", scale=2)
                    gap_note     = gr.Textbox(label="Resolution note", placeholder="Added to handbook section 4.2…", scale=2)
                    resolve_btn  = gr.Button("✅ Mark Resolved", variant="primary", scale=1)

                gaps_status = gr.Markdown("")
                gaps_html   = gr.HTML(value=_render_gaps(store))

                def refresh_gaps():
                    return _render_gaps(store)

                def resolve_gap(gap_id: str, note: str):
                    gap_id = gap_id.strip()
                    if not gap_id:
                        gr.Warning("Please enter a Gap ID.")
                        return "", _render_gaps(store), _render_admin_notifications()
                    store.resolve_gap(gap_id, note)
                    _push_admin_notification(
                        title=f"✅ Knowledge gap resolved — {gap_id[:8]}…",
                        body=(
                            f"<p><strong>Gap ID:</strong> <code>{gap_id}</code></p>"
                            f"<p><strong>Resolution note:</strong> "
                            f"{note.strip() or '<em>(no note)</em>'}</p>"
                        ),
                    )
                    gr.Info(f"Gap {gap_id[:8]}… marked resolved.")
                    return (
                        f"✅ Gap `{gap_id[:8]}…` marked resolved.",
                        _render_gaps(store),
                        _render_admin_notifications(),
                    )

                gaps_refresh.click(fn=refresh_gaps, outputs=[gaps_html])
                # resolve_btn wiring happens after notifications_html is declared

            # ══════════════════════════════════════════════════════════════════
            # TAB 4 — Notifications (activity log)
            # ══════════════════════════════════════════════════════════════════
            # Events (joiner created, LMS confirmed, gap resolved) also pop a
            # transient toast via gr.Info; the full detail is stored here as
            # a click-to-expand list — titles only by default.
            with gr.Tab("🔔 Notifications"):
                gr.HTML('<div class="section-title">Activity &amp; Notifications</div>')
                gr.Markdown(
                    "Click any entry to expand its full details. "
                    "New events also appear briefly as a toast popup in the top-right "
                    "corner — close the toast to dismiss it."
                )
                with gr.Row(elem_classes=["admin-util-row"]):
                    notif_refresh_btn = gr.Button("🔄 Refresh", variant="secondary", scale=1)
                    notif_clear_btn   = gr.Button("🗑️ Clear All", variant="secondary", scale=1)

                notifications_html = gr.HTML(value=_render_admin_notifications())

                def refresh_notifications():
                    return _render_admin_notifications()

                def clear_notifications():
                    _ADMIN_NOTIFICATIONS.clear()
                    gr.Info("Notifications cleared.")
                    return _render_admin_notifications()

                notif_refresh_btn.click(fn=refresh_notifications, outputs=[notifications_html])
                notif_clear_btn.click(fn=clear_notifications,   outputs=[notifications_html])

        # ── Deferred wiring (handlers that update notifications_html) ─────────
        nj_submit.click(
            fn=submit_new_joiner,
            inputs=[
                nj_name, nj_email, nj_start,
                nj_bu, nj_division, nj_dept, nj_team, nj_role,
                nj_seniority, nj_role_desc,
                nj_mgr_name, nj_mgr_email,
                nj_buddy_name, nj_buddy_email, nj_buddy_cal,
                nj_tools_text, nj_phase_ext,
            ],
            outputs=[nj_status, notifications_html],
        )
        lms_btn.click(
            fn=confirm_lms,
            inputs=[lms_id_input],
            outputs=[lms_status, notifications_html],
        )
        resolve_btn.click(
            fn=resolve_gap,
            inputs=[gap_id_input, gap_note],
            outputs=[gaps_status, gaps_html, notifications_html],
        )

    return admin_app
