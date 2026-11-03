# SKILLS.md — operating the HomeTwin demo

How to run the live demo (and the video) so every claim on screen is honest. Repo/development notes live in [AGENTS.md](AGENTS.md).

## The 12-beat run (one continuous session)

Start from `POST /api/reset` (0 lights on, 0 automations, rail at step 1).

1. **Photo.** "Use demo room" → Photo 7, 6 pins (Display, Lamp, Lamp 2, dashed manual Patio Door, String Lights, TV).
2. **Bind.** Suggest bindings → Approve all. Call out one or two reasons + confidences.
3. **Tap.** Reading pin → orange/glow, "1 light on". TV + Display → screen glow; count stays 1 (not lights).
4. **Voice.** Turn the light off by tap first, then push-to-talk ("turn on reading light") → transcript on screen → control button → light on. If the transcript mishears, say so — the verbatim transcript is the feature working.
5. **Automate (hosted).** Patio Door → Reading light, "only after sunset", no delay → plan → Approve & deploy.
6. **Automate (Baseten).** Same pair, 5-minute delay, model dropdown → Open-weight via Baseten → plan shows provider `open` + dashboard model + "same prompt, schema, validator and compiler" → conflict warning names the first rule → Approve & deploy (`via open-weight (…)`).
7. **Safety.** "unlock the front door" → rejected, no plan, no HA write.
8. **Live fire.** Tap patio door ON → reading light turns on for real. Show the last-fired stamp. Daytime? Show the What-If Day card as *simulated* non-fire instead — never present simulation as a fire.
9. **Advisor + time-of-day.** "Cozy evening" → 2 settings → dock "Preview — …" (illustrative) → Apply. Sunset variant preview → Apply.
10. **Rearrange.** Lamp "closer to the sofa" → pin moves → Approve → moved pin still taps the same light. State plainly: the pin moves, Home Assistant is untouched.
11. **Scenes + Time Machine.** Save "movie night," scramble, Apply restores. Drag the scrubber to re-render a past state; back to Live restores. Pre-recorder times say "no snapshots yet" — that honesty is a feature.
12. **Guest + reset.** `?guest=1` → banner, tap-only, Exit restores the same room. Final Reset → everything off, rules deleted, panels cleared.

## Honesty rules (judging-relevant)

- Previews are illustrative, always labelled. Say "preview," never "this is what it will look like."
- Simulated (What-If day card, timelines) is simulation. Fired (door tap → light on, last-fired stamp) is real.
- Baseten titles may read awkwardly; raw IR stays verbatim in responses, store and `spark_calls.jsonl`. The smoothing is display-only.
- One shared demo: Reset before handing the URL to anyone, and leave it clean afterward.

## On-camera troubleshooting

| Problem | Recovery line |
|---|---|
| Voice mishears | "The transcript shows exactly what the model heard — let me rephrase." |
| Preview stalled | Re-propose once (known flake); the clip cut is fine, the retry is real. |
| Topbar looks stale after Reset | Wait one poll cycle (~2 s); counts settle to 0/0. Don't end on the stale frame. |
| Mic prompt missing | URL must be `https` or `http://localhost:<port>` — secure context or nothing. |
