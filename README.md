# Aircraft Data System

Advisory-only distributed aircraft data platform built around a Stratux-enabled Raspberry Pi and an evolving FIX-centered data model.

This repository captures project docs, local Stratux customizations, and build artifacts/process needed to create a reproducible Stage 1 baseline.

---

## Project overview

The goal is to build a non-essential aircraft data system that:

- Runs Stratux for ADS-B / GPS / AHRS data
- Provides a cockpit-accessible Wi-Fi service
- Establishes a scalable architecture where data ultimately flows through FIX-Gateway
- Logs and visualizes system/flight data
- Supports future cloud upload and CAN-based sensor expansion

Safety position:

- Advisory-only (no control authority)
- Parallel to certified/primary avionics
- Failure impact limited to optional display/logging functions

---

## Current state (Stage 1)

Stage 1 implementation is in place and documented.

Implemented baseline:

- Stratux image build workflow validated from local source
- Reproducible build notes and known constraints captured in doco
- Wired management network baseline (`eth0` static `192.168.50.2`)
- Stratux AP baseline (`ap0` at `192.168.10.1`)
- Secondary uplink support via USB Wi-Fi dongle (`wlan1`) for phone hotspot
- AP client passthrough hooks (forwarding/NAT) wired into templates

Operational result:

- Local management and cockpit AP can coexist with optional internet uplink
- Configuration is source-backed so rebuilds preserve expected behavior

---

## Repository layout

- `doco/`  
  Project architecture and implementation documentation.
- `stratux-master/`  
  Local Stratux source tree with project-specific configuration changes.

Key docs:

- `doco/cozy_aircraft_data_system_stage1.md`
- `doco/development_environment.md`
- `doco/stratux_build_and_imaging.md`
- `doco/stratux_local_customizations.md`

---

## Build and image workflow

Primary runbook:

- `doco/stratux_build_and_imaging.md`

This includes:

- local build prerequisites
- image build steps
- known build constraints
- network defaults baked into this codebase

---

## Customization policy

Project rule:

- Changes required to be persistent are applied in source templates/scripts, not as one-off runtime shell tweaks.

Customization reference:

- `doco/stratux_local_customizations.md`

This document is intended to support future merges with newer upstream Stratux versions.

---

## Next milestones (post Stage 1)

- Define and implement Stratux -> FIX mapping
- Introduce FIX-Gateway in runtime flow
- Implement logger as FIX consumer
- Add dashboard and upload services on top of FIX data

---

## Notes

- Large image/artifact files should generally remain outside git history unless intentionally versioned.
- This repository currently prioritizes reproducibility of the Stage 1 operating baseline.
