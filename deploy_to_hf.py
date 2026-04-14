#!/usr/bin/env python3
"""
deploy_to_hf.py — Upload OnboardingBuddy to Hugging Face Spaces
================================================================
Usage:
    python deploy_to_hf.py --token hf_xxxxxxxxxx

Or set the environment variable first:
    export HF_TOKEN=hf_xxxxxxxxxx
    python deploy_to_hf.py
"""

import argparse
import os
import sys
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────
REPO_ID   = "yania-n/OnboardingBuddy"
REPO_TYPE = "space"

# This script lives inside the project folder — BASE is its own directory
BASE = Path(__file__).resolve().parent

# Files/dirs to upload (relative to BASE)
INCLUDE = [
    "app.py",
    "requirements.txt",
    "README_HF.md",
    "core",
    "agents",
    "ui",
]

# Skip these anywhere in the tree
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "onboarding_buddy", ".gradio"}
SKIP_EXTS = {".pyc", ".pkl", ".faiss", ".bin", ".pem"}


def collect_files() -> list[tuple[Path, str]]:
    """
    Walk the INCLUDE list and return (local_path, path_in_repo) pairs.
    README_HF.md is remapped to README.md for Hugging Face Spaces.
    """
    pairs = []
    for inc in INCLUDE:
        p = BASE / inc
        if p.is_file():
            repo_path = "README.md" if p.name == "README_HF.md" else p.name
            pairs.append((p, repo_path))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                if any(skip in f.parts for skip in SKIP_DIRS):
                    continue
                if f.suffix in SKIP_EXTS:
                    continue
                pairs.append((f, str(f.relative_to(BASE))))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Deploy OnboardingBuddy to HF Spaces")
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN", ""),
                        help="Hugging Face token (or set HF_TOKEN env var)")
    args = parser.parse_args()

    token = args.token.strip()
    if not token:
        print("❌  No token provided. Run with:  python deploy_to_hf.py --token hf_xxx")
        print("    Or:  export HF_TOKEN=hf_xxx && python deploy_to_hf.py")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi, login
    except ImportError:
        print("Installing huggingface_hub...")
        os.system(f"{sys.executable} -m pip install huggingface_hub -q")
        from huggingface_hub import HfApi, login

    print(f"\n🌱 OnboardingBuddy — Deploy to HF Spaces")
    print(f"   Target : {REPO_ID}")
    print(f"   Source : {BASE}\n")

    login(token=token, add_to_git_credential=False)
    api = HfApi()

    files = collect_files()
    print(f"📦 {len(files)} files to upload...\n")

    errors = []
    for i, (local_path, repo_path) in enumerate(files, 1):
        try:
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=repo_path,
                repo_id=REPO_ID,
                repo_type=REPO_TYPE,
                token=token,
            )
            print(f"  [{i:>2}/{len(files)}] ✓  {repo_path}")
        except Exception as e:
            msg = f"  [{i:>2}/{len(files)}] ✗  {repo_path}  →  {e}"
            print(msg)
            errors.append(msg)

    print()
    if errors:
        print(f"⚠️  {len(errors)} file(s) failed:")
        for e in errors:
            print(e)
        sys.exit(1)

    print("━" * 55)
    print("✅  Deployment complete!")
    print(f"\n   Space URL: https://huggingface.co/spaces/{REPO_ID}")
    print()
    print("⚠️  Remember to add your secrets in Space Settings:")
    print("   ANTHROPIC_API_KEY  →  your Anthropic key")
    print("   VOYAGE_API_KEY     →  your Voyage AI key")
    print("   GOOGLE_API_KEY     →  your Google key (optional)")
    print("━" * 55)


if __name__ == "__main__":
    main()
