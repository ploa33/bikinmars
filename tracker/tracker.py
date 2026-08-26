"""
BikinMars - Levélo Marseille Trip Tracker & Bike Health Engine
Collecte les flux GBFS Fifteen, reconstruit les trajets réels, détecte les pannes (boomerangs)
et calcule le score de santé de chaque vélo.
"""

import sys
import os
import time
import math
import json
import sqlite3
import argparse
import urllib.request
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

DB_PATH = os.path.join(os.path.dirname(__file__), "levelo_history.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def haversine(lat1, lon1, lat2, lon2):
    """Calcule la distance en mètres entre 2 coordonnées GPS."""
    R = 6371000  # Rayon de la Terre en mètres
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialise la base de données avec le schéma SQL."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    with get_db_connection() as conn:
        conn.executescript(schema)
        conn.commit()

def fetch_json(url, timeout=10):
    """Télécharge et parse un endpoint JSON avec User-Agent."""
    headers = {"User-Agent": "BikinMars-Tracker/1.0 (https://github.com/ploa33/bikinmars)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        if res.status != 200:
            raise Exception(f"HTTP {res.status} on {url}")
        return json.loads(res.read().decode("utf-8"))

def sync_stations(conn, stations_data):
    """Met à jour le référentiel des stations."""
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    for s in stations_data.get("data", {}).get("stations", []):
        cursor.execute("""
            INSERT INTO stations (station_id, name, lat, lon, capacity, is_charging, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(station_id) DO UPDATE SET
                name=excluded.name,
                lat=excluded.lat,
                lon=excluded.lon,
                capacity=excluded.capacity,
                is_charging=excluded.is_charging,
                last_updated=excluded.last_updated
        """, (
            s.get("station_id"),
            s.get("name", "Inconnue"),
            s.get("lat", 0.0),
            s.get("lon", 0.0),
            s.get("capacity", 0),
            1 if s.get("is_charging_station") else 0,
            now_iso
        ))

def process_bikes_snapshot(conn, bikes_data):
    """
    Analyse l'état actuel de la flotte par rapport à l'état précédent :
    - Détecte les départs de trajet (vélo qui quitte une station ou passe en transit)
    - Détecte les arrivées de trajet (vélo qui réapparaît en station)
    - Détecte les boomerangs (< 5 min dans la même station)
    - Met à jour les statistiques individuelles
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cursor = conn.cursor()

    current_bikes = {}
    for b in bikes_data.get("data", {}).get("bikes", []):
        bid = b.get("bike_id")
        if bid:
            current_bikes[bid] = b

    # Récupérer l'état connu de chaque vélo en base
    cursor.execute("SELECT bike_id, last_station_id, last_lat, last_lon, last_range_meters, status, last_seen FROM bikes")
    known_bikes = {row["bike_id"]: dict(row) for row in cursor.fetchall()}

    # Récupérer les trajets actifs en cours
    cursor.execute("SELECT * FROM active_trips")
    active_trips = {row["bike_id"]: dict(row) for row in cursor.fetchall()}

    trips_started = 0
    trips_finished = 0
    boomerangs_detected = 0

    for bike_id, b in current_bikes.items():
        curr_station = b.get("station_id") or ""
        curr_lat = b.get("lat", 0.0)
        curr_lon = b.get("lon", 0.0)
        curr_range = b.get("current_range_meters", 0)
        curr_disabled = 1 if b.get("is_disabled") else 0
        v_type = str(b.get("vehicle_type_id", ""))

        if bike_id not in known_bikes:
            # Nouveau vélo découvert
            initial_status = "station" if curr_station else "free_floating"
            cursor.execute("""
                INSERT INTO bikes (bike_id, vehicle_type_id, first_seen, last_seen, last_station_id,
                                   last_lat, last_lon, last_range_meters, last_disabled, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (bike_id, v_type, now_iso, now_iso, curr_station, curr_lat, curr_lon, curr_range, curr_disabled, initial_status))
            continue

        prev = known_bikes[bike_id]
        prev_station = prev.get("last_station_id") or ""
        prev_lat = prev.get("last_lat", 0.0)
        prev_lon = prev.get("last_lon", 0.0)
        prev_range = prev.get("last_range_meters", 0)

        # 1. DÉTECTION DE FIN DE TRAJET (le vélo était en trajet actif et réapparaît dans une station ou un nouvel endroit stable)
        if bike_id in active_trips:
            atrip = active_trips[bike_id]
            start_time = datetime.fromisoformat(atrip["start_time"])
            duration_sec = int((now - start_time).total_seconds())

            # Le vélo s'est amarré à une station OU a changé de position significativement
            if curr_station or (duration_sec >= 120 and haversine(atrip["start_lat"], atrip["start_lon"], curr_lat, curr_lon) > 50):
                distance_m = haversine(atrip["start_lat"], atrip["start_lon"], curr_lat, curr_lon)
                # Estimation vitesse (vitesse minimale 1 km/h si durée très courte, capée à 45 km/h)
                speed_kmh = (distance_m / duration_sec) * 3.6 if duration_sec > 0 else 0.0
                speed_kmh = round(min(speed_kmh, 45.0), 1)

                battery_delta = (atrip["start_range_meters"] - curr_range) if atrip["start_range_meters"] is not None else 0

                # Détection Boomerang : même station de départ et d'arrivée, et durée < 300s (5 min)
                is_boomerang = 1 if (atrip["start_station_id"] and curr_station and atrip["start_station_id"] == curr_station and duration_sec < 300) else 0

                if is_boomerang:
                    boomerangs_detected += 1

                # Enregistrement du trajet terminé
                cursor.execute("""
                    INSERT INTO completed_trips (
                        bike_id, start_station_id, end_station_id,
                        start_lat, start_lon, end_lat, end_lon,
                        start_time, end_time, duration_sec, distance_meters,
                        avg_speed_kmh, start_range_meters, end_range_meters,
                        battery_delta_meters, is_boomerang
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bike_id, atrip["start_station_id"], curr_station,
                    atrip["start_lat"], atrip["start_lon"], curr_lat, curr_lon,
                    atrip["start_time"], now_iso, duration_sec, round(distance_m, 1),
                    speed_kmh, atrip["start_range_meters"], curr_range,
                    battery_delta, is_boomerang
                ))

                # Suppression du trajet actif
                cursor.execute("DELETE FROM active_trips WHERE bike_id = ?", (bike_id,))
                trips_finished += 1

        # 2. DÉTECTION DE DÉPART DE TRAJET (le vélo était en station et n'y est plus, ou changement de station direct)
        elif prev_station and (not curr_station or curr_station != prev_station):
            # Le vélo quitte sa station
            cursor.execute("""
                INSERT OR REPLACE INTO active_trips (bike_id, start_station_id, start_lat, start_lon, start_time, start_range_meters, last_seen_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (bike_id, prev_station, prev_lat, prev_lon, now_iso, prev_range, now_iso))
            trips_started += 1

        # Mise à jour de l'état courant du vélo
        new_status = "in_trip" if bike_id in active_trips else ("station" if curr_station else "free_floating")
        cursor.execute("""
            UPDATE bikes SET
                last_seen = ?,
                last_station_id = ?,
                last_lat = ?,
                last_lon = ?,
                last_range_meters = ?,
                last_disabled = ?,
                status = ?
            WHERE bike_id = ?
        """, (now_iso, curr_station, curr_lat, curr_lon, curr_range, curr_disabled, new_status, bike_id))

    # Nettoyage des trajets actifs trop vieux (> 6h = vélo disparu ou volé ou bug télématique)
    cursor.execute("""
        DELETE FROM active_trips WHERE (julianday(?) - julianday(start_time)) * 86400 > 21600
    """, (now_iso,))

    conn.commit()
    return trips_started, trips_finished, boomerangs_detected

def run_once():
    """Exécute un cycle de capture unique."""
    init_db()
    with get_db_connection() as conn:
        try:
            info_data = fetch_json(ENDPOINTS["info"])
            sync_stations(conn, info_data)
        except Exception as e:
            print(f"⚠️ Erreur sync stations: {e}", file=sys.stderr)

        bikes_data = fetch_json(ENDPOINTS["bikes"])
        total_bikes = len(bikes_data.get("data", {}).get("bikes", []))
        started, finished, boomerangs = process_bikes_snapshot(conn, bikes_data)

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] 🚲 Vélos scannés: {total_bikes} | Trajets commencés: {started} | Terminés: {finished} | 🪃 Boomerangs: {boomerangs}")

def run_loop(interval_sec=60):
    """Exécute la boucle de capture en continu."""
    print("=" * 65)
    print("🚀 BikinMars Levélo Tracker démarré !")
    print(f"📍 Base SQLite: {DB_PATH}")
    print(f"⏱️ Intervalle de collecte: {interval_sec}s")
    print("=" * 65)
    
    init_db()
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"❌ Erreur de cycle: {e}", file=sys.stderr)
        time.sleep(interval_sec)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BikinMars Levélo Trip & Bike Health Tracker")
    parser.add_argument("--once", action="store_true", help="Exécuter un seul cycle de capture")
    parser.add_argument("--loop", action="store_true", help="Exécuter en continu")
    parser.add_argument("--interval", type=int, default=60, help="Intervalle en secondes (défaut: 60)")

    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        run_loop(interval_sec=args.interval)
