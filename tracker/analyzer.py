"""
BikinMars — Local SQLite Analyzer & JSON Exporter
Calcule les statistiques des vélos (santé, vitesse, boomerangs) et génère data/bikes_health.json.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DB_PATH = os.path.join(os.path.dirname(__file__), "levelo_history.db")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bikes_health.json")

def analyze_and_export():
    if not os.path.exists(DB_PATH):
        print(f"⚠️ Base {DB_PATH} introuvable.")
        return

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Récupération de tous les vélos avec leurs stats des dernières 24h
    cursor.execute("""
        SELECT 
            b.bike_id,
            b.physical_code,
            b.last_station_id,
            b.last_range_meters,
            b.last_disabled,
            b.status,
            b.last_seen,
            COUNT(t.id) as trips_24h,
            SUM(CASE WHEN t.is_boomerang = 1 THEN 1 ELSE 0 END) as boomerangs_24h,
            AVG(t.avg_speed_kmh) as recent_avg_speed_kmh
        FROM bikes b
        LEFT JOIN completed_trips t ON b.bike_id = t.bike_id 
            AND (julianday('now') - julianday(t.start_time)) * 24 <= 24
        GROUP BY b.bike_id
    """)

    bikes_list = []
    for row in cursor.fetchall():
        b_dict = dict(row)
        boomerangs = b_dict.get("boomerangs_24h") or 0
        speed = b_dict.get("recent_avg_speed_kmh") or 15.0
        disabled = bool(b_dict.get("last_disabled"))
        range_m = b_dict.get("last_range_meters") or 0

        # Calcul du score de santé (0-100)
        if disabled:
            score = 0
        elif boomerangs >= 2:
            score = 20
        elif boomerangs == 1:
            score = 50
        elif range_m == 0:
            score = 40
        else:
            score = min(100, max(60, int(80 + (20 if speed > 16 else 0))))

        bikes_list.append({
            "bike_id": b_dict["bike_id"],
            "physical_code": b_dict.get("physical_code"),
            "health_score": score,
            "boomerangs_24h": boomerangs,
            "trips_24h": b_dict.get("trips_24h") or 0,
            "recent_avg_speed_kmh": round(speed, 1),
            "last_seen": b_dict.get("last_seen")
        })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_bikes": len(bikes_list),
        "bikes": bikes_list
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ Export généré avec succès : {OUTPUT_PATH} ({len(bikes_list)} vélos)")

if __name__ == "__main__":
    analyze_and_export()
