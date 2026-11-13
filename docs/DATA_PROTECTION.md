# ParkingNav-X — Data Protection Statement

**Status:** Academic prototype (VIT-AP University B.Tech CSE Capstone 2026–27)  
**Not a production system. No real personal data is collected or stored.**

---

## What data is collected

ParkingNav-X collects and stores **aggregate operational data only**:

| Data field | Purpose | Stored? |
|-----------|---------|---------|
| Parking lot occupancy count (integer) | Simulation and prediction | Yes — in SQLite |
| Gate vehicle count (integer) | Queue modelling | Yes — in SQLite |
| Event type (string label, e.g. "placement_drive") | Demand modelling | Yes — in YAML config |
| Event intensity (float 0–1) | Demand scaling | Yes — in YAML config |
| Simulation run ID and seed | Reproducibility | Yes — in results JSON |
| Timestamps (ISO 8601) | Time-series ordering | Yes — in CSV/DB |

---

## What is NOT collected or stored

The following data is **explicitly excluded** from all system components:

- Vehicle number plates / licence plates
- Driver names, employee IDs, or student IDs  
- Facial recognition data or CCTV footage
- Phone numbers, email addresses, or any contact information
- GPS traces of individual vehicles
- Payment or access-card data
- Any biometric data

---

## Input validation

The observation ingestion module (`digital_twin/validation/validate_observations.py`) validates incoming records and:

- Accepts only the fields listed in the schema (`timestamp`, `lot_id`, `occupied_spaces`, `gate_id`, `vehicle_count`, `event_type`, `event_intensity`, `notes`)
- Rejects records containing unexpected fields that could carry personal identifiers
- Flags impossible occupancy values (negative or exceeding lot capacity)
- Detects and removes duplicate records

---

## Synthetic data labelling

All occupancy data used in this prototype is **synthetic**, generated from a configurable demand model. Synthetic records carry the label `data_source=synthetic_generated` in the CSV schema. No real sensor, CCTV, ANPR, or gate-count data from VIT-AP was used.

Any API response that includes prediction or simulation output is explicitly labelled `[SYNTHETIC]` in the `data_provenance` field.

---

## Compliance note

This system is an academic research prototype and has not been reviewed for PDPA (India), GDPR, or any other privacy regulation compliance. It is not intended for production deployment or for processing real personal data without a full privacy impact assessment and appropriate institutional approval.

If real campus observation data is collected in future:
1. Obtain institutional ethics approval from VIT-AP.
2. Anonymise all data at source (aggregate counts only, no individual vehicle tracking).
3. Store data in an access-controlled environment.
4. Update this document to reflect actual data governance.
