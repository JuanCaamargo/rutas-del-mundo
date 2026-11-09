import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "backend"))
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["RDM_DB"] = _tmp.name
os.environ.pop("GEMINI_API_KEY", None)
os.environ["RDM_TARIFA_NOCHE"] = "90"

import app as rdm  # noqa: E402
import db  # noqa: E402
import ia_service  # noqa: E402

ADMIN = {"correo": "admin@rutasdelmundo.co", "clave": "admin123"}
ASESOR = {"correo": "asesor@rutasdelmundo.co", "clave": "asesor123"}


class Resp:
    def __init__(self, status, datos):
        self.status_code, self._d = status, datos

    def json(self):
        return self._d


def gemini_ok(dias):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps({"dias": dias})}]}}]})


def cliente(cuenta=None):
    c = rdm.app.test_client()
    if cuenta == "viajero":
        c.post("/api/auth/explorar")
    elif cuenta:
        assert c.post("/api/auth/login", json=cuenta).status_code == 200
    return c


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rdm.preparar()
        cls.admin, cls.asesor, cls.viajero, cls.anonimo = cliente(ADMIN), cliente(ASESOR), cliente("viajero"), cliente()
        cls.italia = next(d for d in cls.admin.get("/api/destinos").get_json() if d["pais"] == "Italia")

    def setUp(self):
        os.environ.pop("GEMINI_API_KEY", None)

    def generar(self, cli=None, **extra):
        cuerpo = {"destino_id": self.italia["id"], "noches": 7, "presupuesto": 3000, "tipo_viajero": "pareja", "intereses": ["cultura"]}
        cuerpo.update(extra)
        return (cli or self.asesor).post("/api/itinerarios/generar", json=cuerpo)

    def plan_borrador(self, **extra):
        pid = self.generar(**extra).get_json()["id"]
        return self.asesor.post(f"/api/propuestas/{pid}/plan").get_json()


class TestAdaptadorPostgres(unittest.TestCase):
    def test_esquema_postgres_no_conserva_sintaxis_sqlite(self):
        self.assertNotIn("AUTOINCREMENT", db.ESQUEMA_POSTGRES)
        self.assertNotIn("COLLATE NOCASE", db.ESQUEMA_POSTGRES)
        self.assertNotIn("datetime('now')", db.ESQUEMA_POSTGRES)
        self.assertIn("SERIAL PRIMARY KEY", db.ESQUEMA_POSTGRES)
        self.assertIn("DEFAULT (CURRENT_TIMESTAMP::text)", db.ESQUEMA_POSTGRES)

    def test_consultas_postgres_conservan_busquedas_insensibles_a_mayusculas(self):
        self.assertEqual(
            db._postgres_sql("SELECT id FROM usuario WHERE correo = ?"),
            "SELECT id FROM usuario WHERE lower(correo) = lower(%s)",
        )
        self.assertEqual(
            db._postgres_sql("UPDATE destino SET pais = ? WHERE id = ?"),
            "UPDATE destino SET pais = %s WHERE id = %s",
        )

    def test_esquema_postgres_no_se_separa_en_punto_y_coma_de_comentario(self):
        sentencias = db._sentencias_esquema_postgres()
        self.assertEqual(len(sentencias), 9)
        self.assertTrue(all(sentencia.startswith("CREATE TABLE IF NOT EXISTS") for sentencia in sentencias))
        self.assertIn("costo_estimado REAL NOT NULL", sentencias[4])


class TestSesion(Base):  # HU-01
    def test_login_correcto_e_incorrecto(self):
        c = rdm.app.test_client()
        self.assertEqual(c.post("/api/auth/login", json={"correo": ASESOR["correo"], "clave": "mala"}).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"correo": "nadie@x.co", "clave": "x"}).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={}).status_code, 400)
        r = c.post("/api/auth/login", json=ASESOR)
        self.assertEqual(r.get_json()["rol"], "asesor")
        self.assertEqual(c.get("/api/auth/yo").get_json()["rol"], "asesor")
        c.post("/api/auth/salir")
        self.assertIsNone(c.get("/api/auth/yo").get_json()["rol"])

    def test_permisos_por_rol(self):
        self.assertEqual(self.anonimo.get("/api/destinos").status_code, 401)
        self.assertEqual(self.viajero.get("/api/destinos").status_code, 403)
        self.assertEqual(self.asesor.post("/api/destinos", json={}).status_code, 403)
        self.assertEqual(self.admin.post("/api/itinerarios/generar", json={}).status_code, 403)
        self.assertEqual(self.viajero.get("/api/planes").status_code, 403)
        self.assertEqual(self.admin.get("/api/solicitudes").status_code, 403)
        self.assertEqual(self.anonimo.get("/api/catalogo").status_code, 200)  # el catálogo es público


class TestCatalogoAdmin(Base):  # HU-02, HU-03
    def test_crear_destino(self):
        r = self.admin.post("/api/destinos", json={"pais": "Japón", "continente": "Asia", "ciudades": ["Tokio", "Kioto", "tokio"]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["ciudades"], ["Tokio", "Kioto"])
        for cuerpo in ({}, {"pais": "X", "continente": "Marte", "ciudades": ["A"]}, {"pais": "X", "continente": "Asia", "ciudades": []}):
            self.assertEqual(self.admin.post("/api/destinos", json=cuerpo).status_code, 400)
        self.assertEqual(self.admin.post("/api/destinos", json={"pais": "italia", "continente": "Europa", "ciudades": ["Roma"]}).status_code, 409)

    def test_actividades(self):
        base = f"/api/destinos/{self.italia['id']}/actividades"
        self.assertEqual(self.admin.post(base, json={"nombre": "Catacumbas", "ciudad": "Roma", "categoria": "historia", "costo": 20}).status_code, 201)
        for malo in ({"nombre": "X", "ciudad": "Madrid", "categoria": "historia"}, {"nombre": "X", "ciudad": "Roma", "categoria": "otra"},
                     {"nombre": "X", "ciudad": "Roma", "categoria": "historia", "costo": -5}):
            self.assertEqual(self.admin.post(base, json=malo).status_code, 400)
        self.assertEqual(self.admin.get("/api/destinos/9999/actividades").status_code, 404)


class TestGenerador(Base):  # HU-08, 10, 11, 13
    def test_generar_simulado(self):
        p = self.generar().get_json()
        self.assertEqual(len(p["dias"]), 8)
        self.assertEqual((p["fuente"], p["etiqueta"]), ("simulado", "IA · Editable"))
        self.assertTrue(all(d["generado_por_ia"] for d in p["dias"]))
        d = p["desglose"]
        self.assertEqual(p["costo_estimado"], round(d["alojamiento"] + d["actividades"] + d["vuelo"], 2))
        self.assertTrue(p["vuelo_incluido"] and d["vuelo"] == 790)  # Medellín -> Italia
        ids = [a["id"] for d in p["dias"] for a in d["actividades"]]
        self.assertEqual(len(ids), len(set(ids)))
        for d in p["dias"]:
            self.assertTrue(all(a["ciudad"] == d["ciudad"] for a in d["actividades"]))

    def test_noches_variadas(self):
        for n in (1, 2, 3, 14):
            self.assertEqual(len(self.generar(noches=n).get_json()["dias"]), n + 1)

    def test_validaciones(self):
        for extra, codigo in (({"noches": 0}, 400), ({"noches": 30}, 400), ({"noches": 2.5}, 400), ({"tipo_viajero": "robot"}, 400),
                              ({"intereses": ["magia"]}, 400), ({"destino_id": 9999}, 404)):
            self.assertEqual(self.generar(**extra).status_code, codigo, extra)
        did = self.admin.post("/api/destinos", json={"pais": "Perú", "continente": "América", "ciudades": ["Cusco"]}).get_json()["id"]
        self.assertEqual(self.generar(destino_id=did).status_code, 422)

    def test_presupuesto_y_revisada(self):
        p = self.generar(presupuesto=100).get_json()
        self.assertTrue(p["excede_presupuesto"])
        self.assertIn("supera el presupuesto", p["aviso"])
        r = self.asesor.patch(f"/api/propuestas/{p['id']}/revisada", json={"revisada": True})
        self.assertTrue(r.get_json()["revisada"])
        self.assertEqual(self.asesor.patch(f"/api/propuestas/{p['id']}/revisada", json={"revisada": "si"}).status_code, 400)

    def test_gemini_valido_e_invalido(self):
        os.environ["GEMINI_API_KEY"] = "llave-falsa"
        ids = [a["id"] for a in self.admin.get(f"/api/destinos/{self.italia['id']}/actividades").get_json()][:3]
        dias = [{"numero": 1, "titulo": "Llegada", "ciudad": "Roma", "actividad_ids": []},
                {"numero": 2, "titulo": "Roma", "ciudad": "Roma", "actividad_ids": ids[:2] + [99999]},
                {"numero": 3, "titulo": "Más", "ciudad": "Atlantis", "actividad_ids": ids[2:]}]
        with mock.patch.object(ia_service.requests, "post", return_value=gemini_ok(dias)):
            p = self.generar(noches=2).get_json()
        self.assertEqual(p["fuente"], "gemini")
        self.assertEqual(sum(len(d["actividades"]) for d in p["dias"]), 3)
        for resp in (Resp(500, {}), Resp(200, {"candidates": []}), Resp(200, {"candidates": [{"content": {"parts": [{"text": "no json"}]}}]}),
                     gemini_ok([{"numero": 1, "titulo": "un día", "ciudad": "Roma", "actividad_ids": []}])):
            with mock.patch.object(ia_service.requests, "post", return_value=resp):
                r = self.generar(noches=2)
            self.assertTrue(r.get_json()["fuente"].startswith("simulado (respaldo"))
        with mock.patch.object(ia_service.requests, "post", side_effect=ia_service.requests.ConnectionError()):
            self.assertIn("sin conexión", self.generar().get_json()["fuente"])

    def test_propuesta_ajena(self):
        pid = self.generar().get_json()["id"]
        self.assertEqual(self.admin.get(f"/api/propuestas/{pid}").status_code, 403)


class TestPlanes(Base):  # HU-07, 12, 15, 16
    def test_guardar_borrador_y_panel(self):
        pid = self.generar().get_json()["id"]
        r = self.asesor.post(f"/api/propuestas/{pid}/plan")
        self.assertEqual(r.status_code, 201)
        plan = r.get_json()
        self.assertEqual(plan["estado"], "BORRADOR")
        self.assertEqual(self.asesor.post(f"/api/propuestas/{pid}/plan").status_code, 409)  # no duplicar
        self.assertIn(plan["id"], [x["id"] for x in self.asesor.get("/api/planes").get_json()])
        self.assertTrue(self.asesor.get(f"/api/planes/{plan['id']}").get_json()["catalogo"])

    def test_editar_actividades_actualiza_costo(self):
        plan = self.plan_borrador()
        det = self.asesor.get(f"/api/planes/{plan['id']}").get_json()
        dias = [{"numero": d["numero"], "titulo": d["titulo"], "actividad_ids": [a["id"] for a in d["actividades"]]} for d in det["dias"]]
        con = next(d for d in dias if d["actividad_ids"])
        quitada = con["actividad_ids"].pop()
        r = self.asesor.put(f"/api/planes/{plan['id']}", json={"nombre": "Mi plan", "dias": dias})
        self.assertEqual(r.status_code, 200)
        nuevo = r.get_json()
        costo_quitada = next(a["costo"] for d in det["dias"] for a in d["actividades"] if a["id"] == quitada)
        self.assertEqual(nuevo["precio_persona"], round(det["precio_persona"] - costo_quitada, 2))
        self.assertTrue(next(d for d in nuevo["dias"] if d["numero"] == con["numero"])["revisado"])
        self.assertEqual(nuevo["nombre"], "Mi plan")

    def test_editar_validaciones(self):
        plan = self.plan_borrador()
        pid = plan["id"]
        self.assertEqual(self.asesor.put(f"/api/planes/{pid}", json={"dias": []}).status_code, 400)
        base = [{"numero": d["numero"], "titulo": d["titulo"], "actividad_ids": []} for d in plan["dias"]]
        malo = [dict(d) for d in base]
        malo[1]["actividad_ids"] = [99999]
        self.assertEqual(self.asesor.put(f"/api/planes/{pid}", json={"dias": malo}).status_code, 400)
        rep = [dict(d) for d in base]
        a = self.asesor.get(f"/api/planes/{pid}").get_json()["catalogo"][0]["id"]
        rep[1]["actividad_ids"], rep[2]["actividad_ids"] = [a], [a]
        self.assertEqual(self.asesor.put(f"/api/planes/{pid}", json={"dias": rep}).status_code, 400)
        self.assertEqual(self.asesor.put(f"/api/planes/{pid}", json={"nombre": ""}).status_code, 400)

    def test_publicar_reglas_y_estados(self):
        plan = self.plan_borrador()
        pid = plan["id"]
        vacio = [{"numero": d["numero"], "titulo": d["titulo"], "actividad_ids": []} for d in plan["dias"]]
        self.asesor.put(f"/api/planes/{pid}", json={"dias": vacio})
        self.assertEqual(self.asesor.post(f"/api/planes/{pid}/publicar").status_code, 422)  # sin actividades
        plan = self.plan_borrador()
        pid = plan["id"]
        self.assertEqual(self.asesor.post(f"/api/planes/{pid}/publicar").get_json()["estado"], "PUBLICADO")
        self.assertEqual(self.asesor.post(f"/api/planes/{pid}/publicar").status_code, 409)
        self.assertEqual(self.asesor.put(f"/api/planes/{pid}", json={"nombre": "x"}).status_code, 409)  # publicado no se edita
        self.assertEqual(self.asesor.post(f"/api/planes/{pid}/despublicar").get_json()["estado"], "BORRADOR")
        self.asesor.post(f"/api/planes/{pid}/publicar")
        self.assertEqual(self.asesor.post(f"/api/planes/{pid}/archivar").get_json()["estado"], "ARCHIVADO")
        self.assertEqual(self.viajero.get(f"/api/catalogo/planes/{pid}").status_code, 404)
        self.assertEqual(self.asesor.post("/api/planes/9999/publicar").status_code, 404)


class TestViajero(Base):  # HU-19, 21, 22, 25 y HU-18
    def publicado(self):
        pid = self.plan_borrador()["id"]
        self.asesor.post(f"/api/planes/{pid}/publicar")
        return pid

    def test_catalogo_ficha_y_borrador_oculto(self):
        pid = self.publicado()
        borrador = self.plan_borrador()["id"]
        cat = self.viajero.get("/api/catalogo").get_json()
        italia = next(d for d in cat if d["pais"] == "Italia")
        self.assertGreater(italia["n_planes"], 0)
        self.assertGreater(italia["precio_desde"], 0)
        ids = [p["id"] for p in self.viajero.get(f"/api/catalogo/destinos/{italia['id']}/planes").get_json()["planes"]]
        self.assertIn(pid, ids)
        self.assertNotIn(borrador, ids)
        f = self.viajero.get(f"/api/catalogo/planes/{pid}").get_json()
        self.assertTrue(f["dias"] and f["precio_persona"] > 0 and f["ciudades"] and f["descripcion"])
        self.assertNotIn("generado_por_ia", f["dias"][0])
        self.assertEqual(self.viajero.get(f"/api/catalogo/planes/{borrador}").status_code, 404)
        self.assertEqual(self.viajero.get("/api/catalogo/destinos/9999/planes").status_code, 404)

    def test_solicitud_y_vista_del_asesor(self):
        pid = self.publicado()
        datos = {"nombre": "Sofía Rojas", "correo": "sofia@correo.co", "telefono": "300 123 4567", "viajeros": 2}
        r = self.viajero.post(f"/api/catalogo/planes/{pid}/solicitudes", json=datos)
        self.assertEqual(r.status_code, 201)
        conf = r.get_json()
        self.assertIn("Recibimos tu solicitud", conf["mensaje"])
        precio = self.viajero.get(f"/api/catalogo/planes/{pid}").get_json()["precio_persona"]
        self.assertEqual(conf["total_estimado"], round(precio * 2, 2))
        lista = self.asesor.get("/api/solicitudes").get_json()
        self.assertEqual(lista[0]["id"], conf["id"])  # la más reciente primero
        self.assertEqual((lista[0]["nombre"], lista[0]["plan_id"]), ("Sofía Rojas", pid))

    def test_solicitud_invalida(self):
        pid = self.publicado()
        ok = {"nombre": "Ana", "correo": "ana@correo.co", "telefono": "3001234567", "viajeros": 1}
        url = f"/api/catalogo/planes/{pid}/solicitudes"
        for malo in ({**ok, "nombre": ""}, {**ok, "correo": "sin-arroba"}, {**ok, "telefono": "abc"}, {**ok, "telefono": "12"},
                     {**ok, "viajeros": 0}, {**ok, "viajeros": 11}, {**ok, "viajeros": "2"}, {}):
            self.assertEqual(self.viajero.post(url, json=malo).status_code, 400, malo)
        borrador = self.plan_borrador()["id"]
        self.assertEqual(self.viajero.post(f"/api/catalogo/planes/{borrador}/solicitudes", json=ok).status_code, 404)

    def test_demo_sembrada(self):
        nombres = [p["nombre"] for d in self.viajero.get("/api/catalogo").get_json()
                   for p in self.viajero.get(f"/api/catalogo/destinos/{d['id']}/planes").get_json()["planes"]]
        self.assertIn("Italia Clásica: Roma, Florencia y Venecia", nombres)


def futuro(dias=30):
    return (date.today() + timedelta(days=dias)).isoformat()


class TestIncremento2Admin(Base):  # HU-04, HU-05, HU-06
    def test_alojamientos(self):
        base = f"/api/destinos/{self.italia['id']}/alojamientos"
        self.assertTrue(self.asesor.get(base).get_json())
        ok = self.admin.post(base, json={"nombre": "Hotel Nuevo", "ciudad": "Roma", "categoria": 5, "tarifa_noche": 200})
        self.assertEqual(ok.status_code, 201)
        for malo in ({"nombre": "X", "ciudad": "Madrid", "categoria": 3, "tarifa_noche": 50}, {"nombre": "X", "ciudad": "Roma", "categoria": 9, "tarifa_noche": 50},
                     {"nombre": "X", "ciudad": "Roma", "categoria": 3, "tarifa_noche": 0}, {"ciudad": "Roma"}):
            self.assertEqual(self.admin.post(base, json=malo).status_code, 400)
        self.assertEqual(self.asesor.post(base, json={}).status_code, 403)

    def test_vuelos(self):
        did = self.admin.post("/api/destinos", json={"pais": "Chile", "continente": "América", "ciudades": ["Santiago"]}).get_json()["id"]
        base = f"/api/destinos/{did}/vuelos"
        ok = self.admin.post(base, json={"origen": "Bogotá (BOG)", "aerolinea": "LATAM", "tarifa": 500, "escalas": 1})
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.get_json()["equipaje"], "Maleta de 23 kg incluida")
        for malo in ({"origen": "Marte", "aerolinea": "X", "tarifa": 5}, {"origen": "Bogotá (BOG)", "aerolinea": "", "tarifa": 5},
                     {"origen": "Bogotá (BOG)", "aerolinea": "X", "tarifa": -1}, {"origen": "Bogotá (BOG)", "aerolinea": "X", "tarifa": 5, "escalas": 7}):
            self.assertEqual(self.admin.post(base, json=malo).status_code, 400)

    def test_alojamiento_cambia_el_costo(self):
        did = self.admin.post("/api/destinos", json={"pais": "Ecuador", "continente": "América", "ciudades": ["Quito"]}).get_json()["id"]
        self.admin.post(f"/api/destinos/{did}/actividades", json={"nombre": "Centro histórico", "ciudad": "Quito", "categoria": "historia", "costo": 10})
        sin = self.generar(destino_id=did, noches=2, intereses=["historia"]).get_json()
        self.assertEqual(sin["desglose"]["alojamiento"], 180)  # sin alojamientos registrados: tarifa base 90 x 2 noches
        self.admin.post(f"/api/destinos/{did}/alojamientos", json={"nombre": "Hotel Quito", "ciudad": "Quito", "categoria": 3, "tarifa_noche": 50})
        con = self.generar(destino_id=did, noches=2, intereses=["historia"]).get_json()
        self.assertEqual(con["desglose"]["alojamiento"], 100)

    def test_editar_y_desactivar_destino(self):
        did = self.admin.post("/api/destinos", json={"pais": "Brasil", "continente": "América", "ciudades": ["Río", "Salvador"]}).get_json()["id"]
        self.admin.post(f"/api/destinos/{did}/actividades", json={"nombre": "Cristo Redentor", "ciudad": "Río", "categoria": "cultura", "costo": 20})
        r = self.admin.put(f"/api/destinos/{did}", json={"pais": "Brasil", "ciudades": ["Río", "Salvador", "Recife"]})
        self.assertEqual(r.get_json()["ciudades"], ["Río", "Salvador", "Recife"])
        self.assertEqual(self.admin.put(f"/api/destinos/{did}", json={"ciudades": ["Salvador"]}).status_code, 409)  # Río tiene actividades
        self.assertEqual(self.admin.put(f"/api/destinos/{did}", json={"pais": "Italia"}).status_code, 409)
        self.assertEqual(self.admin.put(f"/api/destinos/{did}", json={"continente": "Marte"}).status_code, 400)
        self.assertEqual(self.admin.put("/api/destinos/9999", json={}).status_code, 404)
        self.assertFalse(self.admin.post(f"/api/destinos/{did}/desactivar").get_json()["activo"])
        self.assertEqual(self.generar(destino_id=did).status_code, 422)
        self.assertTrue(self.admin.post(f"/api/destinos/{did}/activar").get_json()["activo"])

    def test_desactivar_no_rompe_planes(self):
        did = self.admin.post("/api/destinos", json={"pais": "Perú2", "continente": "América", "ciudades": ["Cusco"]}).get_json()["id"]
        self.admin.post(f"/api/destinos/{did}/actividades", json={"nombre": "Machu Picchu", "ciudad": "Cusco", "categoria": "historia", "costo": 50})
        pid = self.plan_borrador(destino_id=did, noches=2)["id"]
        self.asesor.post(f"/api/planes/{pid}/publicar")
        self.assertEqual(self.viajero.get(f"/api/catalogo/planes/{pid}").status_code, 200)
        self.admin.post(f"/api/destinos/{did}/desactivar")
        self.assertEqual(self.viajero.get(f"/api/catalogo/planes/{pid}").status_code, 404)  # oculto, no borrado
        self.assertEqual(self.asesor.get(f"/api/planes/{pid}").status_code, 200)


class TestIncremento2Asesor(Base):  # HU-09, HU-14, HU-17 y alojamiento elegido
    def test_salida_y_viajeros_en_la_propuesta(self):
        a = self.generar(origen="Medellín (MDE)", viajeros=1).get_json()
        b = self.generar(origen="Bogotá (BOG)", viajeros=3).get_json()
        self.assertEqual((a["desglose"]["vuelo"], b["desglose"]["vuelo"]), (790, 750))
        self.assertEqual(b["total_estimado"], round(b["costo_estimado"] * 3, 2))
        for malo in ({"origen": "Marte"}, {"viajeros": 0}, {"viajeros": 11}):
            self.assertEqual(self.generar(**malo).status_code, 400)

    def test_origen_sin_vuelo(self):
        p = self.generar(origen="Barranquilla (BAQ)").get_json()  # no hay vuelo registrado
        self.assertFalse(p["vuelo_incluido"])
        self.assertEqual(p["desglose"]["vuelo"], 0)

    def test_regenerar(self):
        p = self.generar(noches=5, intereses=["cultura"]).get_json()
        r = self.asesor.post(f"/api/propuestas/{p['id']}/regenerar", json={"intereses": ["gastronomia"], "noches": 4})
        self.assertEqual(r.status_code, 201)
        n = r.get_json()
        self.assertEqual((n["anterior_id"], n["noches"], n["intereses"]), (p["id"], 4, ["gastronomia"]))
        self.assertEqual(n["origen"], p["origen"])  # lo no cambiado se conserva
        self.assertNotEqual(n["id"], p["id"])
        self.assertEqual(self.asesor.get(f"/api/propuestas/{p['id']}").status_code, 200)  # la anterior se conserva
        self.assertEqual(self.asesor.post(f"/api/propuestas/{p['id']}/regenerar", json={"noches": 0}).status_code, 400)
        self.assertEqual(self.asesor.post("/api/propuestas/9999/regenerar", json={}).status_code, 404)

    def test_elegir_alojamiento(self):
        plan = self.plan_borrador(noches=3)
        det = self.asesor.get(f"/api/planes/{plan['id']}").get_json()
        roma = [o for o in det["opciones_alojamiento"] if o["ciudad"] == "Roma"]
        caro = max(roma, key=lambda o: o["tarifa_noche"])
        r = self.asesor.put(f"/api/planes/{plan['id']}", json={"alojamientos": {"Roma": caro["id"]}})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.get_json()["precio"]["hospedaje_pp"], det["precio"]["hospedaje_pp"])
        self.assertEqual(r.get_json()["precio"]["alojamientos"]["Roma"]["id"], caro["id"])
        self.assertEqual(self.asesor.put(f"/api/planes/{plan['id']}", json={"alojamientos": {"Roma": 99999}}).status_code, 400)
        self.assertEqual(self.asesor.put(f"/api/planes/{plan['id']}", json={"origen": "Marte"}).status_code, 400)

    def test_salidas_y_cupos(self):
        pid = self.plan_borrador()["id"]
        url = f"/api/planes/{pid}/salidas"
        self.assertEqual(self.asesor.post(url, json={"fecha": futuro(), "cupos": 4}).status_code, 201)
        self.assertEqual(self.asesor.post(url, json={"fecha": futuro(), "cupos": 4}).status_code, 409)  # misma fecha
        for malo in ({"fecha": "2020-01-01", "cupos": 4}, {"fecha": "mañana", "cupos": 4}, {"fecha": futuro(40), "cupos": 0}, {"fecha": futuro(40), "cupos": 500}):
            self.assertEqual(self.asesor.post(url, json=malo).status_code, 400)
        self.asesor.post(f"/api/planes/{pid}/publicar")
        sid = self.asesor.get(f"/api/planes/{pid}").get_json()["salidas"][0]["id"]
        ok = {"nombre": "Ana", "correo": "ana@correo.co", "telefono": "3001234567", "viajeros": 3, "salida_id": sid}
        sol = f"/api/catalogo/planes/{pid}/solicitudes"
        self.assertEqual(self.viajero.post(sol, json={**ok, "salida_id": None}).status_code, 400)   # exige elegir fecha
        self.assertEqual(self.viajero.post(sol, json={**ok, "salida_id": 99999}).status_code, 400)
        self.assertEqual(self.viajero.post(sol, json=ok).status_code, 201)
        self.assertEqual(self.viajero.post(sol, json={**ok, "viajeros": 2}).status_code, 409)       # solo queda 1 cupo
        ficha = self.viajero.get(f"/api/catalogo/planes/{pid}").get_json()
        self.assertEqual(ficha["salidas"][0]["disponibles"], 1)
        self.assertEqual(self.asesor.delete(f"{url}/{sid}").status_code, 409)                        # tiene solicitudes
        self.assertEqual(self.asesor.get("/api/solicitudes").get_json()[0]["salida"], futuro())
        otra = self.asesor.post(url, json={"fecha": futuro(50), "cupos": 2}).get_json()[-1]["id"]
        self.assertEqual(self.asesor.delete(f"{url}/{otra}").status_code, 200)
        self.assertEqual(self.asesor.delete(f"{url}/99999").status_code, 404)


class TestIncremento2Viajero(Base):  # HU-20, HU-23, HU-24, HU-26
    def publicado(self, **extra):
        pid = self.plan_borrador(**extra)["id"]
        self.asesor.post(f"/api/planes/{pid}/publicar")
        return pid

    def test_total_por_habitacion_y_viajeros(self):
        pid = self.publicado()
        doble = self.viajero.get(f"/api/catalogo/planes/{pid}?habitacion=doble&viajeros=2").get_json()["precio"]
        sencilla = self.viajero.get(f"/api/catalogo/planes/{pid}?habitacion=sencilla&viajeros=2").get_json()["precio"]
        triple = self.viajero.get(f"/api/catalogo/planes/{pid}?habitacion=triple&viajeros=2").get_json()["precio"]
        self.assertGreater(sencilla["precio_persona"], doble["precio_persona"])
        self.assertLess(triple["precio_persona"], doble["precio_persona"])
        self.assertEqual(doble["total"], round(doble["precio_persona"] * 2, 2))
        self.assertEqual(sencilla["hospedaje_pp"], round(doble["hospedaje_pp"] * 1.35, 2))
        self.assertEqual(sencilla["actividades_pp"], doble["actividades_pp"])
        for q in ("habitacion=suite", "viajeros=0", "viajeros=11", "viajeros=abc", "origen=Marte"):
            self.assertEqual(self.viajero.get(f"/api/catalogo/planes/{pid}?{q}").status_code, 400, q)

    def test_vuelos_en_la_ficha(self):
        pid = self.publicado()
        f = self.viajero.get(f"/api/catalogo/planes/{pid}?origen=Bogotá (BOG)").get_json()
        v = f["precio"]["vuelo"]
        self.assertEqual((v["aerolinea"], v["tarifa"], v["equipaje"]), ("Iberia", 750, "Maleta de 23 kg incluida"))
        self.assertTrue(v["hora_ida"] and v["hora_regreso"])
        self.assertIn("Bogotá (BOG)", f["origenes_con_vuelo"])
        sin = self.viajero.get(f"/api/catalogo/planes/{pid}?origen=Barranquilla (BAQ)").get_json()["precio"]
        self.assertFalse(sin["vuelo_incluido"])
        self.assertEqual(sin["vuelo"], None)

    def test_whatsapp(self):
        pid = self.publicado()
        f = self.viajero.get(f"/api/catalogo/planes/{pid}?viajeros=2&habitacion=sencilla").get_json()
        self.assertTrue(f["whatsapp_url"].startswith("https://wa.me/573124767207?text="))
        self.assertIn("sencilla", f["whatsapp_url"])
        r = self.viajero.post(f"/api/catalogo/planes/{pid}/solicitudes", json={"nombre": "Ana", "correo": "a@b.co", "telefono": "3001234567",
                                                                              "viajeros": 2, "habitacion": "sencilla"})
        self.assertEqual(r.get_json()["total_estimado"], f["precio"]["total"])
        self.assertIn("wa.me", r.get_json()["whatsapp_url"])

    def test_buscar_y_filtrar(self):
        pid = self.publicado(noches=9)
        self.asesor.post(f"/api/planes/{pid}/salidas", json={"fecha": futuro(120), "cupos": 2})
        get = lambda q="": self.viajero.get("/api/catalogo/planes" + q)
        todos = get().get_json()
        self.assertGreaterEqual(len(todos), 3)
        self.assertEqual(next(p for p in todos if p["id"] == pid)["pais"], "Italia")
        precios = [p["precio_persona"] for p in todos]
        self.assertEqual(precios, sorted(precios))                                   # orden por precio
        self.assertEqual([p["precio_persona"] for p in get("?orden=precio_desc").get_json()], sorted(precios, reverse=True))
        self.assertTrue(all(p["noches"] <= 4 for p in get("?noches_max=4").get_json()))
        self.assertIn(pid, [p["id"] for p in get("?noches_min=9").get_json()])
        self.assertTrue(all(p["precio_persona"] <= precios[0] for p in get(f"?precio_max={precios[0]}").get_json()))
        en_fecha = get(f"?salida_desde={futuro(100)}&salida_hasta={futuro(130)}").get_json()
        self.assertEqual([p["id"] for p in en_fecha], [pid])
        self.assertEqual(get(f"?salida_desde={futuro(200)}").get_json(), [])
        self.assertIn(pid, [p["id"] for p in get("?viajeros=2").get_json()])
        self.assertNotIn(pid, [p["id"] for p in get("?viajeros=3").get_json()])    # solo hay 2 cupos
        bog = get("?origen=Bogotá (BOG)").get_json()
        med = get().get_json()
        self.assertNotEqual({p["id"]: p["precio_persona"] for p in bog}, {p["id"]: p["precio_persona"] for p in med})
        for q in ("?orden=raro", "?precio_max=abc", "?salida_desde=hoy", "?origen=Marte", "?viajeros=99"):
            self.assertEqual(get(q).status_code, 400, q)

    def test_catalogo_por_origen(self):
        med = {d["pais"]: d["precio_desde"] for d in self.viajero.get("/api/catalogo").get_json()}
        bog = {d["pais"]: d["precio_desde"] for d in self.viajero.get("/api/catalogo?origen=Bogotá (BOG)").get_json()}
        self.assertNotEqual(med["Italia"], bog["Italia"])

    def test_recomendar_planes_con_respaldo(self):
        r = self.anonimo.post("/api/catalogo/recomendar", json={
            "consulta": "Quiero visitar Cartagena y disfrutar la playa",
            "origen": "Medellín (MDE)", "viajeros": 2
        })
        self.assertEqual(r.status_code, 200)
        datos = r.get_json()
        self.assertEqual(datos["fuente"], "simulado")
        self.assertTrue(datos["recomendaciones"])
        self.assertEqual(datos["recomendaciones"][0]["pais"], "Colombia")
        self.assertTrue(datos["recomendaciones"][0]["motivo"])
        for cuerpo in ({}, {"consulta": " "}, {"consulta": "x" * 501},
                       {"consulta": "Italia", "origen": "Marte"},
                       {"consulta": "Italia", "viajeros": 11}):
            self.assertEqual(self.anonimo.post("/api/catalogo/recomendar", json=cuerpo).status_code, 400)

    def test_recomendar_planes_con_gemini_y_validar_ids(self):
        os.environ["GEMINI_API_KEY"] = "llave-falsa"
        planes = self.anonimo.get("/api/catalogo/planes").get_json()
        seleccionado = planes[0]
        respuesta = Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps({
            "recomendaciones": [{"plan_id": seleccionado["id"], "motivo": "Coincide con tu destino."}]
        })}]}}]})
        with mock.patch.object(ia_service.requests, "post", return_value=respuesta):
            r = self.anonimo.post("/api/catalogo/recomendar", json={"consulta": "Quiero viajar"})
        self.assertEqual(r.get_json()["fuente"], "gemini")
        self.assertEqual(r.get_json()["recomendaciones"][0]["id"], seleccionado["id"])

        invalida = Resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps({
            "recomendaciones": [{"plan_id": 99999, "motivo": "Plan inventado."}]
        })}]}}]})
        with mock.patch.object(ia_service.requests, "post", return_value=invalida):
            r = self.anonimo.post("/api/catalogo/recomendar", json={"consulta": "Cartagena"})
        self.assertEqual(r.get_json()["fuente"], "simulado (respaldo)")
        self.assertNotIn(99999, [p["id"] for p in r.get_json()["recomendaciones"]])


if __name__ == "__main__":
    unittest.main()
