(() => {
  const badgeIf = document.getElementById("badge-if");
  const badgeFix = document.getElementById("badge-fix");
  const badgeRx = document.getElementById("badge-rx");
  const badgeOk = document.getElementById("badge-ok");
  const badgeWs = document.getElementById("badge-ws");
  const atKv = document.getElementById("at-kv");
  const atErr = document.getElementById("at-err");
  const msgBody = document.querySelector("#msg-table tbody");
  const msgMeta = document.getElementById("msg-meta");
  const watch = document.getElementById("watch-cards");
  const watchMeta = document.getElementById("watch-meta");
  const recentLog = document.getElementById("recent-log");
  const logMeta = document.getElementById("log-meta");
  const hold = document.getElementById("chk-hold");
  const msgHead = document.getElementById("msg-head");
  const ifMeta = document.getElementById("if-meta");

  let prevBytes = {};
  let prevFix = {};

  const USB_HEAD = `<tr>
            <th>Dest</th>
            <th>Label</th>
            <th>Type</th>
            <th>Len</th>
            <th>Hz</th>
            <th>Age ms</th>
            <th>Count</th>
            <th>Check</th>
            <th>Payload</th>
          </tr>`;
  const FIX_HEAD = `<tr>
            <th>Key</th>
            <th>Name</th>
            <th>Value</th>
            <th>Units</th>
            <th>Source</th>
          </tr>`;

  const FIX_FIELDS = [
    { key: "MGL_AT_PITCH", name: "Pitch", units: "°", digits: 1, note: "FF/37 + up" },
    { key: "MGL_AT_ROLL", name: "Roll", units: "°", digits: 1, note: "FF/37 + left" },
    { key: "MGL_AT_HEAD", name: "Heading", units: "°", digits: 0, note: "FF/32 mag" },
    { key: "MGL_AT_YAW", name: "Yaw", units: "°", digits: 1, note: "AHRS yaw" },
    { key: "MGL_AT_SLIP", name: "Slip", units: "", digits: 0, note: "+ ball right" },
    { key: "MGL_AT_G", name: "G", units: "g", digits: 2, note: "normal accel" },
    { key: "MGL_AT_TURN", name: "Turn rate", units: "", digits: 0, note: "FF/37 raw" },
    { key: "MGL_AT_MISC", name: "MISC", units: "", digits: 0, note: "SP-4 status" },
    { key: "MGL_AT_HEAD_STATUS", name: "Head status", units: "", digits: 0, note: "FF/32" },
  ];

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function setBadge(el, text, cls) {
    if (!el) return;
    el.textContent = text;
    el.className = "badge" + (cls ? " " + cls : "");
  }

  function kv(dl, rows) {
    dl.innerHTML = rows
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v == null || v === "" ? "—" : esc(v)}</dd>`)
      .join("");
  }

  function nums(arr) {
    if (!arr || !arr.length) return "—";
    return arr.map((n) => `<span class="num">${n}</span>`).join(" ");
  }

  function byteCells(bytes, prev) {
    return (bytes || [])
      .map((b, i) => {
        const hx = b.toString(16).toUpperCase().padStart(2, "0");
        const ch = prev && prev[i] !== b ? " changed" : "";
        return `<span class="byte${ch}">${hx}</span>`;
      })
      .join("");
  }

  function watchPriority(m) {
    if (m.decoded && m.decoded.length) return 0;
    if (m.dest === "E6") return 1;
    if (m.dest === "E4") return 2;
    if (m.dest === "FF") return 3;
    return 4;
  }

  function decodedBlock(m) {
    const fields = m.decoded || [];
    if (!fields.length) return "";
    const big = fields.filter((f) => f.highlight);
    const rest = fields.filter((f) => !f.highlight);
    const bigHtml = big
      .map((f) => {
        const unit = f.units ? ` <span class="unit">${esc(f.units)}</span>` : "";
        return `<div class="decoded-field"><h3>${esc(f.name)}</h3><div class="value">${esc(f.value)}${unit}</div><p class="muted">${esc(f.note || "")}</p></div>`;
      })
      .join("");
    const restHtml = rest.length
      ? `<dl class="kv">${rest
          .map((f) => {
            const unit = f.units ? ` ${esc(f.units)}` : "";
            const note = f.note ? ` · ${esc(f.note)}` : "";
            return `<dt>${esc(f.name)}</dt><dd>${esc(f.value)}${unit}${note}</dd>`;
          })
          .join("")}</dl>`
      : "";
    return `<div class="decoded-row">${bigHtml}</div>${restHtml}`;
  }

  function fmt(v, d) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(d);
  }

  function setTxt(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function renderFixFeed(fx) {
    const fk = fx.keys || {};
    const liveCount = FIX_FIELDS.filter((f) => fk[f.key] !== null && fk[f.key] !== undefined).length;
    setBadge(badgeRx, fx.ok ? `FIX ${liveCount} keys` : "FIX down", fx.ok ? "ok" : "bad");
    setBadge(badgeOk, fx.ok ? "plugin live" : "no FIX", fx.ok ? "ok" : "bad");
    if (ifMeta) ifMeta.textContent = "FIX plugin";
    watchMeta.textContent = fx.ok ? `${liveCount} live` : "FIX down";
    msgMeta.textContent = `${FIX_FIELDS.length} keys`;
    if (msgHead) msgHead.innerHTML = FIX_HEAD;

    watch.innerHTML = FIX_FIELDS.map((f) => {
      const raw = fk[f.key];
      const text = fmt(raw, f.digits);
      const changed = prevFix[f.key] !== undefined && prevFix[f.key] !== raw ? " changed" : "";
      const unit = f.units ? ` <span class="unit">${esc(f.units)}</span>` : "";
      return `<div class="inner-card watch-card">
            <h3>${esc(f.name)} · ${esc(f.key)}</h3>
            <div class="decoded-row"><div class="decoded-field">
              <div class="value${changed}">${esc(text)}${unit}</div>
              <p class="muted">${esc(f.note)}</p>
            </div></div>
          </div>`;
    }).join("");

    msgBody.innerHTML = FIX_FIELDS.map((f) => {
      const raw = fk[f.key];
      const text = fmt(raw, f.digits);
      const changed = prevFix[f.key] !== undefined && prevFix[f.key] !== raw ? " changed" : "";
      return `<tr>
            <td><code>${esc(f.key)}</code></td>
            <td>${esc(f.name)}</td>
            <td class="${changed}">${esc(text)}</td>
            <td>${esc(f.units)}</td>
            <td>${esc(f.note)}</td>
          </tr>`;
    }).join("");

    kv(atKv, [
      ["Owner", "FIX-Gateway plugin cozy_mgl_airtalk"],
      ["USB tap", "off (web does not open the Nano)"],
      ["FIX", fx.ok ? "OK" : "down"],
      ["FIX error", fx.error || ""],
      ...FIX_FIELDS.map((f) => [f.name, fmt(fk[f.key], f.digits)]),
    ]);
    atErr.textContent = fx.error || "";
    prevFix = { ...fk };
  }

  function renderUsbFeed(msg, a) {
    if (ifMeta) ifMeta.textContent = "Nano USB";
    if (msgHead) msgHead.innerHTML = USB_HEAD;
    kv(atKv, [
      ["Port", a.port],
      ["Baud", a.baud],
      ["Status", a.status],
      ["Invert", a.invert],
      ["HW UART", a.uart],
      ["RX bytes", a.rx_bytes],
      ["Frames", a.rx_frames],
      ["OK / bad", `${a.ok_count ?? 0} / ${a.bad_count ?? 0}`],
      ["Last frame age (ms)", a.last_frame_age_ms],
      ["Last SP-2 (E4) age", a.last_sp2_age_ms],
      ["Last SP-7 (E6) age", a.last_sp7_age_ms],
      ["Banner", a.banner],
      ["Log", a.log_path],
    ]);
    atErr.textContent = a.bus_error || "";

    const messages = msg.messages || [];
    msgMeta.textContent = `${messages.length} types`;
    if (!messages.length) {
      msgBody.innerHTML = `<tr><td colspan="9" class="muted">No frames yet…</td></tr>`;
    } else {
      msgBody.innerHTML = messages
        .map((m) => {
          const chk = m.check === "OK" ? "ok" : "bad";
          return `<tr>
            <td><code>${esc(m.dest)}</code></td>
            <td>${esc(m.label)}</td>
            <td><code>${esc(m.type)}</code></td>
            <td>${m.len}</td>
            <td>${m.rate_hz}</td>
            <td>${m.age_ms}</td>
            <td>${m.count}</td>
            <td class="${chk}">${esc(m.check)}</td>
            <td><code class="payload">${esc(m.data)}</code></td>
          </tr>`;
        })
        .join("");
    }

    const live = messages.filter((m) => m.check === "OK" && (m.age_ms ?? 99999) < 4000);
    const cards = [...live].sort((x, y) => watchPriority(x) - watchPriority(y) || x.type.localeCompare(y.type));
    watchMeta.textContent = `${cards.length} live`;
    if (!cards.length) {
      watch.innerHTML = `<p class="muted">Waiting for frames…</p>`;
    } else {
      watch.innerHTML = cards
        .map((m) => {
          const prev = prevBytes[m.key];
          const endian = (m.dest === "FF" && m.type === "32")
            ? `<p class="muted">Heading is little-endian degrees. i16 BE is the same two bytes swapped and is not a heading.</p>`
            : (m.dest === "FF" && m.type === "37")
              ? `<p class="muted">SP-4 OEM type $37 Euler10 (subtype $05): bank/pitch/yaw are signed int16 LE in tenths of a degree. Compare bank and pitch to the XTreme horizon. Mag heading stays on FF/32.</p>`
              : (m.decoded && m.decoded.length)
                ? ""
                : `<dl class="kv">
              <dt>i16 LE</dt><dd>${nums(m.i16le)}</dd>
              <dt>i16 BE</dt><dd>${nums(m.i16be)}</dd>
              <dt>u16 LE</dt><dd>${nums(m.u16le)}</dd>
              <dt>u16 BE</dt><dd>${nums(m.u16be)}</dd>
            </dl>`;
          return `<div class="inner-card watch-card">
            <h3>${esc(m.label)} · dest ${esc(m.dest)} type ${esc(m.type)} · ${m.rate_hz} Hz</h3>
            ${decodedBlock(m)}
            <div class="byte-row">${byteCells(m.bytes, prev)}</div>
            ${endian}
          </div>`;
        })
        .join("");
      const next = {};
      for (const m of live) next[m.key] = m.bytes || [];
      prevBytes = next;
    }
  }

  function render(msg) {
    if (msg.type !== "mgl_airtalk_update") return;
    if (hold.checked) return;

    const a = msg.airtalk || {};
    const up = a.status === "UP" && !a.bus_error;
    const fx = msg.fix || {};
    const fk = fx.keys || {};
    if (up) {
      setBadge(badgeIf, a.port ? a.port.split("/").pop() : "USB", "ok");
    } else if (fx.ok) {
      setBadge(badgeIf, "FIX owns USB", "ok");
    } else {
      setBadge(badgeIf, "USB off", "bad");
    }
    setBadge(badgeFix, fx.ok ? "FIX OK" : "FIX down", fx.ok ? "ok" : "bad");
    setTxt("v-at-pitch", fmt(fk.MGL_AT_PITCH, 1));
    setTxt("v-at-roll", fmt(fk.MGL_AT_ROLL, 1));
    setTxt("v-at-head", fmt(fk.MGL_AT_HEAD, 0));
    setTxt("v-at-yaw", fmt(fk.MGL_AT_YAW, 1));
    setTxt("v-at-slip", fmt(fk.MGL_AT_SLIP, 0));
    setTxt("v-at-g", fmt(fk.MGL_AT_G, 2));

    if (up) {
      setBadge(badgeRx, `RX ${a.rx_bytes ?? 0}`, "ok");
      setBadge(
        badgeOk,
        `OK ${a.ok_count ?? 0} / bad ${a.bad_count ?? 0}`,
        (a.bad_count || 0) > 0 && (a.ok_count || 0) === 0 ? "bad" : "ok"
      );
      renderUsbFeed(msg, a);
    } else {
      renderFixFeed(fx);
    }

    const recent = msg.recent || [];
    logMeta.textContent = `${recent.length}`;
    recentLog.textContent = recent
      .map((r) => `${r.check} DST=${r.dest} LEN=${r.len} TYPE=${r.type} DATA=${r.data || ""}`)
      .join("\n");
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/mgl-airtalk`);
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
        if (data.type === "mgl_airtalk_update") render(data);
        else if (data.type === "error") {
          atErr.textContent = data.message || "error";
          setBadge(badgeWs, "WS error", "bad");
        }
      } catch (e) {
        console.warn(e);
      }
    };
  }

  fetch("/api/mgl-airtalk/snapshot")
    .then((r) => r.json())
    .then(render)
    .catch(() => {});

  connect();
})();
