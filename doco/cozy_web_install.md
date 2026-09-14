# Phase 5 — Aircraft Web UI

FastAPI + Uvicorn + Jinja/HTMX + WebSocket. Port **8080** (`cozy-web.service`). Independent of Historian.

## Open the UI

- Management Ethernet: `http://192.168.50.2:8080/live`
- Stratux Wi‑Fi: `http://192.168.10.1:8080/live`

## Layout

Each page has a **page-top** strip (title + primary status), then **twisty** sections (`<details>`): primary open by default, secondary closed.

| Page | Top | Open twisty | Closed |
|------|-----|-------------|--------|
| Live | WS / FIX / Historian badges | Instruments + record | Marks |
| Flights | Counts | Flight list | External Data (MGL sync status) |
| Status | Overall / GPS / FIX / Historian / temp | Overview + GPS | FIX / Historian / network / host / MGL |
| Config | Title | Wi‑Fi settings | Aircraft / historian signals |
| Analysis | Flight select | Plot | Export CSV |

## Testable steps (status)

| Step | Deliverable | Status |
|------|-------------|--------|
| **1** | Scaffold, `/api/health`, `/api/status`, systemd | Done |
| **2** | REST flights + start/stop + MARK | Done |
| **3** | WebSocket `/ws/live` ~10 Hz FIX JSON | Done |
| **4** | LIVE page + Start/Stop/MARK | Done |
| **5** | FLIGHTS list + manifest + External Data | Done (Enigma/AvPlan **import UI** still stubbed) |
| **6** | CONFIG + ANALYSIS plot + CSV export | Done |
| **6b** | STATUS page (live state; Config slimmed to settings) | Done |

## Key endpoints

```text
GET  /api/health
GET  /api/status
GET  /api/configuration
GET  /api/external-data
GET  /api/flights
GET  /api/flights/{id}
GET  /api/flights/{id}/manifest
GET  /api/flights/{id}/series?columns=fix_pitch,fix_roll
GET  /api/export/{id}
POST /api/historian/start
POST /api/historian/stop
POST /api/events/mark
WS   /ws/live
```

| `/debug/mgl/can` | MGL CAN monitor (wire decode) |
| `/debug/mgl/airtalk` | MGL Airtalk — FIX instruments plus Watch/Observed/Interface from `MGL_AT_*` (raw USB only if `COZY_AIRTALK_WEB_SERIAL=1`) |
| `/debug/mgl/gps` | Extreme NMEA GGA/RMC (altitudes in feet) |

Live altitudes are **feet**. RDAC CHT/EGT and RDAC temp are compensated **°F** as stored in FIX.

## Install / update

```bash
# from the Mac repo
rsync -az --exclude '__pycache__' web/ stratux-wifi:/cozy-data-system/web/
ssh stratux-wifi 'sudo /cozy-data-system/scripts/persist_cozy_to_robase.sh && sudo systemctl restart cozy-web && curl -s http://127.0.0.1:8080/api/health'
```

See `scripts/setup_cozy_web.sh` for full offline install into robase.

## Related

- Spec: [Phase 5 Aircraft Web UI - Specification.md](Phase%205%20Aircraft%20Web%20UI%20-%20Specification.md)
- Historian: [historian_install.md](historian_install.md)
- MGL card: [mgl_card_install.md](mgl_card_install.md)
- GPS: [gps_matek_sam_m8q.md](gps_matek_sam_m8q.md)
