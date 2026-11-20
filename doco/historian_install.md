# Historian install (Phase 4)

## What runs

| Unit | Role |
|------|------|
| `cozy-historian-data.service` | Bind-mount durable SQLite dir onto SD card |
| `cozy-historian.service` | Daemon: **idle until Start**; Start/Stop over Unix socket |
| CLI `historian` | Talks to the daemon (same path the web UI will use) |

Capture does **not** auto-start on boot. Arm/record with `start-flight`; stop with `stop-flight`.

## Durable storage

Stratux root overlay is a **250 MB tmpfs**. Flight DB lives on the SD card:

1. Files under `/overlay/robase/cozy-data-system/data/historian/`
2. Boot bind-mount → `/cozy-data-system/data/historian`
3. SQLite: `/cozy-data-system/data/historian/cozy_historian.sqlite` (WAL)
4. Control socket: `/cozy-data-system/data/historian/historian.sock`

## Layout

| Item | Path |
|------|------|
| Package | `/cozy-data-system/historian/` |
| Config | `/cozy-data-system/config/historian/` |
| Data | `/cozy-data-system/data/historian/` |
| CLI | `/cozy-data-system/venv/bin/historian` |
| Systemd | `cozy-historian-data.service`, `cozy-historian.service` |

## CLI

```bash
ssh stratux 'systemctl status cozy-historian --no-pager'
ssh stratux '/cozy-data-system/venv/bin/historian status'

# Start recording (returns immediately; daemon keeps sampling)
ssh stratux '/cozy-data-system/venv/bin/historian start-flight'

# Stop recording
ssh stratux '/cozy-data-system/venv/bin/historian stop-flight'

# Timed test (waits until done)
ssh stratux '/cozy-data-system/venv/bin/historian start-flight --duration 5'

# Debug: in-process capture (bypass daemon)
ssh stratux '/cozy-data-system/venv/bin/historian start-flight --foreground --duration 3'

ssh stratux '/cozy-data-system/venv/bin/historian show-flight COZ-YYYYMMDD-NN'
```

Control protocol (JSON line over Unix socket) — for a future web UI:

```text
{"cmd":"status"}
{"cmd":"start","duration_s":null,"flight_id":null}
{"cmd":"stop"}
```

## Deploy package update

```bash
ROOT="/Users/stevenmogg/Documents/Software_Projects/Cozy_Aircraft_Data System"
rsync -az --delete --exclude '__pycache__' "$ROOT/historian/" stratux:/tmp/historian-pkg/
scp "$ROOT/config/historian/historian.yaml" \
    "$ROOT/config/systemd/cozy-historian.service" \
    stratux:/tmp/
ssh stratux 'sudo overlayctl unlock
  sudo rsync -a --delete --exclude __pycache__ /tmp/historian-pkg/ /overlay/robase/cozy-data-system/historian/
  sudo rsync -a --delete --exclude __pycache__ /tmp/historian-pkg/ /cozy-data-system/historian/
  sudo cp /tmp/historian.yaml /overlay/robase/cozy-data-system/config/historian/
  sudo cp /tmp/historian.yaml /cozy-data-system/config/historian/
  sudo cp /tmp/cozy-historian.service /overlay/robase/etc/systemd/system/
  sudo cp /tmp/cozy-historian.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now cozy-historian.service
  systemctl status cozy-historian --no-pager'
```

## Schema (v2)

Tables: `aircraft`, `aircraft_configuration`, `configuration_item`, `flight`, `flight_source`, `historian_10hz`, `historian_1hz`, `event`, `signal`, `meta`.

`historian.yaml` lists **every remaining FIX-Gateway database key** under `signals:`, including units, description, min/max, initial, and tol copied from FIX. On `init-db` / daemon start those keys become SQLite columns; `signal` copies key, column, units, type, rate, and source.

- **10 Hz:** Stratux GPS/AHRS and MGL numeric keys (Airtalk, RDAC, NMEA, servo). Legacy columns stay `fix_lat`, `fix_pitch`, … so existing flights still work.
- **1 Hz:** FIX system keys and all `str` keys.
- **Units:** Historian does not convert. Convert on ingest into FIX; yaml `units:` is the storage contract (`ft`, `degF`, `deg`, `knots`, …).

Seeded: aircraft `COZ` / `VH-COZ`, configuration `COZ_CFG_001`.

Polling ~130 keys at 10 Hz over NetFIX `@r` may overrun the 100 ms tick on a loaded Pi — watch `timing_overruns` after Start. Slow keys are read only on the 1 Hz frames.

### Implemented vs pending

| Capability | Status |
|------------|--------|
| Durable SQLite + bind-mount | Done |
| 10 Hz / 1 Hz FIX sampling | Done (keys in `historian.yaml`) |
| Idle until Start / Stop / MARK | Done |
| Web UI start/stop/mark | Done |
| Enigma.rec import | **Pending** (inbox has `ENIGMA_LATEST.REC` from MGL sync) |
| AvPlan GPX import as flight source | **Pending** |

## Related

- Spec: [Phase 4 Loggingfrom FIX - Specification.md](Phase%204%20Loggingfrom%20FIX%20-%20Specification.md)
- Stage 1: [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md) Phase 4
- MGL inbox: [mgl_card_install.md](mgl_card_install.md)
