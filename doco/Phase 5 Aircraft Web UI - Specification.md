# Phase 5 Aircraft Web UI - Specification

## Cozy Aircraft Web Interface — Functional and Software Specification

> **Implementation status (live Pi / repo):** MVP delivered — FastAPI `:8080`, twisty page layout, LIVE WS, flights + External Data (`/api/external-data`), configuration, analysis/CSV. Enigma/AvPlan **import UI** still deferred until Historian importers exist. See [cozy_web_install.md](cozy_web_install.md).

## 1. Purpose

This specification defines the aircraft-local web interface for the Cozy data system running on the Raspberry Pi.

The aircraft web layer provides:

- live aircraft and system-state display;
- aircraft configuration access;
- flight catalogue and manifest access;
- post-flight MGL Enigma and AvPlan import controls;
- limited analysis of locally retained recent flights;
- Historian and system-health status;
- browser access from the Pi display, iPad, iPhone and maintenance laptop.

The web interface is **not part of the flight-data acquisition path**.

The primary data path remains:

```text
Sensors / Avionics
        ↓
   FIX Gateway
        ↓
    Historian
        ↓
      SQLite
```

The web layer independently accesses FIX Gateway for live data and the Historian/SQLite database for recorded data.


---

## 2. Architectural Principle

FastAPI must be independent of the Historian process.

Historian recording must continue if:

- FastAPI stops;
- Uvicorn stops;
- the browser closes;
- Wi-Fi clients disconnect;
- the Pi display crashes;
- the web UI is restarted or upgraded.

Recommended process architecture:

```text
Raspberry Pi
│
├── stratux.service
├── fix-gateway.service
├── historian.service
│      └── SQLite Historian
└── cozy-web.service
       ├── FastAPI
       ├── Uvicorn
       ├── WebSocket server
       ├── Jinja templates
       ├── HTMX
       └── static assets
```

There must be no dependency from `historian.service` to `cozy-web.service`.


---

## 3. FIX Gateway Access

FIX Gateway is already the common current-state source.

Do **not** introduce another runtime live-data service or a separate shared FIX data client process.

Both Historian and FastAPI independently use the existing FIX Gateway interface:

```text
                 FIX Gateway
                /           \
               /             \
      Historian               FastAPI
          │                      │
        SQLite                WebSocket
                                 │
                                 ▼
                              Browser
```

Shared Python helper functions are acceptable where useful, but there must be no additional runtime service whose failure could affect both Historian and FastAPI.


---

## 4. Technology Stack

### Backend

Use:

- Python 3
- FastAPI
- Uvicorn
- SQLite
- Jinja2

### Frontend

Use:

- HTML5
- CSS
- HTMX
- small amounts of vanilla JavaScript only where necessary

### Live transport

Use:

- WebSockets
- JSON messages

### Charts

Use a browser-side chart library for simple onboard analysis. Plotly.js is acceptable initially.

### Deployment

Use:

- systemd services
- browser access over the aircraft Wi-Fi network
- Chromium kiosk mode for the Pi-mounted display if required

### Explicitly deferred

Do not use Streamlit in the aircraft-local runtime at this phase.


---

## 5. Responsibilities

### Historian

The Historian remains responsible for:

- 10 Hz sampling;
- 1 Hz sampling;
- fixed Historian frame creation;
- event recording;
- flight creation and closure;
- SQLite recording;
- import/synchronisation logic for secondary data;
- protection of recorded flight-data integrity.

### FastAPI

FastAPI may:

- read live FIX values;
- read Historian data;
- read and update approved configuration information;
- invoke Historian/importer operations through defined functions/interfaces;
- create pilot MARK events;
- initiate Enigma and AvPlan imports;
- report import status;
- export recorded flight data;
- serve the web UI.

FastAPI must not own Historian timing or primary data recording.


---

## 6. Functional Areas

The aircraft-local interface is divided into:

```text
LIVE
CONFIGURATION
FLIGHTS
ANALYSIS
```

The ANALYSIS area is deliberately limited to data retained on the aircraft Pi.

Long-term and multi-flight analysis belongs in the future cloud environment.


---

## 7. LIVE

The LIVE page displays the current aircraft state obtained directly from FIX Gateway.

Typical values include:

```text
IAS
TAS
pressure altitude
GPS altitude
groundspeed
track

pitch
roll
heading

RPM
MAP
fuel flow

selected engine data

GPS status
CAN status
FIX Gateway status
Historian status

current flight ID
recording state
elapsed flight time
```

The exact signal set should be configurable.

The LIVE page must not read the Historian database at 10 Hz merely to reproduce live state. Live state comes from FIX Gateway.


---

## 8. WebSocket Live Data

The browser opens one persistent WebSocket connection to FastAPI.

```text
Browser
   │
   │ persistent WebSocket
   ▼
FastAPI
   │
   ▼
FIX Gateway current state
```

FastAPI sends current-state snapshots without repeated HTTP requests from the browser.

The initial maximum live update rate should be **10 Hz**.

The WebSocket does not need to transmit every internal FIX update. It transmits a useful current-state snapshot suitable for display.


---

## 9. JSON Message Format

Use JSON for WebSocket messages.

Example:

```json
{
  "type": "state",
  "timestamp": "2026-08-07T12:48:22.300Z",
  "flight_time_s": 1832.3,
  "air": {
    "ias": 157.2,
    "tas": 171.4,
    "pressure_altitude": 8500
  },
  "engine": {
    "rpm": 2638,
    "map": 22.3,
    "fuel_flow": 27.1
  },
  "attitude": {
    "pitch": 2.3,
    "roll": -4.1,
    "heading": 327.4
  },
  "position": {
    "lat": -36.1234,
    "lon": 145.1234,
    "gps_alt": 8720,
    "groundspeed": 169.2
  },
  "system": {
    "gps_ok": true,
    "fix_ok": true,
    "historian_recording": true
  }
}
```

JSON is preferred initially because it is human-readable, easy to debug, directly supported by browsers and more than adequate for expected bandwidth.

No binary protocol is required initially.


---

## 10. WebSocket Message Types

Support at least:

### State

```json
{"type": "state"}
```

Continuous aircraft and system state.

### Event

```json
{
  "type": "event",
  "event": "GPS_LOST",
  "timestamp": "..."
}
```

### Status

```json
{
  "type": "status",
  "service": "historian",
  "state": "recording"
}
```

### Error

```json
{
  "type": "error",
  "source": "fix",
  "message": "..."
}
```

The protocol may be extended later.


---

## 11. WebSocket Scope

The WebSocket is presentation transport only.

Do not implement:

```text
FIX
 ↓
WebSocket
 ↓
Browser
 ↓
logging
```

Required architecture:

```text
             FIX Gateway
             /         \
            /           \
     Historian          FastAPI
         ↓                 ↓
      SQLite           WebSocket
                          ↓
                       Browser
```

Loss of the WebSocket must have no effect on data recording.


---

## 12. Reconnection and Multiple Clients

The browser must automatically reconnect after WebSocket loss.

The UI must distinguish between:

```text
DISPLAY CONNECTION LOST
```

and:

```text
HISTORIAN NOT RECORDING
```

These are different faults.

FastAPI should support multiple simultaneous clients, typically:

- Pi-mounted display;
- iPad;
- iPhone;
- maintenance laptop.

Each opens its own WebSocket connection and receives the same current state.


---

## 13. REST API

Use REST for discrete actions and queries.

Initial endpoints may include:

```text
GET  /api/status

GET  /api/flights
GET  /api/flights/{flight_id}
GET  /api/flights/{flight_id}/manifest

GET  /api/configuration
GET  /api/configuration/current

POST /api/events/mark

POST /api/import/enigma
POST /api/import/avplan

GET  /api/import/{import_id}

GET  /api/export/{flight_id}
```

Use WebSockets for live state and REST for commands.

For example, MARK should use:

```text
POST /api/events/mark
```

rather than becoming a command embedded in the live WebSocket protocol.


---

## 14. HTMX/Jinja Frontend

HTMX is the preferred aircraft-local UI approach.

Architecture:

```text
FastAPI
   │
   ├── Jinja templates
   ├── HTML fragments
   ├── REST routes
   └── WebSocket
         │
         ▼
       Browser
```

Use HTMX for:

- flight lists;
- manifest views;
- configuration forms;
- import-status panels;
- source details;
- recent-flight analysis controls;
- system-information panels.

Use vanilla JavaScript primarily for:

- WebSocket connection management;
- updating live values;
- live/interactive charts;
- browser functions that HTMX cannot cleanly provide.

Do not introduce React, Vue or another large frontend framework in Phase 5 unless a clear requirement appears later.


---

## 15. CONFIGURATION

The CONFIGURATION area should initially include:

```text
Aircraft identity
Current aircraft configuration
Configuration history

Historian signal allocation
    10 Hz
    1 Hz

FIX signal mapping

Source/import configuration

Software/service versions

System/network information
```

Configuration must use the Historian configuration tables already defined. Do not create a second independent configuration database.

Configuration changes must be explicit (`view` → `edit` → `save`).

Changes that alter the meaning of recorded signals should normally become effective before a new flight rather than silently changing during an active flight.


---

## 16. FLIGHTS

The FLIGHTS page lists locally retained flights.

Suggested columns:

```text
flight ID
date
origin
destination
duration
configuration
sources available
import state
notes
```

Selecting a flight should show:

- manifest;
- configuration reference;
- Historian start/end;
- available sources;
- import status;
- notes;
- export options.


---

## 17. Flight Manifest

Display the Historian `flight` record in human-readable form.

Typical fields:

```text
Flight ID
date

origin
destination

block off
wheels off
wheels on
block on

duration

pilot
POB

configuration

performance profile

purpose
notes

Historian start/end

available data sources
```

Manifest information may come from Historian, AvPlan and manual entry.

The precedence/provenance rules defined in the Historian specification remain applicable.


---

## 18. Secondary Source Import

The FLIGHTS area should allow post-flight import of:

- MGL Enigma CSV;
- AvPlan GPX.

Workflow:

1. Select target flight.
2. Select/upload file.
3. Start import.
4. Display progress/result.
5. Show synchronisation statistics.
6. Show warnings.

The UI must call the existing Historian/importer implementation. FastAPI must not implement a second independent Enigma or AvPlan decoder.


---

## 19. Import Status

Display:

```text
source type
filename

decoder version

records read
records matched
records unmatched
records rejected

mean sync error
maximum sync error

import status
warnings
```

A failed transactional import must leave the Historian unchanged.


---

## 20. Source Visibility and Comparison

Where multiple sources measure the same quantity, show their presence explicitly.

Example:

```text
GPS sources

FIX       available
MGL       available
AvPlan    available
```

The onboard UI may support simple comparisons such as:

- GPS position differences;
- altitude differences;
- heading differences;
- source timing differences.

The aircraft-local system does not need to determine which source is globally “best”.


---

## 21. ANALYSIS — Aircraft Scope

The aircraft-local ANALYSIS page is intentionally limited.

Its purpose is to:

- verify recorded data;
- inspect the current/recent flight;
- check secondary-source synchronisation;
- compare important signals;
- perform simple engineering review before data leaves the aircraft.

Initial functions:

```text
Select flight
Select time range
Select parameter(s)

Plot parameter vs time

Compare two or more source measurements

Basic X-Y plot

Show min / max / mean

Show event markers

Export data
```

Examples:

```text
IAS vs time
RPM vs time
pitch and roll vs time

FIX GPS altitude vs MGL GPS altitude

FIX position vs AvPlan position

EGT/CHT traces

MAP vs RPM
```


---

## 22. Local Storage Boundary

The Pi is expected to retain only a limited number of recent flights.

The exact policy should be configurable later, for example:

```text
retain latest N flights
```

or:

```text
retain until free disk space reaches threshold
```

The initial implementation does not need automatic deletion.

Onboard analysis operates only against flights currently retained on the Pi.


---

## 23. Future Cloud Boundary

Long-term analysis moves off the aircraft.

Conceptually:

```text
Aircraft Pi
   │
   │ completed, synchronised flight
   ▼
Cloud flight store
   │
   ├── many flights
   ├── long-term catalogue
   ├── configuration history
   ├── derived data
   └── multi-flight datasets
          │
          ▼
     Analysis environment
```

Cloud transfer and cloud storage are outside Phase 5 implementation scope.

However, Phase 5 should preserve a clean path to this future architecture.


---

## 24. Future Streamlit Role

Streamlit is deferred to the cloud/off-aircraft analysis environment.

Its likely future role:

```text
Cloud Historian
      │
      ▼
  Streamlit
      │
      ├── select multiple flights
      ├── filter by aircraft configuration
      ├── compare performance across flights
      ├── GAMI analysis
      ├── aerodynamic analysis
      ├── engine trend analysis
      ├── flight-test comparison
      └── engineering dashboards
```

This uses Streamlit where it is strongest: interactive engineering/data analysis across large and evolving datasets.

There should be no Streamlit dependency in the Phase 5 aircraft runtime.


---

## 25. Cloud-Readiness

A completed flight should eventually be transferable as a coherent package containing:

```text
flight manifest

aircraft configuration reference

Historian 10 Hz data
Historian 1 Hz data

events

source catalogue
import records

original Enigma file
original AvPlan GPX

decoder/software versions

checksums
```

Phase 5 need not upload these files, but the local structure should permit later packaging and transfer without redesigning the Historian.


---

## 26. No Internet Dependency

All aircraft-local functions must work without Internet access:

```text
FIX Gateway
Historian
SQLite

FastAPI
WebSocket LIVE page

configuration
flight catalogue
secondary-source import
limited analysis
```

Do not use CDN-hosted JavaScript, CSS, charting libraries or icons.

All web assets must be stored locally on the Pi.


---

## 27. FastAPI Project Structure

Suggested structure:

```text
web/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── status.py
│   │   ├── flights.py
│   │   ├── configuration.py
│   │   ├── imports.py
│   │   ├── events.py
│   │   └── exports.py
│   │
│   ├── websocket/
│   │   ├── live.py
│   │   └── manager.py
│   │
│   ├── services/
│   │   ├── fix.py
│   │   ├── historian.py
│   │   └── system.py
│   │
│   ├── templates/
│   │   ├── base.html
│   │   ├── live.html
│   │   ├── configuration.html
│   │   ├── flights.html
│   │   └── analysis.html
│   │
│   └── static/
│       ├── css/
│       ├── js/
│       └── vendor/
│
└── tests/
```

Cursor may simplify this structure if it preserves the architectural boundaries.


---

## 28. Browser Routes

Initial pages:

```text
/
/live
/configuration
/flights
/flights/{flight_id}
/analysis
```

The root route may redirect to `/live`.

The same application should be usable on:

- Pi cockpit touchscreen;
- iPad;
- iPhone;
- desktop browser.


---

## 29. Cockpit Display Considerations

Design for a touchscreen and cockpit use:

- large touch targets;
- high readability;
- high contrast;
- minimal typing during flight;
- no hover-only controls;
- simple navigation;
- responsive layout;
- kiosk/full-screen compatibility.

The LIVE page should prioritise key information on smaller screens.


---

## 30. System Status

Expose status for at least:

```text
FIX Gateway
Historian
SQLite/database
GPS
CAN
Stratux
disk free space
system uptime
CPU temperature
network status
```

Not all status values need to appear on the main LIVE page.

A dedicated system-status panel may expose detailed diagnostics.


---

## 31. Historian Status

Clearly distinguish:

```text
NOT RECORDING
RECORDING
STOPPING
ERROR
```

Where available, show during recording:

```text
flight ID
elapsed time
10 Hz frame count
1 Hz frame count
timing-overrun count
```

Historian state must come from the Historian/system status mechanism, not be inferred from whether FastAPI is running.


---

## 32. Pilot MARK

The LIVE page should provide an easily accessible `MARK` button.

Use REST:

```text
POST /api/events/mark
```

The resulting event is stored through the Historian event mechanism.

Support:

- quick unlabeled MARK;
- optional label such as `Start speed run`, `Start GAMI sweep`, or `Test point 3`.


---

## 33. SQLite Access

FastAPI may read Historian SQLite data.

Historian-owned writes should normally occur through Historian/importer functions rather than arbitrary SQL from the web layer.

SQLite WAL mode should allow:

```text
Historian writer
      +
FastAPI readers
```

to coexist with minimal blocking.

The web UI must not materially affect 10 Hz Historian timing.


---

## 34. Performance Test Condition

Test the Pi with all of the following active simultaneously:

```text
Historian at 10 Hz
Historian at 1 Hz

FastAPI/Uvicorn

Pi browser in kiosk mode

at least one additional browser

WebSocket live updates

SQLite reads

simple local charts
```

Historian timing diagnostics must remain acceptable under this load.


---

## 35. Error Handling

The UI must distinguish between:

```text
WebSocket disconnected

FIX unavailable

Historian not recording

Historian/database error

secondary-source import failure

aircraft Wi-Fi problem

cloud unavailable
```

These have different meanings and must not collapse into one generic error state.


---

## 36. Security Scope

The initial system runs on the aircraft-local network, but basic safe design is still required:

- changing routes use POST/PUT rather than GET;
- uploads validate file type and size;
- filenames are sanitised;
- arbitrary filesystem paths are rejected;
- FastAPI request models validate inputs;
- imported files are treated as untrusted input;
- no remote/CDN dependencies are required.

Authentication can be added later if needed.


---

## 37. Phase 5 Minimum Viable Product

Cursor should implement:

### Backend

1. Independent FastAPI application.
2. Uvicorn deployment.
3. Direct access to existing FIX Gateway.
4. SQLite Historian read access.
5. REST API framework.
6. WebSocket endpoint.
7. JSON live-state messages.
8. multiple-client support.
9. automatic browser reconnect.
10. systemd service definition.

### Frontend

11. Jinja base template.
12. HTMX integration.
13. LIVE page.
14. CONFIGURATION page.
15. FLIGHTS page.
16. basic ANALYSIS page.
17. responsive layout.
18. all dependencies hosted locally.

### LIVE

19. Display selected FIX parameters.
20. Show FIX connection state.
21. Show Historian state.
22. Show current flight ID/elapsed time where available.
23. Provide MARK button.

### FLIGHTS

24. List local flights.
25. Open manifest.
26. Show source catalogue.
27. Invoke Enigma import.
28. Invoke AvPlan import.
29. Show import result/status.

### ANALYSIS

30. Select locally retained flight.
31. Select time range.
32. Select parameter(s).
33. Plot parameter vs time.
34. Compare independent source values.
35. Show simple statistics.
36. Show event markers where practical.
37. Export flight data.


---

## 38. Acceptance Tests

### Independence

- Historian continues recording when `cozy-web.service` is stopped.
- Historian continues recording when all browsers disconnect.
- Restarting the web service does not alter Historian frames.
- FastAPI failure does not corrupt SQLite Historian data.

### WebSocket

- Browser receives live JSON state.
- Updates are delivered at configured rate up to 10 Hz.
- Connection loss is detected.
- Automatic reconnect succeeds.
- At least two clients can receive live data simultaneously.

### REST

- Flight list can be retrieved.
- Flight manifest can be retrieved.
- MARK event can be created.
- Enigma import can be initiated.
- AvPlan import can be initiated.
- Import result/status can be reviewed.

### Frontend

- Pi touchscreen layout is usable.
- iPad layout is usable.
- UI works without Internet access.
- all JavaScript/CSS libraries are local.

### Performance

- Historian records at 10 Hz while web UI and multiple clients are active.
- no unacceptable Historian timing degradation occurs.
- SQLite reads do not cause unacceptable writer blocking.


---

## 39. Architectural Rules

1. FastAPI is independent of the Historian.
2. FastAPI accesses the existing FIX Gateway directly for LIVE data.
3. No additional shared live-state runtime service is introduced.
4. Historian is authoritative for recorded data.
5. WebSocket is live presentation transport, not acquisition.
6. Use JSON for WebSocket messages.
7. Use REST for discrete commands and operations.
8. Use HTMX/Jinja/HTML for the aircraft-local interface.
9. Use minimal vanilla JavaScript where required.
10. Do not use Streamlit in the aircraft-local Phase 5 runtime.
11. Onboard analysis is limited to locally retained recent flights.
12. Long-term/multi-flight analysis belongs in the future cloud environment.
13. Streamlit is a candidate for that future cloud analysis layer.
14. The complete aircraft-local system must work without Internet access.
15. Web UI failure must never stop or become a prerequisite for Historian recording.


---

## 40. Overall Architecture

```text
                          AIRCRAFT
                             │
                     Sensors / Avionics
                             │
                             ▼
                        FIX Gateway
                        /         \
                       /           \
                      ▼             ▼
               Historian         FastAPI
                   │               │
                   ▼               ├── REST
                 SQLite            ├── WebSocket / JSON
                   │               └── HTMX / Jinja UI
                   │                        │
                   │                ┌───────┼─────────┐
                   │                ▼       ▼         ▼
                   │             Pi UI    iPad      Laptop
                   │
                   ├── 10 Hz
                   ├── 1 Hz
                   ├── Events
                   ├── Manifest
                   ├── Configuration
                   └── Synced sources
                          │
                          ▼
                   Recent onboard flights
                          │
                   Limited local analysis
                          │
                          ▼
                   Future flight transfer
                          │
                          ▼
                         CLOUD
                          │
                    Long-term Historian
                          │
                          ▼
                       Streamlit
                          │
                  Multi-flight analysis
```


---

## 41. Definition of the Aircraft Web Layer

> **The Cozy aircraft web layer is an independent FastAPI-based access and presentation service that reads live aircraft state directly from the existing FIX Gateway, reads recorded flight information from the Historian, distributes live state to browsers using JSON WebSockets, and provides a lightweight HTMX/Jinja interface for live status, configuration, recent flights and limited onboard analysis.**

Its role is intentionally limited to the aircraft-local environment.

Long-term storage and advanced multi-flight analysis are deferred to the future cloud architecture.
