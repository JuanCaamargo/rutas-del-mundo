# Rutas del Mundo

Sistema web con **front + back + base de datos + IA** que implementa **todas las historias del backlog**: el MVP
(sprints 1 a 3) y el incremento 2.

| Entrega | Historias | Qué incluye |
|---|---|---|
| Sprint 1 | HU-02, 03, 08, 10, 11, 13 | Catálogo (destinos y actividades), generador de itinerarios con IA, costo estimado y marca «IA · Editable». |
| Sprint 2 | HU-01, 07, 12, 15, 16 | Inicio de sesión por rol, panel de planes, edición de actividades por día, guardar borrador y publicar. |
| Sprint 3 | HU-18, 19, 21, 22, 25 | Catálogo público, ficha con itinerario día a día, solicitud de reserva con confirmación y bandeja del asesor. |
| Incremento 2 | HU-04, 05, 06, 09, 14, 17, 20, 23, 24, 26 | Alojamientos, vuelos, editar o desactivar destinos, ciudad de salida y viajeros, regenerar propuesta, fechas y cupos, búsqueda y filtros, total por habitación, vuelos con horarios y equipaje, WhatsApp. |

## Cómo correrlo

```bash
python -m venv .venv
.venv\Scripts\activate          # en Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python backend/app.py
```

Abre **http://localhost:5000**. La base de datos (`backend/rutas.db`, SQLite) se crea sola con usuarios, destinos, actividades,
alojamientos, vuelos y **3 planes de ejemplo** (con fechas de salida). Si ya tenías una base de una versión anterior, se
actualiza sola al arrancar.

Pruebas: `python -m unittest discover -s tests -v` (37 pruebas).

## Desplegar en Render con Supabase

El proyecto conserva SQLite para desarrollo local y usa PostgreSQL cuando existe `DATABASE_URL`.
`render.yaml` configura el servicio web, el comando de inicio y las variables que deben cargarse en Render.

1. Crea un proyecto en Supabase y copia la URL PostgreSQL de **Connect**. Para Render usa el *Session pooler* si la conexión directa no está disponible en IPv4; mantén el SSL incluido en la URL.
2. Sube este repositorio a GitHub y en Render crea un **Blueprint** seleccionando ese repositorio y aceptando `render.yaml`.
3. En las variables del servicio completa `DATABASE_URL` con la URL de Supabase, `RDM_ADMIN_PASSWORD` y `RDM_ADVISOR_PASSWORD` con contraseñas propias. Render genera `RDM_SECRET`; `GEMINI_API_KEY` es opcional.
4. Render instala las dependencias, inicializa el esquema PostgreSQL y carga los datos de demostración al primer inicio. Las cuentas de demostración usan las contraseñas configuradas en esas variables.

No publiques la URL de Supabase ni la guardes en el repositorio. La inicialización no copia automáticamente el contenido de `backend/rutas.db`; la base PostgreSQL nueva recibe el esquema y los datos de demostración.

**Cuentas de demostración locales** (los botones de asesor y administrador rellenan el correo; en Render escribe la contraseña configurada como variable de entorno):

| Rol | Correo | Contraseña |
|---|---|---|
| Administrador | admin@rutasdelmundo.co | admin123 |
| Asesor | asesor@rutasdelmundo.co | asesor123 |
| Viajero | no necesita cuenta: «Explorar como viajero» | |

## Recorrido para la demo

1. **Administrador → Catálogo:** elige un destino y usa las pestañas **Actividades, Alojamientos, Vuelos y Editar destino** (HU-02 a 06).
2. **Asesor → Generador con IA:** destino, noches, **ciudad de salida y viajeros**, presupuesto e intereses → propuesta con costo por
   persona, total y vuelo; **Regenerar** crea alternativas que se pueden comparar (HU-08, 09, 10, 11, 13, 14).
3. **Asesor → Guardar como borrador:** en el editor cambia el **alojamiento** de cada ciudad, quita o agrega actividades (el precio se
   recalcula solo), agrega **fechas y cupos** y **publica** (HU-04, 12, 15, 16, 17). *Mis planes* muestra el estado (HU-07).
4. **Viajero → Asistente IA:** desde una pestaña independiente del menú, describe el viaje que imagina para recibir hasta tres planes publicados del catálogo; Gemini explica por qué coinciden y, si no está disponible, se buscan coincidencias por texto. En **Destinos** también puede buscar por **ciudad de salida, fechas, viajeros, precio y noches** y ordenar (HU-19, 20). En la ficha ve el
   itinerario, elige **habitación y viajeros**, ve el **vuelo con horarios y equipaje**, escoge una **fecha**, envía la **solicitud**
   o escribe por **WhatsApp** (HU-21 a 26).
5. **Asesor → Solicitudes:** ve la solicitud con fecha, habitación, origen y total estimado (HU-18). Los cupos de esa salida bajan.

## Cómo se calcula el precio (lo calcula el código, no la IA)

`precio por persona = hospedaje + actividades + vuelo` · `total = precio por persona × viajeros`

- **Hospedaje:** una noche por cada día menos el último, a la tarifa del alojamiento de la ciudad de ese día (por defecto el más
  económico; el asesor puede elegir otro). Las tarifas registradas son por persona en habitación **doble**.
- **Habitación:** sencilla ×1,35 y triple ×0,90 sobre el hospedaje (supuestos del proyecto, en `costos.py`).
- **Vuelo:** tarifa del vuelo registrado para la ciudad de salida elegida. Si no hay vuelo para ese origen, el precio no lo incluye y
  la pantalla lo avisa.
- Si una ciudad no tiene alojamientos registrados se usa `RDM_TARIFA_NOCHE` (90 USD por defecto).

## Activar la IA real (Gemini)

1. Crea una llave en Google AI Studio (con tu cuenta de Google).
2. Copia `.env.example` como `.env` y escribe la llave en `GEMINI_API_KEY=`.
3. Reinicia el servidor. La barra lateral cambia a «IA: Gemini».

Sin llave se usa el **generador simulado** (reglas, sin IA real). Si Gemini falla (sin conexión, límite de uso o respuesta inválida)
se usa el simulado como **respaldo** y se indica en «Fuente». Verifica en la página oficial el nombre del modelo (`GEMINI_MODEL`) y
que el plan gratuito siga vigente. Para WhatsApp define `RDM_WHATSAPP` (número con indicativo, sin +) en `.env`.

## Arquitectura

| Capa | Archivos | Qué hace |
|---|---|---|
| Front | `frontend/` | Una sola página (HTML, CSS y JS sin framework) con menú según el rol. |
| Back | `backend/app.py` | API REST con Flask, validaciones y permisos por rol; sirve también el front. |
| BD | `backend/db.py` | SQLite: `usuario`, `destino`, `actividad`, `alojamiento`, `vuelo`, `propuesta_ia`, `plan_turistico`, `salida_plan`, `solicitud_reserva`. |
| IA | `backend/ia_service.py` | `ServicioIA` (interfaz), `GeminiServicio`, `SimuladoServicio` y validación de la salida. |
| Costos | `backend/costos.py` | Hospedaje por noche y factores de habitación. |

Relación con los diagramas UML: `PropuestaIA` es lo que genera la IA; al guardarla como borrador se convierte en `PlanTuristico`
(BORRADOR → PUBLICADO → ARCHIVADO); `SolicitudReserva` nace RECIBIDA; `Alojamiento` y `Vuelo` alimentan el precio.

## Endpoints principales

| Ruta | Rol | Historia |
|---|---|---|
| `POST /api/auth/login`, `/explorar`, `/salir` · `GET /api/auth/yo` | todos | HU-01 |
| `GET/POST /api/destinos` · `PUT /api/destinos/{id}` · `POST /api/destinos/{id}/desactivar` y `/activar` | administrador | HU-02, 06 |
| `GET/POST /api/destinos/{id}/actividades` · `/alojamientos` · `/vuelos` | administrador (GET también asesor) | HU-03, 04, 05 |
| `POST /api/itinerarios/generar` · `POST /api/propuestas/{id}/regenerar` | asesor | HU-08, 09, 10, 11, 14 |
| `GET /api/propuestas/{id}` · `PATCH /api/propuestas/{id}/revisada` | asesor | HU-13 |
| `POST /api/propuestas/{id}/plan` · `GET /api/planes` · `GET/PUT /api/planes/{id}` | asesor | HU-15, 07, 12 |
| `POST /api/planes/{id}/publicar` · `/despublicar` · `/archivar` | asesor | HU-16 |
| `POST /api/planes/{id}/salidas` · `DELETE /api/planes/{id}/salidas/{sid}` | asesor | HU-17 |
| `GET /api/solicitudes` | asesor | HU-18 |
| `GET /api/catalogo` · `GET /api/catalogo/destinos/{id}/planes` | público | HU-19 |
| `GET /api/catalogo/planes?origen&salida_desde&salida_hasta&viajeros&precio_min&precio_max&noches_min&noches_max&orden` | público | HU-20 |
| `POST /api/catalogo/recomendar` | público | Recomendaciones de viaje con IA |
| `GET /api/catalogo/planes/{id}?origen&habitacion&viajeros` | público | HU-21, 22, 23, 24, 26 |
| `POST /api/catalogo/planes/{id}/solicitudes` | público | HU-25 |

## Reglas de negocio implementadas

- Solo se publica un plan en borrador con nombre, al menos una actividad y precio mayor que cero. Un plan publicado no se edita: se
  despublica primero. Un plan archivado ya no aparece en el catálogo.
- Cada actividad pertenece al destino del plan y no se repite dentro de un plan. Al editar un día queda marcado como «Revisado».
- Las salidas no pueden estar en el pasado ni repetirse en un plan. Una solicitud descuenta cupos y se rechaza si no alcanzan.
  Una salida con solicitudes no se puede eliminar.
- Un destino no puede quitar una ciudad que ya tiene actividades o alojamientos. Desactivar un destino lo oculta del generador y del
  catálogo público, pero no borra sus planes.
- La búsqueda solo muestra planes con cupos para todos los viajeros y salidas dentro del rango de fechas pedido.
- El viajero solo ve planes publicados y no ve las marcas internas del asesor. La solicitud valida nombre, correo, teléfono y de 1 a 10 viajeros.
- Las recomendaciones del asistente se limitan a planes publicados; los precios y la disponibilidad vienen del catálogo y no los inventa la IA.
- La salida de la IA se valida (número de días, actividades del catálogo, ciudades); si no cumple, se usa el respaldo.

## Supuestos y límites

- Los datos del catálogo, las tarifas de alojamientos y vuelos, los horarios y los factores de habitación son **de ejemplo**.
- El **precio por persona es igual al costo calculado**, sin margen de la agencia.
- **Alcance de reservas:** el sistema recibe solicitudes y descuenta cupos; no hay pagos ni confirmación definitiva de la reserva
  (el estado de la solicitud queda en RECIBIDA).
- **Seguridad básica:** contraseñas con hash y sesión firmada. Antes de publicarlo en un servidor real hay que cambiar las cuentas de
  demostración, definir `RDM_SECRET` en `.env` y agregar HTTPS y límite de intentos de inicio de sesión.
- **Tecnología:** Flask.
