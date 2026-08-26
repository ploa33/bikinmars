"""
BikinMars — Levélo Marseille Supabase Tracker
Collecte les flux GBFS Fifteen et synchronise l'état et les trajets dans Supabase.
Peut être exécuté en local ou via GitHub Actions.
"""

import sys
import os
import time
import math
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

GBFS_BASE = "https://gbfs.omega.fifteen.eu/gbfs/2.2/marseille/en"
ENDPOINTS = {
    "info": f"{GBFS_BASE}/station_information.json",
    "status": f"{GBFS_BASE}/station_status.json",
    "bikes": f"{GBFS_BASE}/free_bike_status.json",
}

# Supabase Credentials (lus depuis les variables d'environnement)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")

def haversine(lat1, lon1, lat2, lon2):
    """Calcule la distance en mètres entre 2 coordonnées GPS."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def fetch_json(url, timeout=10):
    """Télécharge et parse un JSON."""
    headers = {"User-Agent": "BikinMars-Tracker/1.0 (https://github.com/ploa33/bikinmars)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        if res.status != 200:
            raise Exception(f"HTTP {res.status} on {url}")
        return json.loads(res.read().decode("utf-8"))

def supabase_request(endpoint, method="GET", data=None, params=None, prefer=None):
    """Effectue un appel PostgREST à l'API Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Variables SUPABASE_URL ou SUPABASE_KEY non définies.")

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "BikinMars-Supabase-Sync/1.0",
    }
    if prefer:
        headers["Prefer"] = prefer

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=15) as res:
        if res.status in (200, 201, 204):
            content = res.read().decode("utf-8")
            return json.loads(content) if content else []
        raise Exception(f"Supabase error {res.status}: {res.read().decode('utf-8')}")

def sync_stations_to_supabase(stations_data):
    """Upsert des stations dans Supabase."""
    now_iso = datetime.now(timezone.utc).isoformat()
    records = []
    for s in stations_data.get("data", {}).get("stations", []):
        records.append({
            "station_id": s.get("station_id"),
            "name": s.get("name", "Inconnue"),
            "lat": float(s.get("lat", 0.0)),
            "lon": float(s.get("lon", 0.0)),
            "capacity": int(s.get("capacity", 0)),
            "is_charging": bool(s.get("is_charging_station")),
            "last_updated": now_iso
        })
    if records:
        supabase_request("stations", method="POST", data=records, prefer="resolution=merge-duplicates")

def process_and_sync_supabase():
    """Cycle principal de détection et synchronisation avec Supabase."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # 1. Récupération des données Fifteen
    info_data = fetch_json(ENDPOINTS["info"])
    bikes_data = fetch_json(ENDPOINTS["bikes"])
    raw_bikes = bikes_data.get("data", {}).get("bikes", [])

    print(f"📡 Récupération GBFS : {len(raw_bikes)} vélos")

    # 2. Synchronisation du référentiel des stations
    try:
        sync_stations_to_supabase(info_data)
    except Exception as e:
        print(f"⚠️ Erreur sync stations: {e}", file=sys.stderr)

    # 3. Récupération de l'état actuel depuis Supabase
    known_bikes_raw = supabase_request("bikes", method="GET", params={"select": "bike_id,last_station_id,last_lat,last_lon,last_range_meters,status"})
    known_bikes = {b["bike_id"]: b for b in known_bikes_raw}

    active_trips_raw = supabase_request("active_trips", method="GET", params={"select": "*"})
    active_trips = {t["bike_id"]: t for t in active_trips_raw}

    bikes_to_upsert = []
    completed_trips_to_insert = []
    active_trips_to_upsert = []
    active_trips_to_delete = []

    trips_started = 0
    trips_finished = 0
    boomerangs_count = 0

    for b in raw_bikes:
        bike_id = b.get("bike_id")
        if not bike_id:
            continue

        curr_station = b.get("station_id") or ""
        curr_lat = float(b.get("lat", 0.0))
        curr_lon = float(b.get("lon", 0.0))
        curr_range = int(b.get("current_range_meters", 0))
        curr_disabled = bool(b.get("is_disabled"))
        v_type = str(b.get("vehicle_type_id", ""))

        if bike_id not in known_bikes:
            # Premier enregistrement
            bikes_to_upsert.append({
                "bike_id": bike_id,
                "vehicle_type_id": v_type,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "last_station_id": curr_station,
                "last_lat": curr_lat,
                "last_lon": curr_lon,
                "last_range_meters": curr_range,
                "last_disabled": curr_disabled,
                "status": "station" if curr_station else "free_floating"
            })
            continue

        prev = known_bikes[bike_id]
        prev_station = prev.get("last_station_id") or ""
        prev_lat = float(prev.get("last_lat") or 0.0)
        prev_lon = float(prev.get("last_lon") or 0.0)
        prev_range = int(prev.get("last_range_meters") or 0)

        # Détection FIN DE TRAJET
        if bike_id in active_trips:
            atrip = active_trips[bike_id]
            start_time = datetime.fromisoformat(atrip["start_time"].replace("Z", "+00:00"))
            duration_sec = max(1, int((now - start_time).total_seconds()))

            if curr_station or (duration_sec >= 120 and haversine(atrip["start_lat"], atrip["start_lon"], curr_lat, curr_lon) > 50):
                distance_m = haversine(atrip["start_lat"], atrip["start_lon"], curr_lat, curr_lon)
                speed_kmh = round(min((distance_m / duration_sec) * 3.6, 45.0), 1)
                start_range = atrip.get("start_range_meters")
                battery_delta = (start_range - curr_range) if start_range is not None else 0

                is_boomerang = bool(atrip.get("start_station_id") and curr_station and atrip["start_station_id"] == curr_station and duration_sec < 300)
                if is_boomerang:
                    boomerangs_count += 1

                completed_trips_to_insert.append({
                    "bike_id": bike_id,
                    "start_station_id": atrip.get("start_station_id"),
                    "end_station_id": curr_station,
                    "start_lat": atrip["start_lat"],
                    "start_lon": atrip["start_lon"],
                    "end_lat": curr_lat,
                    "end_lon": curr_lon,
                    "start_time": atrip["start_time"],
                    "end_time": now_iso,
                    "duration_sec": duration_sec,
                    "distance_meters": round(distance_m, 1),
                    "avg_speed_kmh": speed_kmh,
                    "start_range_meters": start_range,
                    "end_range_meters": curr_range,
                    "battery_delta_meters": battery_delta,
                    "is_boomerang": is_boomerang
                })
                active_trips_to_delete.append(bike_id)
                trips_finished += 1

        # Détection DÉBUT DE TRAJET
        elif prev_station and (not curr_station or curr_station != prev_station):
            active_trips_to_upsert.append({
                "bike_id": bike_id,
                "start_station_id": prev_station,
                "start_lat": prev_lat,
                "start_lon": prev_lon,
                "start_time": now_iso,
                "start_range_meters": prev_range,
                "last_seen_time": now_iso
            })
            trips_started += 1

        # Mise à jour de l'état du vélo
        bikes_to_upsert.append({
            "bike_id": bike_id,
            "vehicle_type_id": v_type,
            "last_seen": now_iso,
            "last_station_id": curr_station,
            "last_lat": curr_lat,
            "last_lon": curr_lon,
            "last_range_meters": curr_range,
            "last_disabled": curr_disabled,
            "status": "in_trip" if bike_id in active_trips else ("station" if curr_station else "free_floating")
        })

    # 4. Exécution des batchs Supabase
    if bikes_to_upsert:
        # Batch par tranches de 200 vélos pour ne pas surcharger la requête
        for i in range(0, len(bikes_to_upsert), 200):
            supabase_request("bikes", method="POST", data=bikes_to_upsert[i:i+200], prefer="resolution=merge-duplicates")

    if completed_trips_to_insert:
        supabase_request("completed_trips", method="POST", data=completed_trips_to_insert)

    if active_trips_to_upsert:
        supabase_request("active_trips", method="POST", data=active_trips_to_upsert, prefer="resolution=merge-duplicates")

    for bid in active_trips_to_delete:
        supabase_request("active_trips", method="DELETE", params={"bike_id": f"eq.{bid}"})

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] ✅ Synchronisation Supabase réussie !")
    print(f"   ├─ Trajets commencés : {trips_started}")
    print(f"   ├─ Trajets terminés  : {trips_finished}")
    print(f"   └─ 🪃 Boomerangs     : {boomerangs_count}")

if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Erreur : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY doivent être définies dans l'environnement.", file=sys.stderr)
        print("Exemple PowerShell : $env:SUPABASE_URL='https://xyz.supabase.co'; $env:SUPABASE_SERVICE_ROLE_KEY='...'")
        sys.exit(1)

    process_and_sync_supabase()
