// layz web: the runs of this clone's flows. #design=NAME opens one run as a single page, top to
// bottom in the flow's order: setup with the inputs it named, then every target.
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
const state = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const go = (patch) => { location.hash = new URLSearchParams(patch).toString(); };
const fileUrl = (design, rel) => `/results/${encodeURIComponent(design)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
const base = (p) => (p || "").split("/").pop();

async function render() {
  const { design } = state();
  $("#crumb").replaceChildren(design ? h("a", { class: "on" }, design) : "");
  const main = $("#main");
  try {
    main.replaceChildren(design ? await designPage(design) : await homePage());
  } catch (e) {
    main.replaceChildren(h("div", { class: "empty" }, String(e.message || e)));
  }
}

// ---------------------------------------------------------------- home: every design's last run

function chip(status, text) {
  return h("span", { class: `chip ${status}` }, text ?? status);
}

async function homePage() {
  const designs = await getJSON("/api/designs");
  if (!designs.length) return h("div", { class: "empty" }, "No runs yet: layz run designs/NAME records one in results/NAME/.");
  const status = (d) => {
    const failed = d.targets.find((t) => t.status === "failed");
    return failed ? chip("failed", `stopped at ${failed.name}`) : d.targets.every((t) => t.status === "ok") ? chip("ok") : chip("pending", "running");
  };
  return h("div", { class: "page" },
    h("h2", {}, "designs: click one to open its run"),
    h("table", { class: "data designs" },
      h("tr", {}, ["design", "status", "targets ok", "layout", "board", "run"].map((c) => h("th", {}, c))),
      designs.map((d) => h("tr", { onclick: () => go({ design: d.name }) },
        h("td", {}, d.name), h("td", {}, status(d)),
        h("td", {}, `${d.targets.filter((t) => t.status === "ok").length} / ${d.targets.length}`),
        h("td", {}, base(d.inputs.layout)), h("td", {}, base(d.inputs.board)), h("td", {}, d.started)))));
}

// ---------------------------------------------------------------- one design, top to bottom

async function designPage(name) {
  const d = await getJSON(`/api/design?name=${encodeURIComponent(name)}`);
  const ok = d.targets.filter((t) => t.status === "ok").length;
  const jump = (t) => (e) => { e.preventDefault(); document.getElementById(`t-${t.name}`)?.scrollIntoView({ behavior: "smooth" }); };
  return h("div", { class: "page" },
    h("div", { class: "title" }, h("h1", {}, d.name), chip(d.targets.some((t) => t.status === "failed") ? "failed" : ok === d.targets.length ? "ok" : "pending", `${ok} of ${d.targets.length} targets ok`), h("span", { class: "caption" }, `run ${d.started} · ${d.flow}`)),
    h("nav", { class: "toc" }, d.targets.map((t) => h("a", { onclick: jump(t) }, chip(t.status, ""), t.name))),
    d.targets.map((t, i) => targetSection(d, t, i)));
}

function targetSection(d, t, i) {
  const board = d.inputs.board && t.status === "ok" && boardTarget(d) === t.name;
  const body = h("div", { class: "body" },
    t.error ? h("div", { class: "error" }, t.error) : null,
    t.name === "setup" ? inputsBlock(d) : null,
    board ? lazy(() => boardBlock(d.name)) : null,
    t.tables.map(table),
    t.plots.length ? h("div", { class: "plots" }, t.plots.map((p) => plot(d.name, p))) : null,
    t.lines.length ? h("details", { class: "log", open: t.status === "failed" ? "" : null },
      h("summary", {}, `log: ${t.lines.length} lines` + countLevels(t.lines)),
      h("pre", {}, t.lines.map(logLine))) : null);
  return h("section", { class: `target ${t.status}`, id: `t-${t.name}` },
    h("div", { class: "head" },
      h("span", { class: "step" }, String(i + 1).padStart(2, "0")), chip(t.status), h("span", { class: "name" }, t.name),
      h("span", { class: "doc" }, t.doc), h("span", { class: "caption" }, t.seconds == null ? "" : `${t.seconds.toFixed(0)} s`)),
    body);
}

function boardTarget(d) {
  // the target whose folder holds the board (results/<design>/<target>/...), else "board"
  const parts = d.inputs.board.split("/");
  return d.targets.find((t) => parts.includes(t.name))?.name || "board";
}

function lazy(make) {
  // heavy blocks (layout canvases, drawings) are built when they scroll into view
  const slot = h("div", { class: "lazy" }, h("div", { class: "caption" }, "loading…"));
  new IntersectionObserver(async (entries, obs) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    obs.disconnect();
    try { slot.replaceChildren(await make()); } catch (e) { slot.replaceChildren(h("div", { class: "caption" }, String(e.message || e))); }
  }, { rootMargin: "300px" }).observe(slot);
  return slot;
}

function inputsBlock(d) {
  return h("div", { class: "inputs" },
    h("h3", {}, "inputs"),
    h("table", { class: "kvtable" }, h("tr", {}, h("td", {}, "flow"), h("td", {}, d.flow)), Object.entries(d.inputs).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v)))),
    lazy(async () => {
      const inp = await getJSON(`/api/inputs?name=${encodeURIComponent(d.name)}`);
      return h("div", {},
        inp.layout ? [h("h3", {}, `layout: ${inp.layout.name}`), layoutViewer(inp.layout)] : null,
        inp.layout_svgs ? [h("h3", {}, `layout: ${base(d.inputs.layout)}`), h("div", { class: "svgs" }, inp.layout_svgs.map((u) => h("img", { src: u, class: "svg board" })))] : null,
        inp.schematic_svgs ? [h("h3", {}, "schematic"), h("div", { class: "svgs" }, inp.schematic_svgs.map((u) => h("a", { href: u, target: "_blank" }, h("img", { src: u, class: "svg" }))))] : null,
        inp.netlist ? [h("h3", {}, `schematic: ${base(d.inputs.schematic)} (netlist)`), table({ path: "", rows: [["net", "pins"], ...inp.netlist.map((n) => [n.net, n.pins.join(" ")])] })] : null);
    }));
}

async function boardBlock(name) {
  const b = await getJSON(`/api/board?name=${encodeURIComponent(name)}`);
  return h("div", {}, h("h3", {}, `board for HyperLynx: ${b.name}`), layoutViewer(b));
}

// ---------------------------------------------------------------- tables, plots, logs

function table(t) {
  const [head, ...rows] = t.rows;
  const passCol = head.indexOf("pass");
  return h("div", { class: "tablewrap" },
    t.path ? h("div", { class: "caption" }, t.path) : null,
    h("table", { class: "data" },
      h("tr", {}, head.map((c) => h("th", {}, c))),
      rows.map((r) => h("tr", {}, r.map((c, i) => h("td", { class: i === passCol ? `pass-${c}` : null }, fmt(c)))))));
}

function fmt(c) {
  const x = Number(c);
  return c !== "" && Number.isFinite(x) && !Number.isInteger(x) ? x.toPrecision(4) : c;
}

function plot(design, p) {
  const src = fileUrl(design, p);
  const zoom = () => document.body.append(h("div", { class: "zoom", onclick: (e) => e.currentTarget.remove() }, h("img", { src })));
  return h("figure", {}, h("img", { src, loading: "lazy", onclick: zoom }), h("figcaption", {}, p));
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
  return (w ? `, ${w} warnings` : "") + (e ? `, ${e} errors` : "");
}

// ---------------------------------------------------------------- layout viewer (GDS or .hyp board)

const NORD_LAYERS = ["#bf616a", "#ebcb8b", "#a3be8c", "#b48ead", "#88c0d0", "#d08770", "#8fbcbb", "#81a1c1"];
const BOTTOM = "#5e81ac";

function layoutViewer(b) {
  const color = Object.fromEntries(b.copper.map((l, i) => [l, i === b.copper.length - 1 && i > 0 ? BOTTOM : NORD_LAYERS[i % NORD_LAYERS.length]]));
  const shown = new Set(b.copper);
  let picked = null;
  const ring = (path, pts) => { pts.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y))); path.closePath(); };
  const paths = b.polys.map((p) => { const path = new Path2D(); for (const r of [p.pts, ...p.holes]) ring(path, r); return { ...p, path }; });
  const cuts = (b.cuts || []).map((c) => { const path = new Path2D(); ring(path, c.pts); return { ...c, path }; });

  const canvas = h("canvas");
  const pickedBox = h("div", { class: "picked", style: "display:none" });
  const wrap = h("div", { class: "canvas" }, canvas, pickedBox, h("div", { class: "hint" }, "drag to pan · wheel to zoom · click copper" + (b.kind === "gds" ? "" : " for its net")));
  const [x0, y0, x1, y1] = b.bbox;
  let view = null;
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--layout-bg").trim() || "#2f343e";

  const fit = () => {
    const w = canvas.clientWidth, hh = canvas.clientHeight;
    const s = 0.92 * Math.min(w / (x1 - x0 || 1), hh / (y1 - y0 || 1));
    view = { s, tx: w / 2 - (s * (x0 + x1)) / 2, ty: hh / 2 + (s * (y0 + y1)) / 2 };
  };
  const draw = () => {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    if (!canvas.clientWidth) return;
    if (!view) fit();
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    const px = 1 / view.s;
    for (const layer of [...b.copper].reverse()) {
      if (!shown.has(layer)) continue;
      ctx.globalAlpha = 0.55;
      for (const p of paths) if (p.layer === layer) { ctx.fillStyle = picked && p.net && p.net === picked ? "#eceff4" : color[layer]; ctx.fill(p.path, "evenodd"); }
      ctx.globalAlpha = 0.9;
      ctx.lineCap = "round";
      for (const s of b.segs) if (s.layer === layer) {
        ctx.strokeStyle = picked && s.net === picked ? "#eceff4" : color[layer];
        ctx.lineWidth = Math.max(s.w, px);
        ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#e5e9f0";
    for (const c of cuts) if (c.layers.some((l) => shown.has(l))) ctx.fill(c.path);
    for (const v of b.vias) if (v.layers.some((l) => shown.has(l))) { ctx.beginPath(); ctx.arc(v.x, v.y, Math.max(v.d / 2, px), 0, 2 * Math.PI); ctx.fill(); }
    ctx.strokeStyle = "#b48ead";
    ctx.lineWidth = px;
    for (const p of b.pins) if (shown.has(p.layer)) ctx.strokeRect(p.x - p.w / 2, p.y - p.h / 2, p.w, p.h);
    ctx.strokeStyle = "#d8dee9";
    ctx.lineWidth = 1.2 * px;
    ctx.beginPath();
    for (const [ax, ay, bx, by] of b.outline) { ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
    ctx.stroke();
    if (b.labels && b.labels.length) {  // labels, where there's room to read them
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = "10px ui-monospace, monospace";
      const onScreen = b.labels.filter((l) => shown.has(l.layer)).map((l) => [l, view.tx + view.s * l.x, view.ty - view.s * l.y]).filter(([, sx, sy]) => sx >= 0 && sy >= 0 && sx <= canvas.clientWidth && sy <= canvas.clientHeight);
      if (onScreen.length <= 300) for (const [l, sx, sy] of onScreen) {
        ctx.fillStyle = color[l.layer];
        ctx.fillRect(sx - 1.5, sy - 1.5, 3, 3);
        ctx.fillStyle = "#eceff4";
        ctx.fillText(l.text, sx + 4, sy - 3);
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
  return h("div", { class: "layout" }, wrap, h("aside", {}, sidePanel(b, color, shown, draw)));
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
    const el = h("div", { class: l.type, style: `height:${Math.max(16, Math.min(64, (340 * l.thickness_mm) / total))}px` + (l.type === "copper" ? `;box-shadow: inset 5px 0 0 ${color[l.name]}` : ""), title: `${l.name}: ${l.material || l.type}, ${um(l.thickness_mm)}` + (l.er ? `, εr ${l.er}` : "") },
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

window.addEventListener("hashchange", render);
render();
