# HomeTwin — built during hackathon

A spatial programming and design studio: turn a room photograph into a controllable, automatable virtual home powered by Meta models and real Home Assistant execution.

Built Oct 27–Nov 4, 2026 for the Meta Global AI Developer Hackathon (Cerebral Valley). Track: Indie (confirmed). All project code in this repo was written during the hackathon window.

## Demo

- Live demo (HTTP for now): http://3.135.147.231/ — an HTTPS domain will be added before submission; Caddy already terminates 80/443, so this is a domain + DNS change, not a re-architecture.
- Honest scope: real Home Assistant engine, virtual devices for this demo. Physical rollout swaps entity IDs; the API, compiler and UI stay the same. Six fixtures: Floor lamp, String lights, Reading light, Patio door, TV and Smart display (as switches).
- The implementation plan is an internal working document and is deliberately not kept in this repo. Shipped behaviour is documented here and in `docs/evidence-log.md`.

## Layout

- `backend/` — HA proxy: entity query, toggle, WebSocket `state_changed` fan-out. No HA credentials in the browser.
- `frontend/` — static views. State comes only from HA WebSocket events. No optimistic UI.
- `ha/` — Home Assistant Core config (Docker). Real engine, virtual devices for this demo.
- `assets/demo-room/` — generated dummy room (rights-clean). See its README for fixtures and SAM prompts.
- `docs/` — evidence log, version records.
- `scripts/` — day exit-test runners.

## Automation patterns (one compiler, three templates)

1. State → action: door opens → light on.
2. State + condition → action: door opens after sunset → light on.
3. State → action + delay: door opens → light on, off after a delay. The Automate panel has an explicit delay dropdown (none / 1 minute for live testing / 5 minutes); a selected delay deterministically overrides anything the model inferred from text, so this beat does not depend on Spark parsing "off after a minute". Live delay beat to run after a rebuild: Patio Door → Reading Light, auto-off 1 minute, Generate → Approve → open the door (light on) → after 60 s the light turns off, via WebSocket state changes.

Approval is required before every HA write. Only the patio door may trigger, only lights may be acted on, and only the sun condition is allowed — no locks, alarms, covers or arbitrary YAML, ever.

## Why dropdowns, not draw-an-arrow, for automation

You are right: dropdowns are the better UX here, and more controlled. Automate uses two dropdowns (trigger region → action region) limited to bound regions only, plus an instruction box and the delay/model dropdowns above. A drawn arrow would have to be parsed into source, target and intent — ambiguous at the edges, fragile under a slightly off drag, and hard to validate before the model runs. Dropdowns make the choice explicit, auditable and re-runnable, which is what a demo and a judge need.

Drawing is kept only where it earns its place: as the manual fallback for creating a region when SAM misses (e.g. the patio door), not for authoring automations.

## Open-weight path (Baseten, labelled)

The Automate panel offers a second model choice: "Open-weight via Baseten (labelled)". It runs the same prompt, JSON schema, deterministic validator and compiler as the hosted Muse Spark path — only the provider changes (Baseten OpenAI-compatible endpoint, `BASETEN_API_KEY` + `BASETEN_MODEL` server-side only, see `.env.example`). The plan panel labels the provider and model on screen, and `spark_calls.jsonl` logs provider + model per call.

Live Baseten beat to run after a rebuild: same door → light plan with the Baseten option selected, approved and deployed, with the provider label visible. Two things remain open before the $10k Best Open Weight bonus is claimed in the submission: (1) set `BASETEN_MODEL` to the exact string shown in the Baseten dashboard (no unverified dated label is hard-coded; the open path returns 503 until it is set), and (2) run that one labelled live beat. Until both are done, Baseten is a shipped, labelled path — not yet a claimed bonus.

## Quick start (Lightsail host)

1. Copy `.env.example` to `.env` and fill in secrets (never commit `.env`).
2. `docker compose up -d --build`
3. Run the Day 1 exit test: `hometwin/.venv/bin/python scripts/day1_exit_test.py`

HA has no published port. Caddy is the only thing on 80/443 and reverse-proxies the backend. HA version pin is recorded in `docs/versions.md`.

## Image attribution

`assets/demo-room/dummy-room.jpg` is AI-generated for this project (rights-clean, no photo release needed).

## License

See [LICENSE](LICENSE).
