// layz web: the runs of this clone's flows. State in the URL hash: #design=NAME&view=run|plots|layout
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
  for (const k of kids.flat()) if (k != null) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
};
const getJSON = async (url) => {
  const r = await fetch(url);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
};
const state = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const go = (patch) => { location.hash = new URLSearchParams({ ...state(), ...patch }).toString(); };

let designs = [];

async function render() {
  const { design, view = "run" } = state();
  designs = await getJSON("/api/designs");
  $("#designs").replaceChildren(design ? h("a", { class: "on" }, design) : "");
  $("#views").style.display = design ? "" : "none";
  for (const a of document.querySelectorAll("#views a")) {
    a.className = a.dataset.view === view ? "on" : "";
    a.onclick = () => go({ view: a.dataset.view });
  }
  const main = $("#main");
  if (!design) return main.replaceChildren(homeView());
  try {
    if (view === "layout") return main.replaceChildren(await layoutView(design));
    const d = await getJSON(`/api/design?name=${encodeURIComponent(design)}`);
    main.replaceChildren(view === "plots" ? plotsView(d) : runView(d));
  } catch (e) {
    main.replaceChildren(h("div", { class: "empty" }, String(e.message || e)));
  }
}

// ---------------------------------------------------------------- home: every design's last run

function homeView() {
  if (!designs.length) return h("div", { class: "empty" }, "No runs yet: layz run designs/NAME records one in results/NAME/.");
  const status = (d) => {
    const failed = d.targets.find((t) => t.status === "failed");
    return failed ? h("span", { class: "chip failed" }, `stopped at ${failed.name}`) : d.targets.every((t) => t.status === "ok") ? h("span", { class: "chip ok" }, "ok") : h("span", { class: "chip pending" }, "running");
  };
  return h("div", { class: "page" },
    h("h2", {}, "designs: click one to open its run"),
    h("table", { class: "data designs" },
      h("tr", {}, ["design", "status", "targets ok", "layout", "board", "run"].map((c) => h("th", {}, c))),
      designs.map((d) => h("tr", { onclick: () => go({ design: d.name, view: "run" }) },
        h("td", {}, d.name),
        h("td", {}, status(d)),
        h("td", {}, `${d.targets.filter((t) => t.status === "ok").length} / ${d.targets.length}`),
        h("td", {}, (d.inputs.layout || "").split("/").pop()),
        h("td", {}, (d.inputs.board || "").split("/").pop()),
        h("td", {}, d.started)))));
}

// ---------------------------------------------------------------- run: targets, inputs, tables

function table(t) {
  const [head, ...rows] = t.rows;
  const passCol = head.indexOf("pass");
  return h("div", {},
    h("div", { class: "caption" }, t.path),
    h("table", { class: "data" },
      h("tr", {}, head.map((c) => h("th", {}, c))),
      rows.map((r) => h("tr", {}, r.map((c, i) => h("td", { class: i === passCol ? `pass-${c}` : "" }, fmt(c)))))));
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

function fmt(c) {
  const x = Number(c);
  return c !== "" && Number.isFinite(x) && !Number.isInteger(x) ? x.toPrecision(4) : c;
}

function runView(d) {
  const ok = d.targets.filter((t) => t.status === "ok").length;
  return h("div", { class: "page" },
    h("h2", {}, `${d.name}: ${ok} of ${d.targets.length} targets ok, run ${d.started}`),
    h("table", { class: "inputs" }, h("tr", {}, h("td", {}, "flow"), h("td", {}, d.flow)), Object.entries(d.inputs).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v)))),
    h("h2", {}, "targets"),
    d.targets.map((t) => {
      const box = h("div", { class: "target" + (t.status === "failed" ? " open" : "") },
        h("div", { class: "head", onclick: () => box.classList.toggle("open") },
          h("span", { class: `chip ${t.status}` }, t.status),
          h("span", { class: "name" }, t.name),
          h("span", { class: "doc" }, t.doc),
          h("span", { class: "caption" }, t.seconds == null ? "" : `${t.seconds.toFixed(0)} s`)),
        h("div", { class: "body" },
          t.error ? h("div", { class: "error" }, t.error) : null,
          t.tables.map(table),
          t.lines.length ? h("details", { class: "log", open: t.status === "failed" ? "" : null },
            h("summary", {}, `log: ${t.lines.length} lines` + countLevels(t.lines)),
            h("pre", {}, t.lines.map(logLine))) : null,
          t.plots.length ? h("div", { class: "caption" }, `${t.plots.length} plots: see PLOTS`) : null));
      return box;
    }));
}

// ---------------------------------------------------------------- plots

function plotsView(d) {
  const zoom = (src) => document.body.append(h("div", { class: "zoom", onclick: (e) => e.currentTarget.remove() }, h("img", { src })));
  const groups = d.targets.filter((t) => t.plots.length);
  if (!groups.length) return h("div", { class: "empty" }, "No plots in this run.");
  return h("div", { class: "page" }, groups.map((t) => [
    h("h2", {}, t.name),
    h("div", { class: "plots" }, t.plots.map((p) => {
      const src = `/results/${encodeURIComponent(d.name)}/${p.split("/").map(encodeURIComponent).join("/")}`;
      return h("figure", {}, h("img", { src, loading: "lazy", onclick: () => zoom(src) }), h("figcaption", {}, p));
    })),
  ]));
}

// ---------------------------------------------------------------- layout: board and stackup

const LAYER_COLORS = ["#c83434", "#d8a33a", "#a3be8c", "#b48ead", "#88c0d0", "#d08770", "#ebcb8b", "#8fbcbb"];
const BOTTOM_COLOR = "#4d7fc4";

async function layoutView(name) {
  const b = await getJSON(`/api/board?name=${encodeURIComponent(name)}`);
  const color = Object.fromEntries(b.copper.map((l, i) => [l, i === b.copper.length - 1 && i > 0 ? BOTTOM_COLOR : LAYER_COLORS[i % LAYER_COLORS.length]]));
  const shown = new Set(b.copper);
  let picked = null;

  // the copper as Path2D, in mm (Y up), per layer, drawn bottom layer first
  const paths = b.polys.map((p) => {
    const path = new Path2D();
    for (const ring of [p.pts, ...p.holes]) {
      ring.forEach(([x, y], i) => (i ? path.lineTo(x, y) : path.moveTo(x, y)));
      path.closePath();
    }
    return { ...p, path };
  });

  const canvas = h("canvas");
  const pickedBox = h("div", { class: "picked", style: "display:none" });
  const wrap = h("div", { class: "canvas" }, canvas, pickedBox, h("div", { class: "hint" }, "drag to pan, wheel to zoom, click copper for its net"));
  const [x0, y0, x1, y1] = b.bbox;
  let view = null; // {s: px per mm, tx, ty}

  const fit = () => {
    const w = canvas.clientWidth, hgt = canvas.clientHeight;
    const s = 0.92 * Math.min(w / (x1 - x0 || 1), hgt / (y1 - y0 || 1));
    view = { s, tx: w / 2 - s * (x0 + x1) / 2, ty: hgt / 2 + s * (y0 + y1) / 2 };
  };

  const draw = () => {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    if (!view) fit();
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0b1220";
    ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    const px = 1 / view.s;
    for (const layer of [...b.copper].reverse()) {
      if (!shown.has(layer)) continue;
      ctx.globalAlpha = 0.55;
      for (const p of paths) {
        if (p.layer !== layer) continue;
        ctx.fillStyle = picked && p.net === picked ? "#ffffff" : color[layer];
        ctx.fill(p.path, "evenodd");
      }
      ctx.globalAlpha = 0.9;
      ctx.lineCap = "round";
      for (const s of b.segs) {
        if (s.layer !== layer) continue;
        ctx.strokeStyle = picked && s.net === picked ? "#ffffff" : color[layer];
        ctx.lineWidth = Math.max(s.w, px);
        ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#e5e9f0";
    for (const v of b.vias) {
      if (!v.layers.some((l) => shown.has(l))) continue;
      ctx.beginPath(); ctx.arc(v.x, v.y, Math.max(v.d / 2, px), 0, 2 * Math.PI); ctx.fill();
    }
    ctx.strokeStyle = "#ff4fd8";
    ctx.lineWidth = px;
    for (const p of b.pins) if (shown.has(p.layer)) ctx.strokeRect(p.x - p.w / 2, p.y - p.h / 2, p.w, p.h);
    ctx.strokeStyle = "#7b88a1";
    ctx.lineWidth = 1.5 * px;
    ctx.beginPath();
    for (const [ax, ay, bx, by] of b.outline) { ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
    ctx.stroke();
  };

  // pan, zoom, pick
  let drag = null;
  canvas.addEventListener("mousedown", (e) => { drag = { x: e.offsetX, y: e.offsetY, tx: view.tx, ty: view.ty, moved: false }; });
  window.addEventListener("mouseup", (e) => {
    if (drag && !drag.moved && e.target === canvas) pick(e.offsetX, e.offsetY);
    drag = null;
  });
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
    const hit = [...b.copper].filter((l) => shown.has(l)).flatMap((l) => paths.filter((p) => p.layer === l)).find((p) => ctx.isPointInPath(p.path, x, y, "evenodd"))
      || b.segs.find((s) => shown.has(s.layer) && segDist(s, x, y) <= s.w / 2);
    picked = hit ? hit.net : null;
    pickedBox.style.display = picked ? "" : "none";
    if (hit) {
      const pins = b.pins.filter((p) => p.net === picked).map((p) => p.ref);
      pickedBox.textContent = `${picked} on ${hit.layer}` + (pins.length ? `: ${pins.slice(0, 8).join(" ")}${pins.length > 8 ? " …" : ""}` : "");
    }
    draw();
  };

  const aside = h("aside", {}, boardPanel(b, color, shown, draw));
  const root = h("div", { class: "layout" }, wrap, aside);
  new ResizeObserver(() => { view = null; draw(); }).observe(wrap);
  return root;
}

function segDist(s, x, y) {
  const dx = s.x2 - s.x1, dy = s.y2 - s.y1;
  const t = Math.max(0, Math.min(1, ((x - s.x1) * dx + (y - s.y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(x - (s.x1 + t * dx), y - (s.y1 + t * dy));
}

function bars(rows, colour, label) {
  if (!rows.length) return h("div", { class: "caption" }, "none");
  const max = Math.max(...rows.map((r) => r[1]));
  return h("div", { class: "bars" }, rows.slice(0, 14).map(([k, n]) => h("div", { class: "row" },
    h("span", {}, label(k)),
    h("div", { class: "bar" }, h("span", { style: `width:${(100 * n) / max}%;background:${colour}` })),
    h("span", { class: "n" }, n))));
}

function boardPanel(b, color, shown, draw) {
  const total = b.stackup.reduce((a, l) => a + l.thickness_mm, 0) || 1;
  const stack = h("div", { class: "stack" }, b.stackup.map((l) => {
    const hgt = Math.max(16, Math.min(70, (360 * l.thickness_mm) / total));
    const el = h("div", { class: l.type, style: `height:${hgt}px` + (l.type === "copper" ? `;box-shadow: inset 4px 0 0 ${color[l.name]}` : ""), title: `${l.name}: ${l.material || l.type}, ${(l.thickness_mm * 1000).toFixed(1)} µm` + (l.er ? `, εr ${l.er}` : "") },
      l.name, h("span", { class: "t" }, `${(l.thickness_mm * 1000).toFixed(l.thickness_mm < 0.01 ? 1 : 0)} µm`));
    if (l.type === "copper") el.onclick = () => { shown.has(l.name) ? shown.delete(l.name) : shown.add(l.name); el.classList.toggle("off"); draw(); };
    return el;
  }));
  const s = b.stats;
  const mm = (x) => `${x.toFixed(x < 1 ? 3 : 2)} mm`;
  return [
    h("h2", {}, `${b.name}: stackup (click copper to hide)`), stack,
    h("h2", {}, "trace widths"), bars(s.trace_widths, "var(--bar-trace)", (w) => mm(w)),
    h("h2", {}, "via profiles (pad / drill)"), bars(s.via_profiles, "var(--bar-via)", (k) => `${k} mm`),
    h("h2", {}, "via spans"), bars(s.via_spans, "var(--bar-span)", (k) => k),
    h("h2", {}, "board"),
    h("div", { class: "kv" }, [
      ["thickness", mm(s.thickness_mm)], ["size", `${s.size_mm[0].toFixed(1)} × ${s.size_mm[1].toFixed(1)} mm`], ["copper layers", s.copper_layers],
      ["nets", s.nets], ["pours", s.pours], ["tracks", s.tracks], ["vias", s.vias], ["pins", s.pins], ["components", s.components],
    ].flatMap(([k, v]) => [h("span", {}, k), h("span", {}, v)])),
  ];
}

window.addEventListener("hashchange", render);
render();
