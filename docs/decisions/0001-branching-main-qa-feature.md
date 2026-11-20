# 0001 – Branching: main → qa → feature

Status: accepted · 2026-11-13

## Decision
- `main` is the base branch and always deployable to production.
- `qa` is created from `main`. It is what the QA environment runs.
- Every change is made on a feature branch created from `main` (`feature/<ticket>-<short-name>`, e.g. `feature/PEAKHRMS-116-roles`).
- Pull requests go **feature → qa** first. After testing on QA, a release PR goes **qa → main**.
- Nobody pushes straight to `main` or `qa`; both are protected (PR + green CI + one review).
- Fixes found in QA go on a new feature branch from `main`, then the same path.

## Why
Feature branches from `main` stay independent: a feature that fails QA can be left out of the release without untangling it from others.

## Consequences
`qa` can drift from `main` with half-tested work. After each release, reset `qa` to `main` if it has diverged (`git checkout qa && git reset --hard origin/main && git push --force-with-lease`, done by the lead only).
