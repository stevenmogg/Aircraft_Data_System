(function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (v, d) => {
    if (v === null || v === undefined || v === "") return "—";
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(d) : "—";
  };

  function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
  }

  function setBadge(el, text, cls) {
    if (!el) return;
    el.textContent = text;
    el.className = "badge " + (cls || "");
  }

  function applyState(msg) {
    const a = msg.attitude || {};
    const mgl = msg.mgl || {};
    const air = msg.air || {};
    const pos = msg.position || {};
    const sys = msg.system || {};
    const r = msg.rdac || {};
    const n = msg.nmea || {};
    setText("v-mgl-pitch", fmt(mgl.pitch, 1));
    setText("v-mgl-roll", fmt(mgl.roll, 1));
    setText("v-mgl-head", fmt(mgl.heading, 0));
    setText("v-mgl-yaw", fmt(mgl.yaw, 1));
    setText("v-mgl-slip", fmt(mgl.slip, 0));
    setText("v-mgl-g", fmt(mgl.g, 2));
    setText("v-rdac-rpm1", fmt(r.rpm1, 0));
    setText("v-rdac-rpm2", fmt(r.rpm2, 0));
    setText("v-rdac-map", fmt(r.map_raw, 0));
    setText("v-rdac-curr", fmt(r.current_raw, 0));
    setText("v-rdac-temp", fmt(r.temp, 0));
    setText("v-rdac-oilt", fmt(r.oilt_raw, 0));
    setText("v-rdac-oilp", fmt(r.oilp_raw, 0));
    setText("v-rdac-fuelp", fmt(r.fuelp_raw, 0));
    setText("v-rdac-cool", fmt(r.coolant_raw, 0));
    setText("v-rdac-fuel1", fmt(r.fuellevel1_raw, 0));
    setText("v-rdac-fuel2", fmt(r.fuellevel2_raw, 0));
    setText("v-rdac-aux1", fmt(r.aux1_raw, 0));
    setText("v-rdac-aux2", fmt(r.aux2_raw, 0));
    for (let i = 1; i <= 12; i++) {
      setText("v-rdac-tc" + i, fmt(r["tc" + i], 0));
    }
    setText("v-pitch", fmt(a.pitch, 1));
    setText("v-roll", fmt(a.roll, 1));
    setText("v-head", fmt(a.heading, 1));
    setText("v-alt", fmt(air.pressure_altitude, 0));
    setText("v-vs", fmt(air.vs, 0));
    setText("v-gs", fmt(pos.groundspeed, 1));
    setText("v-nmea-lat", fmt(n.lat, 6));
    setText("v-nmea-lon", fmt(n.lon, 6));
    setText("v-nmea-alt", fmt(n.alt, 0));
    setText("v-nmea-gs", fmt(n.groundspeed, 2));
    setText("v-nmea-track", fmt(n.track, 1));
    const qual = (n.qual === null || n.qual === undefined) ? "—" : String(n.qual);
    const sats = (n.sats === null || n.sats === undefined) ? "—" : String(n.sats);
    setText("v-nmea-qual", (qual === "—" && sats === "—") ? "—" : qual + " / " + sats);
    setText("v-nmea-hdop", fmt(n.hdop, 2));
    setText("v-nmea-time", (n.time === null || n.time === undefined || n.time === "") ? "—" : String(n.time));
    setText("v-sx-lat", fmt(pos.lat, 6));
    setText("v-sx-lon", fmt(pos.lon, 6));
    setText("v-sx-alt", fmt(pos.gps_alt, 0));
    setText("v-sx-gs", fmt(pos.groundspeed, 1));
    setText("v-sx-track", fmt(pos.track, 1));
    const sxQual = (pos.fix_type === null || pos.fix_type === undefined) ? "—" : String(pos.fix_type);
    const sxSats = (pos.sats === null || pos.sats === undefined) ? "—" : String(pos.sats);
    setText("v-sx-qual", (sxQual === "—" && sxSats === "—") ? "—" : sxQual + " / " + sxSats);

    setBadge($("fix-badge"), sys.fix_ok ? "FIX OK" : "FIX LOST", sys.fix_ok ? "ok" : "bad");
    const rec = !!sys.historian_recording;
    setBadge($("hist-badge"), sys.historian_state || (rec ? "RECORDING" : "NOT RECORDING"),
      rec ? "ok" : "warn");
    setText("flight-id", "Flight: " + (sys.flight_id || "—"));
    const btnStart = $("btn-start");
    const btnStop = $("btn-stop");
    const btnMark = $("btn-mark");
    if (btnStart) btnStart.disabled = rec;
    if (btnStop) btnStop.disabled = !rec;
    if (btnMark) btnMark.disabled = !rec;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(proto + "://" + location.host + "/ws/live");
    setBadge($("ws-badge"), "WS connecting", "warn");
    ws.onopen = () => setBadge($("ws-badge"), "WS connected", "ok");
    ws.onclose = () => {
      setBadge($("ws-badge"), "WS reconnecting…", "bad");
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "state") {
        try { applyState(msg); } catch (e) { console.warn("live applyState", e); }
      }
      if (msg.type === "error") setText("action-msg", "WS error: " + (msg.message || ""));
    };
  }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    return data;
  }

  $("btn-start").onclick = async () => {
    $("action-msg").textContent = "Starting…";
    try {
      const d = await post("/api/historian/start", {});
      $("action-msg").textContent = "Recording " + d.flight_id;
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
  };
  $("btn-stop").onclick = async () => {
    $("action-msg").textContent = "Stopping…";
    try {
      const d = await post("/api/historian/stop", {});
      $("action-msg").textContent = "Stopped " + (d.flight_id || "");
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
  };
  $("btn-mark").onclick = async () => {
    const text = $("mark-label").value || null;
    try {
      const d = await post("/api/events/mark", { text });
      $("action-msg").textContent = "MARK @ " + (d.flight_time_s != null ? d.flight_time_s + "s" : "?");
    } catch (e) {
      $("action-msg").textContent = String(e.message || e);
    }
  };

  connect();
})();
