// layz web: the runs of this clone's flows. #design=NAME opens one run as a single page, top to
// bottom in the flow's order. Each stage (target): its numbers on the left (tables, violations,
// log, in tabs), its pictures on the right (layout with the violations marked, schematic, board,
// interactive plots, in tabs).
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
};
// a report page (layz.web.report: opened as a file, no server): its run is in the page, the rest
// in scripts next to it, each loaded the first time it is asked for
const STATIC = window.LAYZ_STATIC || null;
const got = {};
window.LAYZ_PUT = (key, value) => { got[key] = value; };
const staticGet = (key) => new Promise((ok, no) => {
  if (key in got) return ok(got[key]);
  if (!(key in STATIC.files)) return no(new Error(`${key}: not in this report`));
  const s = document.createElement("script");
  s.src = STATIC.files[key];
  s.onload = () => ok(got[key]);
  s.onerror = () => no(new Error(`${STATIC.files[key]}: could not be read`));
  document.head.append(s);
});
const getJSON = async (url) => {
  if (STATIC) {
    const path = url.split("?")[0];
    if (path === "/api/designs") return [STATIC.design];
    if (path === "/api/design") return STATIC.design;
    return staticGet(path.startsWith("/api/") ? path.slice(1) : decodeURIComponent(url));
  }
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
};
const memo = new Map();
const once = (url) => { if (!memo.has(url)) memo.set(url, getJSON(url)); return memo.get(url); };
const state = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const go = (patch) => { location.hash = new URLSearchParams(patch).toString(); };
const fileUrl = (design, rel) => (STATIC ? "" : `/results/${encodeURIComponent(design)}/`) + rel.split("/").map(encodeURIComponent).join("/");
const base = (p) => (p || "").split("/").pop();
// the theme's colours; while a view is exported, the light theme's (for paper and slides)
const LIGHT = { "--layout-bg": "#fafafa", "--line-1": "#dfdfe0", "--line-2": "#c9c9ca", "--ink-0": "#18191c", "--ink-1": "#242529", "--ink-3": "#58585a", "--ink-4": "#7e8086", "--sem-error": "#d36151", "--sem-warn": "#a48819", "--sem-ok": "#669f59" };
let exporting = false;
const css = (name) => (exporting && LIGHT[name]) || getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------------------------------------------------------- theme: the system's

const themeListeners = new Set();
function initTheme() {
  const light = window.matchMedia("(prefers-color-scheme: light)");
  const set = () => {
    document.documentElement.dataset.theme = light.matches ? "light" : "dark";
    for (const f of themeListeners) f();
  };
  set();
  light.addEventListener("change", set);
}

async function render() {
  const design = state().design || STATIC?.design.name;
  themeListeners.clear();
  const main = $("#main");
  try {
    main.replaceChildren(design ? await designPage(design) : await homePage());
  } catch (e) {
    main.replaceChildren(h("div", { class: "empty" }, String(e.message || e)));
  }
}

// ---------------------------------------------------------------- home: every design's last run

const boardOf = (d) => d.board || d.inputs.board;  // the board a run made for HyperLynx (older runs: among the inputs)
const done = (t) => ["ok", "warnings", "errors", "skipped"].includes(t.status);
const chip = (status, text) => h("span", { class: `chip ${status}` }, text ?? status);

async function homePage() {
  const designs = await getJSON("/api/designs");
  if (!designs.length) return h("div", { class: "empty" }, "No runs yet: layz run designs/NAME records one in results/NAME/.");
  const status = (d) => {
    const failed = d.targets.find((t) => t.status === "failed");
    if (failed) return chip("failed", `stopped at ${failed.name}`);
    if (!d.targets.every(done)) return chip("pending", "running");
    const worst = ["errors", "warnings"].find((st) => d.targets.some((t) => t.status === st));
    return worst ? chip(worst, `${d.targets.filter((t) => t.status === worst).length} with ${worst}`) : chip("ok");
  };
  return h("div", { class: "page" },
    h("h2", {}, "designs: click one to open its run"),
    h("table", { class: "data designs" },
      h("tr", {}, ["design", "status", "targets done", "layout", "board", "run"].map((c) => h("th", {}, c))),
      designs.map((d) => h("tr", { onclick: () => go({ design: d.name }) },
        h("td", {}, d.name), h("td", {}, status(d)),
        h("td", {}, `${d.targets.filter(done).length} / ${d.targets.length}`),
        h("td", {}, base(d.inputs.layout)), h("td", {}, base(boardOf(d))), h("td", {}, d.started)))));
}

// ---------------------------------------------------------------- one design, top to bottom

async function designPage(name) {
  memo.clear();
  const d = await getJSON(`/api/design?name=${encodeURIComponent(name)}`);
  const jump = (t) => (e) => { e.preventDefault(); document.getElementById(`t-${t.name}`)?.scrollIntoView({ behavior: "smooth" }); };
  return h("div", { class: "page" },
    h("div", { class: "title" },
      h("a", { class: "home", href: "#", title: "every design" }, d.name),
      h("span", { class: "dim" }, d.started)),
    h("nav", { class: "toc" }, d.targets.map((t) => h("a", { onclick: jump(t) }, chip(t.status, ""), t.name.replace(/_/g, " ")))),
    d.targets.map((t, i) => stage(d, t, i)));
}

// tabs over one body; a pane is built the first time it is shown
function tabs(entries) {
  entries = entries.filter(Boolean);
  if (!entries.length) return null;
  const bar = h("div", { class: "tabs" });
  const body = h("div", { class: "tabbody" });
  const panes = entries.map(() => null);
  const show = (i) => {
    bar.querySelectorAll("a").forEach((a, k) => a.classList.toggle("on", k === i));
    if (!panes[i]) { panes[i] = h("div", { class: "pane" }, lazy(entries[i][1])); body.append(panes[i]); }
    panes.forEach((p, k) => p && (p.style.display = k === i ? "" : "none"));
  };
  entries.forEach(([label], i) => bar.append(h("a", { onclick: () => { show(i); panes[i].querySelector(".lazy")?.load(); } }, label)));
  show(0);
  const box = h("div", { class: "tabbox" }, bar, body);
  box.show = (label) => { const i = Math.max(0, entries.findIndex(([l]) => l === label)); show(i); panes[i].querySelector(".lazy")?.load(); };
  box.current = () => entries[[...bar.querySelectorAll("a")].findIndex((a) => a.classList.contains("on"))]?.[0];
  return box;
}

function lazy(make) {
  // heavy panes (layouts, plots, drawings) are built when they scroll into view, or at once when
  // asked (a tab clicked open)
  const slot = h("div", { class: "lazy" }, h("div", { class: "caption" }, "loading…"));
  let started = false;
  const obs = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) slot.load(); }, { rootMargin: "300px" });
  slot.load = async () => {
    if (started) return;
    started = true;
    obs.disconnect();
    try { slot.replaceChildren(await make()); } catch (e) { slot.replaceChildren(h("div", { class: "caption" }, String(e.message || e))); }
  };
  obs.observe(slot);
  return slot;
}

function stage(d, t, i) {
  const inputs = () => once(`/api/inputs?name=${encodeURIComponent(d.name)}`);
  const board = () => once(`/api/board?name=${encodeURIComponent(d.name)}`);
  const isBoard = boardOf(d) && !["failed", "pending", "skipped"].includes(t.status) && boardTarget(d) === t.name;
  let viewer = null; // the layout this stage marks its violations on

  // right: pictures
  const right = [];
  if (t.name === "setup") {
    right.push(["layout", async () => {
      const inp = await inputs();
      if (inp.layout) return layoutViewer(inp.layout, null, true).el;
      if (inp.layout_svgs) return (await svgViewer(inp.layout_svgs)).el;
      return h("div", { class: "caption" }, "no layout");
    }]);
    right.push(["3D", async () => {
      const inp = await inputs();
      return inp.layout ? view3d(inp.layout) : h("div", { class: "caption" }, "—");
    }]);
    right.push(["schematic", async () => {
      const inp = await inputs();
      if (inp.schematic_svgs) return (await svgViewer(inp.schematic_svgs, inp.schematic_index)).el;
      if (inp.netlist) return table({ path: "", rows: [["net", "pins"], ...inp.netlist.map((n) => [n.net, n.pins.join(" ")])] });
      return h("div", { class: "caption" }, "no schematic");
    }]);
  }
  if (t.markers && t.markers.boxes.length) {
    right.push(["layout", async () => {
      const b = t.markers.on === "board" ? await board() : (await inputs()).layout;
      if (!b) return h("div", { class: "caption" }, "no layout to mark");
      viewer = layoutViewer(b);
      viewer.setMarkers(t.markers.boxes);
      return viewer.el;
    }]);
  }
  // a result drawn on the board: a tab per kind (for DC: current density, pin voltage, via current)
  for (const o of t.overlays || []) for (const mode of ["voltage drop", "current density", "via current"]) right.push([mode, async () => layoutViewer(await board(), await once(fileUrl(d.name, o)), false, mode).el]);
  let sheet = null; // the schematic this stage marks its findings on
  const unchecked = (t.summary && t.summary["unchecked nets"]) || [];
  if (t.name.includes("lvs") && t.markers && (t.markers.boxes.some((m) => m.names) || unchecked.length)) right.push(["schematic", async () => {
    const inp = await inputs();
    if (!inp.schematic_svgs || !inp.schematic_index) return h("div", { class: "caption" }, "no KiCad schematic to mark");
    sheet = await svgViewer(inp.schematic_svgs, inp.schematic_index, true);  // grey: the marks carry the colour
    sheet.mark(t.markers.boxes.flatMap((m) => m.names || []), [], unchecked, t.markers.boxes);
    return sheet.el;
  }]);
  if (isBoard) right.push(["board", async () => layoutViewer(await board()).el]);
  if (isBoard) right.push(["3D", async () => view3d(await board())]);
  const REPLACES = { dc: ["dc_current_density", "dc_loss_map", "dc_pin_voltage", "dc_via_current"] };  // maps an overlay draws on the board
  const replaced = new Set((t.overlays || []).flatMap((o) => REPLACES[base(o).split("_")[0]] || []));
  // a figure per pair (eye__D1, eye__D2, ...): one tab per kind, the pair picked in it
  const groups = new Map();
  for (const p of t.plots) {
    const stem = base(p.png).replace(/\.png$/, "");
    if (replaced.has(stem)) continue;
    const [kind, pair] = stem.includes("__") ? stem.split("__") : [stem, null];
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind).push([pair, p]);
  }
  for (const [kind, items] of groups) right.push([kind.replace(/_/g, " "), async () => (items.length === 1 && !items[0][0] ? plotPane(d.name, items[0][1]) : plotGroup(d.name, items))]);

  // left: numbers
  const mark = (row, head) => {
    if (!t.markers) return;
    const w = head.indexOf("what"), what = w >= 0 ? row[w] : null;
    const boxes = t.markers.boxes.filter((m) => (what ? m.what === what : m.rule === row[0]));
    if (!boxes.length) return;
    rightTabs.show("layout");
    setTimeout(() => viewer && viewer.setMarkers(boxes, boxes[0]), 50);
  };
  const left = [];
  if (t.name === "setup") left.push(["inputs", async () => {  // what setup named, and the layout's counts
    const inp = await inputs();
    const rows = [["flow", d.flow], ...Object.entries(d.inputs).filter(([k]) => k !== "board")];
    const pins = inp.layout ? (inp.layout.labels && inp.layout.labels.length) || inp.layout.pins.length : null;  // a GDS's pin labels, a board's pads
    if (pins) rows.push(["pins", pins]);
    return h("div", {}, h("table", { class: "kvtable" }, rows.map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, d.paths && d.paths[k] ? pathRow(v, d.paths[k], false, k === "flow" ? (STATIC ? "web/flow.html" : `/flow?name=${encodeURIComponent(d.name)}`) : null) : v)))));
  }]);
  // the step's results in one tab: the board's facts (the board step), its tables (without those
  // another contains), the violations; then its files
  const covers = (big, small) => big !== small && small.rows.length === big.rows.length && small.rows[0].every((c) => big.rows[0].includes(c));
  const tables = t.tables.filter((tb) => !t.tables.some((other) => covers(other, tb)))
    .sort((a, b) => Number(a.rows[0].includes("what")) - Number(b.rows[0].includes("what")));  // in the order the flow wrote them, lists of findings last
  const pickViolation = (m) => {
    if (sheet && m.names && rightTabs.current() === "schematic") { sheet.mark(t.markers.boxes.flatMap((x) => x.names || []), m.names, unchecked, t.markers.boxes); return; }
    rightTabs.show("layout");
    setTimeout(() => viewer && viewer.setMarkers(t.markers.boxes, m), 50);
  };
  const hasMarks = t.markers && t.markers.boxes.length;
  if (isBoard || tables.length || hasMarks) left.push(["results", async () => h("div", { class: "stacked" },
    isBoard ? factsTable((await board()).facts) : null,
    tables.map((tb) => table(tb, t.markers ? mark : null)),
    hasMarks && !tables.some((tb) => tb.rows[0].includes("what")) ? violations(t.markers.boxes, pickViolation) : null)]);  // a findings table lists them already
  const filesLine = () => (t.folder && t.files && t.files.length ? h("div", { class: "files" }, pathRow(`${t.name}/`, t.folder + "/", true), t.files.map((f) => pathRow(f, `${t.folder}/${f}`))) : null);
  // what the step wrote, its log among them
  if (t.files && t.files.length) left.push(["files", () => filesLine()]);

  const rightTabs = tabs(right);
  const leftTabs = tabs(left);
  return h("section", { class: `target ${t.status}`, id: `t-${t.name}` },
    h("div", { class: "head" },
      h("span", { class: `chip ${t.status} timed` }, "● ", t.status, t.seconds == null || t.status === "pending" ? "" : ` ${t.seconds.toFixed(2)} s`),
      h("span", { class: "name", title: t.doc }, t.name.replace(/_/g, " "))),
    t.error ? h("div", { class: "error" }, t.error) : null,
    leftTabs || rightTabs ? h("div", { class: rightTabs && leftTabs ? "split" : "single" }, leftTabs, rightTabs) : null);
}

function boardTarget(d) {
  // the target whose folder holds the board (results/<design>/<target>/...), else "board"
  const parts = boardOf(d).split("/");
  return d.targets.find((t) => parts.includes(t.name))?.name || "board";
}

const overlayName = (o) => ({ dc: "current density" })[base(o).split("_")[0]] || base(o).replace(/\.overlay\.json$/, "");
const firstSentence = (text) => { const m = (text || "").match(/^.*?[.:;](\s|$)/); return m ? m[0].trim().replace(/[:;]$/, "") : text; };
// a file: its name opens a preview in a new tab; ↗ follows its sftp:// link (the file manager, with
// the machine mounted over SFTP); ⧉ copies that link
const sftp = (path) => `sftp://${STATIC ? STATIC.host : location.hostname}${path}`;
// in a report, a run's file opens as itself (the page's neighbour); others only over sftp
const local = (abs) => (STATIC && abs.startsWith(STATIC.design.root + "/") ? abs.slice(STATIC.design.root.length + 1).split("/").map(encodeURIComponent).join("/") : null);
function pathRow(label, abs, folder = false, preview = null) {
  const copy = h("button", { class: "pathbtn", title: "copy the sftp:// path", onclick: async () => {
    try { await navigator.clipboard.writeText(sftp(abs)); } catch { const ta = h("textarea", {}, sftp(abs)); document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
    copy.textContent = "✓"; setTimeout(() => (copy.textContent = "⧉"), 1200);
  } }, "⧉");
  const href = preview || (STATIC ? local(abs) : `/file?path=${encodeURIComponent(abs)}`);
  return h("span", { class: "pathrow" },
    folder || !href ? h("span", { class: "pathname", title: abs }, label) : h("a", { class: "pathname", href, target: "_blank", title: abs }, label),
    h("a", { class: "pathbtn", href: sftp(abs), title: "open (sftp://)" }, "↗"), copy);
}

const plotLabel = (png) => base(png).replace(/\.png$/, "").replace(/_/g, " ");

// ---------------------------------------------------------------- tables, violations, logs

function table(t, mark) {
  const [head, ...rows] = t.rows;
  const passCol = head.indexOf("pass");
  return h("div", { class: "tablewrap" },
    h("table", { class: "data" + (mark ? " clickable" : "") },
      h("tr", {}, head.map((c) => h("th", {}, c))),
      rows.map((r) => h("tr", { onclick: mark ? () => mark(r, head) : null, title: mark ? "show on the layout" : null }, r.map((c, i) => h("td", { class: i === passCol ? `pass-${c}` : null }, fmt(c)))))));
}

function violations(boxes, pick) {
  return h("div", { class: "tablewrap" }, h("table", { class: "data clickable" },
    h("tr", {}, ["rule", "where (mm)", "what"].map((c) => h("th", {}, c))),
    boxes.slice(0, 500).map((m) => h("tr", { onclick: () => pick(m) }, h("td", {}, m.rule), h("td", {}, `${((m.box[0] + m.box[2]) / 2).toFixed(3)}, ${((m.box[1] + m.box[3]) / 2).toFixed(3)}`), h("td", {}, m.what)))));
}

function fmt(c) {
  const x = Number(c);
  return c !== "" && Number.isFinite(x) && !Number.isInteger(x) ? x.toPrecision(4) : c;
}

// one run.log line: "13:41:04 INFO  [gdscheck]   text"
function logLine(line) {
  const m = line.match(/^(\S+) (INFO|WARN|ERROR)\s+(\[[^\]]*\])\s+(.*)$/);
  if (!m) return h("div", {}, line);
  return h("div", { class: `lv-${m[2]}` }, h("span", { class: "ts" }, m[1] + " "), h("span", { class: "lv" }, m[2].padEnd(6)), h("span", { class: "tool" }, m[3].padEnd(13)), m[4]);
}


// ---------------------------------------------------------------- interactive plots (Plotly)

async function plotPane(design, p, lead = null) {
  const png = fileUrl(design, p.png);
  if (!p.data || !window.Plotly) return h("img", { src: png, class: "plotpng" });
  const fig = await once(fileUrl(design, p.data));
  const el = h("div", { class: "plotly" });
  // a figure of several panels: one at a time, full size, picked from a list (nets, runs)
  // the last panel first (the realistic eye, the victim's noise); each named by its y axis where
  // those differ, else by its title without the details in brackets
  let pick = fig.axes.length - 1;
  const ys = fig.axes.map((ax) => ax.ylabel);
  const byY = new Set(ys).size === ys.length && ys.every(Boolean);
  const label = (ax, k) => (byY ? ax.ylabel : (ax.title || "").replace(/\s*\(.*$/, "")) || `panel ${k + 1}`;
  // panels of one kind (the same y axis: an eye per node or run) in a list; of different kinds as tabs
  // panels over one x axis of different kinds (aggressors and the victim's noise) one above the other
  const stack = fig.stacked && byY;
  const select = fig.axes.length < 2 || stack ? null : !byY
    ? h("select", { class: "panelpick", onchange: (e) => { pick = Number(e.target.value); draw(); } }, fig.axes.map((ax, k) => h("option", { value: k, selected: k === pick ? "" : null }, label(ax, k))))
    : h("span", { class: "pages" }, fig.axes.map((ax, k) => h("a", { class: k === pick ? "on" : null, onclick: (e) => { pick = k; e.target.parentNode.querySelectorAll("a").forEach((x, j) => x.classList.toggle("on", j === k)); draw(); } }, label(ax, k))));
  const tops = [];  // [panel axis, its top axis, the map between them]
  const follow = (ev) => {
    if (!tops.length || Object.keys(ev).some((key) => tops.some(([, id]) => key.startsWith(`xaxis${id}`)))) return;
    const upd = {};
    for (const [n, id, f] of tops) { const r = el.layout[`xaxis${n}`].range; upd[`xaxis${id}.range`] = [f(r[0]), f(r[1])]; }
    window.Plotly.relayout(el, upd);
  };
  const draw = () => {
    // one panel at a time, always over the whole area (not where the PNG's layout put it), so every
    // plot has one width
    const gap = 0.09, hk = (1 - gap * (fig.axes.length - 1)) / fig.axes.length;
    const axesShown = stack
      ? fig.axes.map((ax, k) => ({ ...ax, box: [0, 1 - (k + 1) * hk - k * gap, 1, 1 - k * (hk + gap)], xlabel: k === fig.axes.length - 1 ? ax.xlabel : "" }))
      : [{ ...fig.axes[select ? pick : 0], box: [0, 0, 1, 1], title: select ? "" : fig.axes[0].title }];
    const ink = css("--ink-1"), grid = css("--line-2"), dim = css("--ink-4");
    const traces = [], layout = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: ink, family: css("--font-mono"), size: 11 }, margin: { l: 60, r: 20, t: fig.title ? 36 : 14, b: 84 }, showlegend: true, legend: { orientation: "h", x: 0.5, xanchor: "center", yref: "container", y: 0.01, yanchor: "bottom", bgcolor: "rgba(0,0,0,0)", font: { size: 10 } }, title: fig.title ? { text: fig.title, font: { size: 12 } } : undefined, annotations: [] };
    const seen = new Map();  // the PNG's colours, one palette colour each (across stacked panels too)
    tops.length = 0;
    axesShown.forEach((ax, k) => {
      const n = k ? k + 1 : "";
      const axis = (label, log, lim, dom) => ({ title: { text: label, font: { size: 11 } }, type: log ? "log" : "linear", range: log ? lim.map((v) => Math.log10(Math.max(v, 1e-300))) : lim, domain: dom, gridcolor: grid, zerolinecolor: grid, linecolor: dim, mirror: true, ticks: "inside" });
      layout[`xaxis${n}`] = { ...axis(ax.xlabel, ax.xlog, ax.xlim, [ax.box[0], ax.box[2]]), anchor: `y${n}`, ...(stack && k ? { matches: "x" } : {}), ...(stack && k < axesShown.length - 1 ? { showticklabels: false } : {}) };
      layout[`yaxis${n}`] = { ...axis(ax.ylabel, ax.ylog, ax.ylim, [ax.box[1], ax.box[3]]), anchor: `x${n}` };
      if (ax.title) layout.annotations.push({ text: ax.title, xref: "paper", yref: "paper", x: (ax.box[0] + ax.box[2]) / 2, y: ax.box[3], yanchor: "bottom", showarrow: false, font: { size: 11 } });
      if (ax.x2) {  // a second x axis on top, linear in the first (TDR: distance over time), following its zoom
        const id = 20 + k, f = (v) => ax.x2.k * v + ax.x2.b;
        layout[`xaxis${n}`].mirror = false;
        layout[`xaxis${id}`] = { ...axis(ax.x2.label, false, ax.xlim.map(f), [ax.box[0], ax.box[2]]), overlaying: `x${n}`, side: "top", anchor: `y${n}`, showgrid: false, mirror: false };
        traces.push({ type: "scatter", mode: "lines", xaxis: `x${id}`, yaxis: `y${n}`, x: ax.xlim.map(f), y: [ax.ylim[0], ax.ylim[0]], opacity: 0, hoverinfo: "skip", showlegend: false });
        tops.push([n, id, f]);
      }
      for (const im of ax.images) {
        const ny = im.z.length, nx = im.z[0].length;
        traces.push({ type: "heatmap", xaxis: `x${n}`, yaxis: `y${n}`, z: im.log ? im.z.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : im.z, x0: im.x0 + (im.x1 - im.x0) / nx / 2, dx: (im.x1 - im.x0) / nx, y0: im.y0 + (im.y1 - im.y0) / ny / 2, dy: (im.y1 - im.y0) / ny, zmin: im.log ? Math.log10(im.zmin) : im.zmin, zmax: im.log ? Math.log10(im.zmax) : im.zmax, colorscale: [[0, "#5e81ac"], [1, "#bf616a"]], showscale: k === 0, colorbar: { title: { text: im.log ? "log10" : "", side: "right" }, thickness: 10 }, hoverongaps: false });
      }
      const scale = (rev) => (rev ? [[0, "#bf616a"], [1, "#5e81ac"]] : [[0, "#5e81ac"], [1, "#bf616a"]]);
      for (const m of ax.meshes || []) {
        const mid = (e) => e.slice(1).map((v, j) => (v + e[j]) / 2);
        // a density (an eye's samples): smoothed, with its colour bar as the legend
        traces.push({ type: "heatmap", xaxis: `x${n}`, yaxis: `y${n}`, x: mid(m.x), y: mid(m.y), z: m.log ? m.z.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : m.z, colorscale: scale(false), zsmooth: "best", showscale: k === 0, colorbar: { thickness: 10, len: 0.6, title: { text: m.log ? "samples (log10)" : "samples", side: "right" } }, hoverongaps: false });
      }
      for (const f of ax.fills || []) traces.push({ type: "scatter", mode: "lines", xaxis: `x${n}`, yaxis: `y${n}`, x: [...f.x, f.x[0]], y: [...f.y, f.y[0]], fill: "toself", fillcolor: f.color, opacity: Math.min(0.25, f.alpha), line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      for (const p of ax.points || []) {
        const c = p.c && (p.log ? p.c.map((v) => (v > 0 ? Math.log10(v) : null)) : p.c);
        traces.push({ type: "scattergl", mode: "markers", xaxis: `x${n}`, yaxis: `y${n}`, x: p.x, y: p.y, name: p.label || undefined, showlegend: !!p.label, marker: c ? { color: c, colorscale: scale(p.reversed), size: Math.max(3, Math.min(9, p.size)), showscale: true, colorbar: { thickness: 10, len: 0.45, title: { text: p.log ? "log10" : "" } } } : { color: css("--ink-4"), size: Math.max(2, Math.min(6, p.size)) } });
      }
      for (const t of ax.texts || []) layout.annotations.push(t.data ? { text: t.text.replace(/\n/g, "<br>"), x: t.x, y: t.y, xref: `x${n}`, yref: `y${n}`, showarrow: false, font: { size: 10 } } : { text: t.text.replace(/\n/g, "<br>"), x: ax.box[0] + t.x * (ax.box[2] - ax.box[0]), y: ax.box[1] + t.y * (ax.box[3] - ax.box[1]), xref: "paper", yref: "paper", showarrow: false, font: { size: 10 } });
      if (ax.equal) layout[`yaxis${n}`].scaleanchor = `x${n}`;
      // lines in the theme's palette (the PNG's is for white paper), in the order drawn
      const palette = document.documentElement.dataset.theme === "light" ? ["#5e81ac", "#d08770", "#a3be8c", "#b48ead", "#bf616a", "#8fbcbb"] : ["#88c0d0", "#ebcb8b", "#a3be8c", "#b48ead", "#d08770", "#8fbcbb"];
      for (const l of ax.lines) {
        if (!seen.has(l.color)) seen.set(l.color, palette[seen.size % palette.length]);
        const c = seen.get(l.color);
        traces.push({ type: "scattergl", mode: l.markers ? "markers" : "lines", xaxis: `x${n}`, yaxis: `y${n}`, x: l.x, y: l.y, name: l.label || undefined, showlegend: !!l.label, line: { color: c, width: Math.max(1.2, l.width), dash: l.dash ? "dash" : "solid" }, marker: { color: c, size: 4 } });
      }
    });
    window.Plotly.react(el, traces, layout, { responsive: true, displaylogo: false, displayModeBar: false }).then(() => { if (!el.followed) { el.on("plotly_relayout", follow); el.followed = true; } });
  };
  themeListeners.add(draw);
  requestAnimationFrame(draw);
  // the same controls as the layout views: fit, and the flow's own PNG and PDF of the figure
  const tools = h("div", { class: "tools row" }, lead, select,
    h("button", { class: "fit", title: "back to the whole plot", onclick: () => window.Plotly.relayout(el, Object.fromEntries(Object.keys(el.layout || {}).filter((k) => /^[xy]axis\d*$/.test(k)).map((k) => [`${k}.autorange`, true]))) }, "fit"),
    h("a", { class: "fit", href: png, target: "_blank", title: "the figure as PNG" }, "png"),
    h("a", { class: "fit", href: png.replace(/\.png$/, ".pdf"), target: "_blank", title: "the figure as PDF" }, "pdf"));
  return h("div", {}, tools, el);
}

// figures of one kind, one per pair (net): a list to pick the pair, its figure below
async function plotGroup(design, items) {
  const holder = h("div");
  const show = async (k) => holder.replaceChildren(await plotPane(design, items[k][1], pick));
  const pick = h("select", { class: "panelpick", title: "the pair (net)", onchange: (e) => show(Number(e.target.value)) }, items.map(([pair], k) => h("option", { value: k }, pair || "—")));
  await show(0);
  return holder;
}

// ---------------------------------------------------------------- KiCad drawings, inline

// a schematic's sheets or a board, as KiCad drew them in the page's colours (Nord themes when
// dark), inline: pan, zoom, sheets as tabs; redrawn when the system's theme changes
async function svgViewer(themes, index = null, grey = false) {
  const holder = h("div", { class: "schematic" + (grey ? " grey" : "") });
  const bar = h("div", { class: "pages" });
  const cache = new Map();
  let k = 0, vb = null, marked = [], picked = [], warned = [], svgNow = null;
  // where a name is on the sheet: a pin (REF.PIN), a net's labels, a symbol (REF)
  const places = (name) => {
    if (!index) return [];
    if (index.pins[name]) return [index.pins[name]];
    const net = name.replace(/^.*\//, "").toUpperCase();
    if (index.labels[net]) return index.labels[net];
    const ref = index.refs[name.split(".")[0]];
    return ref ? [ref] : [];
  };
  const info = h("div", { class: "picked", style: "display:none" });
  const say = (name, note, colour) => { info.style.display = ""; info.replaceChildren(h("strong", { style: `color:${colour}` }, name), note ? h("div", {}, note) : null); };
  let findings = [];
  const findingOf = (name) => findings.filter((m) => (m.names || []).includes(name)).map((m) => `${m.rule}: ${m.what}`).join("\n");
  const drawMarks = () => {
    if (!svgNow) return;
    svgNow.querySelector("g.marks")?.remove();
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "marks");
    const err = css("--sem-error"), warn = css("--sem-warn");
    const all = [...warned.map((n) => [n, warn, "not checked by any layout label"]), ...marked.map((n) => [n, err, ""])];
    for (const [name, colour, note] of all) for (const [x, y] of places(name)) {
      const hot = picked.includes(name), r = hot ? 3.2 : 2.4;  // a box around it, as the layout's markers
      const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      box.setAttribute("x", x - r); box.setAttribute("y", y - r); box.setAttribute("width", 2 * r); box.setAttribute("height", 2 * r);
      box.setAttribute("fill", colour); box.setAttribute("fill-opacity", hot ? 0.4 : 0.25); box.setAttribute("stroke", colour); box.setAttribute("stroke-width", hot ? 0.7 : 0.45);
      box.style.cursor = "pointer";
      box.addEventListener("click", (e) => { e.stopPropagation(); say(name, note || findingOf(name), colour); });
      g.append(box);
    }
    svgNow.append(g);
  };
  const fetchSvg = async (u) => { if (!cache.has(u)) cache.set(u, STATIC ? staticGet(u) : (await fetch(u)).text()); return cache.get(u); };
  const show = async () => {
    const urls = themes[document.documentElement.dataset.theme] || themes.dark;
    bar.replaceChildren(...(urls.length > 1 ? urls.map((u, j) => h("a", { class: j === k ? "on" : null, onclick: () => { k = j; vb = null; show(); } }, base(u).replace(/\.svg$/, ""))) : []));
    const svg = new DOMParser().parseFromString(await fetchSvg(urls[k]), "image/svg+xml").documentElement;
    svg.removeAttribute("width"); svg.removeAttribute("height");
    holder.querySelector("svg")?.remove();
    holder.prepend(svg);
    svg.addEventListener("click", () => { info.style.display = "none"; });
    svgNow = svg;
    drawMarks();
    requestAnimationFrame(() => {
      if (!vb) { const b = svg.getBBox(); vb = [b.x - 2, b.y - 2, b.width + 4, b.height + 4]; }
      const set = () => svg.setAttribute("viewBox", vb.join(" "));
      set();
      let drag = null;
      svg.addEventListener("mousedown", (e) => { drag = [e.clientX, e.clientY, ...vb]; });
      window.addEventListener("mouseup", () => { drag = null; });
      svg.addEventListener("mousemove", (e) => {
        if (!drag) return;
        const s = vb[2] / svg.clientWidth;
        vb = [drag[2] - (e.clientX - drag[0]) * s, drag[3] - (e.clientY - drag[1]) * s, vb[2], vb[3]]; set();
      });
      svg.addEventListener("wheel", (e) => {
        e.preventDefault();
        const r = svg.getBoundingClientRect(), f = Math.exp(e.deltaY * 0.0015);
        const px = vb[0] + ((e.clientX - r.left) / r.width) * vb[2], py = vb[1] + ((e.clientY - r.top) / r.height) * vb[3];
        vb = [px - (px - vb[0]) * f, py - (py - vb[1]) * f, vb[2] * f, vb[3] * f]; set();
      }, { passive: false });
    });
  };
  themeListeners.add(show);
  await show();
  holder.append(info);
  holder.append(h("div", { class: "tools" }, h("button", { class: "fit", title: "back to the whole sheet", onclick: () => { vb = null; show(); } }, "fit")));
  const el = h("div", {}, bar, holder);
  return {
    el,
    mark: (names, focus = [], warn = [], all = null) => {
      marked = names; picked = focus; warned = warn; if (all) findings = all; drawMarks();
      if (focus.length) say(focus.join(", "), findingOf(focus[0]), css("--sem-error"));
      const pts = focus.flatMap(places);
      if (pts.length && svgNow) {  // zoom to the picked ones
        const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
        const pad = 25, x0 = Math.min(...xs) - pad, y0 = Math.min(...ys) - pad;
        vb = [x0, y0, Math.max(...xs) + pad - x0, Math.max(...ys) + pad - y0];
        svgNow.setAttribute("viewBox", vb.join(" "));
      }
    },
  };
}

// ---------------------------------------------------------------- 3D (three.js, WebGL)

let three = null;
async function view3d(b) {
  three ||= Promise.all([
    import("three"),
    import("three/addons/controls/OrbitControls.js"),
    import("three/addons/utils/BufferGeometryUtils.js"),
  ]);
  const [THREE, { OrbitControls }, { mergeGeometries }] = await three;
  const host = h("div", { class: "view3d" });
  const [x0, y0, x1, y1] = b.bbox;
  const size = Math.max(x1 - x0, y1 - y0);
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 0.1;
  const zs = Math.max(1, Math.min(50, (0.01 * size) / total));  // height stretched (at most 50x): the stack about 1 % of the board's length
  // each layer's bottom and top (mm, z up from the bottom of the stack), exaggerated
  const z = {};
  let at = 0;
  for (const l of [...b.stackup].reverse()) { z[l.name] = [at * zs, (at + l.thickness_mm) * zs]; at += l.thickness_mm; }
  const color = layerColors(b.copper, true);

  const scene = new THREE.Scene();
  const group = new THREE.Group();
  group.position.set(-(x0 + x1) / 2, -(y0 + y1) / 2, 0);
  scene.add(group);
  // merged geometries must match: all non-indexed, positions and normals only, no groups
  const plain = (g) => { const n = g.index ? g.toNonIndexed() : g; for (const k of Object.keys(n.attributes)) if (k !== "position" && k !== "normal") n.deleteAttribute(k); n.clearGroups(); return n; };
  const merge = (geos) => (geos.length ? mergeGeometries(geos.map(plain), false) : null);
  // a solid with its outline, as FRIDA's: the edges sharper than 25° in the colour at 45 %
  const outlines = [];
  const addSolid = (geometry, colour, roughness, metalness) => {
    const c = new THREE.Color(colour);
    group.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: c, roughness, metalness, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })));
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), new THREE.LineBasicMaterial({ color: c.clone().multiplyScalar(0.45), transparent: true, opacity: 0.6 }));
    outlines.push(lines);
    group.add(lines);
  };
  const shape = (pts, holes) => {
    const s = new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)));
    for (const hole of holes || []) s.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, y))));
    return s;
  };
  for (const layer of b.copper) {  // copper: the layer's polygons, extruded to its thickness
    const [zb, zt] = z[layer] || [0, 0.01];
    const geos = [];
    for (const p of b.polys) if (p.layer === layer && p.pts.length > 2) {
      const g = new THREE.ExtrudeGeometry(shape(p.pts, p.holes), { depth: Math.max(zt - zb, 1e-4), bevelEnabled: false });
      g.translate(0, 0, zb);
      geos.push(g);
    }
    for (const sg of b.segs) if (sg.layer === layer) {  // traces: boxes along their centreline
      const len = Math.hypot(sg.x2 - sg.x1, sg.y2 - sg.y1);
      if (!len) continue;
      const g = new THREE.BoxGeometry(len + sg.w, sg.w, Math.max(zt - zb, 1e-4));
      g.rotateZ(Math.atan2(sg.y2 - sg.y1, sg.x2 - sg.x1));
      g.translate((sg.x1 + sg.x2) / 2, (sg.y1 + sg.y2) / 2, (zb + zt) / 2);
      geos.push(g);
    }
    const merged = merge(geos);
    if (merged) addSolid(merged, color[layer], 0.5, 0.1);
  }
  const viaGeos = [];
  for (const c of b.cuts || []) {  // GDS via cuts: from the lower layer's bottom to the upper's top
    const zz = c.layers.map((l) => z[l]).filter(Boolean);
    if (zz.length < 2) continue;
    const lo = Math.min(...zz.map((q) => q[0])), hi = Math.max(...zz.map((q) => q[1]));
    const g = new THREE.ExtrudeGeometry(shape(c.pts), { depth: hi - lo, bevelEnabled: false });
    g.translate(0, 0, lo);
    viaGeos.push(g);
  }
  for (const v of b.vias) {  // board vias: cylinders between their outer layers
    const zz = v.layers.map((l) => z[l]).filter(Boolean);
    if (zz.length < 1) continue;
    const lo = Math.min(...zz.map((q) => q[0])), hi = Math.max(...zz.map((q) => q[1]));
    const g = new THREE.CylinderGeometry(v.d / 2, v.d / 2, Math.max(hi - lo, 1e-4), 10);
    g.rotateX(Math.PI / 2);
    g.translate(v.x, v.y, (lo + hi) / 2);
    viaGeos.push(g);
  }
  const vias = merge(viaGeos);
  if (vias) addSolid(vias, "#d8dee9", 0.5, 0.1);
  for (const l of b.stackup) if (l.type !== "copper" && z[l.name]) {  // dielectrics: translucent slabs
    const [zb, zt] = z[l.name];
    const g = new THREE.BoxGeometry(x1 - x0, y1 - y0, Math.max(zt - zb, 1e-4));
    g.translate((x0 + x1) / 2, (y0 + y1) / 2, (zb + zt) / 2);
    group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: l.type === "mask" ? "#4c566a" : "#8fbcbb", transparent: true, opacity: 0.12, depthWrite: false })));
  }
  // FRIDA's lights (physical units: an intensity of pi lights as 1 did)
  scene.add(new THREE.HemisphereLight(0xeceff4, 0x2e3440, 1.1 * Math.PI));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6 * Math.PI);
  sun.position.set(0.6, -1, 1.4);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x88c0d0, 0.5 * Math.PI);
  fill.position.set(-1, 0.8, 0.6);
  scene.add(fill);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch {
    return h("div", { class: "caption" }, "3D needs WebGL, which this browser doesn't offer (in Firefox or Chrome: hardware acceleration on)");
  }
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  host.append(renderer.domElement, h("div", { class: "legend" }, `z ×${zs.toFixed(0)}`));
  const camera = new THREE.PerspectiveCamera(35, 1, size / 1000, size * 20);
  camera.up.set(0, 0, 1);
  camera.position.set(0, -size * 0.55, size * 0.75);  // from the front, mostly above
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  // left-drag orbits, middle- and right-drag pan; the wheel scrolls the page, Ctrl (⌘) + wheel zooms
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
  controls.enableZoom = false;
  renderer.domElement.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const k = Math.exp(e.deltaY * 0.0015);
    camera.position.sub(controls.target).multiplyScalar(k).add(controls.target);
  }, { passive: false });
  controls.saveState();
  host.append(h("div", { class: "tools" }, h("button", { class: "fit", title: "back to the whole board", onclick: () => controls.reset() }, "fit")));
  const theme = () => { scene.background = new THREE.Color(css("--layout-bg")); };
  theme();
  themeListeners.add(theme);
  const resize = () => {
    const w = host.clientWidth, hh = host.clientHeight;
    if (!w || !hh) return;
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host);
  const loop = () => { if (!host.isConnected && host.dataset.started) return; host.dataset.started = "1"; controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  requestAnimationFrame(() => { resize(); loop(); });
  return host;
}

// ---------------------------------------------------------------- layout viewer (GDS or .hyp board)

// layers in greys, lighter on top: the board stays neutral, so result maps and markers carry the
// only colour
const NORD_LAYERS = ["#bf616a", "#ebcb8b", "#a3be8c", "#b48ead", "#88c0d0", "#d08770", "#8fbcbb", "#81a1c1"];
const layerColors = (copper, colourful = false) => {
  const n = copper.length;
  if (colourful) return Object.fromEntries(copper.map((l, i) => [l, i === n - 1 && i > 0 ? "#5e81ac" : NORD_LAYERS[i % NORD_LAYERS.length]]));  // the first views of a design
  return Object.fromEntries(copper.map((l, i) => { const v = Math.round(200 - (n > 1 ? (110 * i) / (n - 1) : 0)); return [l, `rgb(${v},${v + 4},${v + 12})`]; }));
};

// a base64 grid of a board overlay (layz.hyperlynx.plots.board_overlay)
const unb64 = (text, T) => new T(Uint8Array.from(atob(text), (c) => c.charCodeAt(0)).buffer);
const BLUE = [0x5e, 0x81, 0xac], RED = [0xbf, 0x61, 0x6a];
const mixRGB = (t) => BLUE.map((c, k) => Math.round(c + t * (RED[k] - c)));
const mixCSS = (t) => `rgb(${mixRGB(Math.min(1, Math.max(0, t))).join(",")})`;

// a grid's values (0..1 after ``scale``) as an image, blue (low) to red (high), cells of nets not
// kept clear; each empty cell beside filled ones takes their mean (twice), so the smoothed image
// doesn't fade where it meets the copper's edges (it is cut to the copper when drawn)
function gridImage(g, vals, keep, scale) {
  const { nx, ny } = g;
  let t = new Float32Array(nx * ny).fill(NaN);
  for (let k = 0; k < nx * ny; k++) if (keep(g.net[k]) && Number.isFinite(vals[k])) t[k] = scale(vals[k]);
  for (let pass = 0; pass < 2; pass++) {
    const u = t.slice();
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      if (Number.isFinite(t[k])) continue;
      let sum = 0, n = 0;
      if (i > 0 && Number.isFinite(t[k - 1])) { sum += t[k - 1]; n++; }
      if (i < nx - 1 && Number.isFinite(t[k + 1])) { sum += t[k + 1]; n++; }
      if (j > 0 && Number.isFinite(t[k - nx])) { sum += t[k - nx]; n++; }
      if (j < ny - 1 && Number.isFinite(t[k + nx])) { sum += t[k + nx]; n++; }
      if (n) u[k] = sum / n;
    }
    t = u;
  }
  const c = document.createElement("canvas");
  c.width = nx; c.height = ny;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(nx, ny);
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    const v = t[j * nx + i];
    if (!Number.isFinite(v)) continue;
    const q = 4 * ((ny - 1 - j) * nx + i);  // row 0 at the bottom (Y up)
    const [r, gg, bb] = mixRGB(Math.min(1, Math.max(0, v)));
    img.data[q] = r; img.data[q + 1] = gg; img.data[q + 2] = bb; img.data[q + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

// a round length near ``target`` (1, 2 or 5 times a power of ten), and how to write it (mm in)
const niceLength = (target) => { const e = 10 ** Math.floor(Math.log10(target)); return [1, 2, 5, 10].map((m) => m * e).find((v) => v >= target) || 10 * e; };
const lengthText = (mm) => (mm >= 1 ? `${+mm.toPrecision(3)} mm` : `${+(mm * 1000).toPrecision(3)} µm`);

function layoutViewer(b, overlay = null, full = false, mode = "current density") {
  const color = layerColors(b.copper, full && !overlay);
  const shown = new Set(b.copper);
  let picked = null, markers = [], focus = null, showPins = true, showMarks = true;
  const ring = (path, pts) => { pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y))); path.closePath(); };
  const paths = b.polys.map((p) => { const path = new Path2D(); for (const r of [p.pts, ...p.holes]) ring(path, r); return { ...p, path }; });
  const cuts = (b.cuts || []).map((c) => { const path = new Path2D(); ring(path, c.pts); return { ...c, path }; });

  // power integrity on the board (layz.hyperlynx.plots.board_overlay): per layer and side (supply
  // run, return run) the voltage drop from the VRM and the current density, each cell's net; the
  // vias' currents. Nets and layers to show are picked; values on a linear or log scale
  let ov = null;
  if (overlay && overlay.kind === "pi") {
    const grids = [];
    for (const [layer, sides] of Object.entries(overlay.layers)) for (const [side, g] of Object.entries(sides)) grids.push({ layer, side, ext: g.extent, nx: g.nx, ny: g.ny, drop: unb64(g.drop, Float32Array), J: unb64(g.J, Float32Array), net: unb64(g.net, Int16Array) });
    ov = { mode, grids, nets: overlay.nets, on: new Set(overlay.nets.map((_, k) => k)), log: mode !== "voltage drop", images: [] };
    const most = {};  // the layer carrying the most current, shown first
    for (const g of grids) for (const v of g.J) if (v > (most[g.layer] || 0)) most[g.layer] = v;
    const top = Object.entries(most).sort((a2, b2) => b2[1] - a2[1])[0];
    if (top && mode !== "via current") { shown.clear(); shown.add(top[0]); }
  }
  const names = () => new Set([...ov.on].map((k) => ov.nets[k].name));
  const build = () => {  // the shown layers' images of the picked nets, and their range
    if (!ov || ov.mode === "via current") return;
    const key = ov.mode === "voltage drop" ? "drop" : "J";
    let lo = Infinity, hi = -Infinity;
    for (const g of ov.grids) if (shown.has(g.layer)) for (let k = 0; k < g.net.length; k++) {
      const v = g[key][k];
      if (!ov.on.has(g.net[k]) || !Number.isFinite(v) || (ov.log && !(v > 0))) continue;
      if (v < lo) lo = v; if (v > hi) hi = v;
    }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
    if (ov.log) lo = Math.max(lo, hi * 1e-4);
    const [l0, l1] = [Math.log10(lo), Math.log10(hi)];
    const scale = ov.log ? (v) => (Math.log10(Math.max(v, lo)) - l0) / (l1 - l0 || 1) : (v) => (v - lo) / (hi - lo || 1);
    Object.assign(ov, { lo, hi, images: ov.grids.filter((g) => shown.has(g.layer)).map((g) => ({ g, img: gridImage(g, g[key], (n) => ov.on.has(n), scale) })) });
  };
  build();
  const canvas = h("canvas");
  const pickedBox = h("div", { class: "picked", style: "display:none" });
  const wrap = h("div", { class: "canvas" }, canvas, pickedBox);
  const [x0, y0, x1, y1] = b.bbox;
  let view = null;

  const fitTo = ([a0, b0, a1, b1], frac) => {
    const w = canvas.clientWidth, hh = canvas.clientHeight;
    const s = frac * Math.min(w / (a1 - a0 || 1e-3), hh / (b1 - b0 || 1e-3));
    view = { s, tx: w / 2 - (s * (a0 + a1)) / 2, ty: hh / 2 + (s * (b0 + b1)) / 2 };
  };
  const draw = () => {
    const dpr = exporting ? 2 * (window.devicePixelRatio || 1) : window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    if (!canvas.clientWidth) return;
    if (!view) {
      fitTo(b.bbox, 0.92);
      if (focus) {  // to a violation, at most 300 % of the whole layout's view
        const most = 3 * view.s, pad = Math.max(focus[2] - focus[0], focus[3] - focus[1], 0.05) * 6;
        fitTo([focus[0] - pad, focus[1] - pad, focus[2] + pad, focus[3] + pad], 1);
        if (view.s > most) { const [cx, cy] = [(focus[0] + focus[2]) / 2, (focus[1] + focus[3]) / 2]; view = { s: most, tx: canvas.clientWidth / 2 - most * cx, ty: canvas.clientHeight / 2 + most * cy }; }
      }
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (exporting) ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);  // transparent
    else { ctx.fillStyle = css("--layout-bg"); ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight); }
    // a grid at a fifth of the scale bar's length, where its lines are at least 14 px apart (FRIDA's)
    const step = niceLength(110 / view.s), minor = step / 5;
    if (minor * view.s >= 14 && !exporting) {
      ctx.strokeStyle = css("--line-1");
      ctx.lineWidth = 1;
      ctx.beginPath();
      const wx0 = -view.tx / view.s, wx1 = (canvas.clientWidth - view.tx) / view.s;
      const wy1 = view.ty / view.s, wy0 = (view.ty - canvas.clientHeight) / view.s;
      for (let x = Math.ceil(wx0 / minor) * minor; x <= wx1; x += minor) { const sx = Math.round(view.tx + view.s * x) + 0.5; ctx.moveTo(sx, 0); ctx.lineTo(sx, canvas.clientHeight); }
      for (let y = Math.ceil(wy0 / minor) * minor; y <= wy1; y += minor) { const sy = Math.round(view.ty - view.s * y) + 0.5; ctx.moveTo(0, sy); ctx.lineTo(canvas.clientWidth, sy); }
      ctx.stroke();
    }
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    const px = 1 / view.s;
    for (const layer of [...b.copper].reverse()) {
      if (!shown.has(layer)) continue;
      ctx.globalAlpha = ov ? 0.22 : 0.55;
      // with results over it, the copper is one neutral grey: colours are the results' only
      const base = color[layer];
      for (const p of paths) if (p.layer === layer) { ctx.fillStyle = picked && p.net && p.net === picked ? css("--ink-0") : base; ctx.fill(p.path, "evenodd"); }
      ctx.globalAlpha = 0.9;
      ctx.lineCap = "round";
      for (const s of b.segs) if (s.layer === layer) {
        ctx.strokeStyle = picked && s.net === picked ? css("--ink-0") : base;
        ctx.lineWidth = Math.max(s.w, px);
        ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
      }
    }
    if (ov && ov.mode !== "via current") {  // each shown layer's map, smoothed, cut to its picked nets' copper
      const W = canvas.width, H = canvas.height, keep = names();
      const art = document.createElement("canvas"), mask = document.createElement("canvas");
      art.width = mask.width = W; art.height = mask.height = H;
      const a = art.getContext("2d"), m = mask.getContext("2d");
      const world = [dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty];
      for (const layer of [...b.copper].reverse()) {  // the bottom first: the top drawn over it
        if (!shown.has(layer)) continue;
        a.setTransform(1, 0, 0, 1, 0, 0); a.globalCompositeOperation = "source-over"; a.clearRect(0, 0, W, H);
        m.setTransform(1, 0, 0, 1, 0, 0); m.clearRect(0, 0, W, H);
        a.setTransform(...world); m.setTransform(...world);
        a.imageSmoothingEnabled = true; a.imageSmoothingQuality = "high";
        for (const { g, img } of ov.images) if (g.layer === layer) {
          const [ex0, ex1, ey0, ey1] = g.ext;
          a.save(); a.translate(ex0, ey1); a.scale((ex1 - ex0) / g.nx, -(ey1 - ey0) / g.ny); a.drawImage(img, 0, 0); a.restore();
        }
        m.fillStyle = m.strokeStyle = "#fff"; m.lineCap = "round";
        for (const p of paths) if (p.layer === layer && keep.has(p.net)) m.fill(p.path, "evenodd");
        for (const sg of b.segs) if (sg.layer === layer && keep.has(sg.net)) { m.lineWidth = Math.max(sg.w, px); m.beginPath(); m.moveTo(sg.x1, sg.y1); m.lineTo(sg.x2, sg.y2); m.stroke(); }
        a.setTransform(1, 0, 0, 1, 0, 0); a.globalCompositeOperation = "destination-in"; a.drawImage(mask, 0, 0);
        ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(art, 0, 0); ctx.restore();
      }
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = css("--ink-1");
    for (const c of cuts) if (c.layers.some((l) => shown.has(l))) ctx.fill(c.path);
    for (const v of b.vias) if (v.layers.some((l) => shown.has(l))) { ctx.beginPath(); ctx.arc(v.x, v.y, Math.max(v.d / 2, px), 0, 2 * Math.PI); ctx.fill(); }
    ctx.strokeStyle = "#b48ead";
    ctx.lineWidth = px;
    if (showPins) for (const p of b.pins) if (shown.has(p.layer)) ctx.strokeRect(p.x - p.w / 2, p.y - p.h / 2, p.w, p.h);
    ctx.strokeStyle = css("--ink-3");
    ctx.lineWidth = 1.2 * px;
    ctx.beginPath();
    for (const [ax, ay, bx, by] of b.outline) { ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
    ctx.stroke();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (showPins && b.labels && b.labels.length) {  // pin labels, where there's room to read them
      ctx.font = "10px ui-monospace, monospace";
      const onScreen = b.labels.filter((l) => shown.has(l.layer)).map((l) => [l, view.tx + view.s * l.x, view.ty - view.s * l.y]).filter(([, sx, sy]) => sx >= 0 && sy >= 0 && sx <= canvas.clientWidth && sy <= canvas.clientHeight);
      if (onScreen.length <= 300) for (const [l, sx, sy] of onScreen) {
        ctx.fillStyle = color[l.layer];
        ctx.fillRect(sx - 1.5, sy - 1.5, 3, 3);
        ctx.fillStyle = css("--ink-0");
        ctx.fillText(l.text, sx + 4, sy - 3);
      }
    }
    if (ov) {  // vias by current, or the maps' colour scale
      let scale;
      const kind = ov.log ? "log" : "linear";
      if (ov.mode === "via current") {
        const keep = names(), vias = (overlay.vias || []).filter((v) => v.i > 0 && keep.has(v.net)).sort((a2, b2) => a2.i - b2.i);
        const imin = Math.min(...vias.map((v) => v.i)), imax = Math.max(...vias.map((v) => v.i));
        const l0 = Math.log10(imin), sp = Math.log10(imax) - l0 || 1;
        for (const v of vias) {
          ctx.fillStyle = mixCSS(ov.log ? (Math.log10(v.i) - l0) / sp : (v.i - imin) / (imax - imin || 1));
          ctx.beginPath(); ctx.arc(view.tx + view.s * v.x, view.ty - view.s * v.y, 2.5, 0, 2 * Math.PI); ctx.fill();
        }
        scale = vias.length ? [`${(imin * 1e3).toPrecision(2)} mA`, `${(imax * 1e3).toPrecision(3)} mA`, `via current (${kind})`] : null;
      } else if (ov.mode === "voltage drop") {
        scale = [`${ov.lo.toPrecision(3)} mV`, `${ov.hi.toPrecision(3)} mV`, `voltage drop from the VRM, ${[...shown].join(", ")} (${kind})`];
      } else {
        scale = [`${ov.lo.toPrecision(2)} A/mm²`, `${ov.hi.toPrecision(3)} A/mm²`, `current density, ${[...shown].join(", ")} (${kind})`];
      }
      if (scale) {
        // between the scale bar (bottom left) and the stackup (bottom right)
        const room = canvas.clientWidth - 140 - 170, w = Math.max(120, Math.min(220, room - 20)), x = 140 + Math.max(0, (room - w) / 2), y = canvas.clientHeight - 30;
        const grad = ctx.createLinearGradient(x, 0, x + w, 0);
        grad.addColorStop(0, "#5e81ac"); grad.addColorStop(1, "#bf616a");
        ctx.fillStyle = grad; ctx.fillRect(x, y, w, 8);
        ctx.fillStyle = css("--ink-1"); ctx.font = "10px ui-monospace, monospace";
        ctx.fillText(scale[0], x, y + 20);
        ctx.textAlign = "right"; ctx.fillText(scale[1], x + w, y + 20); ctx.textAlign = "center"; ctx.fillText(scale[2], x + w / 2, y - 6); ctx.textAlign = "left";
      }
    }
    {  // the scale bar, bottom left: a round length near 90 px, as it is at this zoom
      const len = niceLength(90 / view.s), w = len * view.s, hh = canvas.clientHeight;
      ctx.fillStyle = exporting ? "rgba(0,0,0,0)" : document.documentElement.dataset.theme === "light" ? "rgba(250,250,250,0.88)" : "rgba(40,44,51,0.88)";
      ctx.fillRect(10, hh - 34, w + 16, 24);
      ctx.strokeStyle = css("--ink-1");
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(18, hh - 18); ctx.lineTo(18, hh - 14); ctx.lineTo(18 + w, hh - 14); ctx.lineTo(18 + w, hh - 18); ctx.stroke();
      ctx.fillStyle = css("--ink-1");
      ctx.font = "11px ui-monospace, monospace";
      ctx.textAlign = "center";
      ctx.fillText(lengthText(len), 18 + w / 2, hh - 20);
      ctx.textAlign = "left";
    }
    if (exporting) drawStack(ctx, b, color, shown, canvas.clientWidth, canvas.clientHeight);
    // the violations: boxes in the error colour, at least 8 pixels across (as FRIDA's)
    if (showMarks && markers.length) {
      const err = css("--sem-error");
      ctx.strokeStyle = err;
      ctx.fillStyle = err + "33";
      ctx.lineWidth = 1.5;
      for (const m of markers) {
        const [ax, ay] = [view.tx + view.s * m.box[0], view.ty - view.s * m.box[3]];
        const [bx, by] = [view.tx + view.s * m.box[2], view.ty - view.s * m.box[1]];
        const w = Math.max(bx - ax, 8), hh = Math.max(by - ay, 8);
        const l = (ax + bx) / 2 - w / 2, t = (ay + by) / 2 - hh / 2;
        ctx.fillRect(l, t, w, hh);
        ctx.strokeRect(l, t, w, hh);
      }
    }
  };

  let drag = null;
  canvas.addEventListener("mousedown", (e) => { drag = { x: e.offsetX, y: e.offsetY, tx: view.tx, ty: view.ty, moved: false }; });
  window.addEventListener("mouseup", (e) => { if (drag && !drag.moved && e.target === canvas) pick(e.offsetX, e.offsetY); drag = null; });
  canvas.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const dx = e.offsetX - drag.x, dy = e.offsetY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    view.tx = drag.tx + dx; view.ty = drag.ty + dy; draw();
  });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const k = Math.exp(-e.deltaY * 0.0015);
    view.tx = e.offsetX - k * (e.offsetX - view.tx);
    view.ty = e.offsetY - k * (e.offsetY - view.ty);
    view.s *= k; draw();
  }, { passive: false });
  const say = (m) => { pickedBox.style.display = ""; pickedBox.replaceChildren(h("strong", {}, m.rule), m.what ? h("div", {}, m.what) : null, h("div", { class: "caption" }, `at ${((m.box[0] + m.box[2]) / 2).toFixed(3)}, ${((m.box[1] + m.box[3]) / 2).toFixed(3)} mm`)); };
  const pick = (sx, sy) => {
    const near = markers.find((m) => {  // a marked violation under the click (its box, at least 8 px)
      const ax = view.tx + view.s * m.box[0], bx = view.tx + view.s * m.box[2], ay = view.ty - view.s * m.box[3], by = view.ty - view.s * m.box[1];
      const w = Math.max(bx - ax, 8) / 2 + 2, hh = Math.max(by - ay, 8) / 2 + 2;
      return Math.abs(sx - (ax + bx) / 2) <= w && Math.abs(sy - (ay + by) / 2) <= hh;
    });
    if (near) { say(near); return; }
    const x = (sx - view.tx) / view.s, y = (view.ty - sy) / view.s;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const hit = b.copper.filter((l) => shown.has(l)).flatMap((l) => paths.filter((p) => p.layer === l)).find((p) => ctx.isPointInPath(p.path, x, y, "evenodd"))
      || b.segs.find((s) => shown.has(s.layer) && segDist(s, x, y) <= s.w / 2);
    picked = hit ? hit.net : null;
    pickedBox.style.display = hit ? "" : "none";
    if (hit) {
      const pins = b.pins.filter((p) => p.net && p.net === picked).map((p) => p.ref);
      pickedBox.textContent = (hit.net ? `${hit.net} on ${hit.layer}` : hit.layer) + (pins.length ? `: ${pins.slice(0, 8).join(" ")}${pins.length > 8 ? " …" : ""}` : "");
    }
    draw();
  };
  new ResizeObserver(() => { view = null; draw(); }).observe(wrap);
  themeListeners.add(draw);
  // the stackup, bottom right: click a copper layer to hide or show it
  const toggle = (l) => {
    if (shown.has(l)) shown.delete(l); else shown.add(l);
    build(); stack.refresh(); draw();
  };
  const stack = stackPanel(b, color, shown, toggle);
  const tools = h("div", { class: "tools" });
  wrap.append(tools);
  tools.append(h("button", { class: "fit", title: "back to the whole layout", onclick: () => { focus = null; view = null; draw(); } }, "fit"));
  const switchBtn = (label, title, get, set) => { const el2 = h("button", { class: "fit", title, onclick: () => { set(!get()); el2.classList.toggle("off", !get()); draw(); } }, label); return el2; };
  if ((b.labels && b.labels.length) || b.pins.length) tools.append(switchBtn("pins", "show or hide the pin labels (exports too)", () => showPins, (v) => (showPins = v)));
  if (ov) tools.append(switchBtn("log", "log or linear colour scale (exports too)", () => ov.log, (v) => { ov.log = v; build(); }));
  if (ov) {  // the nets, by side: tick to show
    const box = h("div", { class: "netpick" });
    const sides = [...new Set(ov.nets.map((n) => n.side))];
    const tick = (k) => h("label", {}, h("input", { type: "checkbox", checked: "", onchange: (e) => { e.target.checked ? ov.on.add(k) : ov.on.delete(k); build(); draw(); } }), ov.nets[k].name);
    for (const side of sides) box.append(h("div", { class: "side" }, h("span", { class: "dim" }, side), ov.nets.map((n, k) => (n.side === side ? tick(k) : null))));
    wrap.append(box);
  }
  const marksBtn = switchBtn("annotations", "show or hide the violations (exports too)", () => showMarks, (v) => (showMarks = v));
  // the view as it is, in the light theme's colours on a transparent background, at twice the
  // screen's resolution: PNG, or a PDF of it
  const shot = () => { exporting = true; draw(); const url = canvas.toDataURL("image/png"); const size = [canvas.width, canvas.height]; exporting = false; draw(); return [url, size]; };
  const stem = () => `${b.name.replace(/\.[^.]+$/, "")}${ov ? "_" + ov.mode.replace(/ /g, "_") : ""}`;
  tools.append(h("button", { class: "fit", title: "PNG of this view (light, transparent)", onclick: () => { const [url] = shot(); h("a", { href: url, download: `${stem()}.png` }).click(); } }, "png"));
  tools.append(h("button", { class: "fit", title: "PDF of this view (light, transparent)", onclick: async () => {
    window.jspdf || (await new Promise((ok, fail) => document.head.append(h("script", { src: "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js", onload: ok, onerror: fail }))));
    const [url, [w, hh]] = shot();
    const pdf = new window.jspdf.jsPDF({ orientation: w > hh ? "landscape" : "portrait", unit: "px", format: [w / 2, hh / 2], hotfixes: ["px_scaling"] });
    pdf.addImage(url, "PNG", 0, 0, w / 2, hh / 2);
    pdf.save(`${stem()}.pdf`);
  } }, "pdf"));

  wrap.append(h("div", { class: "stackover" }, stack));  // on the grid itself
  const el = h("div", { class: "layout" + (full ? "" : " bare") }, wrap);
  return { el, setMarkers: (boxes, at = null) => { if (boxes.length && !marksBtn.isConnected) tools.insertBefore(marksBtn, tools.children[1]); markers = boxes; focus = at ? at.box || at : null; view = null; draw(); if (at && at.rule) say(at); } };
}

function segDist(s, x, y) {
  const dx = s.x2 - s.x1, dy = s.y2 - s.y1;
  const t = Math.max(0, Math.min(1, ((x - s.x1) * dx + (y - s.y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(x - (s.x1 + t * dx), y - (s.y1 + t * dy));
}

// the stackup, top to bottom: each metal in its layer's colour, the insulators grey; click a metal
// to hide or show it
const stackHeight = (l, total) => Math.max(12, Math.min(30, (160 * l.thickness_mm) / total));
const stackUm = (mm) => `${(mm * 1000).toFixed(mm < 0.01 ? 1 : 0)} µm`;
function stackPanel(b, color, shown, toggle) {
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 1;
  const rows = b.stackup.map((l) => {
    const el = h("div", { class: l.type, style: `height:${stackHeight(l, total)}px` + (l.type === "copper" && color[l.name] ? `;background:${color[l.name]}` : ""), title: `${l.name}: ${l.material || l.type}, ${stackUm(l.thickness_mm)}` + (l.er ? `, εr ${l.er}` : "") },
      l.name, h("span", { class: "t" }, stackUm(l.thickness_mm)));
    if (l.type === "copper") el.onclick = () => toggle(l.name);
    return [l, el];
  });
  const el = h("div", { class: "stack" }, rows.map(([, e]) => e));
  el.refresh = () => rows.forEach(([l, e]) => l.type === "copper" && e.classList.toggle("off", !shown.has(l.name)));
  el.refresh();
  return el;
}

// the same stackup drawn on an exported view, bottom right (the panel is no part of the canvas)
function drawStack(ctx, b, color, shown, W, H) {
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 1;
  const w = 150, hs = b.stackup.map((l) => stackHeight(l, total));
  let y = H - 10 - hs.reduce((a, v) => a + v, 0);
  const x = W - 10 - w;
  ctx.font = "9px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  b.stackup.forEach((l, i) => {
    ctx.globalAlpha = l.type === "copper" && !shown.has(l.name) ? 0.3 : 1;
    ctx.fillStyle = l.type === "copper" && color[l.name] ? color[l.name] : "#d8dee9";
    ctx.fillRect(x, y, w, hs[i]);
    ctx.strokeStyle = "rgba(0,0,0,0.25)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, y + hs[i] - 0.5); ctx.lineTo(x + w, y + hs[i] - 0.5); ctx.stroke();
    ctx.fillStyle = "#2e3440";
    ctx.textAlign = "center"; ctx.fillText(l.name, x + w / 2, y + hs[i] / 2);
    ctx.textAlign = "right"; ctx.fillText(stackUm(l.thickness_mm), x + w - 4, y + hs[i] / 2);
    y += hs[i];
  });
  ctx.globalAlpha = 1; ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
}

// a board's facts (layz.web.facts): one table
function factsTable(rows) {
  return rows && rows.length ? h("div", { class: "tablewrap" }, h("table", { class: "data" }, h("tr", {}, h("th", {}, "fact"), h("th", {}, "value")), rows.map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v))))) : null;
}

// the wheel scrolls the page; a view (layout, schematic, 3D, a plot, a table, a log) takes it only
// once clicked, until a click elsewhere
const GRAB = ".canvas, .schematic, .view3d, .plotly, .tabbody, .tablewrap, pre.log";
let grabbed = null;
document.addEventListener("mousedown", (e) => {
  grabbed?.classList.remove("grabbed");
  grabbed = e.target.closest?.(".canvas, .schematic, .view3d, .plotly, .tabbody") || null;  // the view clicked in
  grabbed?.classList.add("grabbed");
}, true);
window.addEventListener("wheel", (e) => {
  const region = e.target.closest?.(GRAB);
  if (!region || (grabbed && (grabbed === region || grabbed.contains(region)))) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  $("#main").scrollBy({ top: e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? innerHeight : 1) });
}, { capture: true, passive: false });

initTheme();
window.addEventListener("hashchange", render);
render();
