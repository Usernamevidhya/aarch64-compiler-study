#!/usr/bin/env bash
# Publish this project to GitHub.
#
# Runs, in order:
#   git init
#   git add .
#   git commit -m "Initial commit: AArch64 Compiler Optimization Study"
#   git branch -M main
#   git remote add origin https://github.com/Usernamevidhya/aarch64-compiler-study.git
#   git push -u origin main
#
# plus the guard rails that make it safe to re-run:
#   * a .gitignore is generated (or topped up) first, so binaries, raw assembly
#     dumps and the build tree are never staged
#   * after `git add .` the staged file list is checked; if a binary/assembly
#     file slipped in (e.g. it was tracked earlier) the script aborts
#   * an existing `origin` remote is updated instead of failing
#   * "nothing to commit" is not an error
#
# Prerequisites: the (empty) repository must already exist on GitHub, and git
# needs credentials for it (a personal access token via the credential helper,
# `gh auth login`, or an SSH remote via REPO_URL=git@github.com:...).
#
# Override the target with:  REPO_URL=<url> ./scripts/push_to_github.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Usernamevidhya/aarch64-compiler-study.git}"
COMMIT_MSG="Initial commit: AArch64 Compiler Optimization Study"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

die() { echo "error: $*" >&2; exit 1; }
step() { echo "+ $*"; "$@"; }

command -v git >/dev/null 2>&1 || die "git is not installed"

# --- .gitignore ---------------------------------------------------------------
ensure_gitignore() {
    local patterns=(
        "# Build output: binaries, raw assembly dumps, vectorization reports"
        "build/"
        "build-*/"
        "*.s"
        "*.elf"
        "*.bin"
        "*.o"
        "*.obj"
        "*.out"
        "*.exe"
        "*.a"
        "*.so"
        "# Python"
        "__pycache__/"
        "*.pyc"
        ".venv/"
        "# Editor / OS"
        ".DS_Store"
        "*.swp"
        ".vscode/"
        ".idea/"
    )
    touch .gitignore
    local p
    for p in "${patterns[@]}"; do
        grep -qxF -- "$p" .gitignore || printf '%s\n' "$p" >> .gitignore
    done
    echo "+ .gitignore ensured ($(grep -vc '^#' .gitignore) patterns)"
}

# --- publish ---------------------------------------------------------------------
step git init
ensure_gitignore
step git add .

# Safety net: nothing binary or assembly-like may be staged.
leaked="$(git diff --cached --name-only | grep -E '(^|/)build[^/]*/|\.(s|elf|bin|o|obj|out|exe|a|so)$' || true)"
if [ -n "$leaked" ]; then
    git reset -q
    printf 'error: refusing to commit build artifacts:\n%s\n' "$leaked" >&2
    echo "If they were tracked earlier, run: git rm -r --cached <path>" >&2
    exit 1
fi

if git diff --cached --quiet; then
    echo "+ nothing new to commit; skipping git commit"
else
    if [ -z "$(git config user.name || true)" ] || [ -z "$(git config user.email || true)" ]; then
        git reset -q
        die "git identity not set. Run: git config --global user.name \"Your Name\" && git config --global user.email you@example.com"
    fi
    step git commit -m "$COMMIT_MSG"
fi

step git branch -M main

if git remote get-url origin >/dev/null 2>&1; then
    if [ "$(git remote get-url origin)" != "$REPO_URL" ]; then
        step git remote set-url origin "$REPO_URL"
    else
        echo "+ remote origin already set to $REPO_URL"
    fi
else
    step git remote add origin "$REPO_URL"
fi

if ! step git push -u origin main; then
    cat >&2 <<EOF

error: push failed. Common causes:
  * the repository does not exist yet: create an EMPTY repo at $REPO_URL
  * no credentials: use a personal access token (password prompt), 'gh auth login',
    or an SSH remote via REPO_URL=git@github.com:Usernamevidhya/aarch64-compiler-study.git
  * the remote already has commits: fetch/merge them first (the script never force-pushes)
EOF
    exit 1
fi

echo "Done: pushed to $REPO_URL (branch main)"
