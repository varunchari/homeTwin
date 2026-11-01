# Muse Gadgets — HomeTwin spike (read-only first)

> **Decision (Varun, 2026-10-31): the demo is conceptual with a
> virtual proof of concept.** There is no point adding Muse-app
> "ask" support on top of this branch, because a paired connection
> cannot be made from this cloud demo (Bluetooth pairing required;
> Lightsail and this VM have no Bluetooth radio). The Gadgets panel
> below is the virtual proof of concept: real HA state, simulated
> gadget invocation, labelled as conceptual — never presented as
> "ask Muse in the app to control this home".

## What this is, and what it is not

Muse Gadgets is **not** a web UI widget SDK. It is Meta's open-source
hardware SDK (announced Oct 2, 2026, Apache 2.0, repo
`facebookincubator/muse-gadget-sdk`, commit inspected here:
`1b894f5`) for building devices that talk to the Muse personal
agent in the Muse app:

- **ESP32 Device SDK** — microcontroller boards with screens, audio,
  sensors.
- **Linux Device SDK** — a systemd service that turns a Raspberry Pi
  (3B+, 4, 5, Zero 2 W) or any Bluetooth-LE Linux machine (Pi OS
  Bullseye+, Debian 11+, Ubuntu 22.04+, Python 3.9+) into a gadget
  Muse can command.

The gadget itself runs no AI model locally — it is an interface to
Muse in the cloud, over Wi-Fi. Every gadget needs an SDK token and
pairing through the phone app; without those, there is no paired
Muse call, and this branch does **not** claim one.

## Prerequisites checklist (answered from the SDK docs, not memory)

- **SDK source and version:** `facebookincubator/muse-gadget-sdk`,
  `linux/` directory, commit `1b894f5` inspected in this spike.
  Upstream code is **not** vendored into this repo — only HomeTwin's
  two command definitions and two scripts below are.
- **Built-in commands:** `system.run` (shell, as the install account),
  `file.read` (64 KB chunks), `file.write` (64 KB chunks, replace on
  complete), `device.health` (uptime, load, memory, disk, temperature).
  At most 4 commands run at once. **This spike deliberately does not
  expose any of them to HomeTwin** — no shell, no filesystem access.
- **Token:** from `gadgets.muse.ai` → Account → SDK tokens
  (`mgst_…`). One token covers up to 50 devices. Stored on the gadget
  at `/var/lib/musegadget/sdk_token`, readable only by root, never in
  this repo, never in the browser, never in a screenshot. Rotate by
  re-running the installer with a new token, then `sudo musegadget pair --force`.
  Read the Gadget SDK Terms before using a token.
- **Pairing:** on the gadget, run the installer (it refuses to run as
  root; it warns if the chosen account can use sudo, because Muse
  then has that account's exact permissions). Pairing is open for
  10 minutes. In the Muse app: Settings → Devices → Developer mode
  on, Add Device, pick the `MuseGadgetXXXXXX` device, accept the
  community-device warning, pick the Wi-Fi network shown (no password
  needed — the machine is already online). Pairing survives reboots
  and stays connected; pair again with `sudo musegadget pair`.
  Community pairing has no manufacturer verification and cannot
  prevent an active man-in-the-middle attack — use a trusted network.
- **Developer mode:** required, as above. It enables the Devices
  pairing flow; it does not by itself grant the gadget new HA access.
- **Custom commands (the integration point):** drop a JSON file in
  `/etc/musegadget/commands.d/`, named after the command, restart
  the service. The file declares `description`, `exec` (argv, no
  shell), `required` / `optional` parameters (types: string, integer,
  number, boolean, object, array), and `timeout_ms` (default 30 s,
  max 600 s). On invocation the program gets the parameters as one
  JSON object on stdin, prints a JSON object on stdout as the result
  (anything else comes back as text), and a non-zero exit or a
  timeout is an error (last stderr line is the reason). Names are
  lowercase words joined by dots; `system.`, `file.`, `device.` and
  `link.` are reserved. Bad definitions are skipped individually.
  When run as root, the directory and files must be root-owned and
  not group/world-writable (symlinks refused).
- **Browser reflection:** Home Assistant is the source of truth and
  the demo UI already reflects HA state via WebSocket
  `state_changed` events, regardless of what changed it — tap,
  automation, or a gadget command. So a gadget light command that
  reaches HA shows up in the browser within the same ~2 s target as
  a tap, with no second UI. Read-only gadget state is shown in the
  Muse chat on a real gadget; in this demo it is also shown in the
  Gadgets panel, labelled simulated.

## HomeTwin commands in this spike

| Command | Step | What it does | Policy |
|---|---|---|---|
| `hometwin.status` | 1, read-only | Returns light states, patio door state, sun state, from the HomeTwin backend. No HA write. | Output filtered to `light.*` + `binary_sensor.patio_door` + `sun.sun` only. |
| `hometwin.light.set` | 2, one write | Turns one light on/off: `{"entity_id": "light.string_lights", "on": true}`. | Script validates `light.*` + boolean `on` before calling the backend; the backend (`POST /api/voice/control`) validates again to `light.*` turn_on/off only. Locks, covers, doors, switches, helpers → 422 / non-zero exit, no HA write. |

Install on a Pi (after pairing, as above):

```sh
sudo cp gadgets/hometwin_status.py /usr/local/bin/hometwin-status
sudo cp gadgets/hometwin_light.py /usr/local/bin/hometwin-light
sudo cp gadgets/commands.d/hometwin.status.json /etc/musegadget/commands.d/
sudo cp gadgets/commands.d/hometwin.light.set.json /etc/musegadget/commands.d/
sudo systemctl restart musegadget
sudo journalctl -u musegadget | grep commands   # should list both commands
```

Set `HOMETWIN_BASE_URL` for the scripts (default
`http://localhost:8000` — correct if the Pi runs the HomeTwin
backend locally; for the Lightsail demo use
`http://3.135.147.231`). The scripts hold no credential: the
backend holds the HA token server-side, and the scripts talk to
the backend, never directly to HA.

## Simulated invocation in the demo UI (what is actually verified)

A paired Muse call has **not** been verified in this branch — it
needs a token, a Pi/Linux gadget, and phone pairing, which this VM
does not have (no Bluetooth LE, no Muse app pairing). What is
verified here, with tests:

- The two command definitions are valid SDK JSON (names, required
  parameters, timeouts, no reserved prefix).
- The two scripts, run with a fake HomeTwin backend, return the
  filtered status and the allowlisted light result, and reject
  non-light entities, non-boolean `on`, and bad JSON before any
  HA write (T-G3).
- The demo backend endpoints (`GET /api/gadgets/status`,
  `POST /api/gadgets/light`) apply the same policy and HA queries,
  and the frontend Gadgets panel displays their results labelled
  **simulated** (T-G1 for status, T-G2 for the string-lights command
  via HA + WebSocket reflection, in the browser run).
- No token, key, or gadget credential appears in the browser, the
  repo, the README, or any screenshot (T-G4) — there is no token in
  this branch at all.

Do **not** claim a Gadgets integration in the submission on the
basis of this branch alone. The claim becomes valid only after a
paired run: Muse in the app invokes `hometwin.status` on a real
gadget and the result is shown, then (optionally) invokes
`hometwin.light.set` for string lights and the browser reflects it.
Until then, this is a spike + documentation, which the plan
explicitly accepts as an outcome.

## Deliberately NOT shipped

General gadget commands, `system.run`, `file.read`, `file.write`,
`device.health` exposed to HomeTwin, any shell/filesystem access
from the demo, and any claim of a paired integration.
