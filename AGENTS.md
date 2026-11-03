# AGENTS.md — working in this repo

This file is for AI coding agents (and humans) doing development, deployment, and demo operation on HomeTwin. The demo runbook for *running* the product is [SKILLS.md](SKILLS.md).

## What this is

- `backend/` — FastAPI proxy. Owns images, masks, spatial IDs, bindings, proposals, memory, model calls. Mediates **all** Home Assistant traffic. HA credentials stay server-side.
- `frontend/` — static HTML/CSS/JS served through the backend image. State comes **only** from HA WebSocket `state_changed` events. No optimistic UI.
- `ha/` — Home Assistant Core config (Docker). Owns device states and automations. No published port; the backend is its only client.
- `assets/demo-room/` — rights-clean generated frozen room (Photo 7).
- `tests/` — stdlib `unittest` suite. `docs/` — plan, evidence log, version pins. `scripts/` — exit-test runners.

## Principles (do not break)

1. **HA owns state; the backend mediates; the UI observes.** Never write HA state from the frontend except through backend endpoints. Never let the UI guess state.
2. **Approval before every HA write.** Propose → approve → deploy. No exceptions, no background writes.
3. **Allowlist is absolute.** Door trigger only, `light.turn_on/off` only, sun condition only. The banned-intent gate runs *before* any model call because models launder scope ("unlock the front door" once became a door→light plan).
4. **Raw provenance is verbatim.** `spark_calls.jsonl`, `image_calls.jsonl`, `voice_calls.jsonl` and stored IRs keep exact model output. Display polish (Baseten title smoothing, dock labels) is presentation-only and must never rewrite stored/logged text.
5. **States are memory, pixels are not.** Previews are labelled illustrative. Never present an edited image as a live state, and never fake a relit photo.
6. **Guest is a slice, not auth.** `?guest=1` hides authoring UI; the backend refuses guest-headered authoring with 403. There are no accounts.

## Environment

Copy `.env.example` to `.env` (never commit it). Key vars: `HA_URL`/`HA_TOKEN` (internal only), `SITE_ADDRESS` (public site; `http://localhost` block exists for mic-testing tunnels), `MODEL_API_KEY` + `SAM_MODEL` (SAM/Spark), `BASETEN_API_KEY` + `BASETEN_MODEL` (open path; exact dashboard string; unset → 503), `IMAGE_MODEL`, `TRANSCRIBE_MODEL`, `MEMORY_INTERVAL_S` / `MEMORY_RETENTION_DAYS`, `MODEL_RATE_LIMIT_PER_10MIN` / `MODEL_RATE_WINDOW_S` (model-costly endpoints only).

## Local development

- Python: repo venv at `.venv/`. Run the suite from the repo root: `.venv/bin/python -m unittest discover -s tests`. It must be green before any commit, push, or deploy — currently 159 tests.
- Backend imports resolve from `backend/` (tests insert it into `sys.path`). `DATA_DIR` defaults to a temp dir under tests and to `/app/data` (Docker volume `backend_data`) live.
- Frontend has no build step. Static assertions in `tests/test_ui_layout.py` check HTML/CSS/JS structure — update them when you change IDs, classes, or copy they pin.
- Key runtime files: `backend/app.py` (routes, guards, logging), `backend/automation.py` (IR schema/prompt/validate/compile + display smoothing), `backend/advisor.py`, `backend/voice.py` (closed utterance set), `backend/image_client.py` (downscale + edit), `backend/store.py` (SQLite), `backend/rate_limit.py`, `frontend/app.js` (all UI).

## Deploy runbook (Lightsail)

Target: Ubuntu host, `~/hometwin/`, containers `hometwin-backend`, `hometwin-ha`, `hometwin-caddy`. SSH with the PEM key; escalate sandbox when needed.

1. Commit on a branch, merge to `main`, suite green, `git push origin main`.
2. Copy changed files with `scp` (plain `rsync` has silently skipped changed files here — always verify with `md5sum` remote vs local after copying).
3. `docker compose up -d --build backend` (frontend is baked into the backend image; versioned `/static/app.js?v=` defeats caching). `docker restart hometwin-ha` after HA config changes.
4. Verify inside the new container (e.g. `docker exec hometwin-backend grep -c <marker> app.py`, or import the function and run it), plus `GET /health`.
5. Fresh baseline: `POST /api/reset` → expect `{"ok": true, ...}`; confirm 0 automations via `GET /api/entities`.
6. Live-check the changed beat (propose/preview/transcribe round trip as appropriate; repeats of identical previews must return `cached: true`).

Known gotchas: Caddy only answers configured hosts (`SITE_ADDRESS` + `http://localhost`); the HA API answers 400 (not 404) when deleting a missing automation id — check existence first; HA ghost registry entries after restarts need scrubbing; `sun.sun` follows `ha/configuration.yaml` lat/long + `time_zone` (America/Los_Angeles for the Portland demo).

## Conventions

- Commits: day-free messages, author `Muse Code <muse-code@local>`. Merge to `main`, push upstream.
- Log every model call with model, latency, validation status (evidence log + `*_calls.jsonl`).
- Keep `docs/evidence-log.md` current per beat; pins in `docs/versions.md`.
- The collaboration plan draft was removed before submission (local archive in `prep_docs/`, plus git history); do not re-add planning docs to the repo.
- [JUDGES.md](JUDGES.md) is the submission sheet (live link, video, beat map, honesty notes) — keep it accurate when behaviour changes.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Served UI lacks your change | Stale layer / skipped copy | `scp` + `md5sum` verify, rebuild, check `docker exec` + versioned asset URL |
| Rule deployed but never fires | Missing `automation: !include`, no reload, or ghost entity | Fix include, call `automation/reload`, scrub ghosts, restart HA |
| Sunset rule misfires/misfires-not | Wrong tz/lat-long | `ha/configuration.yaml`: Portland lat/long, `time_zone: America/Los_Angeles`, `sun:` present |
| Open path 503 | Host env unset | Set `BASETEN_API_KEY` + exact dashboard `BASETEN_MODEL` on the host |
| Region spray (dozens of regions) | Chip click misread as segment request | `DELETE /api/photos/{id}/phrases/{phrase}` |
| Mic prompt never appears | Not a secure context | Serve over `https` or `http://localhost:<port>` tunnel |

## Safety rails for agents

- Never print, commit, or paste `.env`, API keys, tokens, or PEM contents. Scan diffs before pushing.
- Never rewrite git history, never force-push, never `git clean` untracked user files.
- Never expose HA admin UI or publish HA ports. Caddy stays the only entry (80/443 + SSH).
- Record, don't invent: if a beat wasn't observed live, say so in the README and evidence log.
