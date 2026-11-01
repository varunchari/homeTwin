# HomeTwin — built during hackathon

A spatial programming and design studio: turn a room photograph into a controllable, automatable virtual home powered by Meta models and real Home Assistant execution.

Built Oct 27–Nov 4, 2026 for the Meta Global AI Developer Hackathon (Cerebral Valley). Track: Indie (confirmed). All project code in this repo was written during the hackathon window.

## Demo

- Live demo (HTTP for now): http://3.135.147.231/ — an HTTPS domain will be added before submission; Caddy already terminates 80/443, so this is a domain + DNS change, not a re-architecture.
- Honest scope: real Home Assistant engine, virtual devices for this demo. Physical rollout swaps entity IDs; the API, compiler and UI stay the same. Six fixtures: Floor lamp, String lights, Reading light, Patio door, TV and Smart display (as switches).
- `docs/implementation-plan.md` is kept in the repo for now for collaboration and brainstorming. It will be deleted before the final submission — shipped behaviour is documented here and in `docs/evidence-log.md`.

## Layout

- `backend/` — HA proxy: entity query, toggle, WebSocket `state_changed` fan-out. No HA credentials in the browser.
- `frontend/` — static views. State comes only from HA WebSocket events. No optimistic UI.
- `ha/` — Home Assistant Core config (Docker). Real engine, virtual devices for this demo.
- `assets/demo-room/` — generated dummy room (rights-clean). See its README for fixtures and SAM prompts.
- `docs/` — implementation plan (collaboration draft, removed before submission), evidence log, version records.
- `scripts/` — day exit-test runners.

## Automation patterns (one compiler, three templates)

1. State → action: door opens → light on.
2. State + condition → action: door opens after sunset → light on.
3. State → action + delay: door opens → light on, off after a delay. The Automate panel has an explicit delay dropdown (none / 1 minute for live testing / 5 minutes); a selected delay deterministically overrides anything the model inferred from text, so this beat does not depend on Spark parsing "off after a minute". **Status: NOT tested live yet** — compiled and unit-tested only. Live delay beat still to run: Patio Door → Reading Light, auto-off 1 minute, Generate → Approve → open the door (light on) → after 60 s the light turns off by itself, via WebSocket state changes, with no manual tap to turn it off.

Approval is required before every HA write. Only the patio door may trigger, only lights may be acted on, and only the sun condition is allowed — no locks, alarms, covers or arbitrary YAML, ever.

## Design Advisor and time of day

Design Advisor: type a request (default "cozy evening") → Muse Spark proposes exactly 2 feasible lighting settings → pick one, preview it with Muse Image, then approve to apply it in Home Assistant. Declining changes nothing.

Time of day: pick Morning, Sunset, or Night → Muse Image edits the room photo into an illustrative variant → apply the matching preset lights, or don't.

Both are honest about their limits, and the UI says so on every preview:

- Settings are only the home's real lights, on or off only — the template lights have no brightness or colour, so none is invented. Relocation stays a suggestion in prose, never an HA action.
- Every preview is labelled illustrative: a mood preview, never a photometrically accurate simulation, and never a promise the room will look exactly like the picture.
- Apply is a separate, approval-gated step, and it only ever calls supported `light.turn_on` / `light.turn_off` actions, validated against the live HA registry first.
- Time-of-day presets are deterministic, not model output: Morning = all lights off, Sunset = string lights + reading light on, Night = reading light on only.

## Voice

Push-to-talk only: hold the Voice button, release to transcribe. The transcript is always shown on screen, and voice is never the only path — the typed Automate box still works.

- Automation transcripts fill the Automate box (and its source/target dropdowns, from the bound entities). The user still clicks Generate plan, then approves before any HA write — voice is a second input to the exact same Spark → validator → approval → deploy pipeline as typed input.
- The tap-control transcript shows an explicit button to turn the reading light on. Clicking it is the action, the same live tap as tapping a pin.
- Only 4 utterances are supported, and anything else gets "not supported yet" and is never executed:
  1. "Turn the reading light on" (tap-control)
  2. "When the door opens, turn the reading light on" (pattern 1)
  3. "When the door opens after sunset, turn the string lights on" (pattern 2)
  4. "When the door opens, turn the reading light on, off after a minute" (pattern 3)
- No spoken replies: Voice Transcribe is speech-to-text only. Audio is sent once for transcription and is not stored; only the transcript text is logged for evidence.
- Integration freeze from here: no new models, SDKs, or services after voice, except the already-planned stretch items if time remains.

## Gadgets (conceptual proof of concept)

No Muse-app "ask" support is added, deliberately: asking the Muse app to control this home would need a paired Pi/Linux gadget (SDK token + Bluetooth pairing), which a cloud demo cannot do. Instead, the demo's Gadgets panel is a conceptual proof of concept with real HA state: it runs, as a simulation, the same `hometwin.status` (read-only) and `hometwin.light.set` (string lights only, allowlisted) commands defined in `gadgets/commands.d/` for a real Pi gadget, and the browser reflects any HA change via WebSocket. It is labelled conceptual in the UI and must never be presented as a paired Muse connection. See `gadgets/README.md` for the full SDK research, pairing steps, and what a paired run would still need to prove.

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
