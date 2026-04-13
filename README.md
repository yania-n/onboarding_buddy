# 🧭 OnboardingBuddy

> AI-powered employee onboarding for Nexora Global Corporation — a Proof of Concept.

OnboardingBuddy guides new joiners through a structured 90-day onboarding journey with:
- A **manager admin portal** to register joiners and monitor progress
- A **personalised joiner experience** with phase checklists, a KB-grounded chatbot, training plan, and notifications
- A **multi-agent AI backend** that activates in parallel on Day 1

---

## 🏗 Architecture

```
app.py                        ← Entry point (Gradio, scheduler)
├── core/
│   ├── config.py             ← All constants, phase definitions, model routing
│   ├── models.py             ← Pydantic data models
│   ├── state_store.py        ← JSON persistence layer (swappable for DB)
│   └── knowledge_base.py     ← RAG pipeline (Voyage AI + FAISS)
├── agents/
│   ├── orchestrator.py       ← Central router — activates all agents on Day 1
│   ├── qa_agent.py           ← KB-grounded Q&A chatbot (Haiku)
│   ├── org_agent.py          ← Org & role context builder (Haiku)
│   ├── access_agent.py       ← IT provisioning ticket tracker
│   ├── training_agent.py     ← LMS course plan builder
│   ├── buddy_agent.py        ← Buddy intro booking + peer recommendations (Haiku)
│   ├── feedback_agent.py     ← Phase-end pulse surveys + sentiment (Haiku/Sonnet)
│   └── progress_tracker.py   ← Overdue phase nudges + manager summaries (Haiku)
├── ui/
│   ├── admin_app.py          ← Manager portal (Gradio Blocks)
│   └── joiner_app.py         ← Joiner journey app (Gradio Blocks)
└── data/
    └── kb_documents/         ← 40 Nexora knowledge base documents
```

### Model routing strategy (cost-optimised)

| Task | Model | Why |
|------|-------|-----|
| KB Q&A, nudges, sentiment classification | `claude-haiku-4-5` | Fast, cheap, sufficient |
| Buddy intro letters, escalation messages | `claude-sonnet-4-5` | Higher-stakes communication |
| Embeddings | `voyage-3-lite` | Free tier, high quality |
| Vector search | FAISS `IndexFlatIP` | In-memory, no infra cost |

---

## 🚀 Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/onboarding-buddy.git
cd onboarding-buddy
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your keys
```

Required keys:
- `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com)
- `VOYAGE_API_KEY` — [dash.voyageai.com](https://dash.voyageai.com) (free tier available)

### 4. Run locally

```bash
python app.py
```

Open `http://localhost:7860`

---

## ☁️ Deploy to Hugging Face Spaces

### One-time setup

1. Create a new Space at [huggingface.co/new-space](https://huggingface.co/new-space)
   - SDK: **Gradio**
   - Hardware: **CPU Basic** (free)

2. Set Secrets in Space Settings → Secrets:
   - `ANTHROPIC_API_KEY`
   - `VOYAGE_API_KEY`

3. Push this repo:

```bash
# Add HF remote
git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/OnboardingBuddy

# Push
git push hf main
```

The Space will build automatically. The app stays live 24/7 — no need to keep your laptop on.

> **Note:** On first startup the KB ingestion runs (~2–3 min). Subsequent starts load from cache instantly.

---

## 🗺 Onboarding Phases

| Phase | Days | Gate |
|-------|------|------|
| 1 — Welcome | Day 1–2 | Joiner marks complete |
| 2 — Bearings | Day 3–5 | Joiner marks complete |
| 3 — Learning | Day 5–29 | **LMS confirmation required** + joiner marks complete |
| 4 — Hands Dirty | Day 15–60 | Joiner marks complete |
| 5 — Ready to Own | Day 60–90 | Joiner marks complete |
| 6 — Finish Line | Day 90 | Joiner submits final feedback |

---

## 💰 Cost estimate (per onboarding session)

| Component | Cost |
|-----------|------|
| Claude Haiku (KB Q&A, nudges) | ~$0.02–0.05 |
| Claude Sonnet (buddy letters, escalations) | ~$0.03–0.08 |
| Voyage AI embeddings (free tier) | $0.00 |
| FAISS (in-memory) | $0.00 |
| HF Spaces CPU Basic | $0.00 |
| **Total** | **< $0.15 per joiner** |

---

## 📁 Knowledge Base

The `data/kb_documents/` folder contains 40 Nexora knowledge documents covering:
- Employee Handbook, Policy Library, Culture Playbook
- IT, CE&Q, Finance, HR, Sales, R&D, Operations department handbooks
- Org charts, RACI frameworks, FAQ libraries, meeting templates
- 30/60/90-day plans, career frameworks, compliance matrices

To add new documents: drop `.txt` or `.docx` files into `data/kb_documents/` and the KB
will re-ingest on next startup (or call `kb.ingest()` directly).

---

## 🔧 Development notes

- **State persistence:** JSON files in `data/`. Replace `StateStore._load_json/_save_json` with a DB adapter for production.
- **Integrations:** Slack, Calendar, LMS, and IT provisioning run in **simulated mode**. Each agent has a clear integration point marked with `# In production:` comments.
- **Thread safety:** `StateStore` uses a `threading.Lock`. All agent Day-1 activations run on daemon threads.
- **Output count:** If adding Gradio outputs, count `gr.update()` calls carefully per return path.

---

*Nexora Global Corporation is a fictional company created for this PoC.*
