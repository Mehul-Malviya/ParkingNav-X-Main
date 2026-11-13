-- Coordinate provenance: lets the API/UI tell exact (OpenStreetMap) positions from
-- approximate (image-calibrated) ones. See configs/campus/vitap_calibration.yaml.
ALTER TABLE gates ADD COLUMN coordinate_source TEXT;
ALTER TABLE gates ADD COLUMN coordinate_accuracy_m REAL;

ALTER TABLE parking_lots ADD COLUMN coordinate_source TEXT;
ALTER TABLE parking_lots ADD COLUMN coordinate_accuracy_m REAL;
ALTER TABLE parking_lots ADD COLUMN boundary_source TEXT;

ALTER TABLE destinations ADD COLUMN coordinate_source TEXT;
ALTER TABLE destinations ADD COLUMN coordinate_accuracy_m REAL;

ALTER TABLE roads ADD COLUMN geometry_source TEXT;
