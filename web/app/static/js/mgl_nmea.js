(() => {
  const badgeIf = document.getElementById("badge-if");
  const badgeRx = document.getElementById("badge-rx");
  const badgeWs = document.getElementById("badge-ws");
  const hold = document.getElementById("chk-hold");

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function setBadge(el, text, cls) {
    el.textContent = text;
    el.className = "badge" + (cls ? " " + cls : "");
  }

  function fmtVal(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    return String(v);
  }

  function renderCol(prefix, msg) {
    const meta = document.getElementById(prefix + "-meta");
    const raw = document.getElementById(prefix + "-raw");
    const kv = document.getElementById(prefix + "-kv");
    const logEl = document.getElementById(prefix + "-log");
    if (!msg || !msg.raw) {
      meta.textContent = "no sentences yet";
      raw.textContent = "—";
      kv.innerHTML = "";
      logEl.textContent = "";
      return;
    }
    const age = msg.age_ms == null ? "—" : msg.age_ms + " ms";
    const talker = msg.talker ? msg.talker : "";
    const csum = msg.csum_ok ? "csum ok" : "csum bad";
    meta.textContent = `${talker}${msg.type} · ${msg.rate_hz || 0} Hz · ${msg.count} · age ${age} · ${csum}`;
    raw.textContent = msg.raw;
    const fields = msg.fields || [];
    kv.innerHTML = fields
      .map((f) => {
        const unit = f.units ? ` ${esc(f.units)}` : "";
        return `<dt>${esc(f.name)}</dt><dd>${esc(fmtVal(f.value))}${unit}</dd>`;
      })
      .join("");
    const lines = (msg.recent || []).map((r) => r.raw).join("\n");
    logEl.textContent = lines;
  }

  function render(msg) {
    if (msg.type !== "mgl_nmea_update") return;
    if (hold && hold.checked) return;
    const n = msg.nmea || {};
    setBadge(
      badgeIf,
      n.status === "UP" ? "FIX UP" : "FIX DOWN",
      n.status === "UP" ? "ok" : "bad"
    );
    setBadge(badgeRx, `RX ${n.rx_count ?? 0}`, n.rx_count ? "ok" : "");
    renderCol("gga", msg.gga);
    renderCol("rmc", msg.rmc);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/mgl-nmea`);
    setBadge(badgeWs, "WS connecting", "warn");
    ws.onopen = () => setBadge(badgeWs, "WS connected", "ok");
    ws.onclose = () => {
      setBadge(badgeWs, "WS reconnecting…", "bad");
      setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch (_) { return; }
      if (data.type === "mgl_nmea_update") render(data);
    };
  }

  fetch("/api/mgl-nmea/snapshot")
    .then((r) => r.json())
    .then((data) => render(data))
    .catch(() => {});
  connect();
})();
