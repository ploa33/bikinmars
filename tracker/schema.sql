-- BikinMars Levélo Tracker Schema

CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    capacity INTEGER DEFAULT 0,
    is_charging BOOLEAN DEFAULT 0,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bikes (
    bike_id TEXT PRIMARY KEY,
    vehicle_type_id TEXT,
    physical_code TEXT,                -- Cadre / QR Code si scanné
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_station_id TEXT,
    last_lat REAL,
    last_lon REAL,
    last_range_meters INTEGER,
    last_disabled BOOLEAN DEFAULT 0,
    total_trips INTEGER DEFAULT 0,
    total_boomerangs INTEGER DEFAULT 0,
    total_distance_meters REAL DEFAULT 0,
    avg_speed_kmh REAL DEFAULT 0,
    health_score INTEGER DEFAULT 100,  -- 0 à 100
    status TEXT DEFAULT 'station'      -- 'station', 'free_floating', 'in_trip', 'disabled'
);

CREATE TABLE IF NOT EXISTS active_trips (
    bike_id TEXT PRIMARY KEY,
    start_station_id TEXT,
    start_lat REAL NOT NULL,
    start_lon REAL NOT NULL,
    start_time DATETIME NOT NULL,
    start_range_meters INTEGER,
    last_seen_time DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS completed_trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bike_id TEXT NOT NULL,
    start_station_id TEXT,
    end_station_id TEXT,
    start_lat REAL NOT NULL,
    start_lon REAL NOT NULL,
    end_lat REAL NOT NULL,
    end_lon REAL NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    duration_sec INTEGER NOT NULL,
    distance_meters REAL NOT NULL,
    avg_speed_kmh REAL NOT NULL,
    start_range_meters INTEGER,
    end_range_meters INTEGER,
    battery_delta_meters INTEGER,
    is_boomerang BOOLEAN DEFAULT 0,
    FOREIGN KEY (bike_id) REFERENCES bikes(bike_id)
);

CREATE INDEX IF NOT EXISTS idx_completed_trips_bike_id ON completed_trips(bike_id);
CREATE INDEX IF NOT EXISTS idx_completed_trips_start_time ON completed_trips(start_time);
CREATE INDEX IF NOT EXISTS idx_completed_trips_is_boomerang ON completed_trips(is_boomerang);
