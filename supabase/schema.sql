-- ==============================================================================
-- BIKINMARS — SCHEMA SUPABASE (POSTGRESQL)
-- Tracking des trajets Levélo Marseille & Calcul de santé des vélos
-- ==============================================================================

-- 1. Table des Stations
CREATE TABLE IF NOT EXISTS public.stations (
    station_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    capacity INTEGER DEFAULT 0,
    is_charging BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMPTZ DEFAULT timezone('utc'::text, now())
);

-- 2. Table des Vélos (Historique & État courant)
CREATE TABLE IF NOT EXISTS public.bikes (
    bike_id TEXT PRIMARY KEY,
    vehicle_type_id TEXT,
    physical_code TEXT,                  -- Numéro de cadre / QR code si scanné
    first_seen TIMESTAMPTZ DEFAULT timezone('utc'::text, now()),
    last_seen TIMESTAMPTZ DEFAULT timezone('utc'::text, now()),
    last_station_id TEXT,
    last_lat DOUBLE PRECISION,
    last_lon DOUBLE PRECISION,
    last_range_meters INTEGER DEFAULT 0,
    last_disabled BOOLEAN DEFAULT FALSE,
    total_trips INTEGER DEFAULT 0,
    total_boomerangs INTEGER DEFAULT 0,
    total_distance_meters DOUBLE PRECISION DEFAULT 0,
    avg_speed_kmh DOUBLE PRECISION DEFAULT 0,
    health_score INTEGER DEFAULT 100,    -- Score de 0 à 100
    status TEXT DEFAULT 'station'        -- 'station', 'free_floating', 'in_trip', 'disabled'
);

-- 3. Table des Trajets en cours (Active Trips)
CREATE TABLE IF NOT EXISTS public.active_trips (
    bike_id TEXT PRIMARY KEY,
    start_station_id TEXT,
    start_lat DOUBLE PRECISION NOT NULL,
    start_lon DOUBLE PRECISION NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    start_range_meters INTEGER,
    last_seen_time TIMESTAMPTZ NOT NULL
);

-- 4. Table des Trajets Réalisés (Completed Trips)
CREATE TABLE IF NOT EXISTS public.completed_trips (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bike_id TEXT NOT NULL REFERENCES public.bikes(bike_id),
    start_station_id TEXT,
    end_station_id TEXT,
    start_lat DOUBLE PRECISION NOT NULL,
    start_lon DOUBLE PRECISION NOT NULL,
    end_lat DOUBLE PRECISION NOT NULL,
    end_lon DOUBLE PRECISION NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    duration_sec INTEGER NOT NULL,
    distance_meters DOUBLE PRECISION NOT NULL,
    avg_speed_kmh DOUBLE PRECISION NOT NULL,
    start_range_meters INTEGER,
    end_range_meters INTEGER,
    battery_delta_meters INTEGER,
    is_boomerang BOOLEAN DEFAULT FALSE
);

-- Index pour requêtes ultra-rapides
CREATE INDEX IF NOT EXISTS idx_completed_trips_bike_id ON public.completed_trips(bike_id);
CREATE INDEX IF NOT EXISTS idx_completed_trips_start_time ON public.completed_trips(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_completed_trips_is_boomerang ON public.completed_trips(is_boomerang);
CREATE INDEX IF NOT EXISTS idx_bikes_station ON public.bikes(last_station_id);

-- ==============================================================================
-- VUE AGRÉGÉE DE SANTÉ DES VÉLOS (Accessible par le Front-end)
-- ==============================================================================
CREATE OR REPLACE VIEW public.vw_bikes_health AS
SELECT 
    b.bike_id,
    b.physical_code,
    b.last_station_id,
    b.last_range_meters,
    b.last_disabled,
    b.status,
    b.last_seen,
    COALESCE(trip_stats.trips_24h, 0) AS trips_24h,
    COALESCE(trip_stats.boomerangs_24h, 0) AS boomerangs_24h,
    COALESCE(trip_stats.recent_avg_speed, 15.0) AS recent_avg_speed_kmh,
    -- Calcul dynamique du score de santé (0 à 100)
    CASE 
        WHEN b.last_disabled THEN 0
        WHEN COALESCE(trip_stats.boomerangs_24h, 0) >= 2 THEN 20
        WHEN COALESCE(trip_stats.boomerangs_24h, 0) = 1 THEN 50
        WHEN b.last_range_meters = 0 THEN 40
        ELSE GREATEST(60, LEAST(100, 80 + CASE WHEN COALESCE(trip_stats.recent_avg_speed, 15.0) > 16 THEN 20 ELSE 0 END))
    END AS health_score
FROM public.bikes b
LEFT JOIN (
    SELECT 
        bike_id,
        COUNT(*) AS trips_24h,
        COUNT(*) FILTER (WHERE is_boomerang = TRUE) AS boomerangs_24h,
        ROUND(AVG(avg_speed_kmh)::numeric, 1) AS recent_avg_speed
    FROM public.completed_trips
    WHERE start_time >= NOW() - INTERVAL '24 HOURS'
    GROUP BY bike_id
) trip_stats ON b.bike_id = trip_stats.bike_id;

-- ==============================================================================
-- SÉCURITÉ ROW LEVEL SECURITY (RLS)
-- ==============================================================================
ALTER TABLE public.stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bikes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.active_trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.completed_trips ENABLE ROW LEVEL SECURITY;

-- Lecture publique (Anon) pour le site web
CREATE POLICY "Public Read Stations" ON public.stations FOR SELECT TO anon USING (true);
CREATE POLICY "Public Read Bikes" ON public.bikes FOR SELECT TO anon USING (true);
CREATE POLICY "Public Read Completed Trips" ON public.completed_trips FOR SELECT TO anon USING (true);

-- Écriture réservée au Service Role (GitHub Actions / Scraper)
CREATE POLICY "Service Role All Stations" ON public.stations FOR ALL TO service_role USING (true);
CREATE POLICY "Service Role All Bikes" ON public.bikes FOR ALL TO service_role USING (true);
CREATE POLICY "Service Role All Active Trips" ON public.active_trips FOR ALL TO service_role USING (true);
CREATE POLICY "Service Role All Completed Trips" ON public.completed_trips FOR ALL TO service_role USING (true);
