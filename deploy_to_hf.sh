#!/usr/bin/env bash
# =============================================================
# deploy_to_hf.sh — OnboardingBuddy Deployment Script
# =============================================================
# Sets up a GitHub repo and pushes to Hugging Face Spaces.
#
# Usage:
#   chmod +x deploy_to_hf.sh
#   ./deploy_to_hf.sh
#
# Prerequisites:
#   - git installed and configured (git config --global user.email / user.name)
#   - huggingface_hub installed: pip install huggingface_hub
#   - Your HF token set: huggingface-cli login   OR   export HF_TOKEN=hf_...
#
# What this script does:
#   1. Initialises a git repo (if not already one)
#   2. Copies README_HF.md → README.md for Spaces (overwrites local README)
#   3. Commits all files
#   4. Adds the HF Spaces remote
#   5. Force-pushes to HF Spaces
#
# After running: open https://huggingface.co/spaces/YOUR_USERNAME/OnboardingBuddy
# Then go to Settings → Secrets and add ANTHROPIC_API_KEY + VOYAGE_API_KEY
# =============================================================

set -e  # Exit on first error

# ── Configuration ──────────────────────────────────────────
HF_USERNAME="${HF_USERNAME:-}"          # Set via env or prompt below
SPACE_NAME="${SPACE_NAME:-OnboardingBuddy}"
GITHUB_USERNAME="${GITHUB_USERNAME:-}"  # Optional — for GitHub remote

# ── Colours ────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'  # No colour

echo -e "${CYAN}"
echo "  ┌─────────────────────────────────────────────┐"
echo "  │   OnboardingBuddy — Deployment to HF Spaces │"
echo "  └─────────────────────────────────────────────┘"
echo -e "${NC}"

# ── Prompt for HF username if not set ──────────────────────
if [ -z "$HF_USERNAME" ]; then
    read -rp "Enter your Hugging Face username: " HF_USERNAME
fi

HF_SPACE_URL="https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"
HF_GIT_URL="https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"

echo -e "${YELLOW}Target Space:${NC} ${HF_SPACE_URL}"
echo ""

# ── Step 1: Git init ───────────────────────────────────────
echo -e "${GREEN}[1/5]${NC} Initialising git repository..."
if [ ! -d ".git" ]; then
    git init
    echo "  ✓ New git repo initialised"
else
    echo "  ✓ Existing git repo found"
fi

# ── Step 2: Prepare README for HF Spaces ──────────────────
echo -e "${GREEN}[2/5]${NC} Preparing README for Hugging Face Spaces..."
# HF Spaces requires the YAML front-matter in README.md
# We keep README_HF.md as the Spaces readme and README.md as the developer readme
# On HF, we want the front-matter version
cp README_HF.md README.md
echo "  ✓ README.md updated with HF front-matter"

# ── Step 3: Ensure data directory is committed ────────────
echo -e "${GREEN}[3/5]${NC} Checking KB documents..."
KB_COUNT=$(find data/kb_documents -name "*.txt" 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ ${KB_COUNT} KB documents in data/kb_documents/"

# Create a .gitkeep so empty data/ subfolders are tracked
touch data/.gitkeep

# ── Step 4: Git add & commit ───────────────────────────────
echo -e "${GREEN}[4/5]${NC} Committing files..."
git add -A
git diff --cached --stat | head -20
echo ""
git commit -m "OnboardingBuddy — deploy $(date '+%Y-%m-%d %H:%M')" || echo "  (nothing new to commit)"
echo "  ✓ Committed"

# ── Step 5: Push to HF Spaces ─────────────────────────────
echo -e "${GREEN}[5/5]${NC} Pushing to Hugging Face Spaces..."

# Add remote if not already present
if ! git remote get-url hf &>/dev/null; then
    git remote add hf "${HF_GIT_URL}"
    echo "  ✓ Added HF remote: ${HF_GIT_URL}"
else
    git remote set-url hf "${HF_GIT_URL}"
    echo "  ✓ Updated HF remote"
fi

# Push (HF Spaces uses 'main' branch)
git push hf main --force
echo "  ✓ Pushed to HF Spaces"

# ── Optional: GitHub remote ───────────────────────────────
if [ -n "$GITHUB_USERNAME" ]; then
    GITHUB_URL="https://github.com/${GITHUB_USERNAME}/onboarding-buddy"
    if ! git remote get-url origin &>/dev/null; then
        git remote add origin "${GITHUB_URL}"
    fi
    git push origin main --force 2>/dev/null || echo "  (GitHub push skipped — create the repo at github.com first)"
fi

# ── Done ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo -e "  Space URL:    ${YELLOW}${HF_SPACE_URL}${NC}"
echo ""
echo -e "${YELLOW}⚠️  Next step — add your secrets:${NC}"
echo "  1. Go to: ${HF_SPACE_URL}/settings"
echo "  2. Scroll to 'Repository Secrets'"
echo "  3. Add:  ANTHROPIC_API_KEY = your_key"
echo "  4.       VOYAGE_API_KEY    = your_key"
echo ""
echo "  The Space will rebuild automatically after secrets are set."
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
