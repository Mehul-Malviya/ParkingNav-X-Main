"""
Converts raw GPS survey output (a GPX file's tracks/waypoints + a mapping
CSV) into a campus YAML config. Road geometry is taken directly from the
walked GPX track in original point order -- never straightened, reordered,
or interpolated. Point-type entities (gates/lots/destinations) come from
named GPX waypoints.

Mapping CSV columns: entity_type, entity_id, name, category, gpx_ref,
start_node_id, end_node_id (the last two apply to entity_type=road only).
"""

import csv
import xml.etree.ElementTree as ET

GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


def _parse_gpx(path):
    tree = ET.parse(path)
    root = tree.getroot()

    waypoints = {}
    for wpt in root.findall("gpx:wpt", GPX_NS):
        name = wpt.findtext("gpx:name", default="", namespaces=GPX_NS)
        waypoints[name] = {"lat": float(wpt.get("lat")), "lng": float(wpt.get("lon"))}

    tracks = {}
    for trk in root.findall("gpx:trk", GPX_NS):
        name = trk.findtext("gpx:name", default="", namespaces=GPX_NS)
        points = []
        for trkpt in trk.findall("gpx:trkseg/gpx:trkpt", GPX_NS):
            points.append({"lat": float(trkpt.get("lat")), "lng": float(trkpt.get("lon"))})
        tracks[name] = points  # preserved in recorded order

    return waypoints, tracks


def gps_survey_to_config(gpx_path, csv_path, campus_id, campus_name, timezone="UTC",
                          configuration_version="V1") -> dict:
    waypoints, tracks = _parse_gpx(gpx_path)

    gates, parking_lots, destinations, roads = [], [], [], []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            entity_type = row["entity_type"]
            gpx_ref = row["gpx_ref"]

            if entity_type == "road":
                if gpx_ref not in tracks:
                    raise ValueError(f"Road '{row['entity_id']}' references unknown GPX track '{gpx_ref}'.")
                geometry = tracks[gpx_ref]
                if len(geometry) < 2:
                    raise ValueError(f"GPX track '{gpx_ref}' has fewer than 2 points.")
                travel_time = row.get("expected_travel_time_seconds")
                if not travel_time:
                    raise ValueError(
                        f"Road '{row['entity_id']}' is missing expected_travel_time_seconds "
                        "(must be measured during the walk, never invented)."
                    )
                roads.append({
                    "road_id": row["entity_id"],
                    "name": row["name"],
                    "start_node_id": row["start_node_id"],
                    "end_node_id": row["end_node_id"],
                    "length_meters": float(row.get("length_meters") or _track_length(geometry)),
                    "expected_travel_time_seconds": float(travel_time),
                    "is_walkable": row.get("is_walkable", "true").lower() == "true",
                    "is_driveable": row.get("is_driveable", "true").lower() == "true",
                    "status": "open",
                    "geometry": geometry,
                })
                continue

            if gpx_ref not in waypoints:
                raise ValueError(f"Entity '{row['entity_id']}' references unknown GPX waypoint '{gpx_ref}'.")
            point = waypoints[gpx_ref]

            if entity_type == "gate":
                gates.append({
                    "gate_id": row["entity_id"], "name": row["name"],
                    "latitude": point["lat"], "longitude": point["lng"],
                    "capacity": int(row.get("capacity", 10)), "status": "open",
                })
            elif entity_type == "parking_lot":
                parking_lots.append({
                    "parking_lot_id": row["entity_id"], "name": row["name"],
                    "latitude": point["lat"], "longitude": point["lng"],
                    "total_capacity": int(row["total_capacity"]),
                    "usable_capacity": int(row.get("usable_capacity", row["total_capacity"])),
                    "status": "open",
                })
            elif entity_type == "destination":
                destinations.append({
                    "destination_id": row["entity_id"], "name": row["name"],
                    "category": row.get("category", "other"),
                    "latitude": point["lat"], "longitude": point["lng"],
                })
            else:
                raise ValueError(f"Unknown entity_type '{entity_type}' for '{row['entity_id']}'.")

    return {
        "campus": {
            "campus_id": campus_id, "name": campus_name,
            "timezone": timezone, "configuration_version": configuration_version,
        },
        "gates": gates,
        "parking_lots": parking_lots,
        "destinations": destinations,
        "roads": roads,
        "edges": [
            {
                "from_node_id": r["start_node_id"], "to_node_id": r["end_node_id"], "road_id": r["road_id"],
                "weight_time_seconds": r["expected_travel_time_seconds"],
                "weight_distance_meters": r["length_meters"],
                "is_walkable": r["is_walkable"], "is_driveable": r["is_driveable"], "status": "open",
            }
            for r in roads
        ],
    }


def _track_length(points):
    import math

    def haversine(a, b):
        r = 6371000
        p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
        dphi = math.radians(b["lat"] - a["lat"])
        dl = math.radians(b["lng"] - a["lng"])
        x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))

    return sum(haversine(points[i], points[i + 1]) for i in range(len(points) - 1))
