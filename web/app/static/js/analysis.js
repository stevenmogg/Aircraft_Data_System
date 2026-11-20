(function () {
  const sel = document.getElementById("flight-select");
  const msg = document.getElementById("analysis-msg");
  const wrap = document.getElementById("chart-wrap");
  const canvas = document.getElementById("chart");
  const tip = document.getElementById("chart-tip");
  const ctx = canvas.getContext("2d");
  const plotControls = document.getElementById("plot-controls");
  const plotMeta = document.getElementById("plot-meta");
  const paramSels = [0, 1, 2, 3].map((i) => document.getElementById("param-" + i));
  const COLORS = ["#7ddeb8", "#7db0de", "#e0b45c", "#d47d9a"];
  const HIT_PX = 14;
  const mapEl = document.getElementById("analysis-map");
  const mapMsg = document.getElementById("map-msg");
  const mapLegend = document.getElementById("map-legend");

  let fields = [];
  let plotState = null;
  let hoverRaf = 0;
  let cursorIndex = null;
  let mapObj = null;
  let mapTracks = [];
  let mapTimes = [];
  let mapMarker = null;
  let mapDidFit = false;

  function fieldByColumn(col) {
    return fields.find((f) => f.column === col) || {};
  }

  function fieldLabel(f, includeNone) {
    if (!f || !f.column) return includeNone ? "— none —" : "";
    const key = f.fix_key || f.column;
    const units = f.units ? " (" + f.units + ")" : "";
    return key + units;
  }

  function selectedColumns() {
    const out = [];
    const seen = new Set();
    paramSels.forEach((el) => {
      const v = el.value;
      if (v && !seen.has(v)) {
        seen.add(v);
        out.push(v);
      }
    });
    return out;
  }

  function fillParamSelects(defaults) {
    const want = (defaults || []).slice(0, 4);
    paramSels.forEach((el, i) => {
      el.innerHTML = "";
      const none = document.createElement("option");
      none.value = "";
      none.textContent = "— none —";
      el.appendChild(none);
      fields.forEach((f) => {
        const o = document.createElement("option");
        o.value = f.column;
        o.textContent = fieldLabel(f);
        el.appendChild(o);
      });
      el.value = want[i] && fields.some((f) => f.column === want[i]) ? want[i] : "";
    });
  }

  function layout() {
    const w = canvas.width,
      h = canvas.height;
    const padL = 12,
      padR = 12,
      padB = 36,
      padT = 28;
    return { w, h, padL, padR, padB, padT, x0: padL, y0: h - padB, x1: w - padR, y1: padT };
  }

  function xAt(i, n, L) {
    return L.x0 + (i / (n - 1 || 1)) * (L.x1 - L.x0);
  }

  function yAt(v, ymin, ymax, L) {
    return L.y0 - ((v - ymin) / (ymax - ymin)) * (L.y0 - L.y1);
  }

  function isNum(v) {
    return v !== null && v !== undefined && Number.isFinite(Number(v));
  }

  function formatValue(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const a = Math.abs(n);
    if (Number.isInteger(n)) return String(n);
    if (a >= 100) return n.toFixed(0);
    if (a >= 10) return n.toFixed(1);
    return n.toFixed(2);
  }

  function formatTime(v) {
    return v == null ? "" : Number(v).toFixed(1) + " s";
  }

  function distToSeg(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1,
      dy = y2 - y1;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function buildTraces(series, columns, L) {
    const t = series.flight_time_s || [];
    const traces = [];
    columns.forEach((col, idx) => {
      const arr = series[col] || [];
      const ys = arr.filter(isNum).map(Number);
      const color = COLORS[idx % COLORS.length];
      const info = fieldByColumn(col);
      let ymin = ys.length ? Math.min(...ys) : 0;
      let ymax = ys.length ? Math.max(...ys) : 1;
      if (ymin === ymax) {
        ymin -= 1;
        ymax += 1;
      }
      traces.push({
        col,
        arr,
        ymin,
        ymax,
        color,
        info,
        hasData: ys.length > 0,
      });
    });
    return { t, traces, L };
  }

  function hideTip() {
    tip.hidden = true;
  }

  function showTip(cssX, cssY, timeText, rows) {
    tip.replaceChildren();
    const tEl = document.createElement("div");
    tEl.className = "chart-tip-time";
    tEl.textContent = timeText;
    tip.appendChild(tEl);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "chart-tip-row";
      const sw = document.createElement("span");
      sw.className = "chart-tip-swatch";
      sw.style.background = r.color;
      const name = document.createElement("span");
      name.className = "chart-tip-name";
      name.textContent = r.name;
      const val = document.createElement("span");
      val.className = "chart-tip-val";
      val.style.color = r.color;
      val.textContent = r.valueText;
      row.append(sw, name, val);
      tip.appendChild(row);
    });
    tip.hidden = false;
    const maxL = wrap.clientWidth - tip.offsetWidth - 8;
    const maxT = wrap.clientHeight - tip.offsetHeight - 8;
    let left = cssX + 16;
    let top = cssY + 16;
    if (left > maxL) left = cssX - tip.offsetWidth - 16;
    if (top > maxT) top = cssY - tip.offsetHeight - 16;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  function canvasCoords(ev) {
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    return {
      x: (ev.clientX - rect.left) * sx,
      y: (ev.clientY - rect.top) * sy,
      cssX: ev.clientX - rect.left,
      cssY: ev.clientY - rect.top,
      sx,
      sy,
    };
  }

  function nearestIndex(x, n, L) {
    if (n <= 1) return 0;
    const u = (x - L.x0) / (L.x1 - L.x0);
    return Math.max(0, Math.min(n - 1, Math.round(u * (n - 1))));
  }

  function traceDistance(tr, i, px, py, L, n) {
    if (!tr.hasData || !isNum(tr.arr[i])) return Infinity;
    const x = xAt(i, n, L);
    const y = yAt(Number(tr.arr[i]), tr.ymin, tr.ymax, L);
    let best = Math.hypot(px - x, py - y);
    const prev = i > 0 ? i - 1 : -1;
    const next = i < n - 1 ? i + 1 : -1;
    [prev, next].forEach((j) => {
      if (j < 0 || !isNum(tr.arr[j])) return;
      const x2 = xAt(j, n, L);
      const y2 = yAt(Number(tr.arr[j]), tr.ymin, tr.ymax, L);
      best = Math.min(best, distToSeg(px, py, x, y, x2, y2));
    });
    return best;
  }

  function hoverAt(px, py, hitCanvas) {
    const st = plotState;
    if (!st || !st.t.length) return null;
    const { t, traces, L } = st;
    if (px < L.x0 || px > L.x1 || py < L.y1 || py > L.y0) return null;
    const n = t.length;
    const i = nearestIndex(px, n, L);
    const hits = [];
    traces.forEach((tr) => {
      const d = traceDistance(tr, i, px, py, L, n);
      if (d <= hitCanvas) hits.push({ tr, d, i });
    });
    if (!hits.length) return null;
    hits.sort((a, b) => a.d - b.d);
    return { i, hits };
  }

  function paint(hover) {
    const st = plotState;
    const L = st ? st.L : layout();
    ctx.clearRect(0, 0, L.w, L.h);
    ctx.fillStyle = "#101820";
    ctx.fillRect(0, 0, L.w, L.h);
    if (!st || !st.t.length) return;

    const { t, traces } = st;
    const n = t.length;

    ctx.strokeStyle = "#2a3844";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(L.x0, L.y0);
    ctx.lineTo(L.x1, L.y0);
    ctx.stroke();

    const legend = [];
    traces.forEach((tr) => {
      const name = fieldLabel(tr.info) || tr.col;
      if (!tr.hasData) {
        legend.push({ color: tr.color, text: name + " (no data)" });
        return;
      }
      ctx.beginPath();
      ctx.strokeStyle = tr.color;
      ctx.lineWidth = 2;
      let started = false;
      for (let i = 0; i < tr.arr.length; i++) {
        if (!isNum(tr.arr[i])) {
          started = false;
          continue;
        }
        const x = xAt(i, n, L);
        const y = yAt(Number(tr.arr[i]), tr.ymin, tr.ymax, L);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else ctx.lineTo(x, y);
      }
      ctx.stroke();
      const units = tr.info.units ? " " + tr.info.units : "";
      legend.push({
        color: tr.color,
        text: (tr.info.fix_key || tr.col) + "  " + tr.ymin.toFixed(1) + "–" + tr.ymax.toFixed(1) + units,
      });
    });

    ctx.font = "13px sans-serif";
    let lx = L.padL;
    legend.forEach((item) => {
      ctx.fillStyle = item.color;
      ctx.fillRect(lx, 8, 10, 10);
      ctx.fillStyle = "#c5d4de";
      ctx.fillText(item.text, lx + 14, 18);
      lx += ctx.measureText(item.text).width + 36;
    });

    ctx.fillStyle = "#8fa3b3";
    ctx.font = "12px sans-serif";
    ctx.fillText(formatTime(t[0]), L.x0, L.h - 10);
    ctx.fillText(formatTime(t[t.length - 1]), L.x1 - 48, L.h - 10);

    const iCursor = hover && hover.i != null ? hover.i : cursorIndex;
    if (iCursor != null && iCursor >= 0 && iCursor < n) {
      const x = xAt(iCursor, n, L);
      ctx.strokeStyle = "#e85c5c";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, L.y1);
      ctx.lineTo(x, L.y0);
      ctx.stroke();
    }

    if (!hover) {
      hideTip();
      return;
    }

    hover.hits.forEach((h, idx) => {
      const tr = h.tr;
      if (!isNum(tr.arr[hover.i])) return;
      const x = xAt(hover.i, n, L);
      const y = yAt(Number(tr.arr[hover.i]), tr.ymin, tr.ymax, L);
      ctx.beginPath();
      ctx.fillStyle = tr.color;
      ctx.arc(x, y, idx === 0 ? 5 : 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#101820";
      ctx.stroke();
    });
  }

  function drawSeries(series, columns) {
    const L = layout();
    plotState = buildTraces(series, columns, L);
    if (cursorIndex == null || cursorIndex >= (plotState.t.length || 0)) {
      cursorIndex = plotState.t.length ? 0 : null;
    }
    paint(null);
    syncMapToIndex(cursorIndex);
    if (!plotState.t.length) {
      msg.textContent = "No samples";
      return;
    }
    msg.textContent =
      `${series.returned_rows} points (of ${series.total_rows})  t=${formatTime(plotState.t[0])}–${formatTime(
        plotState.t[plotState.t.length - 1]
      )}` + "  · each trace uses its own scale · hover a line for value";
  }

  function nearestTimeIndex(times, t) {
    if (!times.length || t == null || !Number.isFinite(Number(t))) return -1;
    const target = Number(t);
    let lo = 0,
      hi = times.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Number(times[mid]) < target) lo = mid + 1;
      else hi = mid;
    }
    let i = lo;
    if (i > 0 && Math.abs(Number(times[i - 1]) - target) < Math.abs(Number(times[i]) - target)) {
      i = i - 1;
    }
    return i;
  }

  function chartIndexForMapIndex(mi) {
    if (!plotState || !plotState.t.length || mi < 0 || mi >= mapTimes.length) return cursorIndex;
    return nearestTimeIndex(plotState.t, mapTimes[mi]);
  }

  function mapIndexForChartIndex(ci) {
    if (!mapTimes.length || ci == null || !plotState || !plotState.t.length) return -1;
    return nearestTimeIndex(mapTimes, plotState.t[ci]);
  }

  function ensureMap() {
    if (mapObj || typeof L === "undefined" || !mapEl) return mapObj;
    mapObj = L.map(mapEl, {
      zoomControl: true,
      attributionControl: true,
    });
    mapObj.createPane("cursorMarker");
    mapObj.getPane("cursorMarker").style.zIndex = 650;
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap, &copy; CARTO",
      maxZoom: 19,
    }).addTo(mapObj);
    mapObj.setView([-37.8, 144.97], 8);
    return mapObj;
  }

  function latlngSegments(lat, lon) {
    const segs = [];
    let cur = [];
    for (let i = 0; i < lat.length; i++) {
      if (lat[i] != null && lon[i] != null) cur.push([lat[i], lon[i]]);
      else if (cur.length) {
        segs.push(cur);
        cur = [];
      }
    }
    if (cur.length) segs.push(cur);
    return segs;
  }

  function nearestMapIndex(track, latlng) {
    let best = -1,
      bestD = Infinity;
    const lat = track.lat || [],
      lon = track.lon || [];
    const clat = latlng.lat,
      clon = latlng.lng;
    for (let i = 0; i < lat.length; i++) {
      if (lat[i] == null || lon[i] == null) continue;
      const dlat = lat[i] - clat;
      const dlon = (lon[i] - clon) * Math.cos((clat * Math.PI) / 180);
      const d = dlat * dlat + dlon * dlon;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  function positionOnTrack(track, i) {
    if (!track || i == null || i < 0) return null;
    const lat = track.lat && track.lat[i];
    const lon = track.lon && track.lon[i];
    if (lat != null && lon != null) return [lat, lon];
    return null;
  }

  function positionAt(i) {
    for (let t = 0; t < mapTracks.length; t++) {
      const ll = positionOnTrack(mapTracks[t], i);
      if (ll) return ll;
    }
    return null;
  }

  function placeMarker(ll, timeS) {
    if (!mapObj || typeof L === "undefined") return;
    if (!ll) {
      if (mapMarker) mapMarker.setOpacity(0);
      return;
    }
    if (!mapMarker) {
      mapMarker = L.circleMarker(ll, {
        radius: 6,
        color: "#7a1f1f",
        weight: 2,
        fillColor: "#e85c5c",
        fillOpacity: 1,
        pane: "cursorMarker",
      }).addTo(mapObj);
    } else {
      mapMarker.setLatLng(ll);
      mapMarker.setOpacity(1);
    }
    if (mapMarker.bringToFront) mapMarker.bringToFront();
    const label = timeS == null ? "cursor" : formatTime(timeS);
    if (mapMarker.getTooltip()) mapMarker.setTooltipContent(label);
    else mapMarker.bindTooltip(label, { direction: "top", offset: [0, -8], sticky: false });
  }

  function syncMapToIndex(ci, track) {
    const mi = mapIndexForChartIndex(ci);
    if (mi < 0 || !mapObj || typeof L === "undefined") return;
    const ll = positionOnTrack(track, mi) || positionAt(mi);
    const t = plotState && plotState.t ? plotState.t[ci] : mapTimes[mi];
    placeMarker(ll, t);
  }

  function setCursorFromMapIndex(mi, track) {
    if (mi < 0) return;
    const ci = chartIndexForMapIndex(mi);
    if (ci == null || ci < 0) return;
    cursorIndex = ci;
    paint(null);
    syncMapToIndex(ci, track);
  }

  function renderMapLegend(tracks) {
    if (!mapLegend) return;
    mapLegend.innerHTML = "";
    if (!tracks.length) {
      mapLegend.hidden = true;
      return;
    }
    tracks.forEach((tr) => {
      const item = document.createElement("span");
      item.className = "map-legend-item";
      const sw = document.createElement("span");
      sw.className = "map-legend-swatch";
      sw.style.background = tr.color;
      item.appendChild(sw);
      item.appendChild(document.createTextNode(tr.label + " (" + tr.valid_points + ")"));
      mapLegend.appendChild(item);
    });
    mapLegend.hidden = false;
  }

  function drawMapTracks(payload) {
    mapTracks = payload.tracks || [];
    mapTimes = payload.flight_time_s || [];
    mapDidFit = false;
    if (mapMsg) {
      mapMsg.textContent = mapTracks.length
        ? "Tracks share the chart time cursor. Click a track to jump."
        : "No GPS tracks in this flight.";
    }
    renderMapLegend(mapTracks);
    if (mapObj) {
      mapObj.eachLayer((layer) => {
        if (layer instanceof L.Polyline || layer instanceof L.CircleMarker) mapObj.removeLayer(layer);
      });
      mapMarker = null;
    }
    if (!mapTracks.length) return;
    const map = ensureMap();
    if (!map) {
      if (mapMsg) mapMsg.textContent = "Map library failed to load.";
      return;
    }
    const bounds = [];
    mapTracks.forEach((tr) => {
      latlngSegments(tr.lat || [], tr.lon || []).forEach((seg) => {
        if (seg.length < 2) return;
        const line = L.polyline(seg, {
          color: tr.color,
          weight: 4,
          opacity: 0.9,
        }).addTo(map);
        line.bindTooltip(tr.label, { sticky: true });
        line.on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          const mi = nearestMapIndex(tr, e.latlng);
          setCursorFromMapIndex(mi, tr);
        });
        seg.forEach((ll) => bounds.push(ll));
      });
    });
    if (bounds.length) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 });
      mapDidFit = true;
    }
    setTimeout(() => map.invalidateSize(), 50);
    syncMapToIndex(cursorIndex);
  }

  async function loadTracks(flightId) {
    if (!flightId) {
      drawMapTracks({ tracks: [], flight_time_s: [] });
      return;
    }
    if (mapMsg) mapMsg.textContent = "Loading tracks…";
    try {
      const d = await fetch("/api/flights/" + encodeURIComponent(flightId) + "/tracks").then((r) =>
        r.json()
      );
      if (d.detail && !d.ok) {
        if (mapMsg) mapMsg.textContent = d.detail;
        return;
      }
      drawMapTracks(d);
    } catch (err) {
      if (mapMsg) mapMsg.textContent = "Could not load tracks.";
    }
  }

  function onMove(ev) {
    if (!plotState) return;
    const p = canvasCoords(ev);
    if (hoverRaf) cancelAnimationFrame(hoverRaf);
    hoverRaf = requestAnimationFrame(() => {
      hoverRaf = 0;
      const L = plotState.L;
      if (plotState.t.length && p.x >= L.x0 && p.x <= L.x1) {
        cursorIndex = nearestIndex(p.x, plotState.t.length, L);
        syncMapToIndex(cursorIndex);
      }
      const hover = hoverAt(p.x, p.y, HIT_PX * p.sx);
      paint(hover);
      if (!hover) return;
      const i = hover.i;
      const rows = hover.hits.map((h) => {
        const tr = h.tr;
        const units = tr.info.units ? " " + tr.info.units : "";
        return {
          color: tr.color,
          name: tr.info.fix_key || tr.col,
          valueText: formatValue(tr.arr[i]) + units,
        };
      });
      showTip(p.cssX, p.cssY, formatTime(plotState.t[i]), rows);
    });
  }

  function onLeave() {
    if (hoverRaf) cancelAnimationFrame(hoverRaf);
    hoverRaf = 0;
    paint(null);
  }

  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerdown", onMove);
  canvas.addEventListener("pointerleave", onLeave);
  window.addEventListener("resize", () => {
    if (mapObj) mapObj.invalidateSize();
  });
  document.querySelectorAll("details.twisty").forEach((el) => {
    el.addEventListener("toggle", () => {
      if (mapObj) setTimeout(() => mapObj.invalidateSize(), 80);
    });
  });

  function updateExport() {
    const id = sel.value;
    document.getElementById("btn-export").href = id ? "/api/export/" + encodeURIComponent(id) : "#";
  }

  async function loadFieldsAndPlot() {
    const id = sel.value;
    updateExport();
    if (!id) {
      plotControls.hidden = true;
      plotMeta.textContent = "select a flight";
      msg.textContent = "";
      plotState = null;
      cursorIndex = null;
      paint(null);
      loadTracks("");
      return;
    }
    cursorIndex = null;
    plotControls.hidden = false;
    msg.textContent = "Loading…";
    loadTracks(id);
    const meta = await fetch("/api/flights/" + encodeURIComponent(id) + "/plot-fields").then((r) =>
      r.json()
    );
    if (!meta.ok && meta.detail) {
      msg.textContent = meta.detail;
      return;
    }
    fields = meta.fields || [];
    fillParamSelects(meta.defaults || []);
    plotMeta.textContent =
      selectedColumns()
        .map((c) => fieldByColumn(c).fix_key || c)
        .join(" / ") || "parameters";
    await plot();
  }

  async function plot() {
    const id = sel.value;
    const cols = selectedColumns();
    if (!id) return;
    if (!cols.length) {
      msg.textContent = "Select at least one parameter";
      plotState = null;
      paint(null);
      return;
    }
    msg.textContent = "Loading…";
    plotMeta.textContent = cols.map((c) => fieldByColumn(c).fix_key || c).join(" / ");
    const d = await fetch(
      "/api/flights/" +
        encodeURIComponent(id) +
        "/series?columns=" +
        encodeURIComponent(cols.join(","))
    ).then((r) => r.json());
    if (!d.ok) {
      msg.textContent = d.detail || "error";
      return;
    }
    drawSeries(d.series, d.columns || cols);
  }

  document.getElementById("btn-plot").onclick = plot;
  paramSels.forEach((el) => {
    el.onchange = plot;
  });
  sel.onchange = loadFieldsAndPlot;

  async function loadFlights() {
    const d = await fetch("/api/flights").then((r) => r.json());
    sel.innerHTML = "";
    const flights = d.flights || [];
    if (!flights.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "No flights";
      sel.appendChild(o);
      plotControls.hidden = true;
      updateExport();
      msg.textContent = "No recorded flights";
      return;
    }
    flights.forEach((f) => {
      const o = document.createElement("option");
      o.value = f.flight_id;
      o.textContent =
        f.flight_id + (f.actual_10hz_frames != null ? " (" + f.actual_10hz_frames + " f)" : "");
      sel.appendChild(o);
    });
    await loadFieldsAndPlot();
  }

  loadFlights();
})();
