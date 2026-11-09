"""Base de datos SQLite: esquema, datos de ejemplo y funciones de acceso.

Tablas (salen del diagrama de clases): destino, actividad y propuesta_ia.
"""
import json
import os
import sqlite3

from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("RDM_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rutas.db"))
CONTINENTES = ["América", "Europa", "Asia", "África", "Oceanía"]
CATEGORIAS = ["cultura", "gastronomia", "historia", "playa", "naturaleza", "aventura"]
ORIGENES = ["Medellín (MDE)", "Bogotá (BOG)", "Cali (CLO)", "Cartagena (CTG)", "Barranquilla (BAQ)"]
ORIGEN_BASE = ORIGENES[0]
HABITACIONES = ["sencilla", "doble", "triple"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS destino (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pais        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    continente  TEXT NOT NULL,
    ciudades    TEXT NOT NULL,              -- lista JSON de ciudades
    activo      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS actividad (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    destino_id  INTEGER NOT NULL REFERENCES destino(id) ON DELETE CASCADE,
    nombre      TEXT NOT NULL,
    ciudad      TEXT NOT NULL,
    categoria   TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    costo       REAL NOT NULL DEFAULT 0     -- USD por persona
);
CREATE TABLE IF NOT EXISTS propuesta_ia (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    destino_id         INTEGER NOT NULL REFERENCES destino(id),
    noches             INTEGER NOT NULL,
    presupuesto        REAL,
    tipo_viajero       TEXT NOT NULL,
    intereses          TEXT NOT NULL,       -- lista JSON
    costo_estimado     REAL NOT NULL,
    excede_presupuesto INTEGER NOT NULL DEFAULT 0,
    itinerario         TEXT NOT NULL,       -- JSON con los dias
    fuente             TEXT NOT NULL,       -- gemini | simulado | simulado (respaldo: ...)
    revisada           INTEGER NOT NULL DEFAULT 0,
    creada             TEXT NOT NULL DEFAULT (datetime('now')),
    asesor_id          INTEGER,
    origen             TEXT NOT NULL DEFAULT 'Medellín (MDE)',
    viajeros           INTEGER NOT NULL DEFAULT 1,
    anterior_id        INTEGER                  -- propuesta de la que se regeneró (HU-14)
);
CREATE TABLE IF NOT EXISTS usuario (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL,
    correo      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    clave_hash  TEXT NOT NULL,
    rol         TEXT NOT NULL CHECK (rol IN ('administrador','asesor'))
);
CREATE TABLE IF NOT EXISTS plan_turistico (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    asesor_id      INTEGER NOT NULL REFERENCES usuario(id),
    destino_id     INTEGER NOT NULL REFERENCES destino(id),
    propuesta_id   INTEGER UNIQUE REFERENCES propuesta_ia(id),
    nombre         TEXT NOT NULL,
    descripcion    TEXT NOT NULL DEFAULT '',
    noches         INTEGER NOT NULL,
    costo_estimado REAL NOT NULL,           -- por persona; es el precio que ve el viajero
    estado         TEXT NOT NULL DEFAULT 'BORRADOR' CHECK (estado IN ('BORRADOR','PUBLICADO','ARCHIVADO')),
    itinerario     TEXT NOT NULL,           -- JSON: dias con actividad_ids, generado_por_ia, revisado
    creado         TEXT NOT NULL DEFAULT (datetime('now')),
    origen         TEXT NOT NULL DEFAULT 'Medellín (MDE)',
    alojamientos   TEXT NOT NULL DEFAULT '{}'  -- JSON ciudad -> alojamiento elegido (vacío = el más económico)
);
CREATE TABLE IF NOT EXISTS solicitud_reserva (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id   INTEGER NOT NULL REFERENCES plan_turistico(id),
    nombre    TEXT NOT NULL,
    correo    TEXT NOT NULL,
    telefono  TEXT NOT NULL,
    viajeros  INTEGER NOT NULL,
    estado    TEXT NOT NULL DEFAULT 'RECIBIDA',
    creada    TEXT NOT NULL DEFAULT (datetime('now')),
    salida_id INTEGER,
    habitacion TEXT NOT NULL DEFAULT 'doble',
    origen    TEXT
);
CREATE TABLE IF NOT EXISTS alojamiento (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    destino_id  INTEGER NOT NULL REFERENCES destino(id) ON DELETE CASCADE,
    nombre      TEXT NOT NULL,
    ciudad      TEXT NOT NULL,
    categoria   INTEGER NOT NULL CHECK (categoria BETWEEN 1 AND 5),   -- estrellas
    tarifa_noche REAL NOT NULL                                         -- USD por persona en habitación doble
);
CREATE TABLE IF NOT EXISTS vuelo (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    destino_id   INTEGER NOT NULL REFERENCES destino(id) ON DELETE CASCADE,
    origen       TEXT NOT NULL,
    aerolinea    TEXT NOT NULL,
    tarifa       REAL NOT NULL,                  -- ida y vuelta, USD por persona
    escalas      INTEGER NOT NULL DEFAULT 0,
    hora_ida     TEXT NOT NULL DEFAULT '',
    hora_regreso TEXT NOT NULL DEFAULT '',
    equipaje     TEXT NOT NULL DEFAULT 'Maleta de 23 kg incluida'
);
CREATE TABLE IF NOT EXISTS salida_plan (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id  INTEGER NOT NULL REFERENCES plan_turistico(id) ON DELETE CASCADE,
    fecha    TEXT NOT NULL,                      -- AAAA-MM-DD
    cupos    INTEGER NOT NULL,
    UNIQUE (plan_id, fecha)
);
"""

# Columnas agregadas en sprints posteriores: se añaden a bases creadas con versiones anteriores.
COLUMNAS_NUEVAS = [
    ("propuesta_ia", "asesor_id", "INTEGER"),
    ("propuesta_ia", "origen", "TEXT NOT NULL DEFAULT 'Medellín (MDE)'"),
    ("propuesta_ia", "viajeros", "INTEGER NOT NULL DEFAULT 1"),
    ("propuesta_ia", "anterior_id", "INTEGER"),
    ("plan_turistico", "origen", "TEXT NOT NULL DEFAULT 'Medellín (MDE)'"),
    ("plan_turistico", "alojamientos", "TEXT NOT NULL DEFAULT '{}'"),
    ("solicitud_reserva", "salida_id", "INTEGER"),
    ("solicitud_reserva", "habitacion", "TEXT NOT NULL DEFAULT 'doble'"),
    ("solicitud_reserva", "origen", "TEXT"),
]

# Alojamientos y vuelos de ejemplo (pais -> lista). Valores de referencia, editables desde el Catálogo.
ALOJAMIENTOS_SEMILLA = {
    "Italia": [("Roma", "Hotel Colosseo Centro", 3, 85), ("Roma", "Hotel Pantheon Suites", 4, 130),
               ("Florencia", "Hotel Duomo", 3, 80), ("Florencia", "Palazzo Arno", 4, 125),
               ("Venecia", "Hotel Laguna", 3, 90), ("Venecia", "Ca' Rialto", 4, 140)],
    "Colombia": [("Cartagena", "Hotel Muralla", 3, 70), ("Cartagena", "Caribe Real", 4, 110), ("Medellín", "Hotel Poblado", 3, 60),
                 ("Medellín", "Laureles Boutique", 4, 95)],
    "Francia": [("París", "Hôtel Montmartre", 3, 95), ("París", "Hôtel Louvre", 4, 140)],
}
VUELOS_SEMILLA = {
    "Italia": [("Medellín (MDE)", "Iberia", 790, 1, "09:45 → 00:50 (+1)", "13:45 → 04:50 (+1)"),
               ("Bogotá (BOG)", "Iberia", 750, 1, "11:15 → 04:05 (+1)", "14:30 → 05:10 (+1)"),
               ("Cali (CLO)", "LATAM", 820, 1, "08:20 → 23:40", "12:10 → 04:30 (+1)")],
    "Colombia": [("Medellín (MDE)", "Avianca", 150, 0, "07:30 → 08:50", "18:10 → 19:30"),
                 ("Bogotá (BOG)", "Avianca", 140, 0, "06:50 → 08:20", "17:40 → 19:10"),
                 ("Cali (CLO)", "LATAM", 160, 1, "09:00 → 11:30", "16:20 → 18:50")],
    "Francia": [("Medellín (MDE)", "Air France", 780, 1, "10:10 → 03:20 (+1)", "15:00 → 07:35 (+1)"),
                ("Bogotá (BOG)", "Air France", 740, 0, "21:30 → 13:40 (+1)", "16:50 → 22:20")],
}

# Valores de ejemplo (costos en USD por persona). Se pueden editar desde la pantalla Catálogo.
SEMILLA = {
    ("Italia", "Europa", ("Roma", "Florencia", "Venecia")): [
        ("Roma", "Coliseo y Foro Romano", "historia", 40), ("Roma", "Museos Vaticanos y Capilla Sixtina", "cultura", 35),
        ("Roma", "Fontana de Trevi y Plaza de España", "cultura", 0), ("Roma", "Panteón", "historia", 10),
        ("Roma", "Cena de pasta en Trastevere", "gastronomia", 30),
        ("Florencia", "Duomo y Piazza della Signoria", "cultura", 25), ("Florencia", "Ponte Vecchio y Galería Uffizi", "cultura", 30),
        ("Florencia", "Clase de cocina toscana", "gastronomia", 60),
        ("Venecia", "Paseo en góndola", "cultura", 35), ("Venecia", "Plaza San Marcos y Palacio Ducal", "historia", 30),
        ("Venecia", "Isla de Murano", "cultura", 15),
    ],
    ("Colombia", "América", ("Cartagena", "Medellín")): [
        ("Cartagena", "Ciudad Amurallada a pie", "historia", 15), ("Cartagena", "Islas del Rosario", "playa", 60),
        ("Cartagena", "Castillo San Felipe", "historia", 10),
        ("Medellín", "Comuna 13 y metrocable", "cultura", 20), ("Medellín", "Parque Arví", "naturaleza", 25),
        ("Medellín", "Tour de café", "gastronomia", 30),
    ],
    ("Francia", "Europa", ("París",)): [
        ("París", "Torre Eiffel", "cultura", 30), ("París", "Museo del Louvre", "cultura", 25),
        ("París", "Paseo por el Sena", "cultura", 20), ("París", "Montmartre y Sacré-Cœur", "historia", 0),
        ("París", "Degustación de quesos y vino", "gastronomia", 45),
    ],
}


USUARIOS_DEMO = [("Juan Chaverra", "admin@rutasdelmundo.co", "admin123", "administrador"),
                 ("Samuel Parra", "asesor@rutasdelmundo.co", "asesor123", "asesor")]


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def consultar(sql, args=(), uno=False):
    conn = conectar()
    try:
        filas = [dict(f) for f in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
    return (filas[0] if filas else None) if uno else filas


def ejecutar(sql, args=()):
    conn = conectar()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def iniciar():
    conn = conectar()
    try:
        conn.executescript(ESQUEMA)
        for tabla, col, ddl in COLUMNAS_NUEVAS:
            if col not in [r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")]:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {ddl}")
        if conn.execute("SELECT COUNT(*) FROM usuario").fetchone()[0] == 0:
            conn.executemany("INSERT INTO usuario (nombre, correo, clave_hash, rol) VALUES (?,?,?,?)",
                             [(n, c, generate_password_hash(p), r) for n, c, p, r in USUARIOS_DEMO])
        if conn.execute("SELECT COUNT(*) FROM destino").fetchone()[0] == 0:
            for (pais, cont, ciudades), acts in SEMILLA.items():
                did = conn.execute("INSERT INTO destino (pais, continente, ciudades) VALUES (?,?,?)",
                                   (pais, cont, json.dumps(list(ciudades), ensure_ascii=False))).lastrowid
                conn.executemany("INSERT INTO actividad (destino_id, nombre, ciudad, categoria, costo) VALUES (?,?,?,?,?)",
                                 [(did, n, c, cat, costo) for c, n, cat, costo in acts])
        if conn.execute("SELECT COUNT(*) FROM alojamiento").fetchone()[0] == 0:
            for pais, items in ALOJAMIENTOS_SEMILLA.items():
                d = conn.execute("SELECT id FROM destino WHERE pais = ?", (pais,)).fetchone()
                if d:
                    conn.executemany("INSERT INTO alojamiento (destino_id, ciudad, nombre, categoria, tarifa_noche) VALUES (?,?,?,?,?)",
                                     [(d[0], c, n, cat, t) for c, n, cat, t in items])
        if conn.execute("SELECT COUNT(*) FROM vuelo").fetchone()[0] == 0:
            for pais, items in VUELOS_SEMILLA.items():
                d = conn.execute("SELECT id FROM destino WHERE pais = ?", (pais,)).fetchone()
                if d:
                    conn.executemany("""INSERT INTO vuelo (destino_id, origen, aerolinea, tarifa, escalas, hora_ida, hora_regreso)
                                        VALUES (?,?,?,?,?,?,?)""", [(d[0],) + v for v in items])
        conn.commit()
    finally:
        conn.close()
