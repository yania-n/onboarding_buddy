#!/usr/bin/env bash
# =============================================================
# deploy_to_hf.sh — OnboardingBuddy → Hugging Face Spaces
# =============================================================
# Usage:
#   export HF_TOKEN=hf_xxxxxxxxxxxx
#   bash deploy_to_hf.sh
#
# Or run interactively — it will prompt for your token.
# =============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

REPO_ID="yania-n/OnboardingBuddy"
SPACE_URL="https://huggingface.co/spaces/${REPO_ID}"

echo -e "${CYAN}"
echo "  ┌──────────────────────────────────────────────┐"
echo "  │   OnboardingBuddy — Deploy to HF Spaces      │"
echo "  │   Target: ${REPO_ID}    │"
echo "  └──────────────────────────────────────────────┘"
echo -e "${NC}"

# ── Get HF token ───────────────────────────────────────────
if [ -z "$HF_TOKEN" ]; then
    read -rsp "Enter your Hugging Face token (hf_...): " HF_TOKEN
    echo ""
fi

if [ -z "$HF_TOKEN" ]; then
    echo "Error: HF_TOKEN is required."
    exit 1
fi

echo -e "${GREEN}[1/2]${NC} Uploading files to ${REPO_ID}..."

python3 << PYEOF
import os, sys
from pathlib import Path

token = "${HF_TOKEN}"

try:
    from huggingface_hub import HfApi, login
except ImportError:
    print("Installing huggingface_hub...")
    os.system("pip install huggingface_hub -q --break-system-packages")
    from huggingface_hub import HfApi, login

login(token=token, add_to_git_credential=False)
api = HfApi()

REPO_ID   = "${REPO_ID}"
REPO_TYPE = "space"
BASE      = Path(__file__).parent if "__file__" in dir() else Path(".")

# Detect script location reliably
import inspect
BASE = Path(inspect.getfile(lambda: None) if False else os.path.abspath("."))

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "onboarding_buddy"}
SKIP_EXTS = {".pyc", ".pkl", ".faiss", ".bin"}
INCLUDE   = ["app.py", "requirements.txt", "README_HF.md", "core", "agents", "ui"]

all_files = []
for inc in INCLUDE:
    p = BASE / inc
    if p.is_file():
        all_files.append(p)
    elif p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.is_file():
                if any(d in f.parts for d in SKIP_DIRS):
                    continue
                if f.suffix in SKIP_EXTS:
                    continue
                all_files.append(f)

print(f"Uploading {len(all_files)} files...")
errors = []
for fpath in all_files:
    rel = str(fpath.relative_to(BASE))
    path_in_repo = "README.md" if rel == "README_HF.md" else rel
    try:
        api.upload_file(
            path_or_fileobj=str(fpath),
            path_in_repo=path_in_repo,
            repo_id=REPO_ID,
            repo_type=REPO_TYPE,
            token=token,
        )
        print(f"  ✓ {path_in_repo}")
    except Exception as e:
        errors.append(f"  ✗ {path_in_repo}: {e}")
        print(errors[-1])

if errors:
    print(f"\n{len(errors)} file(s) failed to upload.")
    sys.exit(1)
else:
    print("\nAll files uploaded successfully.")
PYEOF

echo ""
echo -e "${GREEN}[2/2]${NC} Done!"
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo -e "  Space URL:  ${YELLOW}${SPACE_URL}${NC}"
echo ""
echo -e "${YELLOW}⚠️  Add your API secrets in Space Settings:${NC}"
echo "  1. Go to: ${SPACE_URL}/settings"
echo "  2. Scroll to 'Repository Secrets'"
echo "  3. Add:  ANTHROPIC_API_KEY  = your_anthropic_key"
echo "  4. Add:  VOYAGE_API_KEY     = your_voyage_key"
echo "  5. Add:  GOOGLE_API_KEY     = your_google_key  (optional)"
echo ""
echo "  The Space rebuilds automatically after secrets are saved."
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
