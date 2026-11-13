# Real-Data Observation Plan -- Phase 1.4
**Project:** ParkingNav-X - VIT-AP University  
**Prepared by:** Member 1 (Digital Twin & Simulation)  
**Last updated:** 2026-10-10  
**Agreed with:** Member 2 (Forecasting & Calibration)  
**Purpose:** Feed real arrival/occupancy counts into Phase 3 calibration.

---

## 1. Observation Schema

One row per observation interval (every 5 minutes at each location).  
**Aggregate-only -- no licence plates, no personal or identifying data.**

| Column | Type | Example | Notes |
|---|---|---|---|
| `timestamp` | ISO 8601 datetime | `2026-10-12T09:00:00+05:30` | Start of the 5-min window |
| `gate_id` | string | `vitap-gate-main` | Matches vitap.yaml `gate_id` |
| `vehicle_count` | integer | 14 | Vehicles passing through gate in this 5-min window |
| `parking_lot_id` | string | `vitap-lot-academic-main` | Matches vitap.yaml `parking_lot_id` |
| `occupied_spaces` | integer | 87 | Visible/counted occupied spaces at snapshot time |
| `event_type` | string or null | `exam` / `placement` / `fest` / `null` | Active event label if any |
| `event_intensity` | string or null | `low` / `medium` / `high` / `null` | Observer's judgment of crowd pressure |
| `notes` | string | `gate arm stuck 09:15-09:22` | Anomalies, outages, weather, anything unusual |

**CSV header:**
```
timestamp,gate_id,vehicle_count,parking_lot_id,occupied_spaces,event_type,event_intensity,notes
```

---

## 2. Observation Locations

### Gates (2 selected)

| Gate ID | Name | Rationale |
|---|---|---|
| `vitap-gate-main` | Main Gate | Primary inflow for faculty, staff, commuter students -- highest volume |
| `vitap-gate-visitor` | Visitor Gate | Secondary inflow; handles visitors and overflow; distinct demand profile |

### Parking Lots (3 selected)

| Lot ID | Name | Rationale |
|---|---|---|
| `vitap-lot-academic-main` | Academic Block Main Lot | Largest lot; closest to AB-1/AB-2/CB; fills fastest on normal days |
| `vitap-lot-hostel` | Hostel Zone Parking | Captures resident-student demand; different peak pattern from day scholars |
| `vitap-lot-admin-visitor` | Administrative & Visitor Lot | Tied to visitor gate; reflects event-day surge |

> One observer can cover both gates alternating every 5 min, or two observers cover one each.  
> Lot counts are spot-counts (walk-and-count or camera-freeze) at the start of each 5-min window.

---

## 3. Session Schedule

### Session 1 -- Normal Day

| Field | Value |
|---|---|
| **Date** | Monday 2026-10-12 (regular teaching week, no exams) |
| **Time window** | 08:00 - 11:00 IST (morning arrival wave) |
| **Duration** | 3 hours = 36 five-minute intervals per location |
| **Lead observer** | Member 1 |
| **Support** | Member 2 (cross-check lot counts at Academic Main) |
| **Tools** | Phone timer, shared Google Sheet (offline-capable), tally counter |
| **Backup date** | Tuesday 2026-10-13 same window if Session 1 is cancelled |

**What to capture:** Full morning peak -- gate flow peaks around 08:30-09:30, lot fills by 09:45 on a typical day.

---

### Session 2 -- Event Day

| Field | Value |
|---|---|
| **Event** | End-semester examination (Theory exam period) |
| **Date** | Confirm exact date against VIT-AP academic calendar -- target first Monday of Nov 2026 exam block |
| **Proposed date** | 2026-11-02 (placeholder -- confirm with academic section before committing) |
| **Time window** | 08:00 - 11:00 IST |
| **Duration** | 3 hours = 36 five-minute intervals per location |
| **Lead observer** | Member 1 |
| **Support** | Member 2 |
| **Event intensity** | Expected `high` (all students must be on campus by exam start) |

**Fallback event type:** If exam dates shift, substitute with a placement/fest day -- record `event_type=placement` or `event_type=fest` accordingly.

---

## 4. Data Handling

- Raw CSVs stored in `data/observations/` (gitignored -- not committed to repo).
- One file per session: `obs_normal_2026-10-12.csv`, `obs_exam_2026-11-02.csv`.
- Member 2 ingests these files in Phase 3 to fit arrival-rate and dwell-time distributions.
- Member 1 updates `configs/campus/vitap.yaml` capacities if spot-counts reveal discrepancies.

---

## 5. Privacy Rules

- Record only **counts per interval**, never individual vehicles or persons.
- No licence plates, no photos that identify individuals.
- Observation is conducted from public campus areas; no special access required.
- Data is used solely for academic simulation calibration within the ParkingNav-X project.

---

## 6. Verify Checklist

- [ ] Schema agreed with Member 2 (columns, units, interval length)
- [ ] Session 1 date confirmed (normal day -- 2026-10-12)
- [ ] Session 2 date confirmed (event day -- check academic calendar)
- [ ] `data/observations/` added to `.gitignore`
- [ ] Blank CSV template committed to `data/observations/template.csv`
