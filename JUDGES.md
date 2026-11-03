# HomeTwin — judges' sheet

**Live demo:** http://3.135.147.231/ (HTTP; HTTPS is a parked domain+DNS change — Caddy already terminates 80/443)
**Video:** [docs/hometwin_demo.mp4](docs/hometwin_demo.mp4) — local master at `prep_docs/hometwin_demo.mp4`; public URL to be added at submission.
**Track:** Indie. **Built:** Oct 27–Nov 4, 2026, all code in this repo. **License:** see [LICENSE](LICENSE).

> ⏱️ **Runtime note:** the current cut is 3:37 and must be trimmed to ≤3:00 before submission. Suggested cuts: the first misheard voice take (~20 s, keep the retry), and 10–15 s from the rearrange/time-machine beats. The ending must land on settled 0-lights/0-automations counts, not the mid-Reset frame.

## Watch for (in order)

1. **Photo → regions** — frozen demo room segments into 6 labelled pins (5 SAM + 1 hand-drawn patio door).
2. **Bind** — Spark proposes all six with reasons + confidences; Approve-all.
3. **Tap** — pin glows, topbar counts; TV/display show screen glow without raising the light count.
4. **Voice** — transcript on screen ("turn reading light on") → control button → light on.
5. **Automate ×2** — hosted rule, then the **Baseten open-weight** rule (provider + `meta-models/muse-spark-open-1026` labelled, conflict warning names the first rule). Same prompt, schema, validator, compiler — only the provider differs.
6. **Safety** — "unlock the front door" rejected, no plan, no HA write.
7. **Live fire** — patio door ON at night → reading light turns on for real (last-fired stamp on the rule card).
8. **Advisor + time-of-day** — "cozy evening" → 2 settings → dock preview labelled illustrative → Apply; Night preset applied.
9. **Rearrange / Scenes / Time Machine / Guest** — pin moves (HA untouched), "movie night" saved + restored, timeline scrub re-renders past states, `?guest=1` tap-only view.
10. **Reset** — everything off, rules deleted, panels cleared.

## Honest scope (please hold us to this)

- Real Home Assistant engine, **virtual devices** for this demo. Physical rollout swaps entity IDs; API and compiler stay the same.
- Previews are **illustrative mood edits**, never photometric promises. States are memory; pixels are not.
- What-If day cards are **simulation**; the night fire is **real** (sun was down live).
- The Baseten plan title is display-smoothed; the stored IR and `spark_calls.jsonl` keep the model's verbatim text.
- The demo image is AI-generated (rights-clean): `assets/demo-room/dummy-room.jpg`.

## Repo map

`backend/` proxy · `frontend/` static UI · `ha/` engine config · `tests/` 159-test suite · `docs/evidence-log.md` per-beat model evidence · `AGENTS.md` / `SKILLS.md` operator guides.
