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

### Windows

In an **Administrator** PowerShell on a 64-bit Windows 10/11 PC:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/drbugspopcorn/mqtt-printer-client/master/app/install.ps1))) -Broker docker-host-esxi.local -Name packing-3
```

It installs into `C:\mqtt-printer-client`, using pinned downloads that it keeps under `tools\` without touching
PATH:
- Python 3.12, machine-wide, only if a usable one isn't already installed
- portable Git, for updates
- SumatraPDF, for silent PDF printing
- WinSW, which runs the client as the `printer-client` service as LocalSystem, starting at boot

Re-running it is safe and keeps `app\.env`. Service logs are in `logs\`.

How printing works on Windows:
- **ZPL and other raw data** goes straight to the printer through the spooler. Use the ZDesigner driver for Zebras,
  or "Generic / Text Only".
- **PDFs** print silently through SumatraPDF and the printer's own driver, scaled to fit. Set the paper size per
  printer on the fleet page; otherwise the size set on the printer in Windows is used.
- Whether a job is a PDF is decided from the file content, not the `raw` flag.
- **Printers must be installed on the PC itself**, either USB or a network printer added by IP. The service can't
  see printers mapped from another PC (`\\otherpc\printer`).
- **Fleet page support** matches Linux: status, queue, cancel/clear, resume (it also unticks "Use printer
  offline"), test print, add/remove printers (via PowerShell, with drivers already installed on the PC), logs,
  restart, reboot and update.

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
