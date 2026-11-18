#!/usr/bin/env bash
# Apply an updated Peak HRMS codebase zip on a new branch, commit, push and (optionally) open a PR into qa.
# For Git Bash on Windows (also works on Linux/macOS).
#
#   ./scripts/apply-update.sh <zip> <new-branch> ["commit message"] [base-branch]
#   ./scripts/apply-update.sh ~/Downloads/peak-hrms-full.zip feature/SCRUM-128-folder-structure "SCRUM-128: folder structure"
#
# - base-branch defaults to the branch you are on now.
# - The zip must hold the full project (a top folder containing docker-compose.yml).
# - Files tracked in git but missing from the zip are removed with `git rm` (so moves show as renames and
#   history is kept: `git log --follow <file>`). Local-only files (.env, node_modules, .venv, *.db) are never touched.
# - Set NO_PR=1 to skip creating the pull request; PR_INTO=main to target another branch (default qa).
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }
[ $# -ge 2 ] || die "usage: $0 <zip> <new-branch> [\"commit message\"] [base-branch]"
ZIP="$1"; BRANCH="$2"; MSG="${3:-Apply updated codebase}"; BASE="${4:-}"
[ -f "$ZIP" ] || die "zip not found: $ZIP  (check the name in Downloads, e.g. 'peak-hrms-full (1).zip')"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run this inside the cloned repository"
cd "$REPO"
[ -z "$(git status --porcelain)" ] || die "uncommitted changes. Commit them, or run: git stash"
BASE="${BASE:-$(git branch --show-current)}"

echo "1/6  Branch $BRANCH from $BASE"
git fetch origin --quiet || true
git checkout "$BASE" --quiet
git pull --ff-only origin "$BASE" --quiet 2>/dev/null || echo "     (no remote branch $BASE yet - using the local one)"
git checkout -b "$BRANCH"

echo "2/6  Unzipping"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if command -v unzip >/dev/null 2>&1; then
  unzip -q "$ZIP" -d "$TMP"
else
  winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
  powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath '$(winpath "$ZIP")' -DestinationPath '$(winpath "$TMP")' -Force"
fi
SRC="$(dirname "$(find "$TMP" -maxdepth 3 -name docker-compose.yml | head -1)")"
[ -f "$SRC/docker-compose.yml" ] || die "no docker-compose.yml in the zip - is this the full Peak HRMS codebase?"

echo "3/6  Removing tracked files that are no longer in the codebase"
removed=0
while IFS= read -r -d '' f; do
  if [ ! -e "$SRC/$f" ]; then git rm -q -- "$f"; removed=$((removed + 1)); fi
done < <(git ls-files -z)
echo "     $removed files removed"

echo "4/6  Copying the new codebase"
cp -a "$SRC/." "$REPO/"

echo "5/6  Committing"
git add -A
if [ -z "$(git status --porcelain)" ]; then
  echo "No changes compared with $BASE. Nothing to commit."; git checkout "$BASE" --quiet; git branch -D "$BRANCH"; exit 0
fi
git status --short | head -40
git commit -q -m "$MSG"
git push -u origin "$BRANCH"

if [ "${NO_PR:-0}" != "1" ]; then
  echo "6/6  Pull request $BRANCH -> ${PR_INTO:-qa}"
  if command -v gh >/dev/null 2>&1; then
    gh pr create --base "${PR_INTO:-qa}" --head "$BRANCH" --title "$MSG" --body "Codebase update applied from $(basename "$ZIP")." || \
      echo "     Could not open the PR automatically (does branch '${PR_INTO:-qa}' exist on GitHub?). Open it in the browser."
  else
    echo "     GitHub CLI not installed: open the PR in the browser (base ${PR_INTO:-qa} <- $BRANCH)."
  fi
fi

# Folders left with only local files (old node_modules/.venv after a move) are reported, not deleted.
for d in */; do
  d="${d%/}"
  case "$d" in .git|services|docs|scripts|.github) continue ;; esac
  [ -e "$SRC/$d" ] || echo "NOTE: '$d' is no longer part of the codebase (only local files remain). Remove it with:  rm -rf \"$d\""
done
echo "Done."
