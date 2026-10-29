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
