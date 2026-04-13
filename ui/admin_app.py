"""
ui/admin_app.py — Admin Portal (Manager-facing Gradio UI)
==========================================================
The manager's interface for:
  1. Creating new joiner records → triggers the full onboarding pipeline
  2. Monitoring all active joiners (phase, sentiment, access status)
  3. Reviewing the knowledge gap backlog
  4. Manually confirming LMS completion (Phase 3 gate admin override)
  5. Viewing manager weekly summaries

Tab structure:
  ├── 🆕 Add New Joiner  (onboarding setup form)
  ├── 📋 Active Joiners  (progress dashboard)
  ├── 🔍 Knowledge Gaps  (unanswered Q&A log)
  └── 📊 Reports         (weekly summary + sentiment signals)

All state changes go through the Orchestrator — the UI never writes to
the store directly.
"""

import uuid
from datetime import date

import gradio as gr

from core.config import (
    DEPARTMENTS, SENIORITY_LEVELS, PHASES, PHASE_BY_ID,
    APP_TITLE, COLOR_PRIMARY, COLOR_ACCENT,
)
from core.models import JoinerProfile, PhaseStatus
from core.state_store import StateStore


# ─────────────────────────────────────────────
# Shared CSS (injected once)
# ─────────────────────────────────────────────

ADMIN_CSS = """
/* OnboardingBuddy Admin Portal — shared styles */
:root {
    --ob-primary: #00897B;
    --ob-accent: #FF7043;
    --ob-surface: #F5F5F5;
    --ob-card: #FFFFFF;
    --ob-text: #212121;
    --ob-muted: #757575;
    --ob-border: #E0E0E0;
    --ob-success: #43A047;
    --ob-warning: #FB8C00;
    --ob-danger: #E53935;
}

.admin-header {
    background: linear-gradient(135deg, var(--ob-primary), #00695C);
    color: white;
    padding: 24px 32px;
    border-radius: 12px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.admin-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; }
.admin-header p  { margin: 4px 0 0; opacity: 0.85; font-size: 0.95rem; }

.joiner-card {
    background: var(--ob-card);
    border: 1px solid var(--ob-border);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.phase-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--ob-primary);
    color: white;
}
.sentiment-positive { color: var(--ob-success); font-weight: 600; }
.sentiment-neutral   { color: var(--ob-muted); }
.sentiment-concerning { color: var(--ob-danger); font-weight: 600; }

.gap-item {
    background: #FFF8E1;
    border-left: 4px solid var(--ob-warning);
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 8px;
    font-size: 0.9rem;
}
.success-banner {
    background: #E8F5E9;
    border: 1px solid #A5D6A7;
    border-radius: 8px;
    padding: 12px 16px;
    color: #1B5E20;
    font-weight: 500;
}
.section-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--ob-primary);
    margin: 20px 0 12px;
    padding-bottom: 6px;
    border-bottom: 2px solid var(--ob-primary);
}
"""


def build_admin_app(orchestrator, store: StateStore) -> gr.Blocks:
    """
    Construct and return the full Admin Gradio Blocks app.
    `orchestrator` and `store` are injected at startup (shared instances).
    """

    with gr.Blocks(
        title="OnboardingBuddy — Admin Portal",
        css=ADMIN_CSS,
        theme=gr.themes.Soft(primary_hue="teal", secondary_hue="orange"),
    ) as admin_app:

        # ── Header ────────────────────────────
        gr.HTML("""
        <div class="admin-header">
            <div style="font-size:2.5rem">🧭</div>
            <div>
                <h1>OnboardingBuddy — Admin Portal</h1>
                <p>Nexora Global Corporation · Manager & HR view</p>
            </div>
        </div>
        """)

        with gr.Tabs():

            # ══════════════════════════════════
            # TAB 1 — Add New Joiner
            # ══════════════════════════════════
            with gr.Tab("🆕 Add New Joiner"):
                gr.HTML('<div class="section-title">New Joiner Setup</div>')
                gr.Markdown(
                    "Fill in all details below. Submitting this form triggers the full "
                    "onboarding pipeline — tool access tickets, training plan, buddy booking, "
                    "and the joiner's app will all activate in parallel."
                )

                with gr.Row():
                    with gr.Column():
                        gr.HTML('<div class="section-title">Personal Details</div>')
                        nj_name = gr.Textbox(label="Full Name *", placeholder="e.g. Priya Sharma")
                        nj_email = gr.Textbox(label="Work Email *", placeholder="priya.sharma@nexoraglobal.com")
                        nj_start = gr.Textbox(
                            label="Start Date * (YYYY-MM-DD)",
                            placeholder=str(date.today()),
                            value=str(date.today()),
                        )

                    with gr.Column():
                        gr.HTML('<div class="section-title">Role & Placement</div>')
                        nj_title = gr.Textbox(label="Job Title *", placeholder="e.g. Senior Data Analyst")
                        nj_seniority = gr.Dropdown(
                            label="Seniority Level *", choices=SENIORITY_LEVELS, value=SENIORITY_LEVELS[0]
                        )
                        nj_dept = gr.Dropdown(
                            label="Department *", choices=DEPARTMENTS, value=DEPARTMENTS[0]
                        )

                with gr.Row():
                    with gr.Column():
                        nj_bu = gr.Textbox(label="Business Unit", placeholder="e.g. Technology")
                        nj_division = gr.Textbox(label="Division", placeholder="e.g. Digital Products")
                        nj_team = gr.Textbox(label="Team", placeholder="e.g. Platform Engineering")
                        nj_role_desc = gr.Textbox(
                            label="Role Description",
                            placeholder="Brief description of role responsibilities...",
                            lines=3,
                        )

                    with gr.Column():
                        gr.HTML('<div class="section-title">Manager & Buddy</div>')
                        nj_mgr_name = gr.Textbox(label="Manager Name *", placeholder="e.g. David Chen")
                        nj_mgr_email = gr.Textbox(label="Manager Email *", placeholder="d.chen@nexoraglobal.com")
                        nj_buddy_name = gr.Textbox(label="Buddy Name *", placeholder="e.g. Sara Okonkwo")
                        nj_buddy_email = gr.Textbox(label="Buddy Email *", placeholder="s.okonkwo@nexoraglobal.com")
                        nj_buddy_cal = gr.Textbox(
                            label="Buddy Calendar Link (optional)",
                            placeholder="https://calendly.com/...",
                        )

                gr.HTML('<div class="section-title">Tool Access</div>')
                gr.Markdown(
                    "Enter one tool per line in the format: `Tool Name: Permission Level`  \n"
                    "Example: `Salesforce: Full Access` or `Jira: Read Only`"
                )
                nj_tools = gr.Textbox(
                    label="Tool Access List",
                    placeholder="Salesforce: Full Access\nJira: Edit\nSlack: Standard\nGitHub: Contributor",
                    lines=5,
                )

                with gr.Row():
                    nj_submit = gr.Button("🚀 Create Joiner & Activate Onboarding", variant="primary", scale=2)
                    nj_clear = gr.Button("Clear Form", variant="secondary", scale=1)

                nj_result = gr.HTML(visible=False)

                # ── Submit handler ─────────────────────

                def submit_new_joiner(
                    name, email, start, title, seniority, dept,
                    bu, division, team, role_desc,
                    mgr_name, mgr_email, buddy_name, buddy_email, buddy_cal,
                    tools_text,
                ):
                    # Validation
                    missing = []
                    if not name.strip(): missing.append("Full Name")
                    if not email.strip(): missing.append("Work Email")
                    if not start.strip(): missing.append("Start Date")
                    if not title.strip(): missing.append("Job Title")
                    if not mgr_name.strip(): missing.append("Manager Name")
                    if not mgr_email.strip(): missing.append("Manager Email")
                    if not buddy_name.strip(): missing.append("Buddy Name")
                    if not buddy_email.strip(): missing.append("Buddy Email")

                    if missing:
                        return gr.HTML(
                            value=f'<div style="color:#E53935;padding:10px;background:#FFEBEE;border-radius:8px">'
                                  f'⚠️ Please fill in required fields: {", ".join(missing)}</div>',
                            visible=True,
                        )

                    try:
                        start_date = date.fromisoformat(start.strip())
                    except ValueError:
                        return gr.HTML(
                            value='<div style="color:#E53935;padding:10px;background:#FFEBEE;border-radius:8px">'
                                  '⚠️ Start date must be in YYYY-MM-DD format.</div>',
                            visible=True,
                        )

                    # Parse tool access
                    tool_access = {}
                    for line in tools_text.strip().splitlines():
                        if ":" in line:
                            parts = line.split(":", 1)
                            tool_access[parts[0].strip()] = parts[1].strip()

                    profile = JoinerProfile(
                        joiner_id=store.new_joiner_id(),
                        full_name=name.strip(),
                        email=email.strip(),
                        start_date=start_date,
                        job_title=title.strip(),
                        seniority=seniority,
                        business_unit=bu.strip(),
                        division=division.strip(),
                        department=dept,
                        team=team.strip(),
                        role_description=role_desc.strip(),
                        manager_name=mgr_name.strip(),
                        manager_email=mgr_email.strip(),
                        buddy_name=buddy_name.strip(),
                        buddy_email=buddy_email.strip(),
                        buddy_calendar_link=buddy_cal.strip() or None,
                        tool_access=tool_access,
                        created_by=mgr_email.strip(),
                    )

                    state = orchestrator.activate_new_joiner(profile)

                    tool_list = "".join(
                        f"<li>{t} — {v}</li>" for t, v in tool_access.items()
                    ) or "<li>No tools configured</li>"

                    return gr.HTML(
                        value=f"""
                        <div class="success-banner">
                            <h3 style="margin:0 0 8px">✅ Onboarding Activated for {name}!</h3>
                            <p style="margin:4px 0"><strong>Joiner ID:</strong> {profile.joiner_id[:8]}...</p>
                            <p style="margin:4px 0"><strong>Role:</strong> {title} · {dept}</p>
                            <p style="margin:4px 0"><strong>Start Date:</strong> {start}</p>
                            <p style="margin:4px 0"><strong>Phase 1</strong> (Welcome) is now active.</p>
                            <p style="margin:8px 0 4px"><strong>Actions triggered in parallel:</strong></p>
                            <ul style="margin:0;padding-left:20px">
                                <li>🔐 IT access tickets raised: <ul style="margin:2px 0">{tool_list}</ul></li>
                                <li>📚 Training plan built (Phase 3)</li>
                                <li>👋 Buddy intro sent to {buddy_name}</li>
                                <li>🏢 Org context brief prepared (Day 3)</li>
                            </ul>
                            <p style="margin:8px 0 0;font-size:0.85rem;opacity:0.8">
                                Share the Joiner App link with {name} so they can start their journey.
                            </p>
                        </div>
                        """,
                        visible=True,
                    )

                nj_submit.click(
                    fn=submit_new_joiner,
                    inputs=[
                        nj_name, nj_email, nj_start, nj_title, nj_seniority, nj_dept,
                        nj_bu, nj_division, nj_team, nj_role_desc,
                        nj_mgr_name, nj_mgr_email, nj_buddy_name, nj_buddy_email, nj_buddy_cal,
                        nj_tools,
                    ],
                    outputs=[nj_result],
                )

                nj_clear.click(
                    fn=lambda: [""] * 15 + [gr.HTML(visible=False)],
                    outputs=[
                        nj_name, nj_email, nj_start, nj_title, nj_seniority, nj_dept,
                        nj_bu, nj_division, nj_team, nj_role_desc,
                        nj_mgr_name, nj_mgr_email, nj_buddy_name, nj_buddy_email, nj_buddy_cal,
                        nj_result,
                    ],
                )

            # ══════════════════════════════════
            # TAB 2 — Active Joiners Dashboard
            # ══════════════════════════════════
            with gr.Tab("📋 Active Joiners"):
                gr.HTML('<div class="section-title">Joiner Progress Dashboard</div>')

                with gr.Row():
                    refresh_btn = gr.Button("🔄 Refresh", variant="secondary")
                    lms_joiner_id = gr.Textbox(
                        label="Confirm LMS completion (paste Joiner ID)",
                        placeholder="joiner-uuid...",
                        scale=2,
                    )
                    lms_confirm_btn = gr.Button("✅ Confirm LMS Complete", variant="primary")

                lms_result = gr.HTML(visible=False)
                dashboard_html = gr.HTML(value=_render_dashboard(store))

                def refresh_dashboard():
                    return _render_dashboard(store)

                def confirm_lms(joiner_id):
                    joiner_id = joiner_id.strip()
                    if not joiner_id:
                        return gr.HTML(
                            value='<div style="color:red;padding:8px">Please enter a Joiner ID.</div>',
                            visible=True,
                        )
                    orchestrator.confirm_lms_complete(joiner_id)
                    return gr.HTML(
                        value=f'<div class="success-banner">✅ LMS completion confirmed for {joiner_id[:8]}... — Phase 3 gate is now open.</div>',
                        visible=True,
                    )

                refresh_btn.click(fn=refresh_dashboard, outputs=[dashboard_html])
                lms_confirm_btn.click(fn=confirm_lms, inputs=[lms_joiner_id], outputs=[lms_result])

            # ══════════════════════════════════
            # TAB 3 — Knowledge Gaps
            # ══════════════════════════════════
            with gr.Tab("🔍 Knowledge Gaps"):
                gr.HTML('<div class="section-title">Unanswered Q&A Questions</div>')
                gr.Markdown(
                    "These questions were asked by joiners but could not be answered from the knowledge base. "
                    "Review and add missing documentation to close each gap."
                )

                with gr.Row():
                    gaps_refresh = gr.Button("🔄 Refresh Gaps", variant="secondary")
                    gap_id_input = gr.Textbox(label="Gap ID to resolve", placeholder="gap-uuid...")
                    gap_note = gr.Textbox(label="Resolution note", placeholder="Added to handbook section 4.2...")
                    resolve_btn = gr.Button("✅ Mark Resolved", variant="primary")

                gaps_result = gr.HTML(visible=False)
                gaps_html = gr.HTML(value=_render_gaps(store))

                def refresh_gaps():
                    return _render_gaps(store)

                def resolve_gap(gap_id, note):
                    gap_id = gap_id.strip()
                    if not gap_id:
                        return gr.HTML(
                            value='<div style="color:red;padding:8px">Please enter a Gap ID.</div>',
                            visible=True,
                        )
                    store.resolve_gap(gap_id, note)
                    return gr.HTML(
                        value=f'<div class="success-banner">✅ Gap {gap_id[:8]}... marked as resolved.</div>',
                        visible=True,
                    )

                gaps_refresh.click(fn=refresh_gaps, outputs=[gaps_html])
                resolve_btn.click(fn=resolve_gap, inputs=[gap_id_input, gap_note], outputs=[gaps_result])

            # ══════════════════════════════════
            # TAB 4 — Reports
            # ══════════════════════════════════
            with gr.Tab("📊 Reports"):
                gr.HTML('<div class="section-title">Manager Weekly Summary</div>')

                with gr.Row():
                    mgr_email_input = gr.Textbox(
                        label="Manager Email",
                        placeholder="your.email@nexoraglobal.com",
                    )
                    generate_btn = gr.Button("Generate Summary", variant="primary")

                report_output = gr.Textbox(
                    label="Weekly Summary",
                    lines=20,
                    interactive=False,
                )

                def generate_summary(email):
                    if not email.strip():
                        return "Please enter a manager email address."
                    return orchestrator.progress_tracker.build_manager_summary(email.strip())

                generate_btn.click(fn=generate_summary, inputs=[mgr_email_input], outputs=[report_output])

                gr.HTML('<div class="section-title">Sentiment Overview</div>')
                sentiment_html = gr.HTML(value=_render_sentiment_overview(store))
                sentiment_refresh = gr.Button("🔄 Refresh Sentiment", variant="secondary")
                sentiment_refresh.click(fn=lambda: _render_sentiment_overview(store), outputs=[sentiment_html])

    return admin_app


# ─────────────────────────────────────────────
# HTML rendering helpers
# ─────────────────────────────────────────────

def _render_dashboard(store: StateStore) -> str:
    """Build the active joiners dashboard HTML."""
    profiles = store.list_profiles()
    if not profiles:
        return '<p style="color:#757575;padding:20px">No joiners registered yet. Use the "Add New Joiner" tab to get started.</p>'

    cards = []
    for profile in profiles:
        state = store.get_state(profile.joiner_id)
        if not state:
            continue

        phase_def = PHASE_BY_ID.get(state.current_phase)
        phase_name = phase_def.name if phase_def else "Unknown"

        # Checklist progress
        total = len(state.checklist_items)
        done = sum(1 for c in state.checklist_items if c.completed)
        pct = int(done / total * 100) if total else 0

        # Access summary
        access_pending = sum(1 for r in state.access_requests if r.status.value == "pending")
        access_provisioned = sum(1 for r in state.access_requests if r.status.value == "provisioned")

        # Sentiment
        recent_fb = state.feedback_responses[-1] if state.feedback_responses else None
        sentiment_html = ""
        if recent_fb and recent_fb.sentiment:
            s = recent_fb.sentiment.value
            cls = f"sentiment-{s}"
            label = {"positive": "😊 Positive", "neutral": "😐 Neutral", "concerning": "⚠️ Needs attention"}.get(s, s)
            sentiment_html = f'<span class="{cls}">{label}</span>'
        else:
            sentiment_html = '<span class="sentiment-neutral">No feedback yet</span>'

        status_color = {"complete": "#43A047", "active": "#00897B", "locked": "#BDBDBD", "pending_lms": "#FB8C00"}
        status = state.phase_statuses.get(state.current_phase, PhaseStatus.ACTIVE).value

        cards.append(f"""
        <div class="joiner-card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <div>
                    <strong style="font-size:1.05rem">{profile.full_name}</strong>
                    <span style="color:#757575;margin-left:8px">{profile.job_title}</span>
                </div>
                <span class="phase-badge">Phase {state.current_phase}: {phase_name}</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;font-size:0.88rem">
                <div><strong>Dept:</strong> {profile.department}</div>
                <div><strong>Manager:</strong> {profile.manager_name}</div>
                <div><strong>Start:</strong> {profile.start_date}</div>
                <div><strong>Sentiment:</strong> {sentiment_html}</div>
                <div><strong>Access:</strong> ✅ {access_provisioned} ready · ⏳ {access_pending} pending</div>
                <div><strong>ID:</strong> <code style="font-size:0.78rem">{profile.joiner_id}</code></div>
            </div>
            <div style="margin-top:12px">
                <div style="display:flex;justify-content:space-between;font-size:0.82rem;margin-bottom:4px">
                    <span>Overall checklist progress</span>
                    <span>{done}/{total} items ({pct}%)</span>
                </div>
                <div style="background:#E0E0E0;border-radius:4px;height:8px">
                    <div style="background:#00897B;width:{pct}%;height:100%;border-radius:4px;transition:width 0.3s"></div>
                </div>
            </div>
        </div>
        """)

    return "\n".join(cards)


def _render_gaps(store: StateStore) -> str:
    """Build the knowledge gaps list HTML."""
    gaps = store.list_knowledge_gaps(resolved=False)
    if not gaps:
        return '<p style="color:#43A047;padding:20px">✅ No open knowledge gaps — the KB is covering all questions!</p>'

    items = []
    for g in sorted(gaps, key=lambda x: x["asked_at"], reverse=True):
        joiner_id_short = g["joiner_id"][:8] if g.get("joiner_id") else "?"
        items.append(f"""
        <div class="gap-item">
            <div style="font-weight:600;margin-bottom:2px">{g['question']}</div>
            <div style="font-size:0.8rem;color:#757575">
                Gap ID: <code>{g['gap_id'][:8]}...</code> ·
                Joiner: {joiner_id_short}... ·
                Asked: {g['asked_at'][:16]}
            </div>
        </div>
        """)

    return f"<p style='color:#757575;font-size:0.9rem'>{len(gaps)} open gap(s)</p>\n" + "\n".join(items)


def _render_sentiment_overview(store: StateStore) -> str:
    """Build sentiment summary table for all joiners."""
    profiles = store.list_profiles()
    if not profiles:
        return "<p style='color:#757575'>No data yet.</p>"

    rows = []
    for p in profiles:
        state = store.get_state(p.joiner_id)
        if not state or not state.feedback_responses:
            continue
        scores = [f.sentiment_score for f in state.feedback_responses if f.sentiment_score]
        avg = round(sum(scores) / len(scores), 1) if scores else None
        latest = state.feedback_responses[-1]
        sentiment = latest.sentiment.value if latest.sentiment else "unknown"
        color = {"positive": "#43A047", "neutral": "#757575", "concerning": "#E53935"}.get(sentiment, "#757575")
        avg_str = f"{avg}/5" if avg else "—"
        rows.append(f"""
        <tr>
            <td style="padding:8px 12px">{p.full_name}</td>
            <td style="padding:8px 12px">{p.department}</td>
            <td style="padding:8px 12px">Phase {state.current_phase}</td>
            <td style="padding:8px 12px"><span style="color:{color};font-weight:600">{sentiment.title()}</span></td>
            <td style="padding:8px 12px">{avg_str}</td>
        </tr>
        """)

    if not rows:
        return "<p style='color:#757575'>No feedback submitted yet.</p>"

    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
        <thead>
            <tr style="background:#F5F5F5;border-bottom:2px solid #E0E0E0">
                <th style="padding:8px 12px;text-align:left">Joiner</th>
                <th style="padding:8px 12px;text-align:left">Dept</th>
                <th style="padding:8px 12px;text-align:left">Phase</th>
                <th style="padding:8px 12px;text-align:left">Sentiment</th>
                <th style="padding:8px 12px;text-align:left">Avg Score</th>
            </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    """
