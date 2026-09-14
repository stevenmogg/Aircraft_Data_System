# MGL Extreme SD-card exchange

USB card reader ↔ Pi: AvPlan GPX converted to Extreme routes out, `ENIGMA.REC` + `XTFLIGHT.CSV` in.

## Behaviour

On insert of a volume labelled **MGL** or any USB VFAT that contains those files (e.g. **CHASE2**):

1. Mount at `/media/cozy-mgl` (only for the sync window)
2. Delete every `*.ert` already on the card
3. Convert each AvPlan GPX in `/cozy-data-system/data/flight-plans/` to an 8.3 Extreme route (`MCG_FWO0.ert`, …) using the card’s `Navidata.ewd`
4. Merge any new user waypoints into the card’s `WAYPOINT.EWD` (existing waypoints are kept)
5. Remove leftover AvPlan files (`.gpx` and similar) from the card root
6. Copy `ENIGMA.REC` → `/cozy-data-system/data/mgl-inbox/enigma/ENIGMA_LATEST.REC` (overwrite)
7. Copy `XTFLIGHT.CSV` → `/cozy-data-system/data/mgl-inbox/xtflight/XTFLIGHT_LATEST.CSV` (overwrite)
8. Unmount — safe to remove; no user mount/dismount needed

The Flights page (External Data) lists each GPX → `.ert` mapping and waypoint updates.

Only `_LATEST` files are kept in the inbox (plus `_PROCESSED` after import). No timestamped copies.

On yank/remove, a release unit clears any leftover mount. Stale mounts from a previous card are cleared automatically on the next insert.

If a file is added/changed under `/cozy-data-system/data/flight-plans/` while an MGL card is in the reader, `cozy-mgl-plans.path` runs the same sync (`--if-card`) and rebuilds routes on the card (then unmounts). No card → no-op.

Enigma **import into Historian** (renames `ENIGMA_LATEST.REC` → `ENIGMA_PROCESSED.REC`) is still pending.

## Manual test

```bash
ssh stratux 'sudo /cozy-data-system/scripts/mgl_card_sync.sh /dev/sdb1'
ssh stratux 'cat /cozy-data-system/data/mgl-inbox/last_sync.json'
```

## Install

```bash
sudo ./scripts/setup_mgl_card.sh /path/to/repo
```

Udev: insert → `cozy-mgl-card@sdX1.service`; remove → `cozy-mgl-card-release@sdX1.service`

Path watch: `cozy-mgl-plans.path` → `cozy-mgl-plans.service` when the flight-plans folder changes.
