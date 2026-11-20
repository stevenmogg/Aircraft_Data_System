# FlySto Flight Analysis Importer
## Specification for Integration with the Cozy III Flight Data System

**Status:** Draft implementation specification  
**Date:** 2026-10-04  
**Purpose:** Implementation specification for Cursor to add FlySto-derived flight analysis to the existing aircraft data system.

---

## 1. Purpose

Implement a **post-flight FlySto analysis importer** that ingests FlySto data already legitimately delivered to the user's browser, decodes the textual FlySto API responses, extracts derived flight analysis, and stores it alongside existing AvPlan, FIX-Gateway, MGL and historian data.

The first implementation shall focus on FlySto's **summary/sequence analysis**, especially automatically detected flight phases and maneuvers.

The importer is **not** part of the real-time FIX-Gateway path and shall not be required for flight operations.

### Primary objective

Convert FlySto's derived analysis into a stable internal representation:

```text
Flight
 ├── FlySto source/import record
 ├── Maneuvers / phases
 ├── Takeoff / landing / runway associations
 ├── Flags / advisories
 └── Other summary-derived annotations
```

This provides an independent reference classifier against which the project's own flight-phase classifier can later be developed and validated.

---

## 2. Scope

### 2.1 Phase 1 - Required

Implement:

1. HAR file ingestion.
2. Discovery of relevant FlySto API responses.
3. Decoding of FlySto textual `{"RESPONSE":"..."}` wrappers.
4. JSON parsing and schema-tolerant extraction.
5. Extraction of:
   - flight/log identity;
   - sequence information;
   - maneuvers/phases;
   - start time;
   - duration/end time;
   - maneuver type;
   - subtype/label/title where present;
   - runway/approach/takeoff associations where present;
   - FlySto flags/advisories where present.
6. Conversion from FlySto relative time to the project's flight time axis where a reliable reference is available.
7. Persistence into the flight database/historian.
8. CSV/JSON diagnostic export.
9. Automated tests using sanitized captured fixtures.

### 2.2 Phase 2 - Optional / Deferred

Investigate and, if useful, implement:

- `/api/log-data/<log-id>`
- `/api/log-stats/<log-id>`
- binary summary resources such as `trackApproximations` and `rawTerrainElevations`;
- traffic;
- weather;
- terrain;
- other FlySto-derived channels.

Phase 2 shall not block Phase 1.

### 2.3 Out of scope initially

Do not initially implement browser automation, FlySto login automation, credential storage, bypassing authentication/access controls, automatic upload to FlySto, real-time in-flight use, or any flight-control function.

---

## 3. Architectural Principles

### 3.1 Post-flight enrichment only

FlySto integration belongs in the **post-flight enrichment/import layer**, not FIX-Gateway.

```text
Aircraft sensors
      |
      v
 FIX-Gateway
      |
      v
 Historian
      |
      +-------- AvPlan importer
      |
      +-------- MGL/FIX imports
      |
      +-------- FlySto importer
                    |
                    v
             Derived annotations
```

FIX-Gateway remains deterministic and operationally independent.

### 3.2 Preserve provenance

Every imported FlySto value must retain enough provenance to determine which flight/log and endpoint produced it, when it was imported, which decoder/importer version was used, and whether it came directly from FlySto or was derived locally.

### 3.3 Do not overwrite measured data

FlySto-derived values are annotations/derived data. They must not silently replace GPS, air data, AHRS, engine, autopilot, or manually entered flight information.

### 3.4 Schema tolerance

FlySto is an external service with an undocumented internal browser API. Fields may change. The importer must tolerate unknown and missing optional fields, retain raw decoded JSON for troubleshooting, fail gracefully if required structure changes, and log schema/version differences.

---

## 4. Known FlySto Browser Endpoints

The captured browser session has shown endpoints including:

```text
/api/log-metadata?log=<log-id>&...
/api/log-summary?logs=<log-id>&update=true
/api/log-sequence?log=<log-id>

/api/log-data/<log-id>
/api/log-stats/<log-id>

/api/log-summary-binary/<log-id>/trackApproximations
/api/log-summary-binary/<log-id>/rawTerrainElevations

/api/traffic-summary/<log-id>
/api/has-traffic/<log-id>

/api/weather-areas/<log-id>
/api/weather-maps-summary/<log-id>
```

The implementation shall not assume this list is exhaustive. Endpoint matching should be path-based and tolerant of query-string changes.

---

## 5. Input Abstraction

Design the importer so additional acquisition sources can be added later.

```python
class FlyStoSource(Protocol):
    def responses(self) -> Iterable[FlyStoResponse]:
        ...
```

### 5.1 Required source: HAR

Input is a Safari/other browser HAR file.

The parser shall extract request URL/method, response status, MIME type, response body, HAR body encoding if present, and request timestamp where available.

### 5.2 Future source: saved responses

Optionally support a directory such as:

```text
flysto_capture/
    log-summary.json
    log-sequence.json
    log-metadata.json
    manifest.json
```

### 5.3 Future source: direct HTTP

Direct retrieval may later be added for endpoints legitimately accessible to the user, but acquisition must remain separate from decoding and database logic.

```text
HTTP acquisition
      ↓
FlyStoResponse objects
      ↓
decoder
      ↓
normalizer
      ↓
database
```

---

## 6. HAR Security Requirements

HAR files may contain session cookies, authentication headers, browser identifiers, analytics identifiers, and share/access tokens.

Requirements:

1. Never log Cookie headers.
2. Never log Authorization headers.
3. Never persist session cookies into the flight database.
4. Diagnostic output must redact sensitive headers.
5. Test fixtures committed to Git must be sanitized.
6. Provide a HAR sanitization utility.

Example:

```bash
python -m flightdata.flysto sanitize capture.har sanitized.har
```

Remove at least `Cookie`, `Set-Cookie`, `Authorization`, and `Proxy-Authorization`, while preserving paths, response bodies, status codes, and content types needed for tests.

---

## 7. FlySto Text Response Decoding

Several FlySto API responses use a JSON wrapper:

```json
{
  "RESPONSE": "<encoded text>"
}
```

Captured responses have been demonstrated to be reversibly transformed browser data rather than opaque encrypted payloads.

### 7.1 Decoder API

Keep the transform isolated:

```python
def decode_flysto_response(encoded: str) -> str:
    # Return decoded FlySto RESPONSE text.
    ...

def decode_flysto_json(encoded: str) -> dict | list:
    return json.loads(decode_flysto_response(encoded))
```

Place this in `flysto/codec.py`.

### 7.2 Implementation rule

Do not scatter transform knowledge through the importer. Cursor should derive/confirm the exact character mapping from the captured fixture/client JavaScript and encode it in `codec.py` with unit tests. Tests, rather than comments or assumptions, become the authoritative contract.

### 7.3 Decoder acceptance tests

Known sanitized fixtures must decode to valid JSON and contain known semantic markers such as:

```text
climb
descent
ground-roll
turn
pattern-leg
climbout
other-flying
```

Do not test only that JSON parsing succeeds.

---

## 8. API Response Classification

Create:

```python
@dataclass
class FlyStoResponse:
    url: str
    path: str
    query: dict[str, list[str]]
    status: int
    mime_type: str | None
    body: bytes
    captured_at: datetime | None
```

Classify endpoints:

```python
class FlyStoEndpoint(Enum):
    LOG_METADATA = "log-metadata"
    LOG_SUMMARY = "log-summary"
    LOG_SEQUENCE = "log-sequence"
    LOG_DATA = "log-data"
    LOG_STATS = "log-stats"
    TRAFFIC_SUMMARY = "traffic-summary"
    WEATHER_AREAS = "weather-areas"
    WEATHER_MAPS_SUMMARY = "weather-maps-summary"
    SUMMARY_BINARY = "log-summary-binary"
    UNKNOWN = "unknown"
```

Unknown endpoints are retained diagnostically or ignored, not treated as fatal.

---

## 9. Internal Flight Analysis Model

Do not expose FlySto raw JSON directly to the rest of the system.

### 9.1 Flight analysis import

```python
@dataclass
class FlyStoFlightAnalysis:
    flysto_log_id: str
    source_file: str | None
    imported_at: datetime
    decoder_version: str
    raw_summary: dict | None
    raw_sequence: dict | list | None
    maneuvers: list["FlyStoManeuver"]
    flags: list["FlyStoFlag"]
```

### 9.2 Maneuver / phase record

```python
@dataclass
class FlyStoManeuver:
    source_id: str | None
    type: str
    subtype: str | None
    label: str | None
    title: str | None
    start_s: float
    duration_s: float
    end_s: float
    start_utc: datetime | None
    end_utc: datetime | None
    airport: str | None
    runway: str | None
    raw: dict
```

Normally:

```python
end_s = start_s + duration_s
```

while preserving original fields in `raw`.

### 9.3 Flag/advisory record

```python
@dataclass
class FlyStoFlag:
    type: str | None
    label: str | None
    severity: str | None
    start_s: float | None
    end_s: float | None
    start_utc: datetime | None
    end_utc: datetime | None
    raw: dict
```

Do not invent severity mappings if FlySto does not provide one.

---

## 10. Maneuver and Phase Semantics

The captured FlySto analysis demonstrates classifications including:

```text
climb
descent
ground-roll
turn
pattern-leg
climbout
other-flying
```

and pattern-leg subtypes such as `DOWNWIND` and `FINAL`.

Preserve FlySto terminology exactly in source fields. Do not initially convert `other-flying` to `CRUISE`, for example.

If the project later needs a canonical taxonomy, create a separate mapping layer:

```python
FLYSTO_TO_CANONICAL = {
    "ground-roll": "GROUND_ROLL",
    "climb": "CLIMB",
    "climbout": "INITIAL_CLIMB",
    "descent": "DESCENT",
}
```

Leave uncertain mappings unmapped until validated.

---

## 11. Time Model

FlySto maneuver times observed in decoded analysis appear as seconds relative to a log/flight time origin.

Always preserve:

```text
start_s
duration_s
end_s
```

Only calculate UTC after a reliable FlySto-to-flight epoch is identified.

Preferred synchronization sources:

1. explicit FlySto log timestamp;
2. corresponding GPS timestamp;
3. known AvPlan/FIX flight start;
4. sequence metadata once validated.

Do not guess the epoch. If unresolved:

```text
start_utc = NULL
end_utc   = NULL
```

Once resolved:

```python
start_utc = flysto_epoch + timedelta(seconds=start_s)
end_utc = flysto_epoch + timedelta(seconds=end_s)
```

---

## 12. Overlapping Segments

FlySto segments may overlap because they can describe different analytical layers.

Example:

```text
descent
   └── circuit
        └── turn
             └── FINAL
```

**Do not force maneuvers into a mutually exclusive timeline.**

Store them as interval annotations. A separate project classifier can later produce a mutually exclusive phase timeline.

---

## 13. Database Integration

Prefer a generic external-analysis/event model if one already exists.

Suggested import table:

```text
external_analysis_import
------------------------
id
flight_id
provider              = "flysto"
external_log_id
source_filename
source_sha256
imported_at
importer_version
decoder_version
status
raw_summary_json
raw_sequence_json
```

Suggested annotation table:

```text
flight_annotation
-----------------
id
flight_id
analysis_import_id
provider               = "flysto"
annotation_class       = "maneuver" | "flag" | "event"
source_type
source_subtype
label
title
start_offset_s
end_offset_s
start_utc
end_utc
airport
runway
raw_json
```

Indexes should support flight, provider, annotation class, UTC and offset interval queries.

---

## 14. Provenance

Every FlySto annotation should retain:

```text
provider = flysto
source endpoint
FlySto log ID
import timestamp
decoder version
importer version
source HAR checksum
```

Retain raw decoded summary/sequence at least during development. This is important because FlySto may change its undocumented format.

---

## 15. Deduplication and Transactions

Re-importing the same HAR must not duplicate annotations.

Calculate SHA-256 of the HAR and store it.

Suggested uniqueness:

```text
(provider, external_log_id, source_sha256, importer_version)
```

Preferred transactional behavior:

```text
parse completely
    ↓
validate
    ↓
begin transaction
    ↓
replace/update FlySto annotations
    ↓
commit
```

A decoding failure must leave the previous successful import untouched.

---

## 16. Proposed Package Structure

Adapt names to the existing repository rather than creating a parallel architecture unnecessarily.

```text
src/
└── flightdata/
    └── flysto/
        ├── __init__.py
        ├── har.py
        ├── codec.py
        ├── endpoints.py
        ├── models.py
        ├── normalize.py
        ├── importer.py
        ├── sanitize.py
        └── cli.py

tests/
└── flysto/
    ├── fixtures/
    │   ├── log_summary_encoded.json
    │   ├── log_summary_decoded.json
    │   ├── log_sequence_encoded.json
    │   └── sanitized_capture.har
    ├── test_codec.py
    ├── test_har.py
    ├── test_normalize.py
    └── test_importer.py
```

---

## 17. CLI

### Inspect

```bash
python -m flightdata.flysto inspect www.flysto.net.har
```

Example:

```text
FlySto log: x12nii9o

Found:
  log-metadata     yes
  log-summary      yes
  log-sequence     yes
  log-data         yes
  log-stats        yes
  traffic-summary  yes
  weather          yes

Decoded maneuvers: 33
```

### Export maneuvers

```bash
python -m flightdata.flysto export-maneuvers capture.har     --output flysto_maneuvers.csv
```

CSV fields:

```text
flysto_log_id,start_s,end_s,duration_s,type,subtype,label,title,airport,runway
```

### Decode for diagnostics

```bash
python -m flightdata.flysto decode capture.har     --endpoint log-summary     --output decoded_summary.json
```

### Import

```bash
python -m flightdata.flysto import capture.har --flight-id <flight-id>
```

---

## 18. Diagnostics

Produce concise diagnostics such as:

```text
FlySto import
  Log ID: x12nii9o
  Summary: decoded
  Sequence: decoded
  Maneuvers: 33
  UTC synchronization: unresolved
  Unknown maneuver types: 0
  Warnings: 0
```

Report actual parsed values. Never include cookies/authentication headers.

---

## 19. FastAPI / UI Integration

If exposed through the existing web UI, suggested routes are:

```text
GET  /api/flights/{flight_id}/analysis/flysto
GET  /api/flights/{flight_id}/annotations
POST /api/flights/{flight_id}/imports/flysto
```

The UI should be able to overlay interval annotations on existing time-series plots.

```text
RPM       ─────────────────────────────
Altitude      /^^^^^^^^^\____
Phase       [ CLIMB ][ OTHER ][DESCENT]
FlySto         ^ interval annotations ^
```

---

## 20. Historian Integration

Store FlySto classifications primarily as interval/event data, not by repeating the classification into every historian sample.

For analysis requiring per-row labels, perform an explicit temporal join.

Because FlySto intervals can overlap, the result may contain:

```python
active_annotations = [
    "descent",
    "turn",
    "pattern-leg:FINAL",
]
```

Do not assume a single active FlySto phase.

---

## 21. Relationship to the Project Classifier

FlySto is a **reference classifier**, not necessarily ground truth.

Keep distinct:

```text
FLYSTO_PHASE
PROJECT_PHASE
MANUAL_PHASE
```

Future comparisons can measure boundary timing error, agreement, confusion matrices, missed phases, false phases, and takeoff/landing detection error.

Do not train and evaluate the project classifier on the same FlySto-labelled flights without preserving independent test flights.

---

## 22. Phase 2 - Binary `log-data`

Known request pattern:

```text
/api/log-data/<log-id>?format=8&version=0
```

with:

```text
Content-Type: application/octet-stream
```

Treat this as a separate reverse-engineering task.

Investigate header/magic/version, channel dictionary, timestamps, sample encoding, scaling, missing values, compression/delta encoding, and measured versus derived channels.

**Do not delay Phase 1 for this work.**

---

## 23. Tests

Implement at least:

**T1 HAR parser** - finds FlySto requests, handles HAR base64 response bodies and ignores unrelated resources.

**T2 Endpoint classifier** - correctly recognizes summary, sequence, metadata and log-data.

**T3 Text decoder** - known encoded summary decodes to valid JSON.

**T4 Semantic decoder** - decoded fixture contains known classification terms.

**T5 Maneuver extraction** - validates expected fixture count and representative records.

**T6 Timing** - `end_s == start_s + duration_s`.

**T7 Overlap** - overlapping intervals import successfully.

**T8 Unknown fields** - added unknown JSON field does not break import.

**T9 Missing optional fields** - missing label/title/runway does not break import.

**T10 Idempotency** - importing same HAR twice does not double annotations.

**T11 Transaction failure** - forced decoder failure leaves previous successful import intact.

**T12 Security** - sanitizer removes Cookie and Authorization headers.

**T13 UTC alignment** - known epoch converts correctly.

**T14 No guessed UTC** - unresolved epoch leaves UTC null.

---

## 24. Acceptance Criteria - Phase 1

Phase 1 is complete when:

1. A Safari HAR exported from a FlySto flight can be supplied to the importer.
2. The importer identifies the FlySto log ID.
3. `log-summary` decodes without manual intervention.
4. `log-sequence` decodes without manual intervention.
5. Maneuver/phase annotations are normalized.
6. Relative start/end times are preserved.
7. Known fixture classifications are correctly extracted.
8. Overlapping annotations are supported.
9. Results export to CSV/JSON.
10. Results associate with an existing project flight.
11. Re-import is idempotent.
12. Sensitive HAR headers are not logged or stored.
13. Automated tests use sanitized fixtures.
14. A FlySto format change gives a clear import error rather than corrupting existing flight data.

---

## 25. Recommended Cursor Implementation Order

```text
1. har.py
       ↓
2. endpoints.py
       ↓
3. codec.py + decoder tests
       ↓
4. decode log-summary / log-sequence
       ↓
5. models.py
       ↓
6. normalize.py
       ↓
7. CSV/JSON CLI export
       ↓
8. database importer
       ↓
9. FastAPI/UI integration
       ↓
10. Phase 2 binary log-data investigation
```

First prove:

```text
HAR → decoded JSON → normalized maneuvers
```

as a standalone deterministic pipeline.

---

## 26. Suggested First Cursor Task

> Implement Phase 1 of the FlySto HAR decoder described in this specification. Start with `har.py`, `endpoints.py`, and `codec.py`. Use the supplied **sanitized** HAR as the integration fixture. Do not implement database writes or direct FlySto HTTP access yet. The first milestone is a CLI that reads the HAR, identifies the FlySto log ID, decodes `log-summary` and `log-sequence`, writes decoded JSON to disk, and prints the number and types of detected maneuvers. Add pytest coverage before proceeding to normalization.

This deliberately keeps the first change small enough to inspect and validate before integration.

---

## 27. Design Decision Summary

- FlySto is **post-flight enrichment**, not real-time infrastructure.
- Start with HAR ingestion because it is observable and reproducible.
- Isolate the FlySto response codec.
- Treat the browser API as undocumented and changeable.
- Preserve raw decoded data and provenance.
- Store maneuvers as overlapping interval annotations.
- Preserve FlySto terminology rather than prematurely remapping it.
- Keep relative time even if UTC synchronization is unresolved.
- Use FlySto as a reference classifier, not unquestioned ground truth.
- Defer binary `log-data` decoding until summary/sequence integration works.
- Never store browser session credentials as flight data.

---

## 28. Future Direction

Once Phase 1 works, the system can compare:

```text
Measured aircraft data
        +
FlySto derived analysis
        +
Project-derived analysis
```

This provides a foundation for automatic phase classification, performance and engine analysis by phase, flight-test maneuver recognition, approach/takeoff analysis, anomaly detection, classifier validation, and later ML/RFM work.

FlySto should therefore be integrated as an **external analysis provider**, not hard-coded as the definition of aircraft flight state.
