/* Interfaz de PortMaster. Sin framework, sin build: la pagina la sirve el
 * propio CLI y la CSP es default-src 'self'. Nada de estilos inline, todo por
 * clases y atributos. */

const POLL_MS = 2500;

const ui = {
  projects: document.getElementById("projects"),
  empty: document.getElementById("empty"),
  connection: document.getElementById("connection"),
  flash: document.getElementById("flash"),
  enroll: document.getElementById("enroll"),
  path: document.getElementById("path"),
  browse: document.getElementById("browse"),
  find: document.getElementById("find"),
  search: document.getElementById("search"),
  count: document.getElementById("count"),
  pager: document.getElementById("pager"),
  pagerAt: document.getElementById("pager-at"),
  picker: document.getElementById("picker"),
  pickerPath: document.getElementById("picker-path"),
  pickerList: document.getElementById("picker-list"),
  pickerNote: document.getElementById("picker-note"),
  tplProject: document.getElementById("tpl-project"),
  tplService: document.getElementById("tpl-service"),
  orphans: document.getElementById("orphans"),
  orphansList: document.getElementById("orphans-list"),
  orphansHeading: document.getElementById("orphans-heading"),
  health: document.getElementById("health"),
  notify: document.getElementById("notify"),
  pathSuggestions: document.getElementById("path-suggestions"),
  btnPortsModal: document.getElementById("btn-ports-modal"),
  portsModal: document.getElementById("ports-modal"),
  portsModalList: document.getElementById("ports-modal-list"),
};

const TITLE = document.title;

const cards = new Map(); // id -> {root, logSeq, logsOpen}
let flashTimer = null;

// Debajo de esto el buscador estorba mas de lo que ayuda.
const PAGE_MIN = 5;
let query = "";
let statusFilter = "";
let page = 1;

/* token ------------------------------------------------------------------- */

function readToken() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    sessionStorage.setItem("portmaster.token", fromUrl);
    url.searchParams.delete("token");
    // Sacarlo de la barra: no tiene por que quedar en el historial.
    window.history.replaceState({}, "", url.pathname + url.hash);
    return fromUrl;
  }
  return sessionStorage.getItem("portmaster.token") || "";
}

const token = readToken();

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!response.ok) {
    let detail = `error ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    throw new Error(detail);
  }
  return response.json();
}

/* avisos ------------------------------------------------------------------ */

function flash(message, tone) {
  ui.flash.textContent = message;
  ui.flash.dataset.tone = tone || "";
  ui.flash.hidden = false;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => {
    ui.flash.hidden = true;
  }, 4500);
}

async function act(button, work) {
  button.disabled = true;
  button.dataset.busy = "true";
  try {
    await work();
    await refresh();
  } catch (error) {
    flash(error.message, "bad");
  } finally {
    button.disabled = false;
    delete button.dataset.busy;
  }
}

/* etiquetas --------------------------------------------------------------- */

const PROJECT_LABELS = {
  stopped: ["detenido", ""],
  starting: ["arrancando", "starting"],
  running: ["corriendo", "ready"],
  stopping: ["apagando", "starting"],
  error: ["con error", "bad"],
  invalid: ["config invalida", "bad"],
};

const SERVICE_LABELS = {
  stopped: ["detenido", ""],
  starting: ["arrancando", "starting"],
  ready: ["listo", "ready"],
};

/* render ------------------------------------------------------------------ */

const SVG = "http://www.w3.org/2000/svg";

/* Dos iconos, uno por cada cosa que el servidor sabe con certeza: contenedor o
 * proceso local. Trazos a 16px, sin dependencias ni webfonts. */
const ICONS = {
  container: "M2.5 5.5h11v3.5h-11zM2.5 10h11v3.5h-11zM4.5 3.5h7",
  local: "M2.5 3.5h11v9h-11zM5 7l1.75 1.75L5 10.5M8.75 10.5h3",
};

function kindIcon(kind) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "service__icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("d", ICONS[kind] || ICONS.local);
  svg.append(path);
  return svg;
}

function renderService(service, projectId) {
  const node = ui.tplService.content.firstElementChild.cloneNode(true);
  node.querySelector(".service__name").prepend(kindIcon(service.kind));
  node.querySelector(".service__name").title =
    service.kind === "container" ? "contenedor" : "proceso local";

  const portCell = node.querySelector(".service__port");
  portCell.textContent = service.port ? String(service.port) : "—";

  // El boton de abrir sale solo cuando el puerto contesto HTTP. Un postgres
  // listo tiene puerto y abrirlo en el navegador no lleva a ningun lado.
  if (service.openable && service.port) {
    const link = document.createElement("a");
    link.href = `http://localhost:${service.port}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "btn btn--open";
    link.title = `Abrir http://localhost:${service.port}`;
    link.textContent = "Abrir ↗";
    node.querySelector(".service__act").append(link);
  }

  node.querySelector(".service__label").textContent = service.name;

  const stateCell = node.querySelector(".service__state");
  const text = stateCell.querySelector("span:last-child");

  if (service.occupant) {
    const who = service.occupant;
    text.textContent = `ocupado por ${who.name}${who.pid ? ` (${who.pid})` : ""}`;
    stateCell.dataset.tone = "bad";

    const kill = document.createElement("button");
    kill.type = "button";
    kill.className = "btn btn--kill";
    kill.textContent = "Liberar";
    kill.addEventListener("click", () =>
      act(kill, () => api(`/api/ports/${service.port}/kill`, { method: "POST" })),
    );
    node.querySelector(".service__act").append(kill);
  } else {
    const [label, tone] = SERVICE_LABELS[service.state] || SERVICE_LABELS.stopped;
    text.textContent = label;
    stateCell.dataset.tone = tone;
  }

  // Solo hay algo que reiniciar si el stack lo arranco esta interfaz, y eso es
  // justo lo que dice que el servicio tenga estado propio.
  if (service.state === "ready" || service.state === "starting") {
    const again = document.createElement("button");
    again.type = "button";
    again.className = "btn btn--quiet";
    again.textContent = "Reiniciar";
    again.title = `Reiniciar ${service.name} sin tocar el resto del stack`;
    again.addEventListener("click", () =>
      act(again, () =>
        api(`/api/projects/${projectId}/services/${encodeURIComponent(service.name)}/restart`, {
          method: "POST",
        }),
      ),
    );
    node.querySelector(".service__act").append(again);
  }

  node.dataset.project = projectId;
  return node;
}

function buildCard(project) {
  const root = ui.tplProject.content.firstElementChild.cloneNode(true);
  const entry = { root, logSeq: 0, logsOpen: false, expanded: false, userToggled: false };
  const logs = root.querySelector(".logs");

  const toggleBtn = root.querySelector(".project__toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      entry.userToggled = true;
      entry.expanded = !entry.expanded;
      root.setAttribute("data-expanded", String(entry.expanded));
      toggleBtn.setAttribute("aria-expanded", String(entry.expanded));
    });
  }

  root.querySelector('[data-act="up"]').addEventListener("click", (event) => {
    const profile = root.querySelector(".profile__select").value || null;
    act(event.currentTarget, () =>
      api(`/api/projects/${project.id}/up`, {
        method: "POST",
        body: JSON.stringify({ profile }),
      }),
    );
  });

  root.querySelector('[data-act="down"]').addEventListener("click", (event) => {
    act(event.currentTarget, () =>
      api(`/api/projects/${project.id}/down`, { method: "POST" }),
    );
  });

  root.querySelector('[data-act="drop"]').addEventListener("click", (event) => {
    act(event.currentTarget, () =>
      api(`/api/projects/${project.id}`, { method: "DELETE" }),
    );
  });

  // Congelar escribe en el disco del usuario, asi que pide confirmacion. Dos
  // pasos sobre el mismo boton en vez de un dialogo: la interfaz no tiene
  // primitiva de confirmacion y `window.confirm` rompe el registro visual.
  const freezeButton = root.querySelector('[data-act="freeze"]');
  freezeButton.addEventListener("click", (event) => {
    const button = event.currentTarget;
    if (button.dataset.armed !== "true") {
      button.dataset.armed = "true";
      button.textContent = `Escribir en ${project.path}\\stack.yaml?`;
      setTimeout(() => disarmFreeze(button), 6000);
      return;
    }
    disarmFreeze(button);
    act(button, async () => {
      const hecho = await api(`/api/projects/${project.id}/freeze`, { method: "POST" });
      flash(`Escrito ${hecho.path}. Revisalo antes de confiar en el.`, "good");
    });
  });

  const logsBox = root.querySelector(".logs__box");
  const logsFilter = root.querySelector(".logs__filter");
  if (logsFilter) {
    logsFilter.addEventListener("input", () => {
      renderLogsText(entry);
    });
  }

  const logsButton = root.querySelector('[data-act="logs"]');
  logsButton.addEventListener("click", () => {
    entry.logsOpen = !entry.logsOpen;
    if (logsBox) logsBox.hidden = !entry.logsOpen;
    else logs.hidden = !entry.logsOpen;
    logsButton.setAttribute("aria-expanded", String(entry.logsOpen));
    if (entry.logsOpen) pullLogs(project.id, entry);
  });

  cards.set(project.id, entry);
  return entry;
}

function disarmFreeze(button) {
  delete button.dataset.armed;
  button.textContent = "Congelar a stack.yaml";
}

function updateCard(entry, project) {
  const { root } = entry;
  root.querySelector(".project__name").textContent = project.name;
  root.querySelector(".project__path").textContent = project.path;

  if (!entry.userToggled) {
    entry.expanded = project.state === "running" || project.state === "starting" || Boolean(project.error);
    root.setAttribute("data-expanded", String(entry.expanded));
    const toggleBtn = root.querySelector(".project__toggle");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", String(entry.expanded));
  }

  const [label, tone] = PROJECT_LABELS[project.state] || PROJECT_LABELS.stopped;
  root.querySelector(".state").dataset.tone = tone;
  root.querySelector(".state__text").textContent = label;

  // El ultimo abrible, no el primero: el orden de arranque va de los
  // contenedores al frontend, y lo que uno quiere mirar es el final.
  const abrible = [...project.services].reverse().find((s) => s.openable && s.port);
  const open = root.querySelector(".project__open");
  open.hidden = !abrible;
  if (abrible) {
    open.href = `http://localhost:${abrible.port}`;
    open.title = `Abrir ${abrible.name} en http://localhost:${abrible.port}`;
  }

  // Solo lo detectado se puede congelar: lo que ya tiene archivo, no.
  const freeze = root.querySelector('[data-act="freeze"]');
  freeze.hidden = !project.detected;
  if (freeze.hidden) disarmFreeze(freeze);

  const error = root.querySelector(".project__error");
  error.textContent = project.error || "";
  error.hidden = !project.error;

  const services = root.querySelector(".services");
  services.replaceChildren(
    ...project.services.map((service) => renderService(service, project.id)),
  );

  const select = root.querySelector(".profile__select");
  const wanted = ["", ...project.profiles].join("|");
  if (select.dataset.options !== wanted) {
    select.dataset.options = wanted;
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "todo";
    select.replaceChildren(
      all,
      ...project.profiles.map((name) => {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        return option;
      }),
    );
  }
  root.querySelector(".profile").hidden = project.profiles.length === 0;

  const live = project.state === "starting" || project.state === "running";
  const stopping = project.state === "stopping";
  root.querySelector('[data-act="up"]').disabled =
    live || stopping || project.state === "invalid";
  root.querySelector('[data-act="down"]').disabled = !live;

  if (entry.logsOpen) pullLogs(project.id, entry);
}

async function pullLogs(id, entry) {
  try {
    const data = await api(`/api/projects/${id}/logs?since=${entry.logSeq}`);
    if (!data.lines.length) return;
    entry.logSeq = data.lines[data.lines.length - 1].seq;
    entry.rawLogs = (entry.rawLogs || "") + data.lines.map((l) => l.text).join("\n") + "\n";
    renderLogsText(entry);
  } catch {
    /* el proximo ciclo reintenta */
  }
}

function renderLogsText(entry) {
  const logsEl = entry.root.querySelector(".logs");
  const filterInput = entry.root.querySelector(".logs__filter");
  if (!logsEl) return;
  const atBottom = logsEl.scrollHeight - logsEl.scrollTop - logsEl.clientHeight < 40;
  const raw = entry.rawLogs || "";
  const filter = (filterInput ? filterInput.value : "").trim().toLowerCase();
  if (!filter) {
    logsEl.textContent = raw;
  } else {
    const lines = raw.split("\n");
    logsEl.textContent = lines.filter((l) => l.toLowerCase().includes(filter)).join("\n");
  }
  if (atBottom) logsEl.scrollTop = logsEl.scrollHeight;
}

function render(projects, data) {
  // Sin resultados con un filtro puesto no es lo mismo que no tener proyectos:
  // el cartel de "registrá el primero" ahi seria mentira.
  ui.empty.hidden = projects.length > 0 || Boolean(query) || Boolean(statusFilter);

  // El buscador y los chips se muestran siempre que haya al menos un proyecto registrado.
  ui.find.hidden = data.registered === 0;
  ui.count.textContent = query || statusFilter
    ? `${data.total} ${data.total === 1 ? "coincidencia" : "coincidencias"}`
    : "";

  ui.pager.hidden = data.pages <= 1;
  ui.pagerAt.textContent = `${data.page} de ${data.pages}`;
  ui.pager.querySelector('[data-page="prev"]').disabled = data.page <= 1;
  ui.pager.querySelector('[data-page="next"]').disabled = data.page >= data.pages;
  page = data.page;

  const seen = new Set();
  for (const project of projects) {
    seen.add(project.id);
    let entry = cards.get(project.id);
    if (!entry) entry = buildCard(project);
    updateCard(entry, project);
  }

  for (const [id, entry] of cards) {
    if (!seen.has(id)) {
      entry.root.remove();
      cards.delete(id);
    }
  }

  ui.projects.replaceChildren(
    ...projects.map((project) => cards.get(project.id).root),
  );
  ui.projects.setAttribute("aria-busy", "false");
}

/* ciclo ------------------------------------------------------------------- */

async function refreshOrphans() {
  try {
    const data = await api("/api/ports/orphans");
    const list = data.orphans || [];

    // Siempre visible despues del primer check: el estado vacio le dice al
    // usuario que la seccion existe y que todo esta limpio.
    ui.orphans.hidden = false;

    const nextIds = list.map((o) => o.port).join(",") || "__empty__";
    if (ui.orphansList.dataset.ids === nextIds) return;
    ui.orphansList.dataset.ids = nextIds;

    // Actualiza el titulo con el conteo cuando hay intrusos.
    ui.orphansHeading.textContent = list.length
      ? `Procesos intrusos (${list.length})`
      : "Procesos intrusos";

    if (list.length === 0) {
      const empty = document.createElement("li");
      empty.className = "orphan orphan--empty";
      const msg = document.createElement("span");
      msg.className = "orphan__empty-msg";
      msg.textContent = "Ningun proceso intruso detectado";
      empty.append(msg);
      ui.orphansList.replaceChildren(empty);
      return;
    }

    ui.orphansList.replaceChildren(
      ...list.map((orphan) => {
        const li = document.createElement("li");
        li.className = "orphan";

        const portTag = document.createElement("span");
        portTag.className = "orphan__port";
        portTag.textContent = `:${orphan.port}`;

        const info = document.createElement("div");
        info.className = "orphan__info";

        const name = document.createElement("div");
        name.className = "orphan__name";
        name.textContent = `${orphan.name}  ·  ${orphan.project}`;

        const meta = document.createElement("div");
        meta.className = "orphan__meta";
        meta.textContent = orphan.cmd ? orphan.cmd : `pid ${orphan.pid}`;
        if (!orphan.cmd) meta.textContent = `pid ${orphan.pid}`;

        info.append(name, meta);

        const kill = document.createElement("button");
        kill.className = "orphan__kill";
        kill.textContent = "Cerrar";
        kill.type = "button";
        kill.addEventListener("click", () => {
          act(kill, async () => {
            await api(`/api/ports/${orphan.port}/kill`, { method: "POST" });
            delete ui.orphansList.dataset.ids;
            await refreshOrphans();
          });
        });

        li.append(portTag, info, kill);
        return li;
      }),
    );
  } catch {
    // Fallo silencioso: la seccion de intrusos no es critica.
  }
}

/* salud ------------------------------------------------------------------- */

/* Un servicio que se muere cambia un punto de color y nada mas. Si la pestaña
 * esta de fondo, que es donde vive esta herramienta, no te enteras hasta que el
 * navegador te tira un ERR_CONNECTION_REFUSED diez minutos despues.
 *
 * `/api/health` mira todas las sesiones y no la pagina actual: con mas de
 * cuatro proyectos, alimentar esto de `/api/state` seria una mentira
 * silenciosa. */

// Servicios caidos en el sondeo anterior, para avisar solo de los nuevos: sin
// esto, uno caido notifica 24 veces por minuto.
let fallen = new Set();
// El primer sondeo no notifica. Al cargar la pagina con algo ya caido, la
// noticia es vieja y el usuario no la pidio.
let healthKnown = false;

async function refreshHealth() {
  let data;
  try {
    data = await api("/api/health");
  } catch {
    return; // sin conexion ya lo dice el masthead
  }

  // `service: null` es el stack entero, no un servicio suelto.
  const clave = (f) => `${f.project}/${f.service ?? ""}`;
  const ahora = new Set(data.fallen.map(clave));
  const nuevos = data.fallen.filter((f) => !fallen.has(clave(f)));
  fallen = ahora;

  document.title = ahora.size ? `(${ahora.size}) ${TITLE}` : TITLE;
  ui.health.hidden = !ahora.size;
  ui.health.textContent = ahora.size === 1 ? "1 caído" : `${ahora.size} caídos`;

  const puedePedirse = "Notification" in window && Notification.permission === "default";
  ui.notify.hidden = !ahora.size || !puedePedirse;

  if (healthKnown && nuevos.length && window.Notification?.permission === "granted") {
    for (const caido of nuevos) {
      const que = caido.service ? `${caido.stack}: ${caido.service}` : caido.stack;
      new Notification(`${que} se cayó`, {
        body: "PortMaster no lo apagó, se murió solo.",
        tag: clave(caido), // el navegador tambien deduplica
      });
    }
  }
  healthKnown = true;
}

ui.notify.addEventListener("click", async () => {
  // El permiso se pide con un click y nunca al cargar: un pedido de
  // notificaciones que aparece solo es lo que hace que la gente lo deniegue
  // para siempre.
  if (!("Notification" in window)) return;
  await Notification.requestPermission();
  ui.notify.hidden = true;
});

const ORPHAN_EVERY = 4; // cada N ciclos de POLL_MS
let orphanTick = 0;

async function refresh() {
  try {
    const params = new URLSearchParams({ page: String(page) });
    if (query) params.set("q", query);
    if (statusFilter) params.set("status", statusFilter);
    const data = await api(`/api/state?${params}`);
    render(data.projects, data);
    const n = data.registered;
    ui.connection.textContent = `${n} ${n === 1 ? "proyecto" : "proyectos"}`;
    ui.connection.dataset.down = "false";
  } catch (error) {
    ui.connection.textContent = `sin conexión · ${error.message}`;
    ui.connection.dataset.down = "true";
  }
  await refreshHealth();
  orphanTick++;
  if (orphanTick % ORPHAN_EVERY === 1) await refreshOrphans();
}

/* explorador de carpetas -------------------------------------------------- */

/* La ruta absoluta la pone el servidor: el navegador no la conoce y no la puede
 * conocer. Cada click pide el listado de una carpeta y nada mas. */

let here = { path: "", parent: null, markers: [] };
let historyStack = [];

async function browseTo(path, isHistoryAction = false) {
  const from = here.path;

  let data;
  try {
    data = await api(`/api/browse?path=${encodeURIComponent(path)}`);
  } catch (error) {
    // Una ruta mala escrita a mano no puede dejar el dialogo en blanco: se cae
    // a las raices y recien despues se muestra el aviso, que si no lo tapa. El
    // salto a las raices es del historial: si no, Volver traeria de vuelta la
    // ruta que acaba de fallar.
    if (path) await browseTo("", true);
    ui.pickerNote.textContent = error.message;
    ui.pickerNote.hidden = false;
    return;
  }

  // El historial se anota recien cuando la navegacion salio bien, y contra la
  // ruta que devolvio el servidor: es la normalizada, la que Volver puede
  // pedir de nuevo.
  if (!isHistoryAction && from !== data.path) {
    historyStack.push(from);
  }

  here = data;
  ui.pickerPath.textContent = data.path || "Elegí dónde empezar";
  ui.pickerNote.hidden = !data.truncated;
  if (data.truncated) {
    ui.pickerNote.textContent = `Se muestran las primeras ${data.entries.length} carpetas.`;
  }

  const backBtn = ui.picker.querySelector('[data-picker="back"]');
  if (backBtn) backBtn.disabled = historyStack.length === 0;

  ui.picker.querySelector('[data-picker="up"]').disabled = data.parent === null;
  ui.picker.querySelector('[data-picker="pick"]').disabled = !data.path;

  ui.pickerList.replaceChildren(...data.entries.map(entryRow));
  if (!data.entries.length) {
    const empty = document.createElement("li");
    empty.className = "picker__empty";
    empty.textContent = "Sin subcarpetas visibles.";
    ui.pickerList.append(empty);
  }
  ui.pickerList.scrollTop = 0;
}

function entryRow(entry) {
  const item = document.createElement("li");
  const row = document.createElement("button");
  row.type = "button";
  row.className = "picker__row";
  row.dataset.path = entry.path;

  const name = document.createElement("span");
  name.className = "picker__name";
  name.textContent = entry.name;
  row.append(name);

  if (entry.markers.length) {
    const tag = document.createElement("span");
    tag.className = "picker__markers";
    tag.textContent = entry.markers.join(" · ");
    row.append(tag);
  }

  row.addEventListener("click", () => browseTo(entry.path));
  item.append(row);
  return item;
}

/* buscador y paginado ----------------------------------------------------- */

let searchTimer = null;

ui.search.addEventListener("input", () => {
  // Sin esperar, cada tecla dispara un escaneo de puertos en el servidor.
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    query = ui.search.value.trim();
    page = 1;
    refresh();
  }, 200);
});

ui.pager.addEventListener("click", (event) => {
  const move = event.target.dataset.page;
  if (!move) return;
  page = move === "next" ? page + 1 : Math.max(1, page - 1);
  refresh();
});

const filterChips = document.getElementById("filter-chips");
if (filterChips) {
  filterChips.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-status]");
    if (!btn) return;
    statusFilter = btn.dataset.status;
    for (const chip of filterChips.querySelectorAll(".chip")) {
      chip.classList.toggle("chip--active", chip === btn);
    }
    page = 1;
    refresh();
  });
}

document.addEventListener("keydown", (event) => {
  const tag = document.activeElement ? document.activeElement.tagName : "";
  const isInput = ["INPUT", "TEXTAREA", "SELECT"].includes(tag);
  if (event.key === "/" && !isInput) {
    event.preventDefault();
    ui.search.focus();
    ui.search.select();
  } else if (event.key === "Escape" && document.activeElement === ui.search) {
    ui.search.blur();
  } else if (!isInput && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    if (ui.pager.hidden) return;
    if (event.key === "ArrowLeft" && page > 1) {
      page--;
      refresh();
    } else if (event.key === "ArrowRight") {
      page++;
      refresh();
    }
  }
});

ui.browse.addEventListener("click", () => {
  historyStack = [];
  const backBtn = ui.picker.querySelector('[data-picker="back"]');
  if (backBtn) backBtn.disabled = true;
  ui.picker.showModal();
  browseTo(ui.path.value.trim() || here.path, true);
});

ui.picker.querySelector('[data-picker="close"]').addEventListener("click", () => {
  ui.picker.close();
});

const backBtn = ui.picker.querySelector('[data-picker="back"]');
if (backBtn) {
  backBtn.addEventListener("click", () => {
    if (historyStack.length > 0) {
      const prevPath = historyStack.pop();
      browseTo(prevPath, true);
    }
  });
}

ui.picker.querySelector('[data-picker="up"]').addEventListener("click", () => {
  if (here.parent !== null) browseTo(here.parent);
});

ui.picker.querySelector('[data-picker="pick"]').addEventListener("click", (event) => {
  const chosen = here.path;
  if (!chosen) return;
  act(event.currentTarget, async () => {
    await api("/api/projects", { method: "POST", body: JSON.stringify({ path: chosen }) });
    ui.picker.close();
    ui.path.value = "";
  });
});

/* autocompletado no intrusivo en el registro ----------------------------- */

let pathDebounceTimer = null;
if (ui.path && ui.pathSuggestions) {
  ui.path.addEventListener("input", () => {
    clearTimeout(pathDebounceTimer);
    const val = ui.path.value.trim();
    if (val.length < 3) {
      ui.pathSuggestions.replaceChildren();
      return;
    }

    pathDebounceTimer = setTimeout(async () => {
      const sep = val.includes("\\") ? "\\" : "/";
      const lastSepIdx = val.lastIndexOf(sep);
      if (lastSepIdx === -1) return;

      const parentDir = val.slice(0, lastSepIdx) || sep;
      const prefix = val.slice(lastSepIdx + 1).toLowerCase();

      try {
        const data = await api(`/api/browse?path=${encodeURIComponent(parentDir)}`);
        if (!data || !data.entries) return;

        const matches = data.entries.filter((entry) =>
          entry.name.toLowerCase().startsWith(prefix)
        );

        ui.pathSuggestions.replaceChildren(
          ...matches.map((m) => {
            const opt = document.createElement("option");
            opt.value = m.path;
            return opt;
          })
        );
      } catch {
        // Silencioso: mientras se tipea una ruta parcial es normal que no exista aun
      }
    }, 150);
  });
}

ui.enroll.addEventListener("submit", (event) => {
  event.preventDefault();
  const button = ui.enroll.querySelector("button");
  const path = ui.path.value.trim();
  if (!path) return;
  act(button, async () => {
    await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    ui.path.value = "";
    if (ui.pathSuggestions) ui.pathSuggestions.replaceChildren();
  });
});

/* mapa de puertos modal --------------------------------------------------- */

if (ui.btnPortsModal && ui.portsModal) {
  ui.btnPortsModal.addEventListener("click", () => {
    ui.portsModal.showModal();
    refreshPortsModal();
  });
  const closeBtn = ui.portsModal.querySelector('[data-ports-modal="close"]');
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      ui.portsModal.close();
    });
  }
}

async function refreshPortsModal() {
  if (!ui.portsModalList) return;
  try {
    const [stateData, orphansData] = await Promise.all([
      api("/api/state?size=50"),
      api("/api/ports/orphans"),
    ]);

    const items = [];
    for (const project of stateData.projects || []) {
      for (const service of project.services || []) {
        if (service.port) {
          items.push({
            port: service.port,
            label: `${project.name} · ${service.name}`,
            kind: service.state === "ready" ? "corriendo" : "detenido",
            openable: service.openable,
          });
        }
      }
    }

    for (const orphan of orphansData.orphans || []) {
      items.push({
        port: orphan.port,
        label: `Intruso · ${orphan.name} (${orphan.project})`,
        kind: "intruso",
        isOrphan: true,
      });
    }

    items.sort((a, b) => a.port - b.port);

    if (items.length === 0) {
      const empty = document.createElement("li");
      empty.className = "orphan orphan--empty";
      empty.textContent = "Sin puertos asignados ni intrusos";
      ui.portsModalList.replaceChildren(empty);
      return;
    }

    ui.portsModalList.replaceChildren(
      ...items.map((item) => {
        const li = document.createElement("li");
        li.className = "orphan";

        const portTag = document.createElement("span");
        portTag.className = "orphan__port";
        portTag.textContent = `:${item.port}`;

        const info = document.createElement("div");
        info.className = "orphan__info";

        const name = document.createElement("div");
        name.className = "orphan__name";
        name.textContent = item.label;

        const meta = document.createElement("div");
        meta.className = "orphan__meta";
        meta.textContent = `Estado: ${item.kind}`;

        info.append(name, meta);

        if (item.openable) {
          const actLink = document.createElement("a");
          actLink.className = "btn btn--open";
          actLink.target = "_blank";
          actLink.rel = "noopener noreferrer";
          actLink.href = `http://localhost:${item.port}`;
          actLink.textContent = "Abrir ↗";
          li.append(portTag, info, actLink);
        } else if (item.isOrphan) {
          const killBtn = document.createElement("button");
          killBtn.className = "orphan__kill";
          killBtn.textContent = "Cerrar";
          killBtn.type = "button";
          killBtn.addEventListener("click", () => {
            act(killBtn, async () => {
              await api(`/api/ports/${item.port}/kill`, { method: "POST" });
              await refreshPortsModal();
            });
          });
          li.append(portTag, info, killBtn);
        } else {
          li.append(portTag, info);
        }

        return li;
      }),
    );
  } catch {
    // Silencioso
  }
}
