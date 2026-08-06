# Cozy Aircraft Data System
## System Specification – Stage 1 (Revised)
**Distributed Avionics Data System with FIX-Gateway Core**

**See also:** [Development environment — Mac workstation and Raspberry Pi](development_environment.md) · [Stratux build and imaging workflow](stratux_build_and_imaging.md) · [Stratux local customizations](stratux_local_customizations.md)

---

# 1. Purpose and Scope

Design and implement a **non-essential, advisory-only distributed avionics data system** that:

- Uses a **standardised aircraft data model (FIX)**
- Provides a **unified aircraft Wi-Fi network**
- Runs **Stratux for ADS-B / GPS / AHRS**
- Logs flight data automatically
- Displays system status via cockpit touchscreen
- Uploads data to cloud
- Forms the foundation for a **distributed CAN-based sensor network**

---

# 2. Architectural Philosophy

The system follows a **distributed avionics model**:

- Data is **produced by independent modules**
- Data is **transported over a common bus (future CAN)**
- Data is **centralised logically, not physically**, via FIX-Gateway
- Displays and loggers are **consumers, not owners**

---

# 3. Safety Boundary

The system shall:

- Be **non-essential**
- Have **no control authority**
- Operate **in parallel** with existing avionics
- Not interfere with:
  - engine instrumentation
  - autopilot
  - radios
  - transponder

Failure results in:

- Loss of logging and display only

---

# 4. System Overview

                  (Future CAN Bus Backbone)
                          |
     -------------------------------------------------
     |              |              |                |
 Sensor Nodes   Engine Node   Control Node   Vibration Node
     |
     v
               FIX-Gateway (central data model)
                         |
          -----------------------------------------
          |               |           |            |
      Stratux         Logger     Dashboard    Uploader
   (ADS-B/GPS/AHRS)                  |
                                     v
                          Touchscreen / iPad

---

# 5. Core Components

## 5.1 Raspberry Pi 5 (Central Node)

Runs:

- FIX-Gateway (**core data system**)
- Stratux (**ADS-B / GPS / AHRS provider**)
- Wi-Fi Access Point
- Logging service (via FIX)
- Cloud uploader
- Web dashboard (Streamlit)

### Role:

- Data **gateway**
- Data **aggregator**
- Data **distributor**
- Not a real-time acquisition device

For how the codebase is edited on the Mac, deployed over SSH, and when to use a remote editor session on the Pi, see [development_environment.md](development_environment.md).

---

## 5.2 FIX-Gateway (Core System)

FIX-Gateway is the **central data backbone**:

- Maintains aircraft-wide data dictionary
- Stores:
  - values
  - units
  - validity
  - limits
  - status flags
- Enables:
  - multiple producers
  - multiple consumers
  - clean system expansion

All system components interact through FIX.

---

## 5.3 Stratux Integration

Stratux runs on the Pi and provides:

- ADS-B traffic
- GPS position
- AHRS attitude (if installed)

A **Stratux → FIX adapter** shall:

- read Stratux data streams
- map to FIX keys (e.g. lat, lon, gs, track, roll, pitch)
- publish into FIX-Gateway

---

<a id="cockpit-network"></a>

## 5.4 Cockpit Network

### Wi-Fi

- Pi acts as **Access Point**
- Provides:
  - Stratux feed to AvPlan
  - FIX/dashboard access

### Connected devices:

- iPad (AvPlan)
- iPhone (internet gateway)
- Pi touchscreen

### Constraint

Stratux traffic feed must remain stable at all times.

---

## 5.5 Touchscreen Dashboard (Streamlit)

### Role

- System display only
- No critical logic

### Displays

- system health
- FIX data values
- logging status
- GPS / ADS-B status
- network status
- cloud upload status

---

## 5.6 Logging System

Logging is implemented as a **FIX consumer**.

### Behaviour

- starts automatically on boot
- records FIX data at defined intervals
- writes to file

### Data Source

- all logged data comes from FIX

---

## 5.7 File Storage

### Format

- CSV or JSONL

### Structure

/flight_logs/
    YYYY-MM-DD/
        session_001.csv
        session_001_meta.json

---

## 5.8 Cloud Upload

- runs as independent service
- monitors new log files
- uploads when internet available
- retries on failure

---

# 6. Data Flow Model

Data Source → FIX-Gateway → Consumers

---

# 7. CAN Bus Strategy (Future)

CAN bus is the **standard for all new sensors**.

---

# 8. Legacy Avionics Integration (Future)

Potential integrations:

- GNC-300 (RS-232 GPS data)
- autopilot source logging
- ARINC data investigation

---

# 9. Startup Behaviour

On aircraft power:

1. Pi boots
2. Stratux starts
3. FIX-Gateway starts
4. Stratux data begins feeding FIX
5. logging starts automatically
6. Wi-Fi becomes available
7. dashboard available

---

# 10. Failure Modes

| Failure | Effect |
|--------|--------|
| Pi failure | loss of entire system |
| FIX failure | no data distribution |
| Stratux failure | no GPS/traffic |
| Wi-Fi failure | no iPad connectivity |
| logging failure | no recorded data |
| cloud failure | data retained locally |

---

# 11. Installation

- Panel-mounted Pi + touchscreen
- dedicated 12V → 5V supply
- system labelled **non-essential**

Engineering workflow from a Mac (repo on workstation, deploy over SSH): [development_environment.md](development_environment.md).

---

<a id="development-roadmap"></a>

# 12. Development Roadmap

Workflow (local Mac repo, Pi deploy, optional Remote SSH): [development_environment.md](development_environment.md).

## Phase 1
- Pi + Stratux stable
- Wi-Fi working
- AvPlan connected
- **Flight plan file share:** SMB share `cozy-data` on `/cozy-data-system/data/flight-plans/` for AvPlan export from iPad/iPhone ([flight_plan_file_share.md](flight_plan_file_share.md))

## Phase 2
- FIX-Gateway installed

## Phase 3
- Stratux → FIX adapter working

## Phase 4
- logging from FIX

## Phase 5
- Streamlit dashboard reading FIX

## Phase 6
- cloud upload

---

<a id="software-structure"></a>

# 13. Software Structure

On the Raspberry Pi, mirror this tree at your chosen deploy path (see [development_environment.md](development_environment.md)).

/cozy-data-system
    /fix_gateway_plugins
    /dashboard
    /data
    /config

---

# 14. Key Design Rules

1. All data flows through FIX
2. Pi is not a real-time acquisition device
3. Logging must not depend on network
4. System must auto-start
5. All future expansion via CAN

---

# 15. Strategic Outcome

- scalable avionics data platform
- distributed sensor network
- supports future engine monitoring and flight testing

---

# Next Step

Define the Stratux → FIX mapping.

**Documentation:** [Development environment — Mac workstation and Raspberry Pi](development_environment.md).

---

## Stage 1 implementation status

Stage 1 has been implemented in the local project baseline, including:

- Stratux build and image workflow validated and documented
- Stable wired management network baseline (`eth0` static `192.168.50.2`)
- Stratux AP baseline (`ap0` on `192.168.10.1`)
- Secondary `wlan1` uplink support with iPhone hotspot credentials in build templates
- AP-to-uplink passthrough hooks (forwarding/NAT) for dual-Wi-Fi operation
- MPI3508 HDMI console (720×480 + large font)
- SMB flight-plan share (`cozy-data` → `/cozy-data-system/data/flight-plans/`)

Reference runbook: [stratux_build_and_imaging.md](stratux_build_and_imaging.md). Flight plan share: [flight_plan_file_share.md](flight_plan_file_share.md).
