# HomeTwin — built during hackathon

A spatial programming and design studio: turn a room photograph into a controllable, automatable virtual home powered by Meta models and real Home Assistant execution.

Built Oct 27–Nov 4, 2026 for the Meta Global AI Developer Hackathon (Cerebral Valley). Track: Indie (confirmed). All project code in this repo was written during the hackathon window.

## Contributors

- Varun Chari (sole human contributor — plan, review, live testing, video)
- Muse Code, powered by Meta Muse Spark (agentic coding: implementation, tests, deploys)

## Demo

- Live demo (HTTP for now): http://3.135.147.231/ — HTTPS is future product-worthy work (needs a registered domain; Caddy already terminates 80/443, so it is domain + DNS only, not a re-architecture). Secure-context needs were covered without it: mic testing ran over a local SSH port-forward to `http://localhost`, which browsers treat as a secure context.
- Video (2:56): [docs/hometwin_demo.mp4](docs/hometwin_demo.mp4) — beat map and honesty notes for judges live in [JUDGES.md](JUDGES.md).
- Honest scope: real Home Assistant engine, virtual devices for this demo. Physical rollout swaps entity IDs; the API, compiler and UI stay the same. Six fixtures: Floor lamp, String lights, Reading light, Patio door, TV and Smart display (as switches).
- Shipped behaviour is documented here and in `docs/evidence-log.md`; the collaboration plan draft was removed before submission (archived locally, outside the repo).

## What shipped (all live-verified)

**Photo → graph.** Upload or "Use demo room" (frozen Photo 7). SAM 3.1 text prompts segment lamps, string lights, TV, display; misses fall back to a retry with simpler tails plus phrase chips, and the patio door is a hand-drawn manual region. Duplicate box+mask hits are merged (IoU), region spray is guarded (phrase-level delete). Re-segmenting replaces regions instead of duplicating them; closing/reopening the tab retains the graph; re-uploads reuse cached regions without re-spending SAM.

**Bind.** Spark suggests all six bindings with reasons and confidences (Approve-all included); a manual region→entity picker remains the reliable baseline. Unbinding and "start fresh" are one click.

**Tap.** Pins glow orange with ON badges; TV/display show screen glow on power-on. State comes only from HA WebSocket events — no optimistic UI. A topbar clock sits next to the Day/Night badge as the visible "now."

**Automate.** Gesture (bound source/target) + text → Muse Spark AutomationIR → deterministic validator → deterministic compiler (three templates: state→action, +sunset condition, +auto-off delay) → approval → HA deploy with read-back. The delay dropdown (none / 1 min / 5 min) deterministically overrides model text. Safety first: a pre-model banned-intent gate rejects locks/alarms/covers with a plain reason, before any model call. Live-verified: 60-second auto-off fired on its own (#34); the sunset rule fired for real after the timezone root cause was fixed (UTC→America/Los_Angeles, #43).

**Open-weight path (Baseten, labelled).** The Automate model dropdown offers hosted Muse Spark or open-weight via Baseten — same prompt, schema, validator and compiler, only the provider differs (`BASETEN_API_KEY` + dashboard `BASETEN_MODEL`, host env only, 503 until set). The plan panel labels provider + model; `spark_calls.jsonl` logs both per call. Open-weight titles get display-only smoothing (raw IR stays verbatim in the response, store and logs). Live-verified: proposals #30/#31 and deployed rule #54 via `meta-models/muse-spark-open-1026`.

**What-If.** Per-rule cards, simulated sun day/night, fires / no-fire with a door→on→off timeline. Simulated states never touch live lights.

**Design Advisor + time-of-day.** Spark proposes exactly 2 feasible light-only settings; Muse Image edits the *room photo* (anchored prompts keep every fixture in place) into labelled-illustrative previews mirrored in a dock; Apply is approval-gated and only calls `light.turn_on/off`. Morning / Sunset / Night presets are deterministic. Inputs are downscaled to 1024px and repeat previews serve from a content-addressed cache (`cached: true`, ~zero latency) — verified live.

**Rearrange (lamp-move, honest).** Advisor proposes moving one bound lamp; the pin moves in the UI proposal, HA is untouched, Tap still works on the same light. Decline or Reset reverts.

**Scenes.** Save current light states under a name; one approval-gated Apply restores them.

**State memory + Time Machine.** The backend snapshots device states every 60 s (7-day retention, read-only vs HA). Drag the timeline or press play to re-render recorded states; pre-recorder times honestly say "no snapshots yet." States are memory — pixels are not: the photo itself is never relit.

**Voice.** Push-to-talk, transcript always shown, typing always available. Four utterances plus filler-word tolerance ("reading light" or "the reading light"); anything else gets "not supported yet" and never executes. Tap transcripts show an explicit control button; automation transcripts fill the Automate box for the normal review→Generate→approve path. No spoken replies, no stored audio. Live-verified with a real mic over a localhost tunnel (secure context), including a misheard take the transcript caught verbatim. HTTPS would remove the tunnel need.

**Guest view.** `?guest=1` is tap-only: photo auto-loads, authoring panels hide, and guest-headered requests get 403 on any authoring endpoint (observed live). Exiting returns to the same room, not an empty canvas.

**Reliability.** Rate limits on model-costly endpoints only (30/10 min); tap/bind/What-If/approve/reset unlimited. One-click Reset turns everything off, deletes deployed rules, clears bindings/panels/history. Conflict warnings name the overlapping deployed rule before a second one is approved.

## Roadmap (future only — not shipped)

Near term (small, high demo value): HTTPS domain; Onboarding tour (future, NOT a judge mode) — a per-account, resumable walkthrough to be built when user accounts and account management exist, never a judge-specific mode; "why didn't my light turn on" debugger — read-only trace over rules, states, history and sun, with fixes proposed through the normal approval path; advisor variants (accessibility, reading-light); mobile/narrow-screen polish; preview-disk cleanup job (files accumulate today); cost/latency dashboard from the existing `*_calls.jsonl` logs.

Long term (bigger bets): multi-room / multi-photo mapping; Matter/Zigbee/Wi-Fi physical rollout (same API, real entity IDs); energy advisor once real power data exists (never invented numbers); Autopilot-style suggestions; advanced spatial memory (multi-day patterns, anomaly notes); Meta glasses / XR overlay; Muse Gadgets SDK integration; agentic routines — multi-step tool calls (existing endpoints as typed tools) with per-step human approval, proactive memory notes that propose but never act, a new-photo setup agent, and trajectory logging (goal → tool calls → approvals → outcome) as provenance for any future agentic claim.

Non-goals: door locks or security devices in the demo allowlist; photometric "relit photo" claims; mock model calls passed off as real; any HA write without approval — including autonomous agent writes.

## How this product can be improved

- **Real lights, real attributes.** The demo templates are on/off only, so brightness, color and transitions are deliberately uninvented. Real bulbs unlock the Advisor's full vocabulary.
- **Real telemetry.** Energy, occupancy and power readings would ground an energy advisor and a debugger that reasons about actual consumption.
- **Latency.** Model calls take 2–10 s; the preview cache and deterministic delay dropdown already remove two waits. Streaming partial plans and smaller/faster models would remove more.
- **Robustness.** SAM still misses thin or odd fixtures (manual fallback covers it); transcription mishears (verbatim transcript + closed set contain it). Confidence-gated auto-retry is the next step.
- **Multi-user.** Accounts unlock per-user tours, saved rooms, and real auth to replace the tap-only guest slice.
- **Ops.** SQLite backups, log rotation, and snapshot retention jobs before any always-on production use.

## Quick start

From the repo root (`hometwin/`):

1. Copy `.env.example` to `.env` and fill in secrets (never commit `.env`). Every key is server-side; the browser never sees one.
2. `docker compose up -d --build` — services: `hometwin-ha` (no published ports), `hometwin-backend`, `hometwin-caddy` (80/443 only).
3. `.venv/bin/python -m unittest discover -s tests` — full suite, must be green before any push or deploy.
4. `docker restart hometwin-ha` after config changes; Reset in the UI for a clean demo baseline.

HA version pin is recorded in `docs/versions.md`. Deployment notes for agents live in [AGENTS.md](AGENTS.md); the demo runbook lives in [SKILLS.md](SKILLS.md).

## Image attribution

`assets/demo-room/dummy-room.jpg` is AI-generated for this project (rights-clean, no photo release needed).

## License

See [LICENSE](LICENSE).
