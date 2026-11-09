/* Front de Rutas del Mundo: las 26 historias del backlog. Habla con la API de /api. */
const CATEGORIAS = ["cultura", "gastronomia", "historia", "playa", "naturaleza", "aventura"];
const TIPOS = ["solo", "pareja", "familia", "amigos"];
const CONTINENTES = ["América", "Europa", "Asia", "África", "Oceanía"];
const MENUS = { administrador: [["cat", "Catálogo"]], asesor: [["planes", "Mis planes"], ["gen", "Generador con IA"], ["sol", "Solicitudes"]], viajero: [["pub", "Destinos"], ["asistente", "Asistente IA"]] };
const COLORES = [["#27507F", "#F2A65A"], ["#0E6E78", "#F5C86B"], ["#2A2F6B", "#F4A9A0"], ["#D8502B", "#F8CE72"], ["#1D86C8", "#9AD9EA"], ["#2F7FC8", "#C9E8F7"]];
const FOTOS_PAIS = {
  argentina: { src: "/images/argentina-buenos-aires.jpg", alt: "Vista de Buenos Aires, Argentina" },
  colombia: { src: "/images/colombia-medellin.jpg", alt: "Arte urbano en Medellín, Colombia" },
  francia: { src: "/images/francia-paris.jpg", alt: "Vista aérea de París, Francia" },
  italia: { src: "/images/italia-roma.jpg", alt: "Coliseo de Roma, Italia" },
  japon: { src: "/images/japon-tokio.jpg", alt: "Vista de Tokio, Japón" },
};
const normalizarDestino = (s) => (typeof s === "string" ? s : "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const FOTOS_CIUDAD = {
  "buenos aires": FOTOS_PAIS.argentina, cartagena: FOTOS_PAIS.colombia, medellin: FOTOS_PAIS.colombia,
  paris: FOTOS_PAIS.francia, roma: FOTOS_PAIS.italia, florencia: FOTOS_PAIS.italia, venecia: FOTOS_PAIS.italia
};
const $ = (id) => document.getElementById(id);
const estado = { usuario: null, origenes: [], habitaciones: [], destinos: [], destinoSel: null, tipo: "pareja", intereses: new Set(["cultura"]),
  propuesta: null, alternativas: [], plan: null, opcionesAloj: [], catalogoPlan: [], planPublico: null, destinoPublico: null, resultados: null, paisesPorDestino: {} };

async function api(ruta, opciones = {}) {
  const r = await fetch("/api" + ruta, { headers: { "Content-Type": "application/json" }, ...opciones });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(datos.error || "Error inesperado (" + r.status + ")"); e.datos = datos; e.status = r.status; throw e; }
  return datos;
}
const post = (ruta, cuerpo = {}) => api(ruta, { method: "POST", body: JSON.stringify(cuerpo) });
const put = (ruta, cuerpo) => api(ruta, { method: "PUT", body: JSON.stringify(cuerpo) });
function el(tag, props = {}, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) k === "class" ? (n.className = v) : n.setAttribute(k, v);
  for (const h of hijos) if (h !== "" && h != null) n.append(h);
  return n;
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const usd = (n) => "USD " + Math.round(n).toLocaleString("es-CO");
const fecha = (s) => new Date(s.replace(" ", "T") + "Z").toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
const dia = (s) => new Date(s + "T12:00:00").toLocaleDateString("es-CO", { dateStyle: "long" });
const hoy = () => new Date().toISOString().slice(0, 10);
const opciones = (lista, formato = (x) => x) => lista.map((x) => el("option", { value: x }, formato(x)));
function mensaje(id, texto, ok = false) { const m = $(id); m.textContent = texto; m.className = "msg" + (ok ? " ok" : ""); }
function filas(cuerpo, lista) { cuerpo.replaceChildren(...lista); }
function boton(texto, clase, accion) { const b = el("button", { class: "btn " + clase, type: "button" }, texto); b.addEventListener("click", accion); return b; }
const estrellas = (n) => "★".repeat(n);
const vueloTxt = (v) => v ? `${v.aerolinea} · ${v.escalas === 0 ? "directo" : v.escalas + (v.escalas === 1 ? " escala" : " escalas")}` : "";
function arteDestino(pais, ciudades, colores, rotulo, mantenerDegradado = false) {
  const [a, b] = colores;
  const arte = el("div", { class: "arte", style: `background:linear-gradient(90deg,${a},${b})` });
  const foto = FOTOS_PAIS[normalizarDestino(pais)] || ciudades.map((c) => FOTOS_CIUDAD[normalizarDestino(c)]).find(Boolean);
  if (!foto && !mantenerDegradado) return null;
  if (foto) arte.append(el("img", { class: "arte-foto", src: foto.src, alt: foto.alt, loading: "lazy", decoding: "async" }));
  if (rotulo) arte.append(el("span", { class: "arte-titulo" }, rotulo));
  return arte;
}

/* ---------- sesión y navegación (HU-01) ---------- */
const VISTAS = ["planes", "gen", "plan", "sol", "cat", "pub", "asistente", "ficha"];
function mostrar(vista) {
  VISTAS.forEach((v) => { $("vista-" + v).hidden = v !== vista; });
  const base = { plan: "planes", ficha: "pub" }[vista] || vista;
  document.querySelectorAll("#nav .nav").forEach((b) => b.classList.toggle("activo", b.dataset.vista === base));
  const carga = { planes: cargarPlanes, gen: cargarDestinos, sol: cargarSolicitudes, cat: cargarDestinos, pub: cargarPublico }[vista];
  if (carga) carga().catch((e) => console.error(e));
}
function entrar(u) {
  estado.usuario = u;
  $("vista-login").hidden = true; $("app").hidden = false;
  const roles = { administrador: "Administrador", asesor: "Asesor Turístico", viajero: "Viajero" };
  $("usuario-nombre").textContent = u.nombre + " · " + (roles[u.rol] || cap(u.rol));
  $("nav").replaceChildren(...MENUS[u.rol].map(([v, t]) => { const b = el("button", { class: "nav", "data-vista": v }, t); b.addEventListener("click", () => mostrar(v)); return b; }));
  mostrar(MENUS[u.rol][0][0]);
}
$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { entrar(await post("/auth/login", { correo: $("l-correo").value, clave: $("l-clave").value })); } catch (err) { mensaje("l-msg", err.message); }
});
function prepararIngresoDemo(correo) {
  $("l-correo").value = correo;
  $("l-clave").value = "";
  $("l-clave").focus();
}
$("demo-asesor").addEventListener("click", () => prepararIngresoDemo("asesor@rutasdelmundo.co"));
$("demo-admin").addEventListener("click", () => prepararIngresoDemo("admin@rutasdelmundo.co"));
$("demo-viajero").addEventListener("click", async () => entrar(await post("/auth/explorar")));
$("salir").addEventListener("click", async () => { await post("/auth/salir"); location.reload(); });

/* ---------- chips ---------- */
function chips(contenedor, lista, esActivo, alAlternar) {
  contenedor.replaceChildren(...lista.map((o) => {
    const b = el("button", { type: "button", class: "chip", "aria-pressed": String(esActivo(o)) }, cap(o));
    b.addEventListener("click", () => { alAlternar(o); chips(contenedor, lista, esActivo, alAlternar); });
    return b;
  }));
}
function pintarChips() {
  chips($("g-tipo"), TIPOS, (o) => estado.tipo === o, (o) => { estado.tipo = o; });
  chips($("g-intereses"), CATEGORIAS, (o) => estado.intereses.has(o), (o) => { estado.intereses.has(o) ? estado.intereses.delete(o) : estado.intereses.add(o); });
}

/* ---------- catálogo del administrador (HU-02, 03, 04, 05, 06) ---------- */
async function cargarDestinos() {
  estado.destinos = await api("/destinos");
  const sel = $("g-destino"), previo = sel.value;
  sel.replaceChildren(...estado.destinos.filter((d) => d.activo).map((d) => el("option", { value: d.id }, `${d.pais} (${d.n_actividades} actividades)`)));
  if (previo) sel.value = previo;
  $("lista-destinos").replaceChildren(...estado.destinos.map((d) => {
    const li = el("li", { class: d.id === estado.destinoSel ? "sel" : "" },
      el("span", {}, d.pais + (d.activo ? "" : " (desactivado)"), el("br"), el("small", {}, d.continente + " · " + d.ciudades.join(", "))), el("small", {}, d.n_actividades + " act."));
    li.addEventListener("click", () => seleccionarDestino(d.id));
    return li;
  }));
}
function pestana(nombre) {
  ["act", "aloj", "vue", "ed"].forEach((t) => { $("tab-" + t).hidden = t !== nombre; });
  document.querySelectorAll(".pest").forEach((b) => b.classList.toggle("activa", b.dataset.tab === nombre));
}
document.querySelectorAll(".pest").forEach((b) => b.addEventListener("click", () => pestana(b.dataset.tab)));
async function seleccionarDestino(id, tab) {
  estado.destinoSel = id;
  const [acts, alojs, vuelos] = await Promise.all([api(`/destinos/${id}/actividades`), api(`/destinos/${id}/alojamientos`), api(`/destinos/${id}/vuelos`)]);
  await cargarDestinos();
  const d = estado.destinos.find((x) => x.id === id);
  $("act-titulo").textContent = d.pais; $("cat-vacio").hidden = true; $("pestanas").hidden = false;
  filas(document.querySelector("#tabla-act tbody"), acts.map((a) => el("tr", {}, el("td", {}, a.nombre), el("td", {}, a.ciudad), el("td", {}, cap(a.categoria)), el("td", {}, String(a.costo)))));
  filas(document.querySelector("#tabla-aloj tbody"), alojs.map((a) => el("tr", {}, el("td", {}, a.nombre), el("td", {}, a.ciudad), el("td", {}, estrellas(a.categoria)), el("td", {}, String(a.tarifa_noche)))));
  filas(document.querySelector("#tabla-vue tbody"), vuelos.map((v) => el("tr", {}, el("td", {}, v.origen), el("td", {}, v.aerolinea), el("td", {}, String(v.escalas)),
    el("td", {}, `${v.hora_ida || "—"} / ${v.hora_regreso || "—"}`), el("td", {}, String(v.tarifa)))));
  $("a-ciudad").replaceChildren(...opciones(d.ciudades)); $("h-ciudad").replaceChildren(...opciones(d.ciudades));
  $("e-pais").value = d.pais; $("e-continente").value = d.continente; $("e-ciudades").value = d.ciudades.join(", ");
  $("btn-activo").textContent = d.activo ? "Desactivar destino" : "Activar destino";
  pestana(tab || document.querySelector(".pest.activa")?.dataset.tab || "act");
}
const lista = (v) => v.split(",").map((c) => c.trim()).filter(Boolean);
$("form-destino").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const nuevo = await post("/destinos", { pais: $("d-pais").value, continente: $("d-continente").value, ciudades: lista($("d-ciudades").value) });
    e.target.reset(); mensaje("d-msg", "Destino agregado.", true); await seleccionarDestino(nuevo.id, "act");
  } catch (err) { mensaje("d-msg", err.message); }
});
function formularioDestino(id, msg, ruta, tab, cuerpo, limpiar) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await post(`/destinos/${estado.destinoSel}/${ruta}`, cuerpo()); limpiar(); mensaje(msg, "Guardado.", true); await seleccionarDestino(estado.destinoSel, tab); }
    catch (err) { mensaje(msg, err.message); }
  });
}
formularioDestino("form-act", "a-msg", "actividades", "act", () => ({ nombre: $("a-nombre").value, ciudad: $("a-ciudad").value, categoria: $("a-categoria").value,
  costo: Number($("a-costo").value), descripcion: $("a-desc").value }), () => { $("a-nombre").value = ""; $("a-desc").value = ""; });
formularioDestino("form-aloj", "h-msg", "alojamientos", "aloj", () => ({ nombre: $("h-nombre").value, ciudad: $("h-ciudad").value,
  categoria: Number($("h-estrellas").value), tarifa_noche: Number($("h-tarifa").value) }), () => { $("h-nombre").value = ""; });
formularioDestino("form-vue", "v-msg", "vuelos", "vue", () => ({ origen: $("v-origen").value, aerolinea: $("v-aerolinea").value, tarifa: Number($("v-tarifa").value),
  escalas: Number($("v-escalas").value), hora_ida: $("v-ida").value, hora_regreso: $("v-regreso").value, equipaje: $("v-equipaje").value }), () => { $("v-aerolinea").value = ""; $("v-tarifa").value = ""; });
$("form-edit").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await put(`/destinos/${estado.destinoSel}`, { pais: $("e-pais").value, continente: $("e-continente").value, ciudades: lista($("e-ciudades").value) });
    mensaje("e-msg", "Destino actualizado.", true); await seleccionarDestino(estado.destinoSel, "ed"); } catch (err) { mensaje("e-msg", err.message); }
});
$("btn-activo").addEventListener("click", async () => {
  const d = estado.destinos.find((x) => x.id === estado.destinoSel);
  try { await post(`/destinos/${d.id}/${d.activo ? "desactivar" : "activar"}`); mensaje("e-msg", "Estado del destino actualizado.", true); await seleccionarDestino(d.id, "ed"); }
  catch (err) { mensaje("e-msg", err.message); }
});

/* ---------- generador con IA (HU-08, 09, 10, 11, 13, 14) ---------- */
function parametrosForm() {
  const pres = $("g-presupuesto").value;
  return { noches: Number($("g-noches").value), presupuesto: pres === "" ? null : Number(pres), tipo_viajero: estado.tipo, intereses: [...estado.intereses],
    origen: $("g-origen").value, viajeros: Number($("g-viajeros").value) };
}
async function generar(ruta, cuerpo) {
  const boton = $("g-enviar"); boton.disabled = true; mensaje("g-msg", "");
  try { estado.propuesta = await post(ruta, cuerpo); estado.alternativas.push(estado.propuesta); pintarPropuesta(); }
  catch (err) { mensaje("g-msg", err.message); } finally { boton.disabled = false; }
}
$("form-gen").addEventListener("submit", (e) => {
  e.preventDefault(); estado.alternativas = [];
  generar("/itinerarios/generar", { destino_id: Number($("g-destino").value), ...parametrosForm() });
});
function pintarPropuesta() {
  const p = estado.propuesta;
  const alts = estado.alternativas.length > 1 ? el("div", { class: "alts" }, el("span", { class: "nota" }, "Alternativas:"), ...estado.alternativas.map((a, i) => {
    const b = el("button", { type: "button", class: "chip", "aria-pressed": String(a.id === p.id) }, "Propuesta " + (i + 1));
    b.addEventListener("click", () => { estado.propuesta = a; pintarPropuesta(); });
    return b;
  })) : "";
  const cab = el("div", { class: "res-cab" },
    el("div", { class: "tit" }, el("h2", {}, "Propuesta de la IA"), el("span", { class: "etq" }, "✦ IA"), el("span", { class: "etq ed" }, "Editable"), p.revisada ? el("span", { class: "etq rev" }, "Revisada") : ""),
    el("div", { class: "costo" }, el("small", {}, "Costo estimado por persona"), el("strong", {}, usd(p.costo_estimado)),
      el("small", {}, `Total para ${p.viajeros} ${p.viajeros === 1 ? "viajero" : "viajeros"}: ${usd(p.total_estimado)}`)));
  const resumen = el("p", { class: "sub" }, `${p.destino.pais} · ${p.noches} noches · salida desde ${p.origen} · ${cap(p.tipo_viajero)}` + (p.intereses.length ? " · " + p.intereses.map(cap).join(", ") : ""));
  const dias = p.dias.map((d) => el("div", { class: "dia" }, el("span", { class: "n" }, "Día " + d.numero),
    el("div", {}, el("h4", {}, d.titulo), el("p", { class: "ciudad" }, d.ciudad),
      d.actividades.length ? el("ul", {}, ...d.actividades.map((a) => el("li", {}, a.nombre + " ", el("span", {}, `· ${cap(a.categoria)} · ${usd(a.costo)}`)))) : "")));
  const revisar = boton(p.revisada ? "Quitar marca de revisada" : "Marcar como revisada", "sec ancho-auto", async () => {
    try { const n = await api(`/propuestas/${p.id}/revisada`, { method: "PATCH", body: JSON.stringify({ revisada: !p.revisada }) });
      estado.alternativas = estado.alternativas.map((a) => a.id === n.id ? n : a); estado.propuesta = n; pintarPropuesta(); } catch (err) { mensaje("g-msg", err.message); }
  });
  const regenerar = boton("↻ Regenerar con los parámetros del formulario", "sec ancho-auto", () => generar(`/propuestas/${p.id}/regenerar`, parametrosForm()));
  const guardar = boton(p.plan_id ? "Abrir plan guardado" : "Guardar como borrador", "ancho-auto", async () => {
    try { abrirPlan(p.plan_id || (await post(`/propuestas/${p.id}/plan`)).id); }
    catch (err) { err.datos && err.datos.plan_id ? abrirPlan(err.datos.plan_id) : mensaje("g-msg", err.message); }
  });
  const d = p.desglose;
  $("resultado").replaceChildren(alts, cab, resumen, p.aviso ? el("div", { class: "aviso" }, p.aviso) : "",
    p.vuelo_incluido ? "" : el("div", { class: "aviso" }, `No hay vuelo registrado desde ${p.origen}: el costo no incluye tiquetes.`), ...dias,
    el("div", { class: "res-pie" }, el("span", { class: "nota" }, `Fuente: ${p.fuente}. Alojamiento ${usd(d.alojamiento)} + actividades ${usd(d.actividades)} + vuelo ${usd(d.vuelo)} (por persona, habitación doble).`),
      el("div", { class: "fila" }, regenerar, revisar, guardar)));
}

/* ---------- panel y editor de planes (HU-07, 12, 15, 16, 17) ---------- */
async function cargarPlanes() {
  const planes = await api("/planes");
  $("planes-vacio").hidden = planes.length > 0;
  filas(document.querySelector("#tabla-planes tbody"), planes.map((p) => el("tr", {}, el("td", {}, p.nombre), el("td", {}, p.pais), el("td", {}, String(p.noches)),
    el("td", {}, usd(p.precio_persona)), el("td", {}, el("span", { class: "estado " + p.estado }, cap(p.estado.toLowerCase()))), el("td", {}, boton("Abrir", "sec ancho-auto", () => abrirPlan(p.id))))));
}
$("nuevo-plan").addEventListener("click", () => mostrar("gen"));
$("plan-volver").addEventListener("click", () => mostrar("planes"));
async function abrirPlan(id) {
  const plan = await api(`/planes/${id}`);
  estado.catalogoPlan = plan.catalogo; estado.opcionesAloj = plan.opciones_alojamiento; estado.plan = plan;
  pintarPlan(); mensaje("p-msg", ""); mostrar("plan");
}
async function guardarPlan() {
  const p = estado.plan;
  const elegidos = {};
  document.querySelectorAll("#p-alojs select").forEach((s) => { elegidos[s.dataset.ciudad] = Number(s.value); });
  const r = await put(`/planes/${p.id}`, { nombre: $("p-nombre").value, descripcion: $("p-desc").value, origen: $("p-origen").value,
    alojamientos: Object.keys(elegidos).length ? elegidos : undefined,
    dias: p.dias.map((d) => ({ numero: d.numero, titulo: d.titulo, actividad_ids: d.actividades.map((a) => a.id) })) });
  estado.plan = { ...p, ...r, catalogo: p.catalogo };
  pintarPlan();
}
const autoguardar = async () => { try { await guardarPlan(); mensaje("p-msg", "Cambios guardados.", true); } catch (err) { mensaje("p-msg", err.message); } };
function pintarPlan() {
  const p = estado.plan, editable = p.estado === "BORRADOR";
  $("p-titulo").textContent = p.nombre; $("p-sub").textContent = `${p.destino.pais} · ${p.noches} noches · ${p.ciudades.join(", ")}`;
  $("p-estado").textContent = cap(p.estado.toLowerCase()); $("p-estado").className = "estado " + p.estado;
  $("p-nombre").value = p.nombre; $("p-desc").value = p.descripcion;
  $("p-origen").replaceChildren(...opciones(estado.origenes)); $("p-origen").value = p.origen;
  [$("p-nombre"), $("p-desc"), $("p-origen")].forEach((c) => { c.disabled = !editable; c.onchange = autoguardar; });
  // alojamiento por ciudad (HU-04)
  $("p-alojs").replaceChildren(...p.ciudades.filter((c) => estado.opcionesAloj.some((o) => o.ciudad === c)).map((c) => {
    const sel = el("select", { "data-ciudad": c }, ...estado.opcionesAloj.filter((o) => o.ciudad === c).map((o) => el("option", { value: o.id }, `${o.nombre} · ${estrellas(o.categoria)} · ${usd(o.tarifa_noche)}/noche`)));
    sel.value = p.precio.alojamientos[c]?.id; sel.disabled = !editable; sel.onchange = autoguardar;
    return el("label", {}, "Alojamiento en " + c, sel);
  }));
  // días y actividades (HU-12)
  const usadas = new Set(p.dias.flatMap((d) => d.actividades.map((a) => a.id)));
  $("p-dias").replaceChildren(...p.dias.map((d) => {
    const titulo = el("input", { value: d.titulo, maxlength: "120", "aria-label": "Título del día " + d.numero });
    titulo.disabled = !editable; titulo.onchange = () => { d.titulo = titulo.value; autoguardar(); };
    const cab = el("div", { class: "cab-dia" }, el("span", { class: "n etq" }, "Día " + d.numero), titulo,
      d.generado_por_ia ? el("span", { class: "etq" }, "✦ IA · Editable") : "", d.revisado ? el("span", { class: "etq rev" }, "Revisado") : "");
    const acts = d.actividades.map((a) => {
      const q = el("button", { class: "quitar", type: "button", title: "Quitar", "aria-label": "Quitar " + a.nombre }, "✕");
      q.disabled = !editable; q.addEventListener("click", () => { d.actividades = d.actividades.filter((x) => x.id !== a.id); autoguardar(); });
      return el("div", { class: "act-fila" }, el("span", {}, a.nombre + " · " + usd(a.costo)), editable ? q : "");
    });
    const libres = estado.catalogoPlan.filter((a) => a.ciudad === d.ciudad && !usadas.has(a.id));
    let agregar = "";
    if (editable && libres.length) {
      const sel = el("select", { "aria-label": "Actividad a agregar el día " + d.numero }, ...libres.map((a) => el("option", { value: a.id }, `${a.nombre} (${usd(a.costo)})`)));
      agregar = el("div", { class: "agregar" }, sel, boton("+ Agregar", "sec ancho-auto", () => { d.actividades.push(estado.catalogoPlan.find((a) => a.id === Number(sel.value))); autoguardar(); }));
    }
    return el("div", { class: "dia-ed" }, cab, ...acts, agregar);
  }));
  // salidas y cupos (HU-17)
  $("p-salidas").replaceChildren(...(p.salidas.length ? p.salidas.map((s) => {
    const q = el("button", { class: "quitar", type: "button", "aria-label": "Quitar salida " + s.fecha }, "✕");
    q.addEventListener("click", async () => { try { estado.plan.salidas = await api(`/planes/${p.id}/salidas/${s.id}`, { method: "DELETE" }); pintarPlan(); } catch (err) { mensaje("p-msg", err.message); } });
    return el("div", { class: "salida" }, el("span", {}, `${dia(s.fecha)} · ${s.cupos} cupos (${s.disponibles} disponibles)`), p.estado === "ARCHIVADO" ? "" : q);
  }) : [el("p", { class: "nota" }, "Aún no hay fechas de salida.")]));
  $("form-salida").hidden = p.estado === "ARCHIVADO"; $("ps-fecha").min = hoy();
  // precio (HU-11) y acciones (HU-16)
  const pr = p.precio;
  $("p-precio").textContent = usd(pr.precio_persona);
  $("p-precio-nota").textContent = `Hospedaje ${usd(pr.hospedaje_pp)} + actividades ${usd(pr.actividades_pp)} + vuelo desde ${pr.origen} ${pr.vuelo_incluido ? usd(pr.vuelo_pp) : "(sin vuelo registrado)"}. ` +
    (editable ? "Se guarda y recalcula al editar." : "El plan no se puede editar mientras está " + p.estado.toLowerCase() + ".");
  const acciones = [];
  if (editable) acciones.push(boton("Publicar plan", "", publicarPlan));
  else if (p.estado === "PUBLICADO") acciones.push(boton("Despublicar (volver a borrador)", "sec", () => cambiar("despublicar")), boton("Archivar", "sec", () => cambiar("archivar")));
  $("p-acciones").replaceChildren(...acciones);
}
$("form-salida").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { estado.plan.salidas = await post(`/planes/${estado.plan.id}/salidas`, { fecha: $("ps-fecha").value, cupos: Number($("ps-cupos").value) }); pintarPlan(); mensaje("p-msg", "Salida agregada.", true); }
  catch (err) { mensaje("p-msg", err.message); }
});
async function publicarPlan() {
  try { await guardarPlan(); estado.plan = { ...estado.plan, ...(await post(`/planes/${estado.plan.id}/publicar`)) }; pintarPlan(); mensaje("p-msg", "Plan publicado: ya aparece en el catálogo del viajero.", true); }
  catch (err) { mensaje("p-msg", err.message); }
}
async function cambiar(accion) {
  try { estado.plan = { ...estado.plan, ...(await post(`/planes/${estado.plan.id}/${accion}`)) }; pintarPlan(); mensaje("p-msg", "Estado actualizado.", true); }
  catch (err) { mensaje("p-msg", err.message); }
}

/* ---------- solicitudes (HU-18) ---------- */
async function cargarSolicitudes() {
  const l = await api("/solicitudes");
  $("sol-vacio").hidden = l.length > 0;
  filas(document.querySelector("#tabla-sol tbody"), l.map((s) => el("tr", {}, el("td", {}, fecha(s.creada)), el("td", {}, s.nombre), el("td", {}, s.correo, el("br"), s.telefono),
    el("td", {}, s.plan), el("td", {}, s.salida ? dia(s.salida) : "Sin fecha"), el("td", {}, `${s.viajeros} · ${cap(s.habitacion)}`, el("br"), el("small", {}, "desde " + s.origen)), el("td", {}, usd(s.total_estimado)))));
}

/* ---------- catálogo público del viajero (HU-19, 20, 21, 22, 23, 24, 25, 26) ---------- */
const origenBusqueda = () => $("b-origen").value || estado.origenes[0];
async function cargarPublico() {
  $("pub-titulo").textContent = "Encuentra la ruta que todavía no sabías que buscabas";
  $("pub-sub").textContent = "Elige un destino o busca por fecha, ciudad de salida y número de viajeros.";
  $("pub-volver").hidden = true; $("lista-planes-pub").hidden = true; $("grid-destinos").hidden = false;
  const destinos = await api("/catalogo?origen=" + encodeURIComponent(origenBusqueda()));
  estado.paisesPorDestino = Object.fromEntries(destinos.map((d) => [d.id, d.pais]));
  $("pub-vacio").hidden = destinos.length > 0;
  $("grid-destinos").replaceChildren(...destinos.map((d, i) => {
    return el("div", { class: "card" }, arteDestino(d.pais, d.ciudades, COLORES[i % COLORES.length], d.pais, true),
      el("div", { class: "cuerpo" }, el("p", {}, d.ciudades.join(", ")), el("p", { class: "desde" }, `desde ${usd(d.precio_desde)} por persona`),
        el("p", {}, d.n_planes + (d.n_planes === 1 ? " plan disponible" : " planes disponibles")), boton("Ver planes", "", () => verPlanesDe(d))));
  }));
}
function tarjetaPlan(p) {
  return el("div", { class: "card" }, arteDestino(p.pais, p.ciudades, COLORES[0], p.ciudades[0]),
    el("div", { class: "cuerpo" }, el("h3", {}, p.nombre), el("p", {}, p.descripcion), el("p", {}, `${p.noches} noches · ${p.ciudades.join(", ")}`),
    el("p", { class: "desde" }, `${usd(p.precio_persona)} por persona`),
    el("p", {}, p.vuelo_incluido ? `Incluye vuelo desde ${p.origen}` : `Sin vuelo registrado desde ${p.origen}`),
    el("p", {}, p.proxima_salida ? "Próxima salida: " + dia(p.proxima_salida) : "Fechas por confirmar"),
    boton("Ver itinerario y reservar", "", () => verFicha(p.id))));
}
function tarjetaRecomendada(p) {
  return el("div", { class: "card" }, arteDestino(p.pais, p.ciudades, COLORES[0], p.ciudades[0]),
    el("div", { class: "cuerpo" }, el("h3", {}, p.nombre), el("p", {}, p.motivo),
    el("p", {}, `${p.pais} · ${p.noches} noches · ${p.ciudades.join(", ")}`),
    el("p", { class: "desde" }, `${usd(p.precio_persona)} por persona`),
    boton("Ver itinerario y reservar", "", () => verFicha(p.id))));
}
async function recomendarPlan(e) {
  e.preventDefault();
  const botonEnviar = $("asistente-enviar"), resultados = $("asistente-resultados"), intro = $("asistente-intro");
  botonEnviar.disabled = true; resultados.hidden = true; resultados.replaceChildren();
  intro.hidden = true; intro.textContent = "";
  mensaje("asistente-msg", "Buscando planes que coincidan con tu viaje...");
  try {
    const consulta = $("asistente-consulta").value;
    const r = await post("/catalogo/recomendar", {
      consulta,
      origen: origenBusqueda(),
      viajeros: Number($("b-viajeros").value || 1)
    });
    resultados.replaceChildren(...r.recomendaciones.map(tarjetaRecomendada));
    resultados.hidden = r.recomendaciones.length === 0;
    if (r.recomendaciones.length) {
      const ciudades = r.recomendaciones.flatMap((p) => p.ciudades);
      const destino = ciudades.find((ciudad) => consulta.toLocaleLowerCase().includes(ciudad.toLocaleLowerCase()))
        || r.recomendaciones[0].pais;
      intro.textContent = `Veo que te interesa ${destino}. Para empezar a planificar tu viaje, inspírate en estas ofertas que encontré para vos:`;
      intro.hidden = false;
    }
    const fuente = r.fuente === "gemini" ? "Sugerencias generadas con Gemini."
      : r.fuente.includes("respaldo") ? "Gemini no respondió; te mostramos alternativas del catálogo."
        : "Sugerencias por coincidencia con el catálogo.";
    mensaje("asistente-msg", r.recomendaciones.length ? fuente : "No encontramos coincidencias entre los planes publicados.", true);
  } catch (err) {
    mensaje("asistente-msg", err.message);
  } finally {
    botonEnviar.disabled = false;
  }
}
$("form-asistente").addEventListener("submit", recomendarPlan);
async function verPlanesDe(d) {
  estado.destinoPublico = d; estado.resultados = null;
  const r = await api(`/catalogo/destinos/${d.id}/planes?origen=` + encodeURIComponent(origenBusqueda()));
  $("pub-titulo").textContent = "Planes en " + r.destino.pais; $("pub-sub").textContent = "Elige un plan para ver su itinerario completo.";
  $("pub-volver").hidden = false; $("grid-destinos").hidden = true; $("lista-planes-pub").hidden = false;
  $("lista-planes-pub").replaceChildren(...r.planes.map((p) => tarjetaPlan({ ...p, pais: r.destino.pais })));
}
$("pub-volver").addEventListener("click", () => { estado.resultados = null; cargarPublico(); });
$("form-busq").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = new URLSearchParams({ origen: origenBusqueda(), viajeros: $("b-viajeros").value || 1, orden: $("b-orden").value });
  [["b-desde", "salida_desde"], ["b-hasta", "salida_hasta"], ["b-pmax", "precio_max"], ["b-nmax", "noches_max"]].forEach(([id, k]) => { if ($(id).value) q.set(k, $(id).value); });
  try {
    const r = await api("/catalogo/planes?" + q); estado.resultados = r; mensaje("b-msg", "");
    $("pub-titulo").textContent = "Resultados de la búsqueda"; $("pub-sub").textContent = r.length ? `${r.length} ${r.length === 1 ? "plan encontrado" : "planes encontrados"}.` : "Ningún plan cumple esos criterios. Prueba con otras fechas o más precio.";
    $("pub-volver").hidden = false; $("grid-destinos").hidden = true; $("lista-planes-pub").hidden = false; $("pub-vacio").hidden = true;
    $("lista-planes-pub").replaceChildren(...r.map((p) => tarjetaPlan({ ...p, pais: p.pais || estado.paisesPorDestino[p.destino_id] })));
  } catch (err) { mensaje("b-msg", err.message); }
});
$("b-limpiar").addEventListener("click", () => { $("form-busq").reset(); estado.resultados = null; mensaje("b-msg", ""); cargarPublico(); });
$("ficha-volver").addEventListener("click", () => {
  mostrar("pub");
  if (estado.resultados) { $("form-busq").requestSubmit(); } else if (estado.destinoPublico) verPlanesDe(estado.destinoPublico);
});

async function verFicha(id) {
  estado.planPublico = { id };
  $("s-origen").replaceChildren(...opciones(estado.origenes)); $("s-origen").value = origenBusqueda();
  $("s-hab").replaceChildren(...opciones(estado.habitaciones, cap)); $("s-hab").value = "doble";
  $("form-sol").reset(); $("s-viajeros").value = $("b-viajeros").value || 2; $("form-sol").hidden = false; $("s-ok").hidden = true; mensaje("s-msg", "");
  $("s-origen").value = origenBusqueda(); $("s-hab").value = "doble";
  await actualizarFicha(true); mostrar("ficha");
}
async function actualizarFicha(pintarDias = false) {
  const q = new URLSearchParams({ origen: $("s-origen").value, habitacion: $("s-hab").value, viajeros: $("s-viajeros").value || 1 });
  const p = await api(`/catalogo/planes/${estado.planPublico.id}?` + q);
  estado.planPublico = p;
  if (pintarDias) {
    $("f-titulo").textContent = p.nombre; $("f-desc").textContent = p.descripcion;
    $("f-pills").replaceChildren(el("span", { class: "etq ed" }, `${p.noches + 1} días · ${p.noches} noches`), el("span", { class: "etq" }, p.ciudades.join(" · ")));
    $("f-dias").replaceChildren(...p.dias.map((d) => {
      const det = el("details", { class: "dia-pub" }, el("summary", {}, el("span", { class: "etq" }, "Día " + d.numero), el("span", {}, d.titulo)),
        el("p", { class: "ciudad" }, d.ciudad), d.actividades.length ? el("ul", {}, ...d.actividades.map((a) => el("li", {}, a.nombre))) : el("p", { class: "nota" }, "Día de traslado."));
      if (d.numero === 1) det.open = true;
      return det;
    }));
  }
  const pr = p.precio;
  $("f-precio").textContent = usd(pr.precio_persona);
  $("f-desglose").textContent = `Hospedaje ${usd(pr.hospedaje_pp)} + actividades ${usd(pr.actividades_pp)}` + (pr.vuelo_incluido ? ` + vuelo ${usd(pr.vuelo_pp)}` : "");
  const v = pr.vuelo;
  $("f-vuelo").replaceChildren(...(v ? [el("strong", {}, "Vuelo incluido desde " + pr.origen), el("p", {}, vueloTxt(v)), el("p", {}, "Ida: " + (v.hora_ida || "por confirmar")),
    el("p", {}, "Regreso: " + (v.hora_regreso || "por confirmar")), el("p", {}, v.equipaje), el("p", { class: "nota" }, "Horarios de ejemplo; se confirman al emitir los tiquetes.")]
    : [el("strong", {}, "Sin vuelo registrado desde " + pr.origen), el("p", {}, "El precio no incluye tiquetes aéreos. Prueba con otra ciudad de salida.")]));
  const sel = $("s-salida"), previa = sel.value;
  $("lbl-salida").hidden = p.salidas.length === 0; sel.required = p.salidas.length > 0;
  sel.replaceChildren(...p.salidas.map((s) => { const o = el("option", { value: s.id }, `${dia(s.fecha)} · quedan ${s.disponibles} cupos`); o.disabled = s.disponibles < pr.viajeros; return o; }));
  if (previa) sel.value = previa;
  const n = pr.viajeros;
  $("s-total").textContent = `Total estimado para ${n} ${n === 1 ? "viajero" : "viajeros"} en habitación ${pr.habitacion}: ${usd(pr.total)}`;
  $("f-wa").href = p.whatsapp_url;
}
["s-origen", "s-hab", "s-viajeros"].forEach((id) => $(id).addEventListener("change", () => { if ($("s-viajeros").value >= 1) actualizarFicha().catch((e) => mensaje("s-msg", e.message)); }));
$("form-sol").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await post(`/catalogo/planes/${estado.planPublico.id}/solicitudes`, { nombre: $("s-nombre").value, correo: $("s-correo").value, telefono: $("s-tel").value,
      viajeros: Number($("s-viajeros").value), habitacion: $("s-hab").value, origen: $("s-origen").value, salida_id: $("s-salida").value ? Number($("s-salida").value) : null });
    $("form-sol").hidden = true; $("s-ok").hidden = false;
    $("s-ok").replaceChildren(r.mensaje, el("small", {}, `Plan: ${r.plan.nombre} · ${r.viajeros} viajeros · habitación ${r.habitacion} · salida desde ${r.origen}` + (r.salida ? ` · ${dia(r.salida)}` : "") + ` · total estimado ${usd(r.total_estimado)}.`));
    $("f-wa").href = r.whatsapp_url;
  } catch (err) { mensaje("s-msg", err.message); actualizarFicha().catch(() => {}); }
});

/* ---------- inicio ---------- */
(async function iniciar() {
  $("d-continente").replaceChildren(...opciones(CONTINENTES)); $("e-continente").replaceChildren(...opciones(CONTINENTES));
  $("a-categoria").replaceChildren(...opciones(CATEGORIAS, cap));
  pintarChips();
  try {
    const s = await api("/salud");
    estado.origenes = s.origenes; estado.habitaciones = s.habitaciones;
    ["g-origen", "v-origen", "b-origen", "p-origen"].forEach((id) => $(id).replaceChildren(...opciones(s.origenes)));
    $("estado-ia").textContent = s.ia === "gemini" ? "IA: Gemini" : "IA: simulada";
    const yo = await api("/auth/yo");
    if (yo.rol) entrar(yo);
  } catch (err) { mensaje("l-msg", "No se pudo conectar con el servidor: " + err.message); }
})();
