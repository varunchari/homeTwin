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

Baseten A/B rows (Oct 30 only): record model string as shown in the Baseten dashboard, provider, valid-rate, latency per provider.
