(() => {
  const badgeIf = document.getElementById("badge-if");
  const badgeRx = document.getElementById("badge-rx");
  const badgeWs = document.getElementById("badge-ws");
  const canKv = document.getElementById("can-kv");
  const canErr = document.getElementById("can-err");
  const msgBody = document.querySelector("#msg-table tbody");
  const mapBody = document.querySelector("#map-table tbody");
  const msgMeta = document.getElementById("msg-meta");
  const mapMeta = document.getElementById("map-meta");
  const btnReload = document.getElementById("btn-reload");

  function setBadge(el, text, cls) {
    el.textContent = text;
    el.className = "badge" + (cls ? " " + cls : "");
  }

  function kv(dl, rows) {
    dl.innerHTML = rows
      .map(([k, v]) => `<dt>${k}</dt><dd>${v == null || v === "" ? "—" : v}</dd>`)
      .join("");
  }

  function render(msg) {
    if (msg.type !== "mgl_can_update") return;
    const c = msg.can || {};
    setBadge(
      badgeIf,
      `${c.interface || "can0"} ${c.status || "?"}`,
      c.status === "UP" ? "ok" : "bad"
    );
    setBadge(badgeRx, `RX ${c.rx_count ?? 0}`, "ok");
    kv(canKv, [
      ["Interface", c.interface],
      ["Status", c.status],
      ["Bitrate", c.bitrate],
      ["Listen-only", c.listen_only == null ? "—" : String(c.listen_only)],
      ["RX count", c.rx_count],
      ["Errors", c.error_count],
      ["Last frame age (ms)", c.last_frame_age_ms],
      ["Map path", c.map_path],
      ["Monitor running", c.running],
    ]);
    const errs = [c.bus_error, c.map_error].filter(Boolean);
    canErr.textContent = errs.join(" · ");

    const messages = msg.messages || [];
    msgMeta.textContent = `${messages.length} IDs`;
    if (!messages.length) {
      msgBody.innerHTML = `<tr><td colspan="9" class="muted">No frames yet…</td></tr>`;
    } else {
      msgBody.innerHTML = messages
        .map((m) => {
          const decCls = m.decoder === "mapped" ? "ok" : "muted";
          return `<tr>
            <td><code>${m.can_id}</code></td>
            <td>${m.device_address}</td>
            <td>${m.message_id}</td>
            <td>${m.family}</td>
            <td>${m.dlc}</td>
            <td>${m.rate_hz}</td>
            <td>${m.age_ms}</td>
            <td><code class="payload">${m.payload || ""}</code></td>
            <td class="${decCls}">${m.decoder}</td>
          </tr>`;
        })
        .join("");
    }

    const mapped = msg.mapped || [];
    mapMeta.textContent = `${mapped.length} fields`;
    if (!mapped.length) {
      mapBody.innerHTML = `<tr><td colspan="6" class="muted">No mapped fields (edit decode_map.yaml)</td></tr>`;
    } else {
      mapBody.innerHTML = mapped
        .map(
          (r) => `<tr>
            <td>${r.name || "—"}</td>
            <td><strong>${r.value == null ? "—" : r.value}</strong></td>
            <td>${r.units || ""}</td>
            <td><code>${r.fix_key || ""}</code></td>
            <td>${r.age_ms ?? ""}</td>
            <td><code>${r.can_id || ""}</code></td>
          </tr>`
        )
        .join("");
    }
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/mgl-can`);
    setBadge(badgeWs, "WS …", "");
    ws.onopen = () => setBadge(badgeWs, "WS connected", "ok");
    ws.onclose = () => {
      setBadge(badgeWs, "WS reconnecting", "warn");
      setTimeout(connect, 1500);
    };
    ws.onerror = () => setBadge(badgeWs, "WS error", "bad");
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "mgl_can_update") render(data);
        else if (data.type === "error") {
          canErr.textContent = data.message || "error";
          setBadge(badgeWs, "WS error", "bad");
        }
      } catch (e) {
        console.warn(e);
      }
    };
  }

  btnReload.addEventListener("click", async () => {
    try {
      const r = await fetch("/api/mgl-can/reload-config", { method: "POST" });
      const j = await r.json();
      canErr.textContent = j.ok
        ? `Map reloaded (${j.message_rules} rules)`
        : `Reload failed: ${j.error || "?"}`;
    } catch (e) {
      canErr.textContent = String(e);
    }
  });

  // Initial HTTP snapshot while WS connects
  fetch("/api/mgl-can/snapshot")
    .then((r) => r.json())
    .then(render)
    .catch(() => {});

  connect();
})();
