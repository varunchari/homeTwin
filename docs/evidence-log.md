# Evidence log — every model call (v1.6 standing rule)

Stage 1 is pass/fail on real Meta model usage. A mock scores zero on Meta Tooling (25%).

| Day | Model (as billed) | Request | Latency | Output | Validation | Cost |
|-----|-------------------|---------|---------|--------|------------|------|
| 1 | — | No model calls on Day 1 (control plane only) | — | — | n/a | $0.00 |
| 2 | sam-3.1 | photo 2 pass (superseded): lamp / string lights / patio door / tv hit; smart speaker missed → manual fallback demoed live | 0.7–4.9 s | 5 SAM + 1 manual | photo 2 retired when speaker became a display | ~$0.015 |
| 2 | sam-3.1 | `lamp` on frozen photo 5 (1920x1280, smart display) | 2477 ms | 2 regions, both with masks (box+mask dupes merged) | floor lamp + reading lamp | ~$0.0025 |
| 2 | sam-3.1 | `string lights` on photo 5 | 3621 ms | 1 region with mask | thin-fixture risk passed | ~$0.0025 |
| 2 | sam-3.1 | `patio door` on photo 5 | 5113 ms | 1 region with mask | full-height right side | ~$0.0025 |
| 2 | sam-3.1 | `tv` on photo 5 | 2033 ms | 1 region with mask | centered wall TV | ~$0.0025 |
| 2 | sam-3.1 | `smart display` on photo 5 | 1424 ms | 0 regions (miss) | — | ~$0.0025 |
| 2 | sam-3.1 | `display` on photo 5 | 3725 ms | 2 regions: smart display + TV dupe (pruned via DELETE) | display at coffee table confirmed | ~$0.0025 |
| 2 | sam-3.1 | `reading light` on photo 5 | 709 ms | 0 regions (miss) | fixture covered by `lamp` instances; no dupe added | ~$0.0025 |
| 2 | sam-3.1 | photo 7 pass — room with window reading nook (pouf + relocated table/lamp), new frozen photo | — | — | `lamp` instances tracked the move (nook + floor) | ~$0.015 |
| 2 | sam-3.1 | `lamp` / `string lights` / `tv` / `display` on photo 7 | 1.3–2.8 s | 2 + 1 + 1 + 1 (TV dupe pruned) | display = smart display at coffee table | ~$0.01 |
| 2 | sam-3.1 | `patio door` on photo 7 | 2032 ms | 0 regions (miss) | manual fallback region added (P0-critical, works normally) | ~$0.0025 |
| 2 | sam-3.1 | `smart display` on photo 7 (fallback live check) | — | matched as `display`, 2 regions (verification dupes pruned after) | phrase-fallback retry works end to end | ~$0.005 |
| 3 | muse-spark-1.3 | binding-match on photo 7 (lamp unbound) | ~10.8 s | 1 proposal: lamp → light.reading_light (0.9, spatial reasoning) | landmark prompt fixed an earlier floor_lamp misguess | judging-evidence pending |
| 3 | muse-spark-1.3 | binding-match rows in `spark_calls.jsonl` (host) | — | model, latency, proposals, raw ids per call | same provenance rule as SAM log | — |
| 4 | muse-spark-1.3 | IR pattern 1: door → reading light, no text | — | valid, 1 action, no condition | live propose, no deploy | judging-evidence pending |
| 4 | muse-spark-1.3 | IR pattern 2: door → floor lamp, "after sunset" | — | valid, sun-after-sunset condition compiled | live propose, no deploy | judging-evidence pending |
| 4 | muse-spark-1.3 | IR pattern 3: door → string lights, "off after a minute" | — | valid, 60s delay compiled | live propose, no deploy | judging-evidence pending |
| 4 | muse-spark-1.3 | invalid probes (lock text, unknown entity, unbound source) | — | model stayed in allowlist; gates returned 409; forced-bad IR rejected 422 in suite | validator proven in kept tests | $0.00 extra |
| 4 | muse-spark-open-1026 (Baseten) | A/B round 1: same 4-case IR suite | 2.5–6.2 s | 3/4 valid; delay case emitted `sun:null`, validator-caught | safety net worked as designed | Baseten $$$ |
| 4 | both providers | A/B round 2 after explicit-null normalization | 3.8–5.0 s | 4/4 valid each; same prompt/schema/validator | DECISION FINAL: comparable, bonus claimed | — |

Baseten A/B rows (Oct 30 only): record model string as shown in the Baseten dashboard, provider, valid-rate, latency per provider.
| 5 | muse-spark-1.3 | live deploy #14: door → reading light, no text | 4262 ms | approved hometwin_14, HA read-back trigger binary_sensor.patio_door → on | first live HA write; deploy now calls automation/reload | judging-evidence pending |
| 5 | — | 3x end-to-end loop (tap patio-door → light) | — | 3/3 door=on light=on, 2 WS state_changed events each | single live rule after cleanup; reset clean each round | — |
| 5 | muse-spark-1.3 | live deploy #15 (pending): "only after sunset" variant | ~4 s | IR carries sun-after-sunset condition, not approved (no HA write) | What-If target | judging-evidence pending |
| 5 | — | What-If #15 day vs night (simulated, labelled) | — | day: fires False (trigger True, condition False); night: fires True | simulator, not an HA emulator | $0.00 extra |
| 5 | — | HA location fix: lat/long Portland + explicit `sun:` | — | sun.sun=below_horizon live (correct for 18:xx PDT); minimal config kept, no default_config | `sun` only loads via default_config otherwise | — |
| 5 | — | HA engine fix: `automation: !include automations.yaml` + approve-time automation/reload | — | engine saw zero rules before (config API wrote YAML nobody loaded); 7 dup rules cleared, 1 live rule | deploy path was store-only until this | — |
| 5 | — | fresh-session fix: proposals scoped per photo; What-If empty until upload | — | global history no longer leaks across photos | kept test: filter by photo |
| 5 | — | demo reset: automations.yaml emptied, 10 registry ghosts scrubbed, HA restarted | — | 23 entities, 0 automations, all devices off; photo 7 graph + 4 bindings intact | `/api/photos/demo` reuses photo 7, no SAM re-spend |
| 5 | — | Home Map-inspired restyle (2D): pins replace boxes, bottom sheet, ambient header, floating toolbar | — | no new frameworks; boxes only in bind mode; glow = live on-state | 2D by design, no fake 3D |
| 5 | muse-spark-1.3 | live finding: "unlock the front door" laundered into door->light plan (validator-blind) | ~5 s | model guessed instead of clarifying; fixed with deterministic pre-model intent gate | rejected 422 pre-model, kept test |
| 5 | — | reset now deletes deployed hometwin_* rules (config DELETE + reload, stale records marked reset) | — | HA reload never purges YAML-removed rules; registry ghosts scrubbed stopped-HA | kept tests: reset-clears, tap-switch, helper-reject |
| 5 | — | TV + smart display bound as switches (input_boolean.tv_on/display_on) with screen-glow overlay | — | tap toggles live; helper inputs rejected from binding | friendly names from HA, entity_ids hidden in UI |
| 5 | meta-models/muse-spark-open-1026 (Baseten) | labelled live beat: door → reading light via open provider, no delay override | 3474 ms | valid IR, approved hometwin_30, read-back ok, door trigger fired light live | bonus-claim evidence; spark_calls.jsonl provider=open |
| — | meta-models/muse-spark-open-1026 (Baseten) | labelled live beat reproduction #31: door → reading light via open provider, no text | 3109 ms | valid IR, approved hometwin_31, read-back ok, door trigger fired light live (independent reproduction from Reset) | bonus-claim evidence; UI label carries provider + model |
| 5 | muse-spark-1.3 | live deploy #32: door → reading light, "only after sunset", delay dropdown 1 minute | 5787 ms | approved hometwin_32, read-back ok, What-If day "no fire" / night "fires, then off after 60s" | live fire FAIL: at night (~20:48 PDT Oct 30, door on, sun.sun below_horizon, automation on) Reading light stayed off, off→on cycle same — sunset condition under investigation (HA time_zone UTC vs Portland location; see README) |
| — | — | NOT OBSERVED LIVE: delay auto-off — door → light, auto-off 1 minute, light off after 60 s with no manual tap | — | compiled + unit-tested only; #32 could not observe auto-off because the sunset rule never turned the light on | do not claim as a live beat until a no-sunset delay run is observed |
| 6 | muse-spark-1.3 + muse-image-1.5 | Advisor live round trip: "cozy evening" → 2 settings → preview rendered (illustrative) → approved "Soft String Glow" applied, lights verified, reset | — | image spend 1 call; only approved setting wrote to HA | — |
## 2026-10-31 - Suite isolation fix (repro: full-discover-100-OK)
- Cause: test_rearrange.py rebound shared store/app DATA_DIR at import and rmtree'd it in tearDownModule, deleting the dir mid-suite; 14 downstream tests failed appending sam_calls.jsonl/voice_calls.jsonl + 1 reset-count failure from leaked move origins.
- Fix: setdefault DATA_DIR convention (no rebind, no rmtree), drain move origins in setUp.
- `hometwin/.venv/bin/python -m unittest discover -s hometwin/tests` -> Ran 100 tests, OK.
## 2026-10-31 - Live verification beats (final build, Lightsail)
- Delay auto-off OBSERVED (no-sunset): proposal #34, hosted muse-spark-1.3, 3423 ms, delay_s=60; approved hometwin_34; door tap simulated on; reading light on at T+10s through T+50s, off at T+60s with no manual tap.
- Lamp-move OBSERVED: Spark move-propose 7110 ms to [0.34, 0.54]; Muse Image move-preview returned illustrative preview; approve moved pin lamp (0.663, 0.636) -> (0.34, 0.54); binding light.reading_light retained; tap toggled reading light on.
- Scene Composer OBSERVED: saved "Live Check" (floor off, string off, reading on); apply returned all three actions; HA states matched.
- Sunset setup: reset cleared hometwin_34, history, bindings, 1 moved pin, 1 scene; scrubbed stale hometwin_33 ghost (entity_registry -2, restore_state -10); proposal #35, hosted muse-spark-1.3, 4570 ms, after-sunset condition; approved hometwin_35; What-If day=False / night=True; sun.sun above_horizon. Live sunset fire still pending local sunset (~01:00 UTC / 18:00 PDT).
- Deploy: final build synced to Lightsail with host .env preserved; backend rebuilt; HA restarted; Caddy serves versioned UI shell (200, 8249 bytes with Host header).
## 2026-11-01 - Sunset live-fire attempt 1 (no fire observed, scheduler fired late)
- The 18:10 PDT one-shot check actually ran ~08:42 PDT Nov 1 (host clock 2026-11-01T15:42Z); sun.sun was still above_horizon (next setting 2026-11-02T00:58Z).
- Tap simulated door on; reading light stayed off across 12 x 10 s polls — correct daytime non-fire, consistent with What-If day=False, but NOT the sunset proof.
- Re-armed afterwards: door tapped back off; rule hometwin_35 still on; door off, reading off.
- Second one-shot check scheduled for 18:10 PDT Nov 1 with an off-to-on guard.
## 2026-11-01 - Sunset live fire OBSERVED (proposal #43, timezone root cause)
- Pre-check found no rule deployed (fresh reset had cleared hometwin_35) under a below_horizon sun — nothing could have fired.
- Control: no-condition rule #42 at night fired in 10 s (door on -> reading on, last_triggered set) — trigger path proven live.
- Sunset rule #41 under the same sun never triggered (last_triggered null): not the sun state (elevation -32 deg) but the sun CONDITION. Root cause: HA time_zone was UTC, and the sun condition anchors "today" to the HA zone — at 04:11 UTC Nov 2, "today's" sunset lay ~20 h in the future, so after-sunset was false all evening PDT.
- Fix: time_zone America/Los_Angeles in ha/configuration.yaml (matches Portland demo location), deployed, HA restarted.
- Proof: pristine reset -> rebind -> sunset proposal #43 (hosted, 6699 ms) -> approve hometwin_43 -> door tap: reading light ON at T+10 s, last_triggered 2026-11-02T04:15:00Z, no manual tap.
- Cleaned up after: reset deleted hometwin_43, ghost registry entries scrubbed, HA restarted, 0 automations verified.

## 2026-11-02 — Preview cost + anchored prompts (feat/preview-cleanup follow-up)
- Advisor/move/time-of-day prompts now anchor to the detected setting: fixtures (lamp positions, TV, display, sofa, windows) must stay put; the edit changes only light mood/glow or the single named lamp move. Room-context fixtures appended to every prompt.
- Image input downscaled to longest edge 1024 (`shrink_for_edit`) before every edit call; content-addressed cache (sha256 photo + prompt) serves repeat previews with `cached: true`.
- Tests: 149 -> 152 (shrink unit + advisor-cache + tod-cache). Suite green.

## 2026-11-02 — Open-weight sunset divergence (proposal #51, unresolved)
- Daytime run, 11:53 AM PST: Baseten rule #51 ("only after sunset") FIRED on a door tap in daylight, while hosted rule #50 under the same conditions correctly stayed "never fired".
- #51 was deleted and the closing Reset cleared proposals, so its compiled IR is no longer inspectable — the divergence is recorded here, not explained away.
- The compiler is model-agnostic (it emits the sun condition whenever the IR condition is after_sunset, none when it is null), so the prime suspect is the open-weight IR dropping the sun condition while its prose still claimed sunset. The earlier UTC-timezone cause is ruled out as the whole story: HA is on America/Los_Angeles, and hosted and open-weight rules both fired correctly at night on Nov 1.
- Status: unresolved. Do not record sunset as fully live-proven for the open-weight path until the capture run is done: re-propose the same Baseten pair in daytime, record the returned IR JSON and compiled HA payload verbatim before Approve, read back the HA condition before any tap, and do not delete or Reset until those records are saved.
- The submission video's rules are any-time rules, so this cut claims no sunset beat on camera.

## 2026-11-03 — Voice, display polish, guest exit, video (submission eve)
- Voice matcher now tolerates missing filler words ("reading light" == "the reading light"); suite 153. Spoken mic verified live over a localhost tunnel: "Turn on reading light" -> transcript -> tap-control button -> light on. A misheard take ("leading") was caught verbatim and retried clean.
- Baseten plan titles get display-only smoothing for provider == open ("opens to on" stutter, repeats, missing "the"); raw IR unchanged in response, store, and spark_calls.jsonl. Suite 154. New `display_description` field; frontend prefers it.
- Ambient clock (browser-local HH:MM) next to the Day/Night badge; safety rejection confirmed single-period live ("...no HA write."). Suite 154.
- Guest-exit bug fixed: exiting `?guest=1` reloaded `/` and dropped the tab photo over live backend state (empty canvas + stale counts). Photo is now remembered per tab (sessionStorage), stashed/restored across guest entry/exit, restored on host boot after graph validation. Suite 159.
- Preview cache verified live: identical advisor preview repeats return the same URL with `cached: true` in ~0.2 s; generated preview confirmed same-room (anchored prompts).
- Video v2 recorded (2:56, within limit): Baseten rule hometwin_59 deployed via meta-models/muse-spark-open-1026, What-If night timeline for #58, voice retry, Reset ending ("2 automations deleted, 6 bindings cleared"). Master at prep_docs/hometwin_demo.mp4, repo copy at docs/hometwin_demo.mp4. Beat map in JUDGES.md.
- Docs: README rewritten to shipped reality, AGENTS.md + SKILLS.md added, planning draft removed from repo (local archive + history retained).
