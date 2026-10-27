# HomeTwin — built during hackathon

A spatial programming and design studio: turn a room photograph into a controllable, automatable virtual home powered by Meta models and real Home Assistant execution.

Built Oct 27–Nov 4, 2026 for the Meta Global AI Developer Hackathon (Cerebral Valley). Track: Indie (default; confirm Day 1). All project code in this repo was written during the hackathon window.

## Layout

- `backend/` — HA proxy: entity query, toggle, WebSocket `state_changed` fan-out. No HA credentials in the browser.
- `frontend/` — static skeleton views. State comes only from HA WebSocket events. No optimistic UI.
- `ha/` — Home Assistant Core config (Docker). Real engine, virtual devices for this demo.
- `assets/demo-room/` — generated dummy room (rights-clean). See its README for fixtures and SAM prompts.
- `docs/` — implementation plan, evidence log, version records.
- `scripts/` — day exit-test runners.

## Quick start (Lightsail host)

1. Copy `.env.example` to `.env` and fill in secrets (never commit `.env`).
2. `docker compose up -d --build`
3. Run the Day 1 exit test: `hometwin/.venv/bin/python scripts/day1_exit_test.py`

HA has no published port. Caddy is the only thing on 80/443 and reverse-proxies the backend. HA version pin is recorded in `docs/versions.md`.

## Image attribution

`assets/demo-room/dummy-room.jpg` is AI-generated for this project (rights-clean, no photo release needed).

## License

See [LICENSE](LICENSE).
