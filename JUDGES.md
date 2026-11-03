# HomeTwin — judges' sheet

**Live demo:** http://3.135.147.231/ (HTTP; HTTPS is future product-worthy work — needs a registered domain, Caddy already terminates 80/443. The mic beat was executed securely over a local SSH port-forward to `http://localhost`, which browsers treat as a secure context.)
**Video:** [docs/hometwin_demo.mp4](docs/hometwin_demo.mp4) — local master at `prep_docs/hometwin_demo.mp4`; public URL to be added at submission.
**Track:** Indie. **Built:** Oct 27–Nov 4, 2026, all code in this repo. **License:** see [LICENSE](LICENSE).

> ⏱️ **Runtime:** 2:56 — within the 3:00 limit. Ends on the Reset confirmation ("everything off, 2 automations deleted, 6 bindings cleared").

## Watch for (in order)

1. **Photo → regions** — frozen demo room segments into 6 labelled pins (5 SAM + 1 hand-drawn patio door).
2. **Bind** — Spark proposes all six with reasons + confidences; Approve-all.
3. **Tap** — pin glows, topbar counts; TV/display show screen glow without raising the light count.
4. **Voice** — transcript on screen ("turn reading light on") → control button → light on.
5. **Automate ×2** — hosted rule #58 (door → floor lamp, off after 60 s), then the **Baseten open-weight** rule #59 (door → reading light, off after 120 s; provider + `meta-models/muse-spark-open-1026` labelled). Same prompt, schema, validator, compiler — only the provider differs. The two rules have different targets, so no conflict warning appears in this cut.
6. **Live fire + auto-off** — door tap fires the hosted rule live (floor lamp on, last-fired stamp on the card), then the lamp turns itself off after 60 s on camera.
7. **What-If** — #58's +60 s timeline and #59's detail, simulated before anything goes live.
8. **Advisor + time-of-day** — "cozy evening" → 2 settings (Soft String Glow, Warm Reading Corner) → dock preview labelled illustrative → Apply; Sunset preset preview (string + reading on).
9. **Rearrange / Scenes / Time Machine / Guest** — reading-lamp pin move proposed (HA untouched), "cozy morning" scene applied, Time Machine 8:55 AM past view locked then back to live, `?guest=1` tap-only view with automations visible, exit returns to the same room.
10. **Reset** — everything off, rules deleted, panels cleared.

## Honest scope (please hold us to this)

- Real Home Assistant engine, **virtual devices** for this demo. Physical rollout swaps entity IDs; API and compiler stay the same.
- Previews are **illustrative mood edits**, never photometric promises. States are memory; pixels are not.
- What-If cards are **simulation**; the fires in this cut are **real** device state changes (any-time rules, fired live on camera). The sunset rule's live fire is logged separately in the evidence log (#43) and is not a beat in this cut.
- The banned-intent safety gate (locks/alarms/covers rejected pre-model) is shipped code, not a beat in this cut — neither recording captured a refusal on camera, so none is claimed on video.
- The Baseten plan title is display-smoothed; the stored IR and `spark_calls.jsonl` keep the model's verbatim text.
- The demo image is AI-generated (rights-clean): `assets/demo-room/dummy-room.jpg`.

## Repo map

`backend/` proxy · `frontend/` static UI · `ha/` engine config · `tests/` 159-test suite · `docs/evidence-log.md` per-beat model evidence · `AGENTS.md` / `SKILLS.md` operator guides.
