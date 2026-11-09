"""API REST de Rutas del Mundo: las 26 historias del backlog (MVP e incremento 2) y servidor del front.

Sprint 1: HU-02, 03, 08, 10, 11, 13   Sprint 2: HU-01, 07, 12, 15, 16   Sprint 3: HU-18, 19, 21, 22, 25
Incremento 2: HU-04, 05, 06, 09, 14, 17, 20, 23, 24, 26
"""
import json
import os
import re
import sys
from datetime import date, timedelta
from functools import wraps
from urllib.parse import quote

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cargar_env():
    """Lee el archivo .env (si existe) sin pisar variables ya definidas."""
    ruta = os.path.join(RAIZ, ".env")
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


cargar_env()

from flask import Flask, jsonify, request, send_from_directory, session  # noqa: E402
from werkzeug.security import check_password_hash  # noqa: E402

import costos  # noqa: E402
import db  # noqa: E402
from ia_service import ErrorIA, SimuladoServicio, normalizar, normalizar_recomendaciones, obtener_servicios  # noqa: E402

app = Flask(__name__, static_folder=os.path.join(RAIZ, "frontend"), static_url_path="")
app.secret_key = os.environ.get("RDM_SECRET", "clave-de-desarrollo-cambiala")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=bool(os.environ.get("DATABASE_URL")),
)
TIPOS_VIAJERO = ["solo", "pareja", "familia", "amigos"]
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ORDENES = {"precio": ("precio_persona", False), "precio_desc": ("precio_persona", True), "noches": ("noches", False), "nombre": ("nombre", False)}


class ErrorHttp(Exception):
    def __init__(self, mensaje, codigo=400, **extra):
        super().__init__(mensaje)
        self.codigo, self.extra = codigo, extra


class ValidacionError(ErrorHttp):
    pass


@app.errorhandler(ErrorHttp)
def _error(e):
    return jsonify({"error": str(e), **e.extra}), e.codigo


def requiere(*roles):
    def deco(f):
        @wraps(f)
        def envoltura(*a, **k):
            rol = session.get("rol")
            if not rol:
                raise ErrorHttp("Inicia sesión para continuar", 401)
            if rol not in roles:
                raise ErrorHttp("No tienes permiso para esta acción", 403)
            return f(*a, **k)
        return envoltura
    return deco


# ---------- validaciones ----------
def texto(v, nombre, max_len=80, obligatorio=True):
    if not isinstance(v, str) or not v.strip():
        if obligatorio:
            raise ValidacionError(f"{nombre} es obligatorio")
        return ""
    v = v.strip()
    if len(v) > max_len:
        raise ValidacionError(f"{nombre} no puede superar {max_len} caracteres")
    return v


def numero(v, nombre, minimo, maximo=None, entero=False, obligatorio=True):
    if v is None or v == "":
        if obligatorio:
            raise ValidacionError(f"{nombre} es obligatorio")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValidacionError(f"{nombre} debe ser un número")
    if entero and int(v) != v:
        raise ValidacionError(f"{nombre} debe ser un número entero")
    if v < minimo or (maximo is not None and v > maximo):
        rango = f"entre {minimo} y {maximo}" if maximo is not None else f"mayor o igual a {minimo}"
        raise ValidacionError(f"{nombre} debe ser {rango}")
    return int(v) if entero else float(v)


def en_lista(v, nombre, opciones):
    if v not in opciones:
        raise ValidacionError(f"{nombre} debe ser uno de: " + ", ".join(opciones))
    return v


def fecha_iso(v, nombre):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise ValidacionError(f"{nombre} debe tener el formato AAAA-MM-DD")


def arg_numero(nombre, etiqueta, entero=False, minimo=0, maximo=None):
    v = request.args.get(nombre)
    if v in (None, ""):
        return None
    try:
        v = int(v) if entero else float(v)
    except ValueError:
        raise ValidacionError(f"{etiqueta} debe ser un número")
    return numero(v, etiqueta, minimo, maximo, entero=entero)


# ---------- HU-01 sesión por rol ----------
@app.post("/api/auth/login")
def login():
    d = request.get_json(silent=True) or {}
    correo = texto(d.get("correo"), "El correo", 120).lower()
    u = db.consultar("SELECT * FROM usuario WHERE correo = ?", (correo,), uno=True)
    clave = d.get("clave")
    if not u or not isinstance(clave, str) or not check_password_hash(u["clave_hash"], clave):
        raise ErrorHttp("Correo o contraseña incorrectos", 401)
    session.clear()
    session.update(usuario_id=u["id"], rol=u["rol"], nombre=u["nombre"])
    return jsonify({"nombre": u["nombre"], "rol": u["rol"]})


@app.post("/api/auth/explorar")
def explorar_como_viajero():
    session.clear()
    session.update(usuario_id=None, rol="viajero", nombre="Viajero")
    return jsonify({"nombre": "Viajero", "rol": "viajero"})


@app.get("/api/auth/yo")
def yo():
    return jsonify({"rol": session.get("rol"), "nombre": session.get("nombre")})


@app.post("/api/auth/salir")
def salir():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/salud")
def salud():
    principal, _ = obtener_servicios()
    return jsonify({"ok": True, "ia": principal.nombre, "tarifa_noche": costos.tarifa_noche(), "origenes": db.ORIGENES,
                    "habitaciones": list(costos.FACTORES_HABITACION)})


# ---------- HU-02 / HU-06 destinos ----------
def _destino(row):
    row["ciudades"] = json.loads(row["ciudades"])
    row["activo"] = bool(row["activo"])
    return row


def _obtener_destino(did, requerido=True):
    row = db.consultar("SELECT * FROM destino WHERE id = ?", (did,), uno=True)
    if not row and requerido:
        raise ErrorHttp("Destino no encontrado", 404)
    return _destino(row) if row else None


def _ciudades_validas(ciudades):
    if not isinstance(ciudades, list) or not ciudades:
        raise ValidacionError("Indica al menos una ciudad")
    limpias = []
    for c in ciudades:
        c = texto(c, "Cada ciudad", 60)
        if c.lower() not in [x.lower() for x in limpias]:
            limpias.append(c)
    return limpias


@app.get("/api/destinos")
@requiere("administrador", "asesor")
def listar_destinos():
    filas = db.consultar("""SELECT d.*, (SELECT COUNT(*) FROM actividad a WHERE a.destino_id = d.id) AS n_actividades
                            FROM destino d ORDER BY d.continente, d.pais""")
    return jsonify([_destino(f) for f in filas])


@app.post("/api/destinos")
@requiere("administrador")
def crear_destino():
    d = request.get_json(silent=True) or {}
    pais = texto(d.get("pais"), "El país", 60)
    en_lista(d.get("continente"), "El continente", db.CONTINENTES)
    ciudades = _ciudades_validas(d.get("ciudades"))
    if db.consultar("SELECT 1 FROM destino WHERE pais = ?", (pais,), uno=True):
        raise ErrorHttp(f"Ya existe un destino para {pais}", 409)
    did = db.ejecutar("INSERT INTO destino (pais, continente, ciudades) VALUES (?,?,?)",
                      (pais, d["continente"], json.dumps(ciudades, ensure_ascii=False)))
    return jsonify(_obtener_destino(did)), 201


@app.put("/api/destinos/<int:did>")
@requiere("administrador")
def editar_destino(did):
    actual = _obtener_destino(did)
    d = request.get_json(silent=True) or {}
    pais = texto(d.get("pais", actual["pais"]), "El país", 60)
    continente = en_lista(d.get("continente", actual["continente"]), "El continente", db.CONTINENTES)
    ciudades = _ciudades_validas(d.get("ciudades", actual["ciudades"]))
    if db.consultar("SELECT 1 FROM destino WHERE pais = ? AND id != ?", (pais, did), uno=True):
        raise ErrorHttp(f"Ya existe un destino para {pais}", 409)
    for c in actual["ciudades"]:  # no se puede quitar una ciudad que ya tiene datos: rompería planes existentes
        if c.lower() not in [x.lower() for x in ciudades]:
            usada = db.consultar("""SELECT 1 FROM actividad WHERE destino_id = ? AND ciudad = ?
                                    UNION SELECT 1 FROM alojamiento WHERE destino_id = ? AND ciudad = ?""", (did, c, did, c))
            if usada:
                raise ErrorHttp(f"La ciudad {c} tiene actividades o alojamientos; no se puede quitar", 409)
    db.ejecutar("UPDATE destino SET pais = ?, continente = ?, ciudades = ? WHERE id = ?",
                (pais, continente, json.dumps(ciudades, ensure_ascii=False), did))
    return jsonify(_obtener_destino(did))


def _activar(did, valor):
    _obtener_destino(did)
    db.ejecutar("UPDATE destino SET activo = ? WHERE id = ?", (valor, did))  # los planes existentes se conservan
    return jsonify(_obtener_destino(did))


@app.post("/api/destinos/<int:did>/desactivar")
@requiere("administrador")
def desactivar_destino(did):
    return _activar(did, 0)


@app.post("/api/destinos/<int:did>/activar")
@requiere("administrador")
def activar_destino(did):
    return _activar(did, 1)


# ---------- HU-03 actividades, HU-04 alojamientos, HU-05 vuelos ----------
@app.get("/api/destinos/<int:did>/actividades")
@requiere("administrador", "asesor")
def listar_actividades(did):
    _obtener_destino(did)
    return jsonify(db.consultar("SELECT * FROM actividad WHERE destino_id = ? ORDER BY ciudad, id", (did,)))


@app.post("/api/destinos/<int:did>/actividades")
@requiere("administrador")
def crear_actividad(did):
    destino = _obtener_destino(did)
    d = request.get_json(silent=True) or {}
    nombre = texto(d.get("nombre"), "El nombre", 100)
    en_lista(d.get("ciudad"), "La ciudad", destino["ciudades"])
    en_lista(d.get("categoria"), "La categoría", db.CATEGORIAS)
    costo = numero(d.get("costo", 0), "El costo", 0, 100000)
    desc = texto(d.get("descripcion"), "La descripción", 300, obligatorio=False)
    aid = db.ejecutar("INSERT INTO actividad (destino_id, nombre, ciudad, categoria, descripcion, costo) VALUES (?,?,?,?,?,?)",
                      (did, nombre, d["ciudad"], d["categoria"], desc, costo))
    return jsonify(db.consultar("SELECT * FROM actividad WHERE id = ?", (aid,), uno=True)), 201


@app.get("/api/destinos/<int:did>/alojamientos")
@requiere("administrador", "asesor")
def listar_alojamientos(did):
    _obtener_destino(did)
    return jsonify(db.consultar("SELECT * FROM alojamiento WHERE destino_id = ? ORDER BY ciudad, tarifa_noche", (did,)))


@app.post("/api/destinos/<int:did>/alojamientos")
@requiere("administrador")
def crear_alojamiento(did):
    destino = _obtener_destino(did)
    d = request.get_json(silent=True) or {}
    nombre = texto(d.get("nombre"), "El nombre", 100)
    en_lista(d.get("ciudad"), "La ciudad", destino["ciudades"])
    categoria = numero(d.get("categoria"), "La categoría (estrellas)", 1, 5, entero=True)
    tarifa = numero(d.get("tarifa_noche"), "La tarifa por noche", 1, 10000)
    aid = db.ejecutar("INSERT INTO alojamiento (destino_id, nombre, ciudad, categoria, tarifa_noche) VALUES (?,?,?,?,?)",
                      (did, nombre, d["ciudad"], categoria, tarifa))
    return jsonify(db.consultar("SELECT * FROM alojamiento WHERE id = ?", (aid,), uno=True)), 201


@app.get("/api/destinos/<int:did>/vuelos")
@requiere("administrador", "asesor")
def listar_vuelos(did):
    _obtener_destino(did)
    return jsonify(db.consultar("SELECT * FROM vuelo WHERE destino_id = ? ORDER BY origen, tarifa", (did,)))


@app.post("/api/destinos/<int:did>/vuelos")
@requiere("administrador")
def crear_vuelo(did):
    _obtener_destino(did)
    d = request.get_json(silent=True) or {}
    origen = en_lista(d.get("origen"), "El origen", db.ORIGENES)
    aerolinea = texto(d.get("aerolinea"), "La aerolínea", 60)
    tarifa = numero(d.get("tarifa"), "La tarifa", 1, 100000)
    escalas = numero(d.get("escalas", 0), "Las escalas", 0, 3, entero=True)
    ida = texto(d.get("hora_ida"), "El horario de ida", 40, obligatorio=False)
    regreso = texto(d.get("hora_regreso"), "El horario de regreso", 40, obligatorio=False)
    equipaje = texto(d.get("equipaje"), "El equipaje", 60, obligatorio=False) or "Maleta de 23 kg incluida"
    vid = db.ejecutar("""INSERT INTO vuelo (destino_id, origen, aerolinea, tarifa, escalas, hora_ida, hora_regreso, equipaje)
                         VALUES (?,?,?,?,?,?,?,?)""", (did, origen, aerolinea, tarifa, escalas, ida, regreso, equipaje))
    return jsonify(db.consultar("SELECT * FROM vuelo WHERE id = ?", (vid,), uno=True)), 201


# ---------- precios (HU-04, 09, 11, 23, 24) ----------
def _actividades_por_id(did, contexto=None):
    if contexto is not None:
        return contexto["actividades"].get(did, {})
    return {a["id"]: a for a in db.consultar("SELECT * FROM actividad WHERE destino_id = ?", (did,))}


def _tarifas(did, elegidos=None, contexto=None):
    """Alojamiento por ciudad: el elegido por el asesor o, por defecto, el más económico."""
    elegidos = elegidos or {}
    por_ciudad = {}
    alojamientos = (contexto["alojamientos"].get(did, []) if contexto is not None else
                    db.consultar("SELECT * FROM alojamiento WHERE destino_id = ? ORDER BY tarifa_noche, id", (did,)))
    for a in alojamientos:
        por_ciudad.setdefault(a["ciudad"], []).append(a)
    info = {c: next((a for a in lst if a["id"] == elegidos.get(c)), lst[0]) for c, lst in por_ciudad.items()}
    return {c: a["tarifa_noche"] for c, a in info.items()}, info


def _vuelo(did, origen, contexto=None):
    if contexto is None:
        v = db.consultar("SELECT * FROM vuelo WHERE destino_id = ? AND origen = ? ORDER BY tarifa LIMIT 1", (did, origen), uno=True)
    else:
        v = next((v for v in contexto["vuelos"].get(did, []) if v["origen"] == origen), None)
    return {k: v[k] for k in ("origen", "aerolinea", "tarifa", "escalas", "hora_ida", "hora_regreso", "equipaje")} if v else None


def _calcular_precio(did, noches, dias_raw, elegidos, origen, habitacion="doble", viajeros=1, contexto=None):
    acts = _actividades_por_id(did, contexto)
    tarifas, info = _tarifas(did, elegidos, contexto)
    doble = costos.hospedaje(noches, dias_raw, tarifas)
    hospedaje = round(doble * costos.FACTORES_HABITACION[habitacion], 2)
    actividades = round(sum(acts[i]["costo"] for i in {i for d in dias_raw for i in d["actividad_ids"]} if i in acts), 2)
    vuelo = _vuelo(did, origen, contexto)
    vuelo_pp = vuelo["tarifa"] if vuelo else 0.0
    pp = round(hospedaje + actividades + vuelo_pp, 2)
    return {"origen": origen, "habitacion": habitacion, "viajeros": viajeros, "hospedaje_pp": hospedaje, "actividades_pp": actividades,
            "vuelo_pp": vuelo_pp, "vuelo": vuelo, "vuelo_incluido": vuelo is not None, "precio_persona": pp,
            "total": round(pp * viajeros, 2), "terrestre_doble": round(doble + actividades, 2),
            "alojamientos": {c: {k: a[k] for k in ("id", "nombre", "categoria", "tarifa_noche")} for c, a in info.items()}}


def _dias_detalle(dias_raw, acts):
    return [{"numero": d["numero"], "titulo": d["titulo"], "ciudad": d["ciudad"],
             "generado_por_ia": d.get("generado_por_ia", True), "revisado": d.get("revisado", False),
             "actividades": [{k: acts[i][k] for k in ("id", "nombre", "ciudad", "categoria", "costo")}
                             for i in d["actividad_ids"] if i in acts]} for d in dias_raw]


# ---------- HU-08 / 09 / 10 / 11 / 13 / 14 propuestas de la IA ----------
def _propuesta(row):
    destino = db.consultar("SELECT id, pais FROM destino WHERE id = ?", (row["destino_id"],), uno=True)
    raw = json.loads(row["itinerario"])
    dias = _dias_detalle(raw, _actividades_por_id(row["destino_id"]))
    p = _calcular_precio(row["destino_id"], row["noches"], raw, {}, row["origen"], "doble", row["viajeros"])
    aviso = None
    if row["excede_presupuesto"]:
        aviso = (f"El costo estimado (USD {row['costo_estimado']:.0f} por persona) supera el presupuesto "
                 f"(USD {row['presupuesto']:.0f}). Ajusta el plan o genera otra propuesta.")
    plan = db.consultar("SELECT id FROM plan_turistico WHERE propuesta_id = ?", (row["id"],), uno=True)
    return {"id": row["id"], "destino": destino, "noches": row["noches"], "presupuesto": row["presupuesto"],
            "tipo_viajero": row["tipo_viajero"], "intereses": json.loads(row["intereses"]), "origen": row["origen"],
            "viajeros": row["viajeros"], "costo_estimado": row["costo_estimado"], "total_estimado": round(row["costo_estimado"] * row["viajeros"], 2),
            "desglose": {"alojamiento": p["hospedaje_pp"], "actividades": p["actividades_pp"], "vuelo": p["vuelo_pp"]},
            "vuelo_incluido": p["vuelo_incluido"], "excede_presupuesto": bool(row["excede_presupuesto"]), "aviso": aviso, "dias": dias,
            "fuente": row["fuente"], "revisada": bool(row["revisada"]), "etiqueta": "IA · Editable", "creada": row["creada"],
            "plan_id": plan["id"] if plan else None, "anterior_id": row["anterior_id"]}


def _mi_propuesta(pid):
    row = db.consultar("SELECT * FROM propuesta_ia WHERE id = ? AND asesor_id = ?", (pid, session.get("usuario_id")), uno=True)
    if not row:
        raise ErrorHttp("Propuesta no encontrada", 404)
    return row


def _generar(destino, actividades, p):
    """Pide el itinerario a la IA (o al respaldo) y devuelve (itinerario, fuente)."""
    params = {"noches": p["noches"], "presupuesto": p["presupuesto"], "tipo_viajero": p["tipo_viajero"], "intereses": p["intereses"],
              "pais": destino["pais"], "ciudades": destino["ciudades"]}
    principal, respaldo = obtener_servicios()
    try:
        itinerario = principal.generar(params, actividades)
        if principal is not respaldo:
            itinerario = normalizar(itinerario, p["noches"], actividades, destino["ciudades"])
        return itinerario, principal.nombre
    except Exception as e:  # la IA falló: el respaldo evita dejar al asesor sin propuesta
        return respaldo.generar(params, actividades), f"simulado (respaldo: {str(e)[:80]})"


def _parametros(d, base=None):
    """Valida los parámetros del viaje (HU-08, HU-09). `base` aporta los valores previos al regenerar."""
    b = base or {}
    p = {"destino_id": numero(d.get("destino_id", b.get("destino_id")), "El destino", 1, entero=True),
         "noches": numero(d.get("noches", b.get("noches")), "Las noches", 1, 21, entero=True),
         "presupuesto": numero(d.get("presupuesto", b.get("presupuesto")), "El presupuesto", 0, 1000000, obligatorio=False),
         "tipo_viajero": en_lista(d.get("tipo_viajero", b.get("tipo_viajero", "pareja")), "El tipo de viajero", TIPOS_VIAJERO),
         "origen": en_lista(d.get("origen", b.get("origen", db.ORIGEN_BASE)), "La ciudad de salida", db.ORIGENES),
         "viajeros": numero(d.get("viajeros", b.get("viajeros", 1)), "Los viajeros", 1, 10, entero=True)}
    intereses = d.get("intereses", b.get("intereses", []))
    if not isinstance(intereses, list) or any(i not in db.CATEGORIAS for i in intereses):
        raise ValidacionError("Los intereses deben ser de: " + ", ".join(db.CATEGORIAS))
    p["intereses"] = intereses
    return p


def _nueva_propuesta(p, anterior_id=None):
    destino = _obtener_destino(p["destino_id"])
    if not destino["activo"]:
        raise ErrorHttp("El destino está desactivado", 422)
    actividades = db.consultar("SELECT * FROM actividad WHERE destino_id = ? ORDER BY id", (p["destino_id"],))
    if not actividades:
        raise ErrorHttp("El destino no tiene actividades registradas. Regístralas en el catálogo.", 422)
    itinerario, fuente = _generar(destino, actividades, p)
    total = _calcular_precio(p["destino_id"], p["noches"], itinerario, {}, p["origen"], "doble", p["viajeros"])["precio_persona"]
    excede = int(p["presupuesto"] is not None and total > p["presupuesto"])
    pid = db.ejecutar("""INSERT INTO propuesta_ia (destino_id, noches, presupuesto, tipo_viajero, intereses, costo_estimado,
                         excede_presupuesto, itinerario, fuente, asesor_id, origen, viajeros, anterior_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (p["destino_id"], p["noches"], p["presupuesto"], p["tipo_viajero"], json.dumps(p["intereses"]), total, excede,
                       json.dumps(itinerario, ensure_ascii=False), fuente, session["usuario_id"], p["origen"], p["viajeros"], anterior_id))
    return jsonify(_propuesta(db.consultar("SELECT * FROM propuesta_ia WHERE id = ?", (pid,), uno=True))), 201


@app.post("/api/itinerarios/generar")
@requiere("asesor")
def generar_itinerario():
    return _nueva_propuesta(_parametros(request.get_json(silent=True) or {}))


@app.post("/api/propuestas/<int:pid>/regenerar")
@requiere("asesor")
def regenerar(pid):
    previa = _mi_propuesta(pid)
    base = {"destino_id": previa["destino_id"], "noches": previa["noches"], "presupuesto": previa["presupuesto"],
            "tipo_viajero": previa["tipo_viajero"], "intereses": json.loads(previa["intereses"]), "origen": previa["origen"],
            "viajeros": previa["viajeros"]}
    return _nueva_propuesta(_parametros(request.get_json(silent=True) or {}, base), anterior_id=pid)


@app.get("/api/propuestas/<int:pid>")
@requiere("asesor")
def ver_propuesta(pid):
    return jsonify(_propuesta(_mi_propuesta(pid)))


@app.patch("/api/propuestas/<int:pid>/revisada")
@requiere("asesor")
def marcar_revisada(pid):
    _mi_propuesta(pid)
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get("revisada"), bool):
        raise ValidacionError("Indica revisada: true o false")
    db.ejecutar("UPDATE propuesta_ia SET revisada = ? WHERE id = ?", (int(d["revisada"]), pid))
    return jsonify(_propuesta(_mi_propuesta(pid)))


# ---------- HU-15 / 07 / 12 / 16 / 17 planes del asesor ----------
def _salidas(plan_id, futuras=True, contexto=None):
    if contexto is not None:
        filas = contexto["salidas"].get(plan_id, [])
        return [f for f in filas if f["fecha"] >= date.today().isoformat()] if futuras else filas
    filas = db.consultar("""SELECT s.id, s.fecha, s.cupos, s.cupos - COALESCE((SELECT SUM(r.viajeros) FROM solicitud_reserva r
                            WHERE r.salida_id = s.id AND r.estado != 'CANCELADA'), 0) AS disponibles
                            FROM salida_plan s WHERE s.plan_id = ? ORDER BY s.fecha""", (plan_id,))
    return [f for f in filas if f["fecha"] >= date.today().isoformat()] if futuras else filas


def _plan_dict(row):
    destino = db.consultar("SELECT id, pais, continente FROM destino WHERE id = ?", (row["destino_id"],), uno=True)
    raw = json.loads(row["itinerario"])
    dias = _dias_detalle(raw, _actividades_por_id(row["destino_id"]))
    precio = _calcular_precio(row["destino_id"], row["noches"], raw, json.loads(row["alojamientos"]), row["origen"])
    return {"id": row["id"], "nombre": row["nombre"], "descripcion": row["descripcion"], "destino": destino, "noches": row["noches"],
            "ciudades": list(dict.fromkeys(d["ciudad"] for d in dias)), "origen": row["origen"], "precio": precio,
            "precio_persona": precio["precio_persona"], "estado": row["estado"], "dias": dias, "propuesta_id": row["propuesta_id"],
            "creado": row["creado"], "salidas": _salidas(row["id"], futuras=False)}


def _mi_plan(pid):
    row = db.consultar("SELECT * FROM plan_turistico WHERE id = ? AND asesor_id = ?", (pid, session.get("usuario_id")), uno=True)
    if not row:
        raise ErrorHttp("Plan no encontrado", 404)
    return row


def _guardar_terrestre(pid):
    """Mantiene costo_estimado = costo terrestre (hospedaje doble + actividades) de referencia."""
    r = db.consultar("SELECT * FROM plan_turistico WHERE id = ?", (pid,), uno=True)
    p = _calcular_precio(r["destino_id"], r["noches"], json.loads(r["itinerario"]), json.loads(r["alojamientos"]), r["origen"])
    db.ejecutar("UPDATE plan_turistico SET costo_estimado = ? WHERE id = ?", (p["terrestre_doble"], pid))


@app.post("/api/propuestas/<int:pid>/plan")
@requiere("asesor")
def guardar_borrador(pid):
    prop = _mi_propuesta(pid)
    existente = db.consultar("SELECT * FROM plan_turistico WHERE propuesta_id = ?", (pid,), uno=True)
    if existente:
        raise ErrorHttp("Esta propuesta ya se guardó como plan", 409, plan_id=existente["id"])
    destino = _obtener_destino(prop["destino_id"])
    dias = [{**d, "generado_por_ia": True, "revisado": False} for d in json.loads(prop["itinerario"])]
    ciudades = list(dict.fromkeys(d["ciudad"] for d in dias))
    plan_id = db.ejecutar("""INSERT INTO plan_turistico (asesor_id, destino_id, propuesta_id, nombre, descripcion, noches,
                             costo_estimado, itinerario, origen) VALUES (?,?,?,?,?,?,?,?,?)""",
                          (session["usuario_id"], prop["destino_id"], pid, f"{destino['pais']}: {prop['noches']} noches",
                           f"Recorrido de {prop['noches'] + 1} días por {', '.join(ciudades)}.", prop["noches"], 0,
                           json.dumps(dias, ensure_ascii=False), prop["origen"]))
    _guardar_terrestre(plan_id)
    return jsonify(_plan_dict(_mi_plan(plan_id))), 201


@app.get("/api/planes")
@requiere("asesor")
def mis_planes():
    filas = db.consultar("SELECT * FROM plan_turistico WHERE asesor_id = ? ORDER BY id DESC", (session["usuario_id"],))
    out = []
    for f in filas:
        d = _plan_dict(f)
        out.append({"id": f["id"], "nombre": f["nombre"], "pais": d["destino"]["pais"], "noches": f["noches"],
                    "precio_persona": d["precio_persona"], "estado": f["estado"], "creado": f["creado"], "salidas": len(d["salidas"])})
    return jsonify(out)


@app.get("/api/planes/<int:pid>")
@requiere("asesor")
def ver_plan(pid):
    row = _mi_plan(pid)
    plan = _plan_dict(row)
    plan["catalogo"] = db.consultar("SELECT id, nombre, ciudad, categoria, costo FROM actividad WHERE destino_id = ? ORDER BY ciudad, id", (row["destino_id"],))
    plan["opciones_alojamiento"] = db.consultar("SELECT id, nombre, ciudad, categoria, tarifa_noche FROM alojamiento WHERE destino_id = ? ORDER BY ciudad, tarifa_noche", (row["destino_id"],))
    return jsonify(plan)


@app.put("/api/planes/<int:pid>")
@requiere("asesor")
def editar_plan(pid):
    row = _mi_plan(pid)
    if row["estado"] != "BORRADOR":
        raise ErrorHttp("Solo se pueden editar planes en borrador. Despublica el plan primero.", 409)
    d = request.get_json(silent=True) or {}
    nombre = texto(d.get("nombre", row["nombre"]), "El nombre", 100)
    descripcion = texto(d.get("descripcion", row["descripcion"]), "La descripción", 500, obligatorio=False)
    origen = en_lista(d.get("origen", row["origen"]), "La ciudad de salida", db.ORIGENES)
    actuales = json.loads(row["itinerario"])
    acts = _actividades_por_id(row["destino_id"])
    if "dias" in d:
        nuevos = d["dias"]
        if not isinstance(nuevos, list) or len(nuevos) != len(actuales):
            raise ValidacionError("El plan debe conservar sus %d días" % len(actuales))
        usados, resultado = set(), []
        for viejo, nuevo in zip(actuales, nuevos):
            if not isinstance(nuevo, dict) or not isinstance(nuevo.get("actividad_ids"), list):
                raise ValidacionError("Cada día debe incluir actividad_ids")
            ids = nuevo["actividad_ids"]
            for i in ids:
                if not isinstance(i, int) or i not in acts:
                    raise ValidacionError("Hay actividades que no pertenecen al destino")
                if i in usados:
                    raise ValidacionError("Una actividad no puede repetirse en el plan")
                usados.add(i)
            titulo = texto(nuevo.get("titulo", viejo["titulo"]), "El título del día", 120)
            cambio = ids != viejo["actividad_ids"] or titulo != viejo["titulo"]
            resultado.append({**viejo, "titulo": titulo, "actividad_ids": ids, "revisado": viejo.get("revisado", False) or cambio})
        actuales = resultado
    elegidos = json.loads(row["alojamientos"])
    if "alojamientos" in d:
        if not isinstance(d["alojamientos"], dict):
            raise ValidacionError("alojamientos debe ser un objeto ciudad -> alojamiento")
        elegidos = {}
        for ciudad, aid in d["alojamientos"].items():
            a = db.consultar("SELECT * FROM alojamiento WHERE id = ? AND destino_id = ?", (aid, row["destino_id"]), uno=True) if isinstance(aid, int) else None
            if not a or a["ciudad"] != ciudad:
                raise ValidacionError(f"El alojamiento elegido para {ciudad} no es válido")
            elegidos[ciudad] = aid
    db.ejecutar("UPDATE plan_turistico SET nombre = ?, descripcion = ?, itinerario = ?, origen = ?, alojamientos = ? WHERE id = ?",
                (nombre, descripcion, json.dumps(actuales, ensure_ascii=False), origen, json.dumps(elegidos), pid))
    _guardar_terrestre(pid)
    return jsonify(_plan_dict(_mi_plan(pid)))


def _cambiar_estado(pid, desde, hacia, mensaje):
    row = _mi_plan(pid)
    if row["estado"] not in desde:
        raise ErrorHttp(mensaje, 409)
    db.ejecutar("UPDATE plan_turistico SET estado = ? WHERE id = ?", (hacia, pid))
    return jsonify(_plan_dict(_mi_plan(pid)))


@app.post("/api/planes/<int:pid>/publicar")
@requiere("asesor")
def publicar(pid):
    row = _mi_plan(pid)
    if row["estado"] != "BORRADOR":
        raise ErrorHttp("Solo se puede publicar un plan en borrador", 409)
    faltan = []
    if not row["nombre"].strip():
        faltan.append("nombre")
    if not any(d["actividad_ids"] for d in json.loads(row["itinerario"])):
        faltan.append("al menos una actividad en el itinerario")
    if row["costo_estimado"] <= 0:
        faltan.append("precio")
    if faltan:
        raise ErrorHttp("Para publicar falta: " + ", ".join(faltan), 422)
    return _cambiar_estado(pid, ["BORRADOR"], "PUBLICADO", "")


@app.post("/api/planes/<int:pid>/despublicar")
@requiere("asesor")
def despublicar(pid):
    return _cambiar_estado(pid, ["PUBLICADO"], "BORRADOR", "Solo se puede despublicar un plan publicado")


@app.post("/api/planes/<int:pid>/archivar")
@requiere("asesor")
def archivar(pid):
    return _cambiar_estado(pid, ["PUBLICADO"], "ARCHIVADO", "Solo se puede archivar un plan publicado")


@app.post("/api/planes/<int:pid>/salidas")
@requiere("asesor")
def agregar_salida(pid):
    row = _mi_plan(pid)
    if row["estado"] == "ARCHIVADO":
        raise ErrorHttp("Un plan archivado no admite nuevas salidas", 409)
    d = request.get_json(silent=True) or {}
    f = fecha_iso(d.get("fecha"), "La fecha")
    if f < date.today():
        raise ValidacionError("La fecha de salida no puede estar en el pasado")
    cupos = numero(d.get("cupos"), "Los cupos", 1, 200, entero=True)
    if db.consultar("SELECT 1 FROM salida_plan WHERE plan_id = ? AND fecha = ?", (pid, f.isoformat()), uno=True):
        raise ErrorHttp("Ya hay una salida en esa fecha", 409)
    db.ejecutar("INSERT INTO salida_plan (plan_id, fecha, cupos) VALUES (?,?,?)", (pid, f.isoformat(), cupos))
    return jsonify(_salidas(pid, futuras=False)), 201


@app.delete("/api/planes/<int:pid>/salidas/<int:sid>")
@requiere("asesor")
def quitar_salida(pid, sid):
    _mi_plan(pid)
    if not db.consultar("SELECT 1 FROM salida_plan WHERE id = ? AND plan_id = ?", (sid, pid), uno=True):
        raise ErrorHttp("Salida no encontrada", 404)
    if db.consultar("SELECT 1 FROM solicitud_reserva WHERE salida_id = ? AND estado != 'CANCELADA'", (sid,), uno=True):
        raise ErrorHttp("La salida ya tiene solicitudes; no se puede eliminar", 409)
    db.ejecutar("DELETE FROM salida_plan WHERE id = ?", (sid,))
    return jsonify(_salidas(pid, futuras=False))


# ---------- HU-19 / 20 / 21 / 22 / 23 / 24 / 25 / 26 catálogo público del viajero ----------
def _plan_publicado(pid):
    row = db.consultar("""SELECT p.* FROM plan_turistico p JOIN destino d ON d.id = p.destino_id
                          WHERE p.id = ? AND p.estado = 'PUBLICADO' AND d.activo = 1""", (pid,), uno=True)
    if not row:
        raise ErrorHttp("Este plan no está disponible", 404)
    return row


def _publicados(did=None):
    sql = """SELECT p.* FROM plan_turistico p JOIN destino d ON d.id = p.destino_id
             WHERE p.estado = 'PUBLICADO' AND d.activo = 1"""
    return db.consultar(sql + (" AND p.destino_id = ?" if did else "") + " ORDER BY p.id", (did,) if did else ())


def _contexto_planes(rows):
    """Carga de una vez los datos usados para valorar una lista de planes."""
    destino_ids = sorted({row["destino_id"] for row in rows})
    plan_ids = sorted({row["id"] for row in rows})
    contexto = {"destinos": {}, "actividades": {}, "alojamientos": {}, "vuelos": {}, "salidas": {}}
    if not destino_ids:
        return contexto

    placeholders_destinos = ",".join("?" for _ in destino_ids)
    contexto["destinos"] = {
        row["id"]: row for row in db.consultar(
            f"SELECT id, pais, continente, ciudades FROM destino WHERE id IN ({placeholders_destinos})",
            destino_ids,
        )
    }
    for tabla, clave, destino_clave in (
        ("actividad", "actividades", "destino_id"),
        ("alojamiento", "alojamientos", "destino_id"),
        ("vuelo", "vuelos", "destino_id"),
    ):
        filas = db.consultar(
            f"SELECT * FROM {tabla} WHERE {destino_clave} IN ({placeholders_destinos})"
            + (" ORDER BY tarifa_noche, id" if tabla == "alojamiento" else " ORDER BY tarifa, id" if tabla == "vuelo" else ""),
            destino_ids,
        )
        for fila in filas:
            if clave == "actividades":
                contexto[clave].setdefault(fila["destino_id"], {})[fila["id"]] = fila
            else:
                contexto[clave].setdefault(fila["destino_id"], []).append(fila)

    if plan_ids:
        placeholders_planes = ",".join("?" for _ in plan_ids)
        filas = db.consultar(
            f"""SELECT s.id, s.plan_id, s.fecha, s.cupos,
                       s.cupos - COALESCE((
                           SELECT SUM(r.viajeros) FROM solicitud_reserva r
                           WHERE r.salida_id = s.id AND r.estado != 'CANCELADA'
                       ), 0) AS disponibles
                FROM salida_plan s WHERE s.plan_id IN ({placeholders_planes}) ORDER BY s.fecha""",
            plan_ids,
        )
        for fila in filas:
            contexto["salidas"].setdefault(fila["plan_id"], []).append(
                {clave: valor for clave, valor in fila.items() if clave != "plan_id"}
            )
    return contexto


def _origen_arg():
    return en_lista(request.args.get("origen") or db.ORIGEN_BASE, "El origen", db.ORIGENES)


def _resumen(row, origen, viajeros=1, habitacion="doble", contexto=None):
    raw = json.loads(row["itinerario"])
    precio = _calcular_precio(
        row["destino_id"], row["noches"], raw, json.loads(row["alojamientos"]), origen, habitacion, viajeros, contexto
    )
    salidas = _salidas(row["id"], contexto=contexto)
    return {"id": row["id"], "nombre": row["nombre"], "descripcion": row["descripcion"], "noches": row["noches"],
            "destino_id": row["destino_id"], "ciudades": list(dict.fromkeys(d["ciudad"] for d in raw)), "origen": origen,
            "precio_persona": precio["precio_persona"], "total": precio["total"], "vuelo_incluido": precio["vuelo_incluido"],
            "proxima_salida": salidas[0]["fecha"] if salidas else None, "salidas": salidas}


@app.get("/api/catalogo")
def catalogo():
    origen = _origen_arg()
    destinos = {}
    planes = _publicados()
    contexto = _contexto_planes(planes)
    for row in planes:
        d = destinos.setdefault(row["destino_id"], {"n": 0, "min": None})
        precio = _resumen(row, origen, contexto=contexto)["precio_persona"]
        d["n"] += 1
        d["min"] = precio if d["min"] is None else min(d["min"], precio)
    out = []
    for did, info in destinos.items():
        dest = contexto["destinos"][did]
        out.append({"id": did, "pais": dest["pais"], "continente": dest["continente"],
                    "ciudades": json.loads(dest["ciudades"]),
                    "n_planes": info["n"], "precio_desde": info["min"], "origen": origen})
    return jsonify(sorted(out, key=lambda x: (x["continente"], x["pais"])))


@app.get("/api/catalogo/destinos/<int:did>/planes")
def planes_publicados(did):
    destino = _obtener_destino(did)
    if not destino["activo"]:
        raise ErrorHttp("Destino no encontrado", 404)
    origen = _origen_arg()
    planes = _publicados(did)
    contexto = _contexto_planes(planes)
    return jsonify({"destino": {"id": did, "pais": destino["pais"]},
                    "planes": sorted(
                        (_resumen(r, origen, contexto=contexto) for r in planes), key=lambda p: p["precio_persona"]
                    )})


@app.get("/api/catalogo/planes")
def buscar_planes():
    """HU-20: busca por fecha, origen y pasajeros; filtra por precio y noches; ordena."""
    origen = _origen_arg()
    viajeros = arg_numero("viajeros", "Los viajeros", entero=True, minimo=1, maximo=10) or 1
    did = arg_numero("destino_id", "El destino", entero=True, minimo=1)
    pmin, pmax = arg_numero("precio_min", "El precio mínimo"), arg_numero("precio_max", "El precio máximo")
    nmin, nmax = arg_numero("noches_min", "Las noches mínimas", entero=True), arg_numero("noches_max", "Las noches máximas", entero=True)
    desde = fecha_iso(request.args["salida_desde"], "La fecha desde").isoformat() if request.args.get("salida_desde") else None
    hasta = fecha_iso(request.args["salida_hasta"], "La fecha hasta").isoformat() if request.args.get("salida_hasta") else None
    orden = request.args.get("orden", "precio")
    if orden not in ORDENES:
        raise ValidacionError("El orden debe ser uno de: " + ", ".join(ORDENES))
    planes = _publicados(did)
    contexto = _contexto_planes(planes)
    res = []
    for row in planes:
        r = _resumen(row, origen, viajeros, contexto=contexto)
        r["pais"] = contexto["destinos"][row["destino_id"]]["pais"]
        if (pmin is not None and r["precio_persona"] < pmin) or (pmax is not None and r["precio_persona"] > pmax):
            continue
        if (nmin is not None and r["noches"] < nmin) or (nmax is not None and r["noches"] > nmax):
            continue
        salidas = r["salidas"]
        if desde or hasta:
            salidas = [s for s in salidas if (not desde or s["fecha"] >= desde) and (not hasta or s["fecha"] <= hasta)]
            if not salidas:
                continue
        if r["salidas"]:  # con salidas definidas, debe haber cupos para todos los viajeros
            salidas = [s for s in salidas if s["disponibles"] >= viajeros]
            if not salidas:
                continue
        r["salidas"] = salidas
        r["proxima_salida"] = salidas[0]["fecha"] if salidas else None
        res.append(r)
    clave, inverso = ORDENES[orden]
    res.sort(key=lambda r: r[clave], reverse=inverso)
    return jsonify(res)


@app.post("/api/catalogo/recomendar")
def recomendar_catalogo():
    d = request.get_json(silent=True) or {}
    consulta = texto(d.get("consulta"), "Describe el viaje que buscas", 500)
    origen = en_lista(d.get("origen", db.ORIGEN_BASE), "El origen", db.ORIGENES)
    viajeros = numero(d.get("viajeros", 1), "Los viajeros", 1, 10, entero=True)
    filas = _publicados()
    contexto = _contexto_planes(filas)
    planes = []
    for row in filas:
        plan = _resumen(row, origen, viajeros, contexto=contexto)
        plan["pais"] = contexto["destinos"][row["destino_id"]]["pais"]
        planes.append(plan)
    if not planes:
        return jsonify({"recomendaciones": [], "fuente": "catalogo"})

    principal, respaldo = obtener_servicios()
    try:
        sugerencias = normalizar_recomendaciones(principal.recomendar(consulta, planes), planes)
        fuente = principal.nombre
    except ErrorIA:
        sugerencias = normalizar_recomendaciones(respaldo.recomendar(consulta, planes), planes)
        fuente = "simulado (respaldo)" if principal is not respaldo else respaldo.nombre

    por_id = {p["id"]: p for p in planes}
    recomendaciones = [{**por_id[s["plan_id"]], "motivo": s["motivo"]} for s in sugerencias]
    return jsonify({"recomendaciones": recomendaciones, "fuente": fuente})


def _whatsapp(nombre, precio):
    numero_wa = re.sub(r"\D", "", os.environ.get("RDM_WHATSAPP", "573124767207"))
    msg = (f"Hola, me interesa el plan «{nombre}» (salida desde {precio['origen']}, habitación {precio['habitacion']}, "
           f"{precio['viajeros']} {'viajero' if precio['viajeros'] == 1 else 'viajeros'}). Precio estimado: USD {precio['total']:.0f}.")
    return f"https://wa.me/{numero_wa}?text={quote(msg)}"


@app.get("/api/catalogo/planes/<int:pid>")
def ficha(pid):
    row = _plan_publicado(pid)
    habitacion = en_lista(request.args.get("habitacion", "doble"), "La habitación", list(costos.FACTORES_HABITACION))
    viajeros = arg_numero("viajeros", "Los viajeros", entero=True, minimo=1, maximo=10) or 1
    origen = en_lista(request.args.get("origen") or row["origen"], "El origen", db.ORIGENES)
    plan = _plan_dict(row)
    for d in plan["dias"]:  # al viajero no se le muestran marcas internas del asesor
        d.pop("generado_por_ia", None)
        d.pop("revisado", None)
    precio = _calcular_precio(row["destino_id"], row["noches"], json.loads(row["itinerario"]), json.loads(row["alojamientos"]),
                              origen, habitacion, viajeros)
    plan.update({"precio": precio, "precio_persona": precio["precio_persona"], "salidas": _salidas(pid),
                 "whatsapp_url": _whatsapp(row["nombre"], precio),
                 "origenes_con_vuelo": [v["origen"] for v in db.consultar("SELECT DISTINCT origen FROM vuelo WHERE destino_id = ?", (row["destino_id"],))]})
    for k in ("propuesta_id", "origen"):
        plan.pop(k, None)
    return jsonify(plan)


@app.post("/api/catalogo/planes/<int:pid>/solicitudes")
def solicitar_reserva(pid):
    row = _plan_publicado(pid)
    d = request.get_json(silent=True) or {}
    nombre = texto(d.get("nombre"), "El nombre", 100)
    correo = texto(d.get("correo"), "El correo", 120)
    if not CORREO.match(correo):
        raise ValidacionError("El correo no es válido")
    telefono = texto(d.get("telefono"), "El teléfono", 20)
    if not re.fullmatch(r"\+?[\d\s-]{7,20}", telefono) or len(re.sub(r"\D", "", telefono)) < 7:
        raise ValidacionError("El teléfono no es válido")
    viajeros = numero(d.get("viajeros"), "Los viajeros", 1, 10, entero=True)
    habitacion = en_lista(d.get("habitacion", "doble"), "La habitación", list(costos.FACTORES_HABITACION))
    origen = en_lista(d.get("origen") or row["origen"], "El origen", db.ORIGENES)
    salidas = _salidas(pid)
    salida = None
    if salidas:
        sid = numero(d.get("salida_id"), "La fecha de salida", 1, entero=True)
        salida = next((s for s in salidas if s["id"] == sid), None)
        if not salida:
            raise ValidacionError("La fecha de salida no es válida")
        if salida["disponibles"] < viajeros:
            raise ErrorHttp(f"No hay cupos suficientes en esa salida (quedan {salida['disponibles']})", 409)
    precio = _calcular_precio(row["destino_id"], row["noches"], json.loads(row["itinerario"]), json.loads(row["alojamientos"]),
                              origen, habitacion, viajeros)
    sid_db = salida["id"] if salida else None
    rid = db.ejecutar("""INSERT INTO solicitud_reserva (plan_id, nombre, correo, telefono, viajeros, salida_id, habitacion, origen)
                         VALUES (?,?,?,?,?,?,?,?)""", (pid, nombre, correo, telefono, viajeros, sid_db, habitacion, origen))
    return jsonify({"id": rid, "plan": {"id": pid, "nombre": row["nombre"]}, "viajeros": viajeros, "habitacion": habitacion, "origen": origen,
                    "salida": salida["fecha"] if salida else None, "total_estimado": precio["total"],
                    "whatsapp_url": _whatsapp(row["nombre"], precio),
                    "mensaje": "¡Recibimos tu solicitud! Un asesor te contactará pronto."}), 201


# ---------- HU-18 solicitudes para el asesor ----------
@app.get("/api/solicitudes")
@requiere("asesor")
def mis_solicitudes():
    filas = db.consultar("""SELECT s.*, p.nombre AS plan_nombre, p.destino_id, p.noches, p.itinerario, p.alojamientos, p.origen AS origen_plan,
                            sp.fecha AS salida FROM solicitud_reserva s JOIN plan_turistico p ON p.id = s.plan_id
                            LEFT JOIN salida_plan sp ON sp.id = s.salida_id WHERE p.asesor_id = ? ORDER BY s.id DESC""", (session["usuario_id"],))
    out = []
    for f in filas:
        total = _calcular_precio(f["destino_id"], f["noches"], json.loads(f["itinerario"]), json.loads(f["alojamientos"]),
                                 f["origen"] or f["origen_plan"], f["habitacion"], f["viajeros"])["total"]
        out.append({"id": f["id"], "nombre": f["nombre"], "correo": f["correo"], "telefono": f["telefono"], "viajeros": f["viajeros"],
                    "plan_id": f["plan_id"], "plan": f["plan_nombre"], "habitacion": f["habitacion"], "origen": f["origen"] or f["origen_plan"],
                    "salida": f["salida"], "total_estimado": total, "estado": f["estado"], "creada": f["creada"]})
    return jsonify(out)


# ---------- datos de ejemplo y arranque ----------
def sembrar_planes():
    """Planes de ejemplo para que el catálogo público no arranque vacío."""
    if db.consultar("SELECT 1 FROM plan_turistico LIMIT 1", uno=True):
        return
    asesor = db.consultar("SELECT id FROM usuario WHERE rol = 'asesor' ORDER BY id LIMIT 1", uno=True)
    hoy = date.today()
    for pais, noches, estado, intereses, nombre, cupos in [
            ("Italia", 7, "PUBLICADO", ["cultura", "historia"], "Italia Clásica: Roma, Florencia y Venecia", 12),
            ("Colombia", 4, "PUBLICADO", ["historia", "playa"], "Cartagena y Medellín esencial", 10),
            ("Francia", 3, "BORRADOR", ["cultura"], "París en 3 noches", 0)]:
        destino = db.consultar("SELECT * FROM destino WHERE pais = ?", (pais,), uno=True)
        if not destino or not asesor:
            continue
        destino = _destino(destino)
        acts = db.consultar("SELECT * FROM actividad WHERE destino_id = ? ORDER BY id", (destino["id"],))
        params = {"noches": noches, "intereses": intereses, "ciudades": destino["ciudades"]}
        dias = [{**d, "generado_por_ia": True, "revisado": estado == "PUBLICADO"} for d in SimuladoServicio().generar(params, acts)]
        ciudades = list(dict.fromkeys(d["ciudad"] for d in dias))
        pid = db.ejecutar("""INSERT INTO plan_turistico (asesor_id, destino_id, nombre, descripcion, noches, costo_estimado, estado, itinerario)
                             VALUES (?,?,?,?,?,?,?,?)""",
                          (asesor["id"], destino["id"], nombre, f"Recorrido de {noches + 1} días por {', '.join(ciudades)}.", noches, 0,
                           estado, json.dumps(dias, ensure_ascii=False)))
        _guardar_terrestre(pid)
        for dias_adelante in ((30, 60) if cupos else ()):
            db.ejecutar("INSERT INTO salida_plan (plan_id, fecha, cupos) VALUES (?,?,?)", (pid, (hoy + timedelta(days=dias_adelante)).isoformat(), cupos))


def preparar():
    db.iniciar()
    sembrar_planes()


@app.get("/")
def inicio():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    preparar()
    principal, _ = obtener_servicios()
    print(f"IA activa: {principal.nombre}  ·  abre http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
