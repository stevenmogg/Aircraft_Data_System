# Phase 4 Loggingfrom FIX - Specification

## Cozy Aircraft Historian — Functional and Software Specification

> **Implementation status (live Pi / repo):** Capture core done — durable SQLite, 10/1 Hz FIX sampling, idle-until-start daemon, MARK, web start/stop. MGL card copies `ENIGMA_LATEST.REC` / `XTFLIGHT_LATEST.CSV` into inbox. **Not done:** Enigma/AvPlan importers and secondary-source sync into Historian tables. See [historian_install.md](historian_install.md) · [mgl_card_install.md](mgl_card_install.md).

## 1. Purpose

The Cozy Aircraft Historian is a flight-data recording, cataloguing and post-flight synchronisation system.

Its purpose is to create one coherent historical data record for each flight from:

1. Real-time data available through FIX Gateway during flight.
2. Secondary data sources imported after flight, initially:
   - MGL `Enigma.rec` / exported CSV data.
   - AvPlan GPX flight logs.
3. Future additional sources such as test instrumentation, weather data, maintenance/configuration information and externally generated analysis.

The Historian is not intended to preserve every asynchronous bus message.

It creates a fixed-rate representation of the best available aircraft state at defined points in time.

The initial standard sampling rates are:

- **10 Hz — fast aircraft state**
- **1 Hz — slow aircraft state**
- **Events — asynchronous state changes and annotations**

The 10 Hz timeline is the principal dynamic flight timeline.

---

## 2. Core Design Principle

FIX Gateway maintains the current aircraft state.

The Historian periodically samples selected FIX Gateway values and records those values against a common fixed timebase.

For the 10 Hz table:

```text
T0
T0 + 0.100 s
T0 + 0.200 s
T0 + 0.300 s
...
```

For the 1 Hz table:

```text
T0
T0 + 1.000 s
T0 + 2.000 s
...
```

A row therefore means:

> This was the best available representation of the selected aircraft state at this Historian time.

The system accepts that an individual sensor measurement may have been generated shortly before the Historian sample time.

This timing difference is considered **measurement/sample jitter**.

Provided that:

- the signal sampling rate is appropriate for the useful bandwidth of that signal, and
- transport/update latency is reasonably small compared with that bandwidth,

this is acceptable for the intended flight-analysis application.

The Historian does not require the actual sensor acquisition timestamp for live FIX data.

---

## 3. Two-Phase Historian Creation

### Phase 1 — Live FIX Gateway Capture

During flight:

```text
Sensors / avionics
        ↓
     CAN etc.
        ↓
   FIX Gateway
 current state store
        ↓
Historian sampler
    ↙       ↘
 10 Hz      1 Hz
    \       /
      Events
```

This phase creates:

- Flight record
- Fixed Historian timeline
- 10 Hz records
- 1 Hz records
- Event records
- Initial source records
- Initial flight metadata

At the end of the flight these timelines become authoritative.

They must not subsequently be shifted or regenerated when additional data is imported.

### Phase 2 — Secondary Source Synchronisation

After flight, additional files are imported.

Initially:

```text
MGL Enigma
     ↓
decode
     ↓
time synchronisation
     ↓
existing Historian frames
```

and:

```text
AvPlan GPX
     ↓
decode
     ↓
manifest extraction
     +
track synchronisation
     ↓
existing Historian frames
```

Secondary data does **not create a second independent analysis timeline**.

It is synchronised onto the existing Historian time frames.

Its original timestamp is preserved as data.

---

## 4. Recommended Technology

Initial database:

**SQLite**

Reasons:

- Single database file per aircraft or installation.
- No database server required.
- Excellent Raspberry Pi support.
- Reliable transactional writes.
- SQL query support.
- Very easy access from Python.
- Can later be migrated to PostgreSQL if required.
- Database size for 10 Hz aircraft data is modest.

Recommended Python database layer:

```text
sqlite3
```

or SQLAlchemy if an ORM is considered useful.

The first implementation should favour simplicity over abstraction.

SQLite should use:

```sql
PRAGMA journal_mode=WAL;
```

to improve resilience and permit readers while data is being recorded.

---

## 5. Database Architecture

Primary entities:

```text
AIRCRAFT
   │
   ├── AIRCRAFT_CONFIGURATION
   │        │
   │        └── CONFIGURATION_ITEM
   │
   └── FLIGHT
          │
          ├── FLIGHT_SOURCE
          │
          ├── HISTORIAN_10HZ
          │
          ├── HISTORIAN_1HZ
          │
          ├── EVENT
          │
          ├── IMPORT
          │
          └── ANALYSIS / DERIVED DATA
```

---

## 6. Aircraft Table

Table:

```text
aircraft
```

Minimum fields:

```text
aircraft_id
registration
type
description
created_at
notes
```

Example:

```text
aircraft_id:   COZ
registration:  VH-COZ
type:          Cozy III
```

`aircraft_id` should be a stable internal identifier.

---

## 7. Aircraft Configuration Management

Aircraft configuration must be independently recorded because flight data is meaningful only when the aircraft configuration associated with that flight is known.

### 7.1 aircraft_configuration

Fields:

```text
configuration_id
aircraft_id

valid_from
valid_to

name
description
notes

created_at
```

Example:

```text
configuration_id = COZ_CFG_017
valid_from       = 2026-08-01
valid_to         = NULL
```

Only one configuration should normally be active for a given aircraft/date.

### 7.2 configuration_item

Configuration should use item/value records rather than requiring a database schema change whenever another configurable feature is introduced.

Fields:

```text
configuration_item_id
configuration_id

category
item
value
units

notes
```

Examples:

```text
engine       model              IO-320
ignition     left               Lightspeed EI
ignition     right              Magneto
propeller    type               Fixed Pitch
avionics     efis               MGL Extreme
avionics     transponder        Trig TT31
avionics     com1               Icom IC-A210
airframe     wheel_pants        installed
airframe     nose_spat          installed
test         cowl_config        COWL_V4
```

This table should support engineering configuration as well as conventional installed equipment.

---

## 8. Flight Record / Manifest

Table:

```text
flight
```

One row represents one flight.

The manifest is initially created by the live Historian and enriched after flight from sources such as AvPlan.

Suggested fields:

```text
flight_id
aircraft_id
configuration_id

flight_date

origin
destination
flight_rules

planned_departure_utc

block_off_utc
wheels_off_utc
wheels_on_utc
block_on_utc

historian_start_utc
historian_end_utc

pilot
pob

performance_profile

purpose
description
notes

created_at
updated_at
```

Flight duration values should preferably be calculated rather than permanently duplicated where possible.

Examples:

```text
block_duration =
block_on - block_off

airborne_duration =
wheels_on - wheels_off
```

---

## 9. Flight Identification

Every flight must have a unique `flight_id`.

Recommended format:

```text
COZ-YYYYMMDD-NN
```

Example:

```text
COZ-20260807-01
```

Do not rely solely on filenames for identifying flights.

All:

- Historian records
- imported sources
- events
- configuration
- analysis products

must relate back to `flight_id`.

---

## 10. Flight Source Catalogue

Every data source contributing to a flight must be recorded.

Table:

```text
flight_source
```

Fields:

```text
source_id
flight_id

source_type
source_name

filename
file_hash

original_start_time
original_end_time

nominal_rate_hz

imported_at
decoder_name
decoder_version

notes
```

Initial `source_type` values:

```text
FIX_LIVE
MGL_ENIGMA
AVPLAN_GPX
MANUAL
```

Future examples:

```text
PRESSURE_LOGGER
CONTROL_LOGGER
WEATHER
ADS_B
CFD
```

A SHA-256 hash should preferably be stored for imported original files.

This permits confirmation that a particular database import originated from an exact source file.

Original files should not be modified during import.

---

## 11. Signal Catalogue

A signal catalogue should define every parameter that can enter the Historian.

Table:

```text
signal
```

Suggested fields:

```text
signal_id

canonical_name
description

source_type
source_field

units
data_type

historian_rate

category

valid_min
valid_max

notes
```

Example:

```text
canonical_name:   mgl.rpm
source_type:      MGL_ENIGMA
source_field:     ERPM
units:            RPM
historian_rate:   10
category:         engine
```

Example:

```text
canonical_name:   fix.pitch
source_type:      FIX_LIVE
source_field:     PITCH
units:            deg
historian_rate:   10
category:         attitude
```

Signal names should explicitly retain source where different independent measurements of the same physical parameter are useful.

For example:

```text
fix.gps_lat
mgl.gps_lat
avplan.gps_lat

fix.gps_lon
mgl.gps_lon
avplan.gps_lon

fix.gps_alt
mgl.gps_alt
avplan.gps_alt
```

Do not automatically collapse these into a single GPS position.

The ability to compare independent sources is useful.

---

## 12. 10 Hz Historian Table

Table:

```text
historian_10hz
```

One row represents one fixed 100 ms Historian frame.

Mandatory fields:

```text
flight_id
frame_number
historian_time_utc
flight_time_s
```

Suggested primary key:

```text
PRIMARY KEY (flight_id, frame_number)
```

`frame_number` begins at zero.

Nominal relationship:

```text
flight_time_s = frame_number / 10
```

Example:

```text
frame    flight_time_s
0        0.000
1        0.100
2        0.200
3        0.300
...
```

`historian_time_utc` should correspond to this frame time.

---

## 13. 1 Hz Historian Table

Table:

```text
historian_1hz
```

Mandatory fields:

```text
flight_id
frame_number
historian_time_utc
flight_time_s
```

Nominal relationship:

```text
flight_time_s = frame_number
```

The 1 Hz timeline should preferably use the same T0 as the 10 Hz timeline.

Therefore:

```text
1 Hz frame 0 = 10 Hz frame 0
1 Hz frame 1 = 10 Hz frame 10
1 Hz frame 2 = 10 Hz frame 20
```

This ensures deterministic alignment between Historian rates.

---

## 14. Allocation of Signals to Rates

### 10 Hz

Signals where aircraft dynamics or high-resolution track reconstruction is useful.

Examples:

```text
GPS position
GPS altitude
groundspeed
track

pitch
roll
heading

pitch rate
roll rate
yaw rate

G / acceleration

IAS
TAS
pressure altitude
vertical speed

RPM
MAP

control positions
```

The exact list should be configured rather than hard-coded.

### 1 Hz

Slow-changing data.

Examples:

```text
CHT
EGT

oil temperature
oil pressure

fuel quantity
fuel flow if high-rate behaviour is not required

OAT

battery voltage
current

GPS quality values

system status
```

Again, allocation should be configurable.

A parameter may be moved between rates without modifying core Historian code.

---

## 15. Historian Configuration File

Sampling configuration should preferably be external.

Example concept:

```yaml
historian:

  fast_rate_hz: 10
  slow_rate_hz: 1

  fast_signals:
    - LAT
    - LONG
    - GPSALT
    - PITCH
    - ROLL
    - HEAD
    - IAS
    - TAS
    - RPM
    - MAP

  slow_signals:
    - OAT
    - OILT
    - OILP
    - EGT1
    - EGT2
    - EGT3
    - EGT4
    - CHT1
    - CHT2
    - CHT3
    - CHT4
```

The exact FIX keys can later be substituted.

---

## 16. Phase 1 — FIX Gateway Sampling

### 16.1 Sampling mechanism

A single Historian process should manage timing.

It should maintain a monotonic timing loop.

At each 10 Hz interval:

1. Determine the target Historian frame.
2. Read all configured 10 Hz FIX values.
3. Build one complete row.
4. Write that row transactionally.

At each 1 Hz boundary:

1. Read configured 1 Hz FIX values.
2. Build the 1 Hz row.
3. Write the row.

Do not use separate independent timing loops if this could cause their timebases to drift.

---

## 17. UTC and Monotonic Time

The Historian should maintain:

```text
historian_time_utc
flight_time_s
```

`flight_time_s` should be generated from a monotonic clock.

UTC should preferably be GPS-disciplined where available.

Temporary GPS loss must not interrupt the Historian timebase.

The Historian timeline must remain monotonically increasing.

---

## 18. FIX Data Age / Quality

FIX Gateway's current-value quality/staleness information should be considered during recording.

The first version does not need to store a timestamp for every FIX parameter.

Data quality transitions should preferably create Events.

For example:

```text
PARAMETER_STALE
PARAMETER_RECOVERED
PARAMETER_BAD
PARAMETER_GOOD
```

Example:

```text
14:42:03.200
PARAMETER_STALE
fix.pitch
```

This avoids duplicating large quantities of quality flags in every Historian row.

Where necessary, quality bit fields can later be added.

---

## 19. Events Table

Table:

```text
event
```

Fields:

```text
event_id
flight_id

historian_time_utc
flight_time_s

event_type
source

parameter
value

text
metadata_json
```

Examples:

```text
ENGINE_START
ENGINE_STOP

TAKEOFF
LANDING

GEAR_UP
GEAR_DOWN

AUTOPILOT_ON
AUTOPILOT_OFF

BOOST_PUMP_ON
BOOST_PUMP_OFF

PARAMETER_STALE
PARAMETER_RECOVERED

PILOT_MARK

IMPORT_WARNING
```

Events do not need to conform to the 10 Hz or 1 Hz frame rate.

They retain their own event timestamp.

---

## 20. Pilot Marker

The system should eventually provide a simple means of inserting a manual event.

Examples:

```text
MARK
"Start speed run"
```

```text
MARK
"Start GAMI sweep"
```

```text
MARK
"Pressure test point 4"
```

This can initially be implemented through the web interface/API.

Hardware button support can be added later.

---

## 21. End-of-Flight State

When a flight finishes:

1. Flush outstanding database writes.
2. Mark the flight as complete.
3. Record Historian end time.
4. Preserve the 10 Hz timeline.
5. Preserve the 1 Hz timeline.
6. Preserve all events.

These become the authoritative Historian frame grids.

Subsequent imports must populate these existing grids rather than recreating them.

---

## 22. Phase 2 — Secondary Data Import

Post-flight imports perform four logical operations:

```text
SOURCE FILE
     ↓
PARSE
     ↓
NORMALISE
     ↓
TIME SYNCHRONISE
     ↓
MERGE INTO EXISTING HISTORIAN
```

The original file is always retained independently.

---

## 23. Import Processing

Each import should create an `import` record.

Suggested table:

```text
import
```

Fields:

```text
import_id
flight_id
source_id

started_at
completed_at

status

records_read
records_matched
records_unmatched
records_rejected

mean_time_error_ms
max_time_error_ms

warnings
decoder_version
```

This creates an audit trail for post-flight data merging.

---

## 24. Secondary Source Time Synchronisation

Each imported source sample has:

```text
source_timestamp
```

The Historian already contains:

```text
historian_time_utc
```

For every secondary sample, determine the closest corresponding Historian frame appropriate to that signal.

Define:

```text
sync_error =
source_timestamp - historian_time_utc
```

The original source timestamp must be retained.

Where useful, also retain:

```text
sync_error_ms
```

This permits later evaluation of timing jitter or systematic clock offsets.

---

## 25. Frame Assignment

For a source being synchronised to 10 Hz:

```text
frame period = 100 ms
```

A source record should normally be assigned to the nearest existing 10 Hz frame.

Conceptually:

```text
frame =
round((source_time - historian_T0) × 10)
```

For 1 Hz:

```text
frame =
round(source_time - historian_T0)
```

Do not create a new frame when synchronising source data.

---

## 26. Synchronisation Tolerance

Frame matching must have a configurable tolerance.

Suggested initial values:

```text
10 Hz:
maximum sync error = ±50 ms nominally
```

and:

```text
1 Hz:
maximum sync error = ±500 ms nominally
```

However, practical source logging behaviour may justify larger configurable limits.

A sample outside tolerance should:

- not silently populate the frame,
- be recorded as unmatched,
- generate an import warning where appropriate.

The importer should report sync statistics.

---

## 27. Clock Offset Estimation

Some external devices may have clocks offset from the Historian UTC clock.

The import architecture should permit:

```text
corrected_source_time =
source_time + source_time_offset
```

The first implementation can allow a manually supplied offset.

Future versions may calculate the optimum offset automatically by correlating common variables such as:

```text
GPS position
GPS speed
heading
RPM
altitude
```

The applied offset must be stored in the import record.

---

## 28. Merge Semantics

The term **merge** has a specific meaning in this system.

Secondary source data is added to the existing Historian row corresponding to its synchronised time.

Example before Enigma import:

```text
historian_time     fix_pitch   fix_roll   fix_gps_lat
12:00:00.100       2.1         4.3        -36.1234
```

After Enigma synchronisation:

```text
historian_time     fix_pitch   fix_roll   fix_gps_lat   mgl_pitch   mgl_roll   mgl_gps_lat
12:00:00.100       2.1         4.3        -36.1234      2.0         4.5        -36.1235
```

The Enigma data becomes part of the same Historian frame.

It does not remain isolated in a separate analysis timeline.

---

## 29. Source Ownership and Overwrite Rules

An importer may overwrite values belonging to **its own source**.

For example, re-importing an Enigma file may overwrite:

```text
mgl.pitch
mgl.roll
mgl.rpm
```

It must not overwrite:

```text
fix.pitch
fix.roll
fix.rpm
```

Likewise an AvPlan re-import may replace:

```text
avplan.gps_lat
avplan.gps_lon
```

but not MGL or FIX GPS fields.

Therefore source identity is part of the identity of a measurement.

This permits safe re-import.

---

## 30. Duplicate Measurements Are Deliberately Preserved

If several systems measure the same physical parameter, retain all useful versions.

For example:

```text
FIX GPS position
MGL GPS position
AvPlan GPS position
```

or:

```text
FIX heading
MGL heading
```

These are valuable independent observations.

Analysis may calculate:

```text
GPS position difference

altitude difference

heading difference

timing lag

sensor bias
```

Do not discard duplicate-source measurements simply because their semantic meaning is similar.

---

## 31. Canonical/Preferred Values

The database should distinguish between:

1. **Source measurements**, and
2. **Derived/preferred values**.

For example:

```text
fix.gps_alt
mgl.gps_alt
avplan.gps_alt
```

may all exist.

A future analysis process might generate:

```text
derived.gps_alt_best
```

The raw/source-specific measurements should remain unchanged.

Do not make the importer decide which sensor is "correct".

---

## 32. MGL Enigma Importer

The MGL importer must support the format represented by the supplied example.

The example contains metadata rows identifying:

- subsystem/source, including PFD, RDAC1, RDAC2, AHRS and GPS;
- engineering units;
- subsequent timestamped measurements.

The importer should:

1. Read the source-identification row.
2. Read the units row.
3. Create/map signals in the signal catalogue.
4. Parse the data records.
5. Convert timestamps to a common internal UTC representation.
6. Assign each signal to its configured Historian rate.
7. Synchronise records onto the relevant Historian frames.
8. Preserve the original Enigma timestamp.
9. Preserve source identity.
10. Record import statistics.

No useful source or unit metadata should be discarded.

---

## 33. MGL Timestamp Storage

Because several MGL values occur in one source record, storing an individual timestamp column beside every MGL parameter would be wasteful.

Instead the Historian frame should contain a source timestamp associated with the imported source record.

Example:

```text
historian_time_utc

mgl_source_time_utc
mgl_sync_error_ms

mgl_pitch
mgl_roll
mgl_heading
mgl_rpm
mgl_map
...
```

Therefore:

```text
Historian timestamp = common analysis time

MGL timestamp       = when MGL says its source record occurred

sync error          = difference between them
```

This directly preserves the jitter information discussed during system design.

---

## 34. AvPlan GPX Importer

The AvPlan importer performs two functions.

### A. Flight manifest enrichment

Extract where available:

```text
aircraft
origin
destination
flight rules

planned departure

POB

performance profile

block off
wheels off
wheels on
block on
```

The supplied AvPlan example demonstrates that this metadata can be present in GPX extensions.

### B. Track synchronisation

Extract each GPX track point including where available:

```text
timestamp
latitude
longitude
elevation
HDOP
VDOP
speed
track
other AvPlan extensions
```

Synchronise this data onto the existing Historian frames.

Preserve:

```text
avplan_source_time_utc
avplan_sync_error_ms
```

alongside AvPlan measurements.

---

## 35. Manifest Merge Rules

AvPlan should be considered a high-quality source of operational flight metadata.

However, manifest changes should be traceable.

Recommended precedence initially:

```text
manual value
    >
AvPlan metadata
    >
automatically inferred FIX value
```

A manually confirmed value should not automatically be replaced by subsequent imports.

The provenance of important manifest fields should ideally be retained.

This can be implemented later as:

```text
field_source
```

or through a manifest change/audit table.

---

## 36. Handling Different Native Rates

A secondary source need not have the same native sample rate as its target Historian table.

Example:

```text
MGL source = ~1 Hz
Historian dynamic table = 10 Hz
```

The system must **not pretend MGL generated ten independent measurements per second**.

Preferred initial approach:

Only the Historian frame nearest the actual MGL timestamp receives the new MGL record.

Example:

```text
12:00:01.0    MGL values
12:00:01.1    NULL
12:00:01.2    NULL
...
12:00:02.0    next MGL values
```

This preserves the original measurement density.

Interpolation or forward-fill should occur only in the analysis layer.

Do not automatically forward-fill imported data during ingestion.

---

## 37. Slow MGL Signals

Where an MGL signal naturally belongs in the 1 Hz dataset, synchronise it directly to `historian_1hz`.

For example:

```text
CHT
EGT
oil temperature
fuel quantity
OAT
```

Where an MGL signal is useful dynamically despite being logged at approximately 1 Hz, it may be stored on `historian_10hz`, but only on the corresponding matching frame.

The signal catalogue determines its destination.

---

## 38. Wide Tables

For this application, wide Historian tables are preferred over an Entity-Attribute-Value measurement table for routine analysis.

Example:

```text
historian_10hz

flight_id
frame
time
fix_lat
fix_lon
fix_pitch
fix_roll
fix_ias
fix_rpm

mgl_lat
mgl_lon
mgl_pitch
mgl_roll

avplan_lat
avplan_lon
...
```

Reasons:

- efficient engineering analysis;
- easy Pandas loading;
- easy SQL queries;
- intuitive plotting;
- simple time alignment;
- substantially fewer rows.

Schema migration is acceptable as the signal set evolves.

---

## 39. Schema Evolution

Importers should not dynamically create arbitrary database columns without control.

Adding a new Historian signal should occur through a schema/configuration migration.

The signal catalogue and historian configuration should define:

```text
signal
source
units
destination table
database column
```

Unknown fields encountered during import should:

1. be reported,
2. optionally be retained in an import staging structure,
3. not silently alter the production schema.

---

## 40. Import Staging

Secondary data should initially be decoded into temporary staging data before modifying the Historian.

Example:

```text
source file
    ↓
parser
    ↓
staging dataframe
    ↓
validation
    ↓
time synchronisation
    ↓
database transaction
```

Pandas DataFrames are suitable for this step.

The importer should validate:

```text
timestamps
numeric conversion
required columns
units
record ordering
duplicates
time range
```

before updating Historian tables.

---

## 41. Transactional Import

Each secondary-source merge should be performed transactionally.

Conceptually:

```text
BEGIN TRANSACTION

validate source
create source record
merge data
update manifest
write import statistics

COMMIT
```

If the import fails:

```text
ROLLBACK
```

A partially synchronised source must never remain in the production Historian.

---

## 42. Re-import

Re-importing a corrected/re-decoded secondary file should be supported.

Procedure:

1. Identify existing source/import.
2. Clear fields belonging to that source for the affected flight.
3. Parse file again.
4. Synchronise again.
5. Populate source-owned fields.
6. Update decoder version and import statistics.

FIX live data remains untouched.

---

## 43. Original File Retention

Original imported files should be retained.

Recommended directory structure:

```text
data/
  aircraft/
    COZ/
      flights/
        COZ-20260807-01/
          sources/
            enigma/
              original.csv
            avplan/
              original.gpx
          exports/
          analysis/
```

Database records should contain the path and SHA-256 hash.

Do not use the original source files as the active analysis database.

---

## 44. Derived Data

Derived values must be separated conceptually from measurements.

Examples:

```text
density altitude
percent power
fuel economy
specific range
GAMI spread

estimated wind
angle of attack
drag estimate

GPS source difference
sensor bias
```

Derived values may eventually be stored:

- in dedicated analysis tables,
- as database views,
- or in Parquet analysis products.

They should not overwrite acquired measurements.

---

## 45. External Analysis

The Historian should be readily accessible using:

```text
SQL
Python
Pandas
Jupyter
DuckDB
```

Typical query:

```sql
SELECT
    historian_time_utc,
    fix_pitch,
    fix_roll,
    fix_ias,
    mgl_rpm,
    mgl_map
FROM historian_10hz
WHERE flight_id = ?
ORDER BY frame_number;
```

---

## 46. Export

The system should eventually support:

```text
CSV
Parquet
```

for a selected flight.

A combined export may contain all synchronised values against the Historian timebase.

Example:

```text
time
flight_time

fix_lat
fix_lon
fix_pitch
fix_roll

mgl_source_time
mgl_pitch
mgl_roll
mgl_rpm

avplan_source_time
avplan_lat
avplan_lon
```

This becomes convenient for external analysis without compromising the database architecture.

---

## 47. Software Modules

Recommended code organisation:

```text
historian/
│
├── database/
│   ├── schema.py
│   ├── migrations.py
│   └── repository.py
│
├── capture/
│   ├── fix_client.py
│   ├── sampler.py
│   ├── timing.py
│   └── events.py
│
├── importers/
│   ├── base.py
│   ├── mgl_enigma.py
│   └── avplan_gpx.py
│
├── sync/
│   ├── frame_matcher.py
│   └── clock_offset.py
│
├── catalogue/
│   ├── signals.py
│   └── configuration.py
│
├── analysis/
│   └── export.py
│
├── config/
│   └── historian.yaml
│
├── tests/
│
└── main.py
```

---

## 48. Importer Interface

Secondary importers should implement a common conceptual interface:

```python
parse(file)
validate()
normalise()
get_metadata()
get_samples()
sync(flight)
commit()
```

This makes adding future sources straightforward.

Future importer examples:

```text
Stratux logfile
pressure measurement system
engine-monitor export
ADS-B log
weather observation
control-position logger
```

---

## 49. API / Command-Line Operations

Initial implementation should support commands equivalent to:

```text
historian start-flight
historian stop-flight

historian import-enigma <flight_id> <file>
historian import-avplan <flight_id> <file>

historian show-flight <flight_id>

historian export <flight_id>
```

These functions can later be exposed through FastAPI/web UI.

Core Historian operation should not depend on the web interface.

---

## 50. Logging

Application logging should capture:

```text
flight start/stop

database errors
FIX connection loss/recovery

missed Historian frames

secondary-source import start/end

timestamp parsing problems
sync failures
unknown source fields

schema errors
```

---

## 51. Missed Live Frames

The Historian should never silently hide a missed sample.

If a 10 Hz frame cannot be populated at its scheduled time, the system should still preserve the timebase.

Options:

1. Create the frame with NULL data, or
2. identify a sequence gap through frame numbering.

Preferred:

**Create the frame with available/current data where possible and generate an event indicating timing overrun when the sampling tolerance is exceeded.**

The exact timing performance should be measured during development.

---

## 52. Historian Timing Diagnostics

For each flight, record timing statistics such as:

```text
expected_10hz_frames
actual_10hz_frames

mean_sample_period
minimum_sample_period
maximum_sample_period

timing_overruns
```

This makes it possible to confirm that the Raspberry Pi is actually achieving the intended 10 Hz timeline.

---

## 53. Database Indexes

At minimum:

```sql
INDEX historian_10hz(flight_id, historian_time_utc)

INDEX historian_1hz(flight_id, historian_time_utc)

INDEX event(flight_id, historian_time_utc)

INDEX flight_source(flight_id)
```

Primary-key indexes on:

```text
flight_id + frame_number
```

will cover many common queries.

---

## 54. Null Handling

Missing information must be represented as:

```text
NULL
```

not:

```text
0
```

unless zero is genuinely the measured value.

This is particularly important when importing Enigma records because some sensor fields may contain zero as a legitimate value while others may use source-specific failure indicators.

The importer must understand the source format rather than globally treating zero as missing.

---

## 55. Unit Handling

Each signal must have a defined canonical unit.

Original source units must be recorded in the signal catalogue.

Conversion should preferably occur during normalisation.

For example:

```text
source: mBar
canonical: inHg
```

or:

```text
source: mph
canonical: knots
```

However, conversion policy should be explicit.

Original raw values need not be duplicated if the exact source file is retained.

---

## 56. Data Provenance Principle

For any value in the Historian it should eventually be possible to answer:

```text
What does this value represent?

What units is it in?

Where did it come from?

Which source file/device produced it?

When did that source say it was measured?

Which Historian frame was it associated with?

What software version decoded/imported it?
```

This is a core requirement.

---

## 57. Phase 1 Minimum Viable Product

Cursor should implement Phase 1 first.

Required:

1. SQLite schema.
2. Aircraft table.
3. Configuration tables.
4. Flight table.
5. Flight source table.
6. 10 Hz Historian table.
7. 1 Hz Historian table.
8. Events table.
9. YAML signal configuration.
10. FIX Gateway interface.
11. 10 Hz deterministic sampler.
12. 1 Hz sampler tied to the same timebase.
13. Flight start/stop.
14. Basic timing diagnostics.
15. CSV export.
16. Automated tests.

Phase 1 is complete when a flight can be simulated and a coherent 10 Hz/1 Hz Historian database produced.

---

## 58. Phase 2A — MGL Import

Required:

1. Parse MGL/Enigma CSV.
2. Recognise source row.
3. Recognise units row.
4. Parse timestamps.
5. Produce staging DataFrame.
6. Validate fields.
7. Determine relevant Historian destination for each mapped field.
8. Synchronise source records to existing frames.
9. Store `mgl_source_time`.
10. Store `mgl_sync_error_ms`.
11. Merge MGL fields into existing Historian rows.
12. Preserve FIX fields.
13. Support re-import.
14. Produce import statistics.
15. Automated tests using the supplied example file.

---

## 59. Phase 2B — AvPlan Import

Required:

1. Parse GPX.
2. Parse AvPlan XML extensions.
3. Extract manifest information.
4. Extract track points.
5. Produce staging DataFrame.
6. Synchronise track points to existing Historian frames.
7. Store `avplan_source_time`.
8. Store `avplan_sync_error_ms`.
9. Merge AvPlan source-specific fields.
10. Update appropriate manifest fields.
11. Preserve manual manifest values.
12. Support re-import.
13. Produce import statistics.
14. Automated tests using the supplied example GPX.

---

## 60. Phase 1 Acceptance Tests

A test flight of 10 minutes should produce approximately:

```text
10 Hz records = 6000
1 Hz records  = 600
```

subject to defined start/end behaviour.

Tests must confirm:

- monotonically increasing frame numbers;
- monotonically increasing timestamps;
- approximately 100 ms 10 Hz periods;
- approximately 1 second 1 Hz periods;
- common T0;
- valid flight_id on every record;
- no duplicate frame IDs;
- database survives clean application shutdown;
- FIX connection failure does not corrupt the database.

---

## 61. MGL Synchronisation Acceptance Test

Given a known MGL CSV:

- source timestamp parsing succeeds;
- every accepted record maps to an existing Historian frame;
- no new Historian frames are created;
- original MGL timestamps are retained;
- sync error is calculated;
- FIX values remain unchanged;
- MGL values populate their source-owned columns;
- re-import produces the same result;
- duplicate import does not duplicate data;
- unmatched records are reported.

---

## 62. AvPlan Acceptance Test

Given a known AvPlan GPX:

- GPX track timestamps are parsed;
- track latitude/longitude/elevation are extracted;
- AvPlan metadata extensions are decoded;
- origin and destination are extracted;
- POB is extracted where supplied;
- block/wheels times are extracted where supplied;
- aircraft identifier is extracted where supplied;
- performance profile is extracted where supplied;
- track points synchronise to existing Historian frames;
- original AvPlan timestamps remain available;
- duplicate import is idempotent.

---

## 63. Important Architectural Rules

The implementation should observe these rules.

### Rule 1
The Historian fixed timebase is created during live recording.

### Rule 2
Secondary sources never redefine that timebase.

### Rule 3
Secondary records are synchronised to existing Historian frames.

### Rule 4
Original secondary-source timestamps are preserved.

### Rule 5
Timing difference between secondary time and Historian time is measurable.

### Rule 6
Different sources measuring the same quantity may coexist.

### Rule 7
Re-import may overwrite data belonging to the same source.

### Rule 8
One source must never silently overwrite another source's measurement.

### Rule 9
Acquired measurements and derived values remain conceptually separate.

### Rule 10
The original imported files are retained.

### Rule 11
Aircraft configuration is explicitly associated with every flight.

### Rule 12
The Flight Manifest is progressively assembled from live, imported and manual information.

### Rule 13
NULL means unknown/missing; zero remains a legitimate measurement.

### Rule 14
Import operations are transactional and repeatable.

### Rule 15
Every imported value should retain sufficient provenance to establish where it came from.

---

## 64. Overall Data Lifecycle

```text
                BEFORE FLIGHT
                     │
                     ▼
          Select aircraft configuration
                     │
                     ▼
                 Start Flight
                     │
                     ▼
              PHASE 1 — LIVE
                     │
               FIX Gateway
                     │
          ┌──────────┼───────────┐
          ▼          ▼           ▼
        10 Hz       1 Hz       Events
          │          │           │
          └──────────┼───────────┘
                     │
              HISTORIAN TIMEBASE
                     │
                 End Flight
                     │
                     ▼
             PHASE 2 — SYNC
                     │
          ┌──────────┴──────────┐
          │                     │
      Enigma.rec              AvPlan
          │                     │
        Decode                Decode
          │                     │
      Timestamp             Timestamp
          │                     │
         Sync                  Sync
          │                     │
          └──────────┬──────────┘
                     ▼
            EXISTING HISTORIAN
                     │
                     ▼
           Complete Flight Record
                     │
          ┌──────────┼───────────┐
          ▼          ▼           ▼
         SQL       Pandas      Export
                              CSV/Parquet
```

---

## 65. Definition of the Historian

> **The Cozy Historian is a fixed-timebase flight record created by sampling the live FIX Gateway aircraft state at defined rates and subsequently synchronising other timestamped aircraft data sources onto those same time frames.**

It therefore provides one consistent temporal reference while retaining independent measurements, original source timestamps, aircraft configuration, flight metadata and complete source provenance.

The Historian becomes the authoritative record used for subsequent flight reconstruction, performance analysis, flight testing and engineering analysis.
