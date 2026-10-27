# Demo room — dummy-room.jpg

Generated dummy room for HomeTwin development and demo. Rights-clean. No proprietary code or knowledge used.

## Visible devices

- Tall floor lamp, back-left corner → `light 1`. Easy SAM target. Prompt: "lamp".
- String lights across back wall → `light 2`. Thin-fixture case for manual-region fallback. Prompt: "string lights".
- Glass patio door, right with dark frame → door sensor. Prompt: "patio door".
- Roller blind on side window → optional blind entity only if free.
- Wall-mounted TV above sofa → display/status target. Prompt: "tv".
- Smart speaker/display on coffee table → voice interaction target. Prompt: "smart speaker".
- Reading light on side table beside sofa on left wall → `light 3`. Prompt: "reading light".

## Demo coverage

- SAM masks + scene graph: lamp, string lights, patio door, tv, speaker, reading light.
- Manual binding + tap-to-control: lamp, string lights, reading light.
- Draw-to-automate: door → light, door + sunset → light, motion → lamp + delay.
- What-If preview: daytime no-fire vs simulated-night fire.
- Design Advisor: "cozy evening" lighting preview.
