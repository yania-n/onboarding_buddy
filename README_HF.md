---
title: OnboardingBuddy
emoji: 🌱
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: "4.44.1"
app_file: app.py
pinned: false
license: mit
---

# 🌱 OnboardingBuddy

**AI-powered 90-day employee onboarding system** built with Claude (Anthropic) + Gradio.

---

## What it does

OnboardingBuddy guides new employees through a structured 6-phase onboarding journey while giving managers real-time visibility and control.

**Admin Portal** (manager-facing):
- Add new joiners via a form with dropdowns (business unit, department, role, tools)
- Monitor all active joiners: phase progress, checklist completion, sentiment
- Confirm LMS training completion to unlock Phase 3
- Review knowledge gaps (unanswered chatbot questions)
- Generate weekly manager summaries

**Joiner App** (new employee-facing):
- Phase timeline showing progress across all 6 phases
- Interactive checklist per phase — tick items and mark phases complete
- "Ask Anything" chatbot grounded in the company knowledge base
- Training plan with mandatory vs role-specific courses
- IT access request tracker
- Pulse feedback surveys at 50% and 100% completion
- All agent notifications in one place

---

## Architecture

```
Apps (Gradio)
  ├── admin_app.py        Manager portal
  └── joiner_app.py       New joiner companion

Orchestrator
  └── orchestrator.py     Wires all agents, enforces phase gates

Core Agents
  ├── org_agent           Org structure brief
  ├── access_agent        IT ticket simulation
  ├── training_agent      Personalised course plan
  └── qa_agent            KB-grounded chatbot

Added Agents
  ├── buddy_agent         Buddy welcome note
  ├── integration_agent   IT/LMS confirmation, buddy contact
  ├── feedback_agent      Pulse survey + sentiment analysis
  └── progress_tracker    Overdue phase nudges (every 6h)

Infrastructure
  ├── KnowledgeBase       Google Drive sync → FAISS RAG pipeline
  └── StateStore          Thread-safe JSON persistence
```

**Models**: `claude-haiku-4-5-20251001` (fast tasks) · `claude-sonnet-4-6` (quality tasks)  
**Embeddings**: Voyage AI `voyage-3-lite`  
**Vector search**: FAISS IndexFlatIP (cosine similarity)

---

## Environment variables

Set these in **Space Settings → Variables and Secrets**:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | Claude API key |
| `VOYAGE_API_KEY` | ✅ Yes | Voyage AI embeddings key |
| `GOOGLE_API_KEY` | Optional | Google Drive API key for KB sync |
| `GOOGLE_DRIVE_FOLDER_ID` | Optional | Drive folder with company docs (default: shared folder) |

The app starts in **degraded mode** if keys are missing — agents fall back to templates, KB uses keyword search.

---

## 6-Phase onboarding journey

| Phase | Name | Days | Gate |
|---|---|---|---|
| 1 | Welcome | 1–2 | Joiner ticks checklist |
| 2 | Bearings | 3–5 | Joiner ticks checklist |
| 3 | Learning | 5–30 | **LMS gate** — admin confirms course completion |
| 4 | Hands Dirty | 15–60 | Joiner ticks checklist |
| 5 | Ready to Own | 60–90 | Joiner ticks checklist |
| 6 | Finish Line | Day 90 | Joiner ticks checklist + feedback |

---

## PoC constraints

This is a **Proof of Concept** — the following are simulated (not live integrations):
- IT provisioning → tickets written to in-app state; would call IT API in production
- LMS → admin confirms manually; would poll LMS API in production
- Calendar booking → joiner is directed to email/calendar link directly
- Notifications → in-app only; would use MS Teams/email in production
- HRIS → no integration; org data sourced from knowledge base

---

## Local development

```bash
git clone https://huggingface.co/spaces/yania-n/OnboardingBuddy
cd OnboardingBuddy

# Install dependencies
pip install -r requirements.txt

# Create .env
echo "ANTHROPIC_API_KEY=your_key" > .env
echo "VOYAGE_API_KEY=your_key" >> .env

# Run
python app.py
# → Open http://localhost:7860
```

---

*Built with ❤️ using [Anthropic Claude](https://www.anthropic.com), [Gradio](https://gradio.app), and [Voyage AI](https://www.voyageai.com)*
