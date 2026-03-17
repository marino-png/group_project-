#!/usr/bin/env bash
set -euo pipefail

# Clean generated artifacts so the repo is in a fresh "ready to run" state.
# This script is intentionally conservative: it does not remove source, configs,
# reference datasets, examples, or docs.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "Cleaning generated artifacts in: $ROOT_DIR"

# Python bytecode/caches from script runs and tests.
find . -type d -name "__pycache__" -prune -exec find {} -depth -delete \;
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

# Generated model outputs and figures (keep placeholders).
if [ -d "outputs" ]; then
  find outputs -type f ! -name ".gitkeep" -delete
  find outputs -mindepth 1 -type d -empty -delete
fi

if [ -d "figures" ]; then
  find figures -type f ! -name ".gitkeep" -delete
  find figures -mindepth 1 -type d -empty -delete
fi

# Generated synthetic datasets.
if [ -d "data" ]; then
  find data -maxdepth 1 -type f -name "timeseries*.csv" -delete
fi

# Optional solver scratch files if present in repo root.
find . -maxdepth 1 -type f \( -name "*.lp" -o -name "*.mps" -o -name "*.sol" \) -delete

echo "Clean complete."
