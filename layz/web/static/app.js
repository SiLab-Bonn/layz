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

// ---------------------------------------------------------------- theme: the OS's, or the switch's

const themeListeners = new Set();
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#theme").textContent = theme === "dark" ? "☾" : "☀";
  for (const f of themeListeners) f();
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("layz-theme"); } catch {}
  const os = window.matchMedia("(prefers-color-scheme: light)");
  setTheme(saved || (os.matches ? "light" : "dark"));
  os.addEventListener("change", (e) => { if (!saved) setTheme(e.matches ? "light" : "dark"); });
  $("#theme").onclick = () => {
    saved = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("layz-theme", saved); } catch {}
    setTheme(saved);
  };
}

async function render() {
  const { design } = state();
  themeListeners.clear();
  $("#crumb").replaceChildren(design ? h("a", { class: "on" }, design) : "");
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
    h("div", { class: "title" }, h("h1", {}, d.name), chip(d.targets.some((t) => t.status === "failed") ? "failed" : n === d.targets.length ? "ok" : "pending", `${n} of ${d.targets.length} targets done`), h("span", { class: "caption" }, `run ${d.started} · ${d.flow}`)),
    h("nav", { class: "toc" }, d.targets.map((t) => h("a", { onclick: jump(t) }, chip(t.status, ""), t.name))),
    d.source ? h("details", { class: "flowsrc" }, h("summary", {}, `flow.py: the flow as it ran (${d.source.split("\n").length} lines)`), h("pre", {}, d.source)) : null,
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
      if (inp.layout) return layoutViewer(inp.layout).el;
      if (inp.layout_svgs) return h("div", { class: "svgs" }, inp.layout_svgs.map((u) => h("img", { src: u, class: "svg board" })));
      return h("div", { class: "caption" }, "no layout");
    }]);
    right.push(["schematic", async () => {
      const inp = await inputs();
      if (inp.schematic_svgs) return schematicViewer(inp.schematic_svgs);
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
  if (isBoard) right.push(["board", async () => layoutViewer(await board()).el]);
  for (const p of t.plots) right.push([plotLabel(p.png), async () => plotPane(d.name, p)]);

  // left: numbers
  const mark = (rule) => {
    if (!t.markers) return;
    const boxes = t.markers.boxes.filter((m) => !rule || m.rule === rule);
    if (!boxes.length) return;
    rightTabs.show(`layout · ${t.markers.boxes.length} marked`);
    setTimeout(() => viewer && viewer.setMarkers(boxes, boxes[0].box), 50);
  };
  const left = [];
  if (t.name === "setup") left.push(["inputs", () => h("table", { class: "kvtable" }, h("tr", {}, h("td", {}, "flow"), h("td", {}, d.flow)), Object.entries(d.inputs).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v))))]);
  for (const tb of t.tables) left.push([base(tb.path).replace(/\.csv$/, ""), () => table(tb, t.markers ? mark : null)]);
  if (t.markers && t.markers.boxes.length) left.push(["violations", () => violations(t.markers.boxes, (m) => { rightTabs.show(`layout · ${t.markers.boxes.length} marked`); setTimeout(() => viewer && viewer.setMarkers(t.markers.boxes, m.box), 50); })]);
  if (t.lines.length) left.push([`log${countLevels(t.lines)}`, () => h("pre", { class: "log" }, t.lines.map(logLine))]);

  const rightTabs = tabs(right);
  const leftTabs = tabs(left);
  return h("section", { class: `target ${t.status}`, id: `t-${t.name}` },
    h("div", { class: "head" },
      h("span", { class: "step" }, String(i + 1).padStart(2, "0")), chip(t.status), h("span", { class: "name" }, t.name),
      h("span", { class: "doc" }, t.doc), h("span", { class: "caption" }, t.seconds == null ? "" : `${t.seconds.toFixed(0)} s`)),
    t.error ? h("div", { class: "error" }, t.error) : null,
    leftTabs || rightTabs ? h("div", { class: rightTabs && leftTabs ? "split" : "single" }, leftTabs, rightTabs) : null);
}

function boardTarget(d) {
  // the target whose folder holds the board (results/<design>/<target>/...), else "board"
  const parts = d.inputs.board.split("/");
  return d.targets.find((t) => parts.includes(t.name))?.name || "board";
}

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
  const draw = () => {
    const ink = css("--ink-1"), grid = css("--line-2"), dim = css("--ink-4");
    const traces = [], layout = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: ink, family: css("--font-mono"), size: 11 }, margin: { l: 60, r: 20, t: fig.title ? 36 : 14, b: 46 }, showlegend: true, legend: { bgcolor: "rgba(0,0,0,0)", font: { size: 10 } }, title: fig.title ? { text: fig.title, font: { size: 12 } } : undefined, annotations: [] };
    fig.axes.forEach((ax, k) => {
      const n = k ? k + 1 : "";
      const axis = (label, log, lim, dom) => ({ title: { text: label, font: { size: 11 } }, type: log ? "log" : "linear", range: log ? lim.map((v) => Math.log10(Math.max(v, 1e-300))) : lim, domain: dom, gridcolor: grid, zerolinecolor: grid, linecolor: dim, mirror: true, ticks: "inside" });
      layout[`xaxis${n}`] = { ...axis(ax.xlabel, ax.xlog, ax.xlim, [ax.box[0], ax.box[2]]), anchor: `y${n}` };
      layout[`yaxis${n}`] = { ...axis(ax.ylabel, ax.ylog, ax.ylim, [ax.box[1], ax.box[3]]), anchor: `x${n}` };
      if (ax.title) layout.annotations.push({ text: ax.title, xref: "paper", yref: "paper", x: (ax.box[0] + ax.box[2]) / 2, y: ax.box[3], yanchor: "bottom", showarrow: false, font: { size: 11 } });
      for (const im of ax.images) {
        const ny = im.z.length, nx = im.z[0].length;
        traces.push({ type: "heatmap", xaxis: `x${n}`, yaxis: `y${n}`, z: im.log ? im.z.map((r) => r.map((v) => (v > 0 ? Math.log10(v) : null))) : im.z, x0: im.x0 + (im.x1 - im.x0) / nx / 2, dx: (im.x1 - im.x0) / nx, y0: im.y0 + (im.y1 - im.y0) / ny / 2, dy: (im.y1 - im.y0) / ny, zmin: im.log ? Math.log10(im.zmin) : im.zmin, zmax: im.log ? Math.log10(im.zmax) : im.zmax, colorscale: [[0, "#5e81ac"], [1, "#bf616a"]], showscale: k === 0, colorbar: { title: { text: im.log ? "log10" : "", side: "right" }, thickness: 10 }, hoverongaps: false });
      }
      for (const l of ax.lines) traces.push({ type: "scattergl", mode: l.markers ? "markers" : "lines", xaxis: `x${n}`, yaxis: `y${n}`, x: l.x, y: l.y, name: l.label || undefined, showlegend: !!l.label, line: { color: l.color, width: Math.max(1, l.width), dash: l.dash ? "dash" : "solid" }, marker: { color: l.color, size: 4 } });
    });
    window.Plotly.react(el, traces, layout, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  };
  themeListeners.add(draw);
  requestAnimationFrame(draw);
  return h("div", {}, el, h("div", { class: "caption" }, h("a", { href: png, target: "_blank" }, "PNG"), " · ", h("a", { href: png.replace(/\.png$/, ".pdf"), target: "_blank" }, "PDF")));
}

// ---------------------------------------------------------------- schematic, inline

async function schematicViewer(urls) {
  const pages = await Promise.all(urls.map(async (u) => [u, await (await fetch(u)).text()]));
  const holder = h("div", { class: "schematic" });
  const bar = pages.length > 1 ? h("div", { class: "pages" }) : null;
  const show = (k) => {
    bar && bar.querySelectorAll("a").forEach((a, j) => a.classList.toggle("on", j === k));
    const svg = new DOMParser().parseFromString(pages[k][1], "image/svg+xml").documentElement;
    svg.removeAttribute("width"); svg.removeAttribute("height");
    holder.replaceChildren(svg);
    requestAnimationFrame(() => {
      const b = svg.getBBox();  // crop to the drawing
      let vb = [b.x - 2, b.y - 2, b.width + 4, b.height + 4];
      const set = () => svg.setAttribute("viewBox", vb.join(" "));
      set();
      let drag = null;
      svg.addEventListener("mousedown", (e) => { drag = [e.clientX, e.clientY, ...vb]; });
      window.addEventListener("mouseup", () => { drag = null; });
      svg.addEventListener("mousemove", (e) => {
        if (!drag) return;
        const k2 = vb[2] / svg.clientWidth;
        vb = [drag[2] - (e.clientX - drag[0]) * k2, drag[3] - (e.clientY - drag[1]) * k2, vb[2], vb[3]]; set();
      });
      svg.addEventListener("wheel", (e) => {
        e.preventDefault();
        const r = svg.getBoundingClientRect(), f = Math.exp(e.deltaY * 0.0015);
        const px = vb[0] + ((e.clientX - r.left) / r.width) * vb[2], py = vb[1] + ((e.clientY - r.top) / r.height) * vb[3];
        vb = [px - (px - vb[0]) * f, py - (py - vb[1]) * f, vb[2] * f, vb[3] * f]; set();
      }, { passive: false });
    });
  };
  pages.forEach((p, k) => bar && bar.append(h("a", { onclick: () => show(k) }, base(p[0]).replace(/\.svg$/, ""))));
  show(0);
  return h("div", {}, bar, holder, h("div", { class: "caption" }, "drag to pan · wheel to zoom · ", h("a", { href: pages[0][0], target: "_blank" }, "SVG")));
}

// ---------------------------------------------------------------- layout viewer (GDS or .hyp board)

const NORD_LAYERS = ["#bf616a", "#ebcb8b", "#a3be8c", "#b48ead", "#88c0d0", "#d08770", "#8fbcbb", "#81a1c1"];
const BOTTOM = "#5e81ac";

function layoutViewer(b) {
  const color = Object.fromEntries(b.copper.map((l, i) => [l, i === b.copper.length - 1 && i > 0 ? BOTTOM : NORD_LAYERS[i % NORD_LAYERS.length]]));
  const shown = new Set(b.copper);
  let picked = null, markers = [], focus = null;
  const ring = (path, pts) => { pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y))); path.closePath(); };
  const paths = b.polys.map((p) => { const path = new Path2D(); for (const r of [p.pts, ...p.holes]) ring(path, r); return { ...p, path }; });
  const cuts = (b.cuts || []).map((c) => { const path = new Path2D(); ring(path, c.pts); return { ...c, path }; });

  const canvas = h("canvas");
  const pickedBox = h("div", { class: "picked", style: "display:none" });
  const wrap = h("div", { class: "canvas" }, canvas, pickedBox, h("div", { class: "hint" }, "drag to pan · wheel to zoom · click copper" + (b.kind === "gds" ? "" : " for its net")));
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
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    const px = 1 / view.s;
    for (const layer of [...b.copper].reverse()) {
      if (!shown.has(layer)) continue;
      ctx.globalAlpha = 0.55;
      for (const p of paths) if (p.layer === layer) { ctx.fillStyle = picked && p.net && p.net === picked ? css("--ink-0") : color[layer]; ctx.fill(p.path, "evenodd"); }
      ctx.globalAlpha = 0.9;
      ctx.lineCap = "round";
      for (const s of b.segs) if (s.layer === layer) {
        ctx.strokeStyle = picked && s.net === picked ? css("--ink-0") : color[layer];
        ctx.lineWidth = Math.max(s.w, px);
        ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
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
  const pick = (sx, sy) => {
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
  const el = h("div", { class: "layout" }, wrap, h("aside", {}, sidePanel(b, color, shown, draw)));
  return { el, setMarkers: (boxes, at = null) => { markers = boxes; focus = at; view = null; draw(); } };
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

function sidePanel(b, color, shown, draw) {
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 1;
  const um = (mm) => `${(mm * 1000).toFixed(mm < 0.01 ? 1 : 0)} µm`;
  const stack = h("div", { class: "stack" }, b.stackup.map((l) => {
    const el = h("div", { class: l.type, style: `height:${Math.max(16, Math.min(64, (300 * l.thickness_mm) / total))}px` + (l.type === "copper" ? `;box-shadow: inset 5px 0 0 ${color[l.name]}` : ""), title: `${l.name}: ${l.material || l.type}, ${um(l.thickness_mm)}` + (l.er ? `, εr ${l.er}` : "") },
      l.name, h("span", { class: "t" }, um(l.thickness_mm)));
    if (l.type === "copper") el.onclick = () => { shown.has(l.name) ? shown.delete(l.name) : shown.add(l.name); el.classList.toggle("off"); draw(); };
    return el;
  }));
  const s = b.stats;
  const mm = (x) => `${x.toFixed(x < 1 ? 3 : 2)} mm`;
  const facts = [["thickness", mm(s.thickness_mm)], ["size", `${s.size_mm[0].toFixed(2)} × ${s.size_mm[1].toFixed(2)} mm`], ["copper layers", s.copper_layers]];
  for (const k of ["nets", "pours", "tracks", "vias", "pins", "components", "via cuts", "labels"]) if (s[k] != null) facts.push([k, s[k]]);
  return [
    h("h4", {}, "stackup (click copper to hide)"), stack,
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
