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
  picker: document.getElementById("picker"),
  pickerPath: document.getElementById("picker-path"),
  pickerList: document.getElementById("picker-list"),
  pickerNote: document.getElementById("picker-note"),
  tplProject: document.getElementById("tpl-project"),
  tplService: document.getElementById("tpl-service"),
};

const cards = new Map(); // id -> {root, logSeq, logsOpen}
let flashTimer = null;

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
  const entry = { root, logSeq: 0, logsOpen: false };
  const logs = root.querySelector(".logs");

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

  const logsButton = root.querySelector('[data-act="logs"]');
  logsButton.addEventListener("click", () => {
    entry.logsOpen = !entry.logsOpen;
    logs.hidden = !entry.logsOpen;
    logsButton.setAttribute("aria-expanded", String(entry.logsOpen));
    if (entry.logsOpen) pullLogs(project.id, entry);
  });

  cards.set(project.id, entry);
  return entry;
}

function updateCard(entry, project) {
  const { root } = entry;
  root.querySelector(".project__name").textContent = project.name;
  root.querySelector(".project__path").textContent = project.path;

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
    const logs = entry.root.querySelector(".logs");
    const atBottom =
      logs.scrollHeight - logs.scrollTop - logs.clientHeight < 40;
    logs.append(data.lines.map((line) => line.text).join("\n") + "\n");
    if (atBottom) logs.scrollTop = logs.scrollHeight;
  } catch {
    /* el proximo ciclo reintenta */
  }
}

function render(projects) {
  ui.empty.hidden = projects.length > 0;

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

async function refresh() {
  try {
    const data = await api("/api/state");
    render(data.projects);
    const count = data.projects.length;
    ui.connection.textContent = `${count} ${count === 1 ? "proyecto" : "proyectos"}`;
    ui.connection.dataset.down = "false";
  } catch (error) {
    ui.connection.textContent = `sin conexión · ${error.message}`;
    ui.connection.dataset.down = "true";
  }
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
  });
});

refresh();
setInterval(refresh, POLL_MS);
