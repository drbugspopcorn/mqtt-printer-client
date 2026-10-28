# MQTT printer client

Runs on a box with printers attached (Raspberry Pi, Ubuntu; Windows for raw printing only) and prints whatever the
ShopifyOMS sends it over MQTT. Because the browser only talks to the broker, any device running the OMS - a phone,
an iPad, another PC - can print to printers plugged into any client.

Each client also reports its health to the OMS **Printers** page (`/react/fleet`) and accepts management commands
from it: add/remove CUPS printers, resume stopped queues, cancel jobs, test print, view logs, restart, reboot, and
update itself from GitHub.

## Install

On a fresh Pi OS / Debian / Ubuntu box:

```sh
curl -fsSL https://raw.githubusercontent.com/drbugspopcorn/mqtt-printer-client/master/app/install.sh \
    | sudo bash -s -- --broker docker-host-esxi.local --name packing-1
```

From an existing checkout (also how you migrate an older Pi install - it keeps `app/.env`):

```sh
cd ~/mqtt-printer-client && git pull && sudo ./app/install.sh
```

The installer sets up CUPS, a Python venv in `.venv/`, `app/.env`, a sudoers rule that only allows
`systemctl reboot`, and the `printer-client` systemd service running as the invoking user.

- Only printers physically plugged in by USB are offered to the OMS. That includes ipp-usb/"driverless" USB
  printers, which CUPS shows as `ipp://localhost:60000/…`. Wi-Fi and network printers (including ones cups-browsed
  auto-adds) still appear on the fleet page, marked "Not offered to OMS". Set `PRINTER_CONNECTIONS=usb,network` in
  `.env` to offer them too (the Docker print server does this).
- Logs: `journalctl -u printer-client -f` (or **Load logs** on the fleet page)
- Config: `app/.env` (see `app/example.env`)
- CUPS web UI: `http://<host>.local:631` (the installer enables remote admin, pass `--no-remote-cups` to skip)

## Updates and rollback

**Update** on the fleet page runs `git fetch` then `git reset --hard origin/master`, reinstalls requirements if they
changed, and restarts the service. If the box has local edits, it refuses unless you confirm an overwrite.

systemd starts `app/launcher.py`, which counts starts after an update. If the new code hasn't connected and stayed up
for a minute within 3 starts, the launcher resets back to the previous commit and records the rollback, and the
fleet page shows it. Keep `launcher.py` stdlib-only and simple: it's what recovers a bad update.

## MQTT topics

| Topic | Direction | |
|---|---|---|
| `despatch/printers/` | ← `{"command": "enumerate"}` → `["despatch/printers/<client>/<printer>", …]` | printer discovery (also announced on connect) |
| `despatch/printers/<client>` | ← `{"printer", "url", "raw", "options"?}` | print a document |
| `despatch/clients/<client>/online` | → retained `{"online", "reason", "ts"}` | last will marks the client offline |
| `despatch/clients/<client>/status` | → retained, every 30s | host, temp, disk, memory, Pi throttling, printers, queue, recent jobs, errors, version |
| `despatch/clients/<client>/cmd` | ← `{"id", "action", "args"}` | see `app/commands.py` for actions |
| `despatch/clients/_all/cmd` | ← same | broadcast to every client |
| `despatch/clients/<client>/result` | → `{"id", "action", "ok", "data" \| "error"}` | command results |
| `despatch/clients/<client>/events` | → `{"type": "print", "ok", …}` | each print job's outcome |

**Security:** there's no auth yet. Anyone who can reach the broker can print, reboot clients or trigger updates, so
keep the broker LAN-only. The client already reads `MQTT_USERNAME`/`MQTT_PASSWORD` from `.env` for when the broker
gets per-client credentials and ACLs.

## Local development

**Demo mode** for testing the OMS without paper: set `DEMO_MODE=true` in `app/.env` and run
`python app/printer_client.py`. It registers a printer called `Demo` (`DEMO_PRINTERS=Demo,Demo_Labels` for more).
Anything printed to it shows up at http://localhost:8631, which opens automatically and keeps the last 15 jobs.
PDFs display inline, and ZPL is rendered to label images in the browser with
[zpl-renderer-js](https://github.com/Fabrizz/zpl-renderer-js) (WASM loaded from jsDelivr, so the label data never
leaves your machine). Pick the label size and dpi in the page header. Demo mode doesn't need CUPS or pycups.
It's off unless the flag is set, and it isn't meant for real boxes.

`PRINTER_HANDLER=mock` swaps CUPS for a fake handler that just logs, if you only need the fleet page.
