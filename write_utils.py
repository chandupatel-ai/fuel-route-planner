code = """import math
import requests
import logging
from django.conf import settings
from .models import FuelStop

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.8
VEHICLE_MAX_RANGE = 500
VEHICLE_MPG = 10
SEARCH_RADIUS = 30
REFUEL_INTERVAL = 450


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(a))


def geocode_location(location_str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": location_str + ", USA", "format": "json", "limit": 1, "countrycodes": "us"}
    headers = {"User-Agent": "FuelRoutePlanner/1.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError(f"Could not find location: {location_str}")
        return float(data[0]["lat"]), float(data[0]["lon"])
    except requests.RequestException as e:
        raise ValueError(f"Geocoding failed: {e}")


def get_route(start_coords, end_coords):
    api_key = settings.ORS_API_KEY
    if not api_key:
        return _straight_line_route(start_coords, end_coords)
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    body = {"coordinates": [[start_coords[1], start_coords[0]], [end_coords[1], end_coords[0]]]}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        feature = data["features"][0]
        props = feature["properties"]["segments"][0]
        distance_miles = props["distance"] * 0.621371
        duration_s = props["duration"]
        coords = feature["geometry"]["coordinates"]
        waypoints = _sample_waypoints(coords, distance_miles)
        return {"distance_miles": round(distance_miles, 2), "duration_seconds": round(duration_s), "waypoints": waypoints, "geometry": coords}
    except requests.RequestException as e:
        logger.warning("ORS API failed, falling back to straight-line.")
        return _straight_line_route(start_coords, end_coords)


def _straight_line_route(start, end):
    distance = haversine(start[0], start[1], end[0], end[1])
    n = max(20, int(distance / 20))
    waypoints = []
    for i in range(n + 1):
        t = i / n
        lat = start[0] + t * (end[0] - start[0])
        lon = start[1] + t * (end[1] - start[1])
        waypoints.append((lat, lon))
    geometry = [[wp[1], wp[0]] for wp in waypoints]
    return {"distance_miles": round(distance, 2), "duration_seconds": round(distance / 55 * 3600), "waypoints": waypoints, "geometry": geometry, "note": "Straight-line estimate."}


def _sample_waypoints(coords, distance_miles):
    total = len(coords)
    if total == 0:
        return []
    step = max(1, total // 200)
    sampled = [(coords[i][1], coords[i][0]) for i in range(0, total, step)]
    last = (coords[-1][1], coords[-1][0])
    if sampled[-1] != last:
        sampled.append(last)
    return sampled


def find_optimal_fuel_stops(waypoints, total_distance_miles):
    if not waypoints:
        return []
    all_stops = list(FuelStop.objects.filter(latitude__isnull=False, longitude__isnull=False).values("id", "opis_id", "name", "city", "state", "address", "retail_price", "latitude", "longitude"))
    if not all_stops:
        return []
    stops = []
    miles_traveled = 0
    miles_since_last_fuel = 0
    for i in range(1, len(waypoints)):
        prev = waypoints[i - 1]
        curr = waypoints[i]
        segment_dist = haversine(prev[0], prev[1], curr[0], curr[1])
        miles_traveled += segment_dist
        miles_since_last_fuel += segment_dist
        if miles_since_last_fuel >= REFUEL_INTERVAL:
            best = _cheapest_nearby_stop(curr, all_stops)
            if best:
                gallons = miles_since_last_fuel / VEHICLE_MPG
                cost = gallons * best["retail_price"]
                stops.append({"name": best["name"], "city": best["city"], "state": best["state"], "address": best["address"], "retail_price": round(best["retail_price"], 3), "latitude": best["latitude"], "longitude": best["longitude"], "miles_from_start": round(miles_traveled, 2), "gallons_needed": round(gallons, 2), "cost_at_stop": round(cost, 2)})
                miles_since_last_fuel = 0
    return stops


def _cheapest_nearby_stop(position, all_stops):
    lat, lon = position
    nearby = []
    for stop in all_stops:
        dist = haversine(lat, lon, stop["latitude"], stop["longitude"])
        if dist <= SEARCH_RADIUS:
            nearby.append((stop, dist))
    if not nearby:
        for stop in all_stops:
            dist = haversine(lat, lon, stop["latitude"], stop["longitude"])
            if dist <= SEARCH_RADIUS * 3:
                nearby.append((stop, dist))
    if not nearby:
        return None
    return min(nearby, key=lambda x: x[0]["retail_price"])[0]


def calculate_total_cost(fuel_stops, total_distance_miles):
    total = sum(s["cost_at_stop"] for s in fuel_stops)
    if fuel_stops:
        remaining = total_distance_miles - fuel_stops[-1]["miles_from_start"]
        avg_price = sum(s["retail_price"] for s in fuel_stops) / len(fuel_stops)
    else:
        remaining = total_distance_miles
        avg_price = 3.50
    total += (remaining / VEHICLE_MPG) * avg_price
    return round(total, 2)
"""

with open("api/utils.py", "w") as f:
    f.write(code)
print("utils.py written successfully!")