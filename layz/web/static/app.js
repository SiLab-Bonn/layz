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
const getJSON = async (url) => {
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
};
const memo = new Map();
const once = (url) => { if (!memo.has(url)) memo.set(url, getJSON(url)); return memo.get(url); };
const state = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const go = (patch) => { location.hash = new URLSearchParams(patch).toString(); };
const fileUrl = (design, rel) => `/results/${encodeURIComponent(design)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
const base = (p) => (p || "").split("/").pop();
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
  const { design } = state();
  themeListeners.clear();
  const main = $("#main");
  try {
    main.replaceChildren(design ? await designPage(design) : await homePage());
  } catch (e) {
    main.replaceChildren(h("div", { class: "empty" }, String(e.message || e)));
  }
}

// ---------------------------------------------------------------- home: every design's last run

const done = (t) => t.status === "ok" || t.status === "skipped";
const chip = (status, text) => h("span", { class: `chip ${status}` }, text ?? status);

async function homePage() {
  const designs = await getJSON("/api/designs");
  if (!designs.length) return h("div", { class: "empty" }, "No runs yet: layz run designs/NAME records one in results/NAME/.");
  const status = (d) => {
    const failed = d.targets.find((t) => t.status === "failed");
    return failed ? chip("failed", `stopped at ${failed.name}`) : d.targets.every(done) ? chip("ok") : chip("pending", "running");
  };
  return h("div", { class: "page" },
    h("h2", {}, "designs: click one to open its run"),
    h("table", { class: "data designs" },
      h("tr", {}, ["design", "status", "targets done", "layout", "board", "run"].map((c) => h("th", {}, c))),
      designs.map((d) => h("tr", { onclick: () => go({ design: d.name }) },
        h("td", {}, d.name), h("td", {}, status(d)),
        h("td", {}, `${d.targets.filter(done).length} / ${d.targets.length}`),
        h("td", {}, base(d.inputs.layout)), h("td", {}, base(d.inputs.board)), h("td", {}, d.started)))));
}

// ---------------------------------------------------------------- one design, top to bottom

async function designPage(name) {
  memo.clear();
  const d = await getJSON(`/api/design?name=${encodeURIComponent(name)}`);
  const n = d.targets.filter(done).length;
  const jump = (t) => (e) => { e.preventDefault(); document.getElementById(`t-${t.name}`)?.scrollIntoView({ behavior: "smooth" }); };
  return h("div", { class: "page" },
    h("div", { class: "title" },
      h("a", { class: "home", href: "#", title: "every design" }, d.name),
      h("span", { class: d.targets.some((t) => t.status === "failed") ? "bad" : n === d.targets.length ? "good" : "dim" }, `${n}/${d.targets.length} steps`),
      h("span", { class: "dim" }, d.started),
      h("a", { href: `/flow?name=${encodeURIComponent(d.name)}`, target: "_blank" }, "flow.py")),
    h("nav", { class: "toc" }, d.targets.map((t) => h("a", { onclick: jump(t) }, chip(t.status, ""), t.name))),
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
  entries.forEach(([label], i) => bar.append(h("a", { onclick: () => show(i) }, label)));
  show(0);
  const box = h("div", { class: "tabbox" }, bar, body);
  box.show = (label) => show(Math.max(0, entries.findIndex(([l]) => l === label)));
  box.current = () => entries[[...bar.querySelectorAll("a")].findIndex((a) => a.classList.contains("on"))]?.[0];
  return box;
}

function lazy(make) {
  // heavy panes (layouts, plots, drawings) are built when they scroll into view
  const slot = h("div", { class: "lazy" }, h("div", { class: "caption" }, "loading…"));
  new IntersectionObserver(async (entries, obs) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    obs.disconnect();
    try { slot.replaceChildren(await make()); } catch (e) { slot.replaceChildren(h("div", { class: "caption" }, String(e.message || e))); }
  }, { rootMargin: "300px" }).observe(slot);
  return slot;
}

function stage(d, t, i) {
  const inputs = () => once(`/api/inputs?name=${encodeURIComponent(d.name)}`);
  const board = () => once(`/api/board?name=${encodeURIComponent(d.name)}`);
  const isBoard = d.inputs.board && t.status === "ok" && boardTarget(d) === t.name;
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
    right.push([`layout · ${t.markers.boxes.length} marked`, async () => {
      const b = t.markers.on === "board" ? await board() : (await inputs()).layout;
      if (!b) return h("div", { class: "caption" }, "no layout to mark");
      viewer = layoutViewer(b);
      viewer.setMarkers(t.markers.boxes);
      return viewer.el;
    }]);
  }
  for (const o of t.overlays || []) right.push([`on the board`, async () => layoutViewer(await board(), await once(fileUrl(d.name, o))).el]);
  let sheet = null; // the schematic this stage marks its findings on
  const unchecked = (t.summary && t.summary["unchecked nets"]) || [];
  if (t.name.includes("lvs") && t.markers && (t.markers.boxes.some((m) => m.names) || unchecked.length)) right.push([`schematic · marked`, async () => {
    const inp = await inputs();
    if (!inp.schematic_svgs || !inp.schematic_index) return h("div", { class: "caption" }, "no KiCad schematic to mark");
    sheet = await svgViewer(inp.schematic_svgs, inp.schematic_index);
    sheet.mark(t.markers.boxes.flatMap((m) => m.names || []), [], unchecked, t.markers.boxes);
    return sheet.el;
  }]);
  if (isBoard) right.push(["board", async () => layoutViewer(await board()).el]);
  if (isBoard) right.push(["board 3D", async () => view3d(await board())]);
  const REPLACES = { dc: ["dc_current_density", "dc_loss_map", "dc_pin_voltage", "dc_via_current"] };  // maps an overlay draws on the board
  const replaced = new Set((t.overlays || []).flatMap((o) => REPLACES[base(o).split("_")[0]] || []));
  for (const p of t.plots) if (!replaced.has(base(p.png).replace(/\.png$/, ""))) right.push([plotLabel(p.png), async () => plotPane(d.name, p)]);

  // left: numbers
  const mark = (rule) => {
    if (!t.markers) return;
    const boxes = t.markers.boxes.filter((m) => !rule || m.rule === rule);
    if (!boxes.length) return;
    rightTabs.show(`layout · ${t.markers.boxes.length} marked`);
    setTimeout(() => viewer && viewer.setMarkers(boxes, boxes[0]), 50);
  };
  const left = [];
  if (t.name === "setup") left.push(["inputs", () => h("table", { class: "kvtable" }, h("tr", {}, h("td", {}, "flow"), h("td", {}, d.flow)), Object.entries(d.inputs).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v))))]);
  if (t.name === "setup") left.push(["layout facts", async () => { const inp = await inputs(); return inp.layout ? h("div", { class: "facts" }, layoutFacts(inp.layout)) : h("div", { class: "caption" }, "—"); }]);
  if (isBoard) left.push(["board facts", async () => h("div", { class: "facts" }, layoutFacts(await board()))]);
  const names = t.tables.map((tb) => tb.path.split("/").slice(1).join("/").replace(/\.csv$/, ""));
  t.tables.forEach((tb, k) => left.push([names[k], () => table(tb, t.markers ? mark : null)]));
  if (t.markers && t.markers.boxes.length) left.push(["each violation", () => violations(t.markers.boxes, (m) => {
    if (sheet && m.names && rightTabs.current() === "schematic · marked") { sheet.mark(t.markers.boxes.flatMap((x) => x.names || []), m.names, unchecked, t.markers.boxes); return; }
    rightTabs.show(`layout · ${t.markers.boxes.length} marked`);
    setTimeout(() => viewer && viewer.setMarkers(t.markers.boxes, m), 50);
  })]);
  if (t.lines.length) left.push([`log${countLevels(t.lines)}`, () => h("pre", { class: "log" }, t.lines.map(logLine))]);

  const rightTabs = tabs(right);
  const leftTabs = tabs(left);
  return h("section", { class: `target ${t.status}`, id: `t-${t.name}` },
    h("div", { class: "head" },
      h("span", { class: "step" }, String(i + 1).padStart(2, "0")), chip(t.status), h("span", { class: "name" }, t.name),
      h("span", { class: "doc", title: t.doc }, firstSentence(t.doc)), h("span", { class: "caption" }, t.seconds == null ? "" : `${t.seconds.toFixed(0)} s`)),
    t.error ? h("div", { class: "error" }, t.error) : null,
    leftTabs || rightTabs ? h("div", { class: rightTabs && leftTabs ? "split" : "single" }, leftTabs, rightTabs) : null);
}

function boardTarget(d) {
  // the target whose folder holds the board (results/<design>/<target>/...), else "board"
  const parts = d.inputs.board.split("/");
  return d.targets.find((t) => parts.includes(t.name))?.name || "board";
}

const overlayName = (o) => ({ dc: "current density" })[base(o).split("_")[0]] || base(o).replace(/\.overlay\.json$/, "");
const firstSentence = (text) => { const m = (text || "").match(/^.*?[.:;](\s|$)/); return m ? m[0].trim().replace(/[:;]$/, "") : text; };
const plotLabel = (png) => base(png).replace(/\.png$/, "").replace(/_/g, " ");

// ---------------------------------------------------------------- tables, violations, logs

function table(t, mark) {
  const [head, ...rows] = t.rows;
  const passCol = head.indexOf("pass");
  return h("div", { class: "tablewrap" },
    h("table", { class: "data" + (mark ? " clickable" : "") },
      h("tr", {}, head.map((c) => h("th", {}, c))),
      rows.map((r) => h("tr", { onclick: mark ? () => mark(r[0]) : null, title: mark ? "show on the layout" : null }, r.map((c, i) => h("td", { class: i === passCol ? `pass-${c}` : null }, fmt(c)))))));
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

function countLevels(lines) {
  const n = (lv) => lines.filter((l) => l.includes(` ${lv} `)).length;
  const w = n("WARN"), e = n("ERROR");
  return (e ? ` · ${e} errors` : "") + (w ? ` · ${w} warnings` : "");
}

// ---------------------------------------------------------------- interactive plots (Plotly)

async function plotPane(design, p) {
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
  const select = fig.axes.length > 1 ? h("select", { class: "panelpick", onchange: (e) => { pick = Number(e.target.value); draw(); } }, fig.axes.map((ax, k) => h("option", { value: k, selected: k === pick ? "" : null }, label(ax, k)))) : null;
  const draw = () => {
    const axesShown = select ? [{ ...fig.axes[pick], box: [0, 0, 1, 1], title: "" }] : fig.axes;
    const ink = css("--ink-1"), grid = css("--line-2"), dim = css("--ink-4");
    const traces = [], layout = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: ink, family: css("--font-mono"), size: 11 }, margin: { l: 60, r: 20, t: fig.title ? 36 : 14, b: 46 }, showlegend: true, legend: { orientation: "h", x: 0, xanchor: "left", y: -0.16, yanchor: "top", bgcolor: "rgba(0,0,0,0)", font: { size: 10 } }, title: fig.title ? { text: fig.title, font: { size: 12 } } : undefined, annotations: [] };
    axesShown.forEach((ax, k) => {
      const n = k ? k + 1 : "";
      const axis = (label, log, lim, dom) => ({ title: { text: label, font: { size: 11 } }, type: log ? "log" : "linear", range: log ? lim.map((v) => Math.log10(Math.max(v, 1e-300))) : lim, domain: dom, gridcolor: grid, zerolinecolor: grid, linecolor: dim, mirror: true, ticks: "inside" });
      layout[`xaxis${n}`] = { ...axis(ax.xlabel, ax.xlog, ax.xlim, [ax.box[0], ax.box[2]]), anchor: `y${n}` };
      layout[`yaxis${n}`] = { ...axis(ax.ylabel, ax.ylog, ax.ylim, [ax.box[1], ax.box[3]]), anchor: `x${n}` };
      if (ax.title) layout.annotations.push({ text: ax.title, xref: "paper", yref: "paper", x: (ax.box[0] + ax.box[2]) / 2, y: ax.box[3], yanchor: "bottom", showarrow: false, font: { size: 11 } });
      for (const im of ax.images) {
        const ny = im.z.length, nx = im.z[0].length;
        traces.push({ type: "heatmap", xaxis: `x${n}`, yaxis: `y${n}`, z: im.log ? im.z.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : im.z, x0: im.x0 + (im.x1 - im.x0) / nx / 2, dx: (im.x1 - im.x0) / nx, y0: im.y0 + (im.y1 - im.y0) / ny / 2, dy: (im.y1 - im.y0) / ny, zmin: im.log ? Math.log10(im.zmin) : im.zmin, zmax: im.log ? Math.log10(im.zmax) : im.zmax, colorscale: [[0, "#5e81ac"], [1, "#bf616a"]], showscale: k === 0, colorbar: { title: { text: im.log ? "log10" : "", side: "right" }, thickness: 10 }, hoverongaps: false });
      }
      const scale = (rev) => (rev ? [[0, "#bf616a"], [1, "#5e81ac"]] : [[0, "#5e81ac"], [1, "#bf616a"]]);
      for (const m of ax.meshes || []) {
        const mid = (e) => e.slice(1).map((v, j) => (v + e[j]) / 2);
        traces.push({ type: "heatmap", xaxis: `x${n}`, yaxis: `y${n}`, x: mid(m.x), y: mid(m.y), z: m.log ? m.z.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : m.z, colorscale: scale(false), showscale: false, hoverongaps: false });
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
      const seen = new Map();  // the PNG's colours, one palette colour each
      for (const l of ax.lines) {
        if (!seen.has(l.color)) seen.set(l.color, palette[seen.size % palette.length]);
        const c = seen.get(l.color);
        traces.push({ type: "scattergl", mode: l.markers ? "markers" : "lines", xaxis: `x${n}`, yaxis: `y${n}`, x: l.x, y: l.y, name: l.label || undefined, showlegend: !!l.label, line: { color: c, width: Math.max(1.2, l.width), dash: l.dash ? "dash" : "solid" }, marker: { color: c, size: 4 } });
      }
    });
    window.Plotly.react(el, traces, layout, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  };
  themeListeners.add(draw);
  requestAnimationFrame(draw);
  return h("div", {}, select, el, h("div", { class: "caption" }, h("a", { href: png, target: "_blank" }, "PNG"), " · ", h("a", { href: png.replace(/\.png$/, ".pdf"), target: "_blank" }, "PDF")));
}

// ---------------------------------------------------------------- KiCad drawings, inline

// a schematic's sheets or a board, as KiCad drew them in the page's colours (Nord themes when
// dark), inline: pan, zoom, sheets as tabs; redrawn when the system's theme changes
async function svgViewer(themes, index = null) {
  const holder = h("div", { class: "schematic" });
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
  const fetchSvg = async (u) => { if (!cache.has(u)) cache.set(u, (await fetch(u)).text()); return cache.get(u); };
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
  const zs = Math.max(1, (0.04 * size) / total);  // height exaggerated: a thin stack stays visible
  // each layer's bottom and top (mm, z up from the bottom of the stack), exaggerated
  const z = {};
  let at = 0;
  for (const l of [...b.stackup].reverse()) { z[l.name] = [at * zs, (at + l.thickness_mm) * zs]; at += l.thickness_mm; }
  const color = layerColors(b.copper);

  const scene = new THREE.Scene();
  const group = new THREE.Group();
  group.position.set(-(x0 + x1) / 2, -(y0 + y1) / 2, 0);
  scene.add(group);
  // merged geometries must match: all non-indexed, positions and normals only, no groups
  const plain = (g) => { const n = g.index ? g.toNonIndexed() : g; for (const k of Object.keys(n.attributes)) if (k !== "position" && k !== "normal") n.deleteAttribute(k); n.clearGroups(); return n; };
  const merge = (geos) => (geos.length ? mergeGeometries(geos.map(plain), false) : null);
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
    if (merged) group.add(new THREE.Mesh(merged, new THREE.MeshStandardMaterial({ color: color[layer], metalness: 0.3, roughness: 0.55 })));
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
  if (vias) group.add(new THREE.Mesh(vias, new THREE.MeshStandardMaterial({ color: "#d8dee9", metalness: 0.5, roughness: 0.4 })));
  for (const l of b.stackup) if (l.type !== "copper" && z[l.name]) {  // dielectrics: translucent slabs
    const [zb, zt] = z[l.name];
    const g = new THREE.BoxGeometry(x1 - x0, y1 - y0, Math.max(zt - zb, 1e-4));
    g.translate((x0 + x1) / 2, (y0 + y1) / 2, (zb + zt) / 2);
    group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: l.type === "mask" ? "#4c566a" : "#8fbcbb", transparent: true, opacity: 0.12, depthWrite: false })));
  }
  scene.add(new THREE.AmbientLight(0xffffff, 0.75));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(size, -size, size);
  scene.add(sun);

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
  camera.position.set(0, -size * 1.1, size * 0.8);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
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
const layerColors = (copper) => {
  const n = copper.length;
  return Object.fromEntries(copper.map((l, i) => { const v = Math.round(200 - (n > 1 ? (110 * i) / (n - 1) : 0)); return [l, `rgb(${v},${v + 4},${v + 12})`]; }));
};

// an overlay's values as an image: log scale, blue (low) to red (high), empty cells clear
function overlayImage(layer, lo, hi) {
  const c = document.createElement("canvas");
  c.width = layer.nx; c.height = layer.ny;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(layer.nx, layer.ny);
  const [b0, b1] = [[0x5e, 0x81, 0xac], [0xbf, 0x61, 0x6a]];
  const l0 = Math.log10(lo), span = Math.log10(hi) - l0 || 1;
  layer.z.forEach((row, j) => row.forEach((v, i) => {
    const k = 4 * ((layer.ny - 1 - j) * layer.nx + i);  // row 0 at the bottom (Y up)
    if (v == null || !(v > 0)) return;
    const t = Math.min(1, Math.max(0, (Math.log10(v) - l0) / span));
    img.data[k] = b0[0] + t * (b1[0] - b0[0]); img.data[k + 1] = b0[1] + t * (b1[1] - b0[1]); img.data[k + 2] = b0[2] + t * (b1[2] - b0[2]); img.data[k + 3] = 235;
  }));
  ctx.putImageData(img, 0, 0);
  return c;
}

// a round length near ``target`` (1, 2 or 5 times a power of ten), and how to write it (mm in)
const niceLength = (target) => { const e = 10 ** Math.floor(Math.log10(target)); return [1, 2, 5, 10].map((m) => m * e).find((v) => v >= target) || 10 * e; };
const lengthText = (mm) => (mm >= 1 ? `${+mm.toPrecision(3)} mm` : `${+(mm * 1000).toPrecision(3)} µm`);

function layoutViewer(b, overlay = null, full = false) {
  const color = layerColors(b.copper);
  const shown = new Set(b.copper);
  let picked = null, markers = [], focus = null;
  const ring = (path, pts) => { pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y))); path.closePath(); };
  const paths = b.polys.map((p) => { const path = new Path2D(); for (const r of [p.pts, ...p.holes]) ring(path, r); return { ...p, path }; });
  const cuts = (b.cuts || []).map((c) => { const path = new Path2D(); ring(path, c.pts); return { ...c, path }; });

  // the overlay: current density per layer (one layer at a time), pin voltages, via currents
  let ov = null;
  if (overlay) {
    const vals = Object.values(overlay.layers).flatMap((l) => l.z.flat().filter((v) => v > 0)).sort((x, y) => x - y);
    const lo = vals.length ? vals[Math.floor(vals.length * 0.02)] : 1, hi = vals.length ? vals[vals.length - 1] : 1;
    const supply = overlay.pins[0]?.run;
    const pins = overlay.pins.filter((p) => p.run === supply);
    const vs = pins.map((p) => p.v), is = (overlay.vias || []).map((v) => v.i).filter((i) => i > 0);
    ov = { mode: "current density", lo, hi, pins, vmin: Math.min(...vs), vmax: Math.max(...vs), imin: Math.min(...is), imax: Math.max(...is), images: Object.fromEntries(Object.entries(overlay.layers).map(([n, l]) => [n, { img: overlayImage(l, lo, hi), ext: l.extent }])) };
    // current density: the layer carrying the most, alone
    const top = Object.entries(overlay.layers).map(([n, l]) => [n, Math.max(0, ...l.z.flat().filter((v) => v > 0))]).sort((a2, b2) => b2[1] - a2[1])[0];
    if (top) { shown.clear(); shown.add(top[0]); ov.top = top[0]; }
  }
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
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    if (!canvas.clientWidth) return;
    if (!view) {
      if (focus) { const pad = Math.max(focus[2] - focus[0], focus[3] - focus[1], 0.05) * 6; fitTo([focus[0] - pad, focus[1] - pad, focus[2] + pad, focus[3] + pad], 1); }
      else fitTo(b.bbox, 0.92);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = css("--layout-bg");
    ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    // a grid at a fifth of the scale bar's length, where its lines are at least 14 px apart (FRIDA's)
    const step = niceLength(110 / view.s), minor = step / 5;
    if (minor * view.s >= 14) {
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
    if (ov && ov.mode === "current density") {  // each shown layer's map over its copper
      ctx.imageSmoothingEnabled = false;
      for (const layer of [...b.copper].reverse()) {
        const o = ov.images[layer];
        if (!o || !shown.has(layer)) continue;
        const [ex0, ex1, ey0, ey1] = o.ext;
        ctx.save();
        ctx.translate(ex0, ey1);
        ctx.scale((ex1 - ex0) / o.img.width, -(ey1 - ey0) / o.img.height);
        ctx.globalAlpha = 0.9;
        ctx.drawImage(o.img, 0, 0);
        ctx.restore();
      }
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = css("--ink-1");
    for (const c of cuts) if (c.layers.some((l) => shown.has(l))) ctx.fill(c.path);
    for (const v of b.vias) if (v.layers.some((l) => shown.has(l))) { ctx.beginPath(); ctx.arc(v.x, v.y, Math.max(v.d / 2, px), 0, 2 * Math.PI); ctx.fill(); }
    ctx.strokeStyle = "#b48ead";
    ctx.lineWidth = px;
    for (const p of b.pins) if (shown.has(p.layer)) ctx.strokeRect(p.x - p.w / 2, p.y - p.h / 2, p.w, p.h);
    ctx.strokeStyle = css("--ink-3");
    ctx.lineWidth = 1.2 * px;
    ctx.beginPath();
    for (const [ax, ay, bx, by] of b.outline) { ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
    ctx.stroke();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (b.labels && b.labels.length) {  // labels, where there's room to read them
      ctx.font = "10px ui-monospace, monospace";
      const onScreen = b.labels.filter((l) => shown.has(l.layer)).map((l) => [l, view.tx + view.s * l.x, view.ty - view.s * l.y]).filter(([, sx, sy]) => sx >= 0 && sy >= 0 && sx <= canvas.clientWidth && sy <= canvas.clientHeight);
      if (onScreen.length <= 300) for (const [l, sx, sy] of onScreen) {
        ctx.fillStyle = color[l.layer];
        ctx.fillRect(sx - 1.5, sy - 1.5, 3, 3);
        ctx.fillStyle = css("--ink-0");
        ctx.fillText(l.text, sx + 4, sy - 3);
      }
    }
    if (ov) {  // pins by voltage, or vias by current, and the colour scale
      const mix = (t) => `rgb(${0x5e + t * (0xbf - 0x5e)},${0x81 + t * (0x61 - 0x81)},${0xac + t * (0x6a - 0xac)})`;
      let scale = null;
      if (ov.mode === "pin voltage") {
        for (const p of ov.pins) {
          const t = 1 - (p.v - ov.vmin) / (ov.vmax - ov.vmin || 1);  // the lowest voltage red
          ctx.fillStyle = mix(t);
          ctx.beginPath(); ctx.arc(view.tx + view.s * p.x, view.ty - view.s * p.y, 4, 0, 2 * Math.PI); ctx.fill();
        }
        scale = [`${ov.vmax.toFixed(4)} V`, `${ov.vmin.toFixed(4)} V`, "pin voltage (supply)"];
      } else if (ov.mode === "via current") {
        const l0 = Math.log10(ov.imin), sp = Math.log10(ov.imax) - l0 || 1;
        for (const v of [...(overlay.vias || [])].sort((a2, b2) => a2.i - b2.i)) {
          if (!(v.i > 0)) continue;
          ctx.fillStyle = mix((Math.log10(v.i) - l0) / sp);
          ctx.beginPath(); ctx.arc(view.tx + view.s * v.x, view.ty - view.s * v.y, 2.5, 0, 2 * Math.PI); ctx.fill();
        }
        scale = [`${(ov.imin * 1e3).toPrecision(2)} mA`, `${(ov.imax * 1e3).toPrecision(3)} mA`, "via current (log)"];
      } else {
        scale = [`${ov.lo.toPrecision(2)}`, `${ov.hi.toPrecision(3)} ${overlay.unit}`, `current density, ${[...shown].join(", ")} (log)`];
      }
      const w = 180, x = canvas.clientWidth - w - 12, y = 52;
      const grad = ctx.createLinearGradient(x, 0, x + w, 0);
      grad.addColorStop(0, "#5e81ac"); grad.addColorStop(1, "#bf616a");
      ctx.fillStyle = grad; ctx.fillRect(x, y, w, 8);
      ctx.fillStyle = css("--ink-1"); ctx.font = "10px ui-monospace, monospace";
      ctx.fillText(scale[0], x, y + 20);
      ctx.textAlign = "right"; ctx.fillText(scale[1], x + w, y + 20); ctx.fillText(scale[2], x + w, y - 6); ctx.textAlign = "left";
    }
    {  // the scale bar, bottom left: a round length near 90 px, as it is at this zoom
      const len = niceLength(90 / view.s), w = len * view.s, hh = canvas.clientHeight;
      ctx.fillStyle = document.documentElement.dataset.theme === "light" ? "rgba(250,250,250,0.88)" : "rgba(40,44,51,0.88)";
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
    // the violations: boxes in the error colour, at least 8 pixels across (as FRIDA's)
    if (markers.length) {
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
  // the full panel (stackup, counts) once, with the inputs; elsewhere the layers as toggles
  const toggles = h("div", { class: "layers" }, b.copper.map((l) => h("a", { style: `--c:${color[l]}`, class: shown.has(l) ? null : "off", onclick: () => {
    if (ov && ov.mode === "current density") { shown.clear(); shown.add(l); }  // one layer's map at a time
    else if (shown.has(l)) shown.delete(l); else shown.add(l);
    toggles.querySelectorAll("a").forEach((x) => x.classList.toggle("off", !shown.has(x.textContent)));
    draw();
  } }, l)));
  if (!full) wrap.append(toggles);
  const tools = h("div", { class: "tools" });
  wrap.append(tools);
  tools.append(h("button", { class: "fit", title: "back to the whole layout", onclick: () => { focus = null; view = null; draw(); } }, "fit"));
  if (ov) tools.prepend(h("select", { class: "panelpick modes", onchange: (e) => {
    const m = e.target.value;
    ov.mode = m;
    if (m !== "current density") b.copper.forEach((l) => shown.add(l));
    else { shown.clear(); shown.add(ov.top); }  // one layer's map at a time
    toggles.querySelectorAll("a").forEach((x) => x.classList.toggle("off", !shown.has(x.textContent)));
    draw();
  } }, ["current density", "pin voltage", "via current"].map((m) => h("option", { value: m }, m))));
  const el = h("div", { class: "layout" + (full ? "" : " bare") }, wrap, full ? h("aside", {}, stackPanel(b, color, shown, draw)) : null);
  return { el, setMarkers: (boxes, at = null) => { markers = boxes; focus = at ? at.box || at : null; view = null; draw(); if (at && at.rule) say(at); } };
}

function segDist(s, x, y) {
  const dx = s.x2 - s.x1, dy = s.y2 - s.y1;
  const t = Math.max(0, Math.min(1, ((x - s.x1) * dx + (y - s.y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(x - (s.x1 + t * dx), y - (s.y1 + t * dy));
}

function bars(rows, colour, label) {
  if (!rows || !rows.length) return h("div", { class: "caption" }, "none");
  const max = Math.max(...rows.map((r) => r[1]));
  return h("div", { class: "bars" }, rows.slice(0, 12).map(([k, n]) => h("div", { class: "row" },
    h("span", {}, label(k)), h("div", { class: "bar" }, h("span", { style: `width:${(100 * n) / max}%;background:${colour}` })), h("span", { class: "n" }, n))));
}

// the stackup, top to bottom: click a copper layer to hide or show it
function stackPanel(b, color, shown, draw) {
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 1;
  const um = (mm) => `${(mm * 1000).toFixed(mm < 0.01 ? 1 : 0)} µm`;
  return [h("h4", {}, "stackup"), h("div", { class: "stack" }, b.stackup.map((l) => {
    const el = h("div", { class: l.type, style: `height:${Math.max(16, Math.min(64, (300 * l.thickness_mm) / total))}px` + (l.type === "copper" ? `;box-shadow: inset 5px 0 0 ${color[l.name]}` : ""), title: `${l.name}: ${l.material || l.type}, ${um(l.thickness_mm)}` + (l.er ? `, εr ${l.er}` : "") },
      l.name, h("span", { class: "t" }, um(l.thickness_mm)));
    if (l.type === "copper") el.onclick = () => { shown.has(l.name) ? shown.delete(l.name) : shown.add(l.name); el.classList.toggle("off"); draw(); };
    return el;
  }))];
}

// a layout's counts: shapes per layer (GDS), trace widths and vias (board), and its facts
function layoutFacts(b) {
  const s = b.stats;
  const mm = (x) => `${x.toFixed(x < 1 ? 3 : 2)} mm`;
  const facts = [["thickness", mm(s.thickness_mm)], ["size", `${s.size_mm[0].toFixed(2)} × ${s.size_mm[1].toFixed(2)} mm`], ["copper layers", s.copper_layers]];
  for (const k of ["nets", "pours", "tracks", "vias", "pins", "components", "via cuts", "labels"]) if (s[k] != null) facts.push([k, s[k]]);
  return [
    b.kind === "gds"
      ? [h("h4", {}, "shapes per layer"), bars(Object.entries(s["shapes per layer"]), "var(--nord8)", (k) => k)]
      : [h("h4", {}, "trace widths"), bars(s.trace_widths, "var(--nord14)", (w) => mm(w)),
         h("h4", {}, "via profiles (pad / drill)"), bars(s.via_profiles, "var(--nord13)", (k) => `${k} mm`),
         h("h4", {}, "via spans"), bars(s.via_spans, "var(--nord8)", (k) => k)],
    h("h4", {}, "facts"), h("div", { class: "kv" }, facts.flatMap(([k, v]) => [h("span", {}, k), h("span", {}, v)])),
  ];
}

initTheme();
window.addEventListener("hashchange", render);
render();
