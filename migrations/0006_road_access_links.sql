-- Length (metres) at each end of a road that is NOT on a mapped OSM road: open ground or
-- building interior between the node and the road network. The UI draws these as dotted
-- "access links" so they are not mistaken for mapped roads. See docs/map_calibration.md.
ALTER TABLE roads ADD COLUMN access_start_m REAL;
ALTER TABLE roads ADD COLUMN access_end_m REAL;
