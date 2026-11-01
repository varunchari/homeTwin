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
3. State → action + delay: door opens → light on, off after a delay. The Automate panel has an explicit delay dropdown (none / 1 minute for live testing / 5 minutes); a selected delay deterministically overrides anything the model inferred from text, so this beat does not depend on Spark parsing "off after a minute". **Status: auto-off after 60 s still unobserved live.** A sunset + 1-minute rule was deployed live on Oct 30 (proposal #32) and did not fire at night — the sunset condition, not the delay, is under investigation (see `docs/evidence-log.md`). Do not claim the delay beat as live until a no-sunset delay run is observed: door on → light on → after 60 s the light turns off by itself, via WebSocket state changes, with no manual tap to turn it off.

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

Push-to-talk only: hold the Voice button, release to transcribe. The transcript is always shown on screen, and voice is never the only path — the typed Automate box still works. Voice is the preferred input, typing is always available alongside it: not everyone is comfortable speaking to a demo, and typed input makes testing and recording deterministic.

Spoken live verification is still open: the Voice panel and its 4-example hint are live, and the transcribe wire (WAV request/audio/encoding, transcript extraction) was proven against the real API, but a mic → transcript → tap / Automate fill run has not yet been observed in a browser with a microphone. It is not claimed as live-verified here.

- Automation transcripts fill the Automate box (and its source/target dropdowns, from the bound entities). The user still clicks Generate plan, then approves before any HA write — voice is a second input to the exact same Spark → validator → approval → deploy pipeline as typed input.
- The tap-control transcript shows an explicit button to turn the reading light on. Clicking it is the action, the same live tap as tapping a pin.
- Only 4 utterances are supported, and anything else gets "not supported yet" and is never executed:
  1. "Turn the reading light on" (tap-control)
  2. "When the door opens, turn the reading light on" (pattern 1)
  3. "When the door opens after sunset, turn the string lights on" (pattern 2)
  4. "When the door opens, turn the reading light on, off after a minute" (pattern 3)
- No spoken replies: Voice Transcribe is speech-to-text only. Audio is sent once for transcription and is not stored; only the transcript text is logged for evidence.
- Integration freeze from here: no new models, SDKs, or services after voice, except the already-planned stretch items if time remains.

## Why dropdowns, not draw-an-arrow, for automation

You are right: dropdowns are the better UX here, and more controlled. Automate uses two dropdowns (trigger region → action region) limited to bound regions only, plus an instruction box and the delay/model dropdowns above. A drawn arrow would have to be parsed into source, target and intent — ambiguous at the edges, fragile under a slightly off drag, and hard to validate before the model runs. Dropdowns make the choice explicit, auditable and re-runnable, which is what a demo and a judge need.

Drawing is kept only where it earns its place: as the manual fallback for creating a region when SAM misses (e.g. the patio door), not for authoring automations.

## Open-weight path (Baseten, labelled)

The Automate panel offers a second model choice: "Open-weight via Baseten (labelled)". It runs the same prompt, JSON schema, deterministic validator and compiler as the hosted Muse Spark path — only the provider changes (Baseten OpenAI-compatible endpoint, `BASETEN_API_KEY` + `BASETEN_MODEL` server-side only, see `.env.example`). The plan panel labels the provider and model on screen, and `spark_calls.jsonl` logs provider + model per call.

Live Baseten beats, both observed: proposal #30 (3,474 ms) and an independent reproduction, proposal #31 (3,109 ms), both via `meta-models/muse-spark-open-1026`, both approved and deployed, both firing door → light live via Home Assistant, with the provider and model labelled on screen (see `docs/evidence-log.md`). That evidence supports an open-weight bonus claim at submission; the claim itself is a submission-day decision, not made in this README.

## Guest view (sliced, tap-only)

`/?guest=1` opens a tap-only view: the demo room photo and bound pins, tap to turn lights/devices on/off, live state via WebSocket. Bind, Automate, Voice, What-If, Advisor, Rearrange, Scenes, and Reset are hidden, and requests carrying `X-HomeTwin-Guest: 1` are refused 403 by the backend before any HA write or model call. Sliced deliberately: no accounts, no expiry, no per-guest permissions — and not authentication, since the public demo has no accounts. A guest is someone who can use the room, not someone who can change the house.

## Reliability (public demo)

- One shared demo, one HA engine. HA has no published port and no admin UI is exposed; the backend is its only client, and no HA or model credentials ever reach the browser.
- Model-costly endpoints (upload, segment, suggest-bindings, propose, advisor suggest/preview/time-of-day, voice transcribe) are rate-limited per client address (30 per 10 minutes by default, `MODEL_RATE_LIMIT_PER_10MIN` / `MODEL_RATE_WINDOW_S` in `.env.example`). Tap, bind, What-If, approve and reset are not limited, so a limited visitor can still run the demo and retry the model step later. This is a demo guard, not authentication.
- Live state comes only from HA WebSocket `state_changed` events, never optimistically. If the socket drops, the UI shows "Reconnecting…" and reconnects after 2 seconds.
- The frozen demo photo is cached and labelled as such ("Photo 7 already known — loaded its regions directly"); a re-uploaded photo reuses its regions without re-spending SAM. A fresh photo on video is the one fresh SAM run.
- Reset works from a fresh session: it turns everything off, deletes deployed `hometwin_*` rules, and clears bindings and history, leaving the demo usable again immediately.
- Advisor and time-of-day live round trips (suggest → preview → apply, all three presets) are still to be verified live after a rebuild; they are described above as shipped code, not claimed as live-verified beats.

## Roadmap (future only — not shipped)

The following are planned, in future tense, and are not present-tense claims about this demo:

- P2: automation debugger, conflict detection, Time Machine, Scene Composer, energy advisor, accessibility advisor, foundational spatial memory.
- P3: persistent multi-photo tracking, guest mode, Autopilot, multi-room mapping, Meta glasses / XR, advanced spatial memory, physical deployment path (Matter / Zigbee / Wi-Fi, swapping entity IDs, same API).
- Stretch, not shipped: light-only active binding, Muse Gadgets Linux SDK (capped, read-only first), advanced What-If.

## Still open before submission

- HTTPS domain for the demo (Caddy already terminates 80/443; this is a domain + DNS change).
- Sunset-condition live fire (see the delay status above and `docs/evidence-log.md`).
- Spoken voice live verification (see Voice above).
- Delete `docs/implementation-plan.md` before final submission, as noted at the top.

## Quick start (Lightsail host)

1. Copy `.env.example` to `.env` and fill in secrets (never commit `.env`).
2. `docker compose up -d --build`
3. Run the Day 1 exit test: `hometwin/.venv/bin/python scripts/day1_exit_test.py`

HA has no published port. Caddy is the only thing on 80/443 and reverse-proxies the backend. HA version pin is recorded in `docs/versions.md`.

## Image attribution

`assets/demo-room/dummy-room.jpg` is AI-generated for this project (rights-clean, no photo release needed).

## License

See [LICENSE](LICENSE).
