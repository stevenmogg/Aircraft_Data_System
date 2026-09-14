(function () {
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function badge(el, cls, text) {
    el.className = "badge " + (cls || "");
    el.textContent = text;
  }

  function fmtUptime(s) {
    if (s == null) return "—";
    const n = Math.floor(s);
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    const sec = n % 60;
    if (h > 0) return h + "h " + m + "m";
    if (m > 0) return m + "m " + sec + "s";
    return sec + "s";
  }

  function fmtBytes(n) {
    if (n == null) return "—";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
    return (n / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  }

  function kv(el, rows) {
    el.innerHTML = rows
      .map(
        ([k, v]) =>
          `<dt>${esc(k)}</dt><dd>${v == null || v === "" ? "—" : esc(v)}</dd>`
      )
      .join("");
  }

  function shortUnit(u) {
    return String(u || "").replace(/\.service$/, "").replace(/\.path$/, " (path)");
  }

  function render(d) {
    const sys = d.system || {};
    const gps = d.gps || {};
    const fix = d.fix || {};
    const samples = fix.samples || {};
    const hist = d.historian || {};
    const wifi = d.wifi || {};
    const ext = d.external_data || {};
    const fan = sys.fan || {};
    const power = sys.power || {};
    const samba = sys.samba || {};
    const smbd = samba.smbd || {};
    const services = (sys.services && sys.services.items) || [];

    const gpsOk = !!gps.GPS_connected && (gps.fix_quality || 0) >= 1;
    const fixOk = !!fix.reachable;
    const histOk = !!hist.ok && hist.state !== "ERROR";

    badge(
      document.getElementById("badge-overall"),
      gpsOk && fixOk ? "ok" : fixOk ? "warn" : "bad",
      gpsOk && fixOk ? "System OK" : fixOk ? "Degraded" : "FIX down"
    );
    badge(
      document.getElementById("badge-gps"),
      gpsOk ? "ok" : gps.GPS_connected ? "warn" : "bad",
      gpsOk
        ? "GPS 3D"
        : gps.GPS_connected
          ? "GPS " + (gps.GPS_solution || "no fix")
          : "GPS off"
    );
    badge(
      document.getElementById("badge-fix"),
      fixOk ? "ok" : "bad",
      fixOk ? "FIX up" : "FIX down"
    );
    badge(
      document.getElementById("badge-hist"),
      hist.state === "RECORDING" ? "ok" : histOk ? "" : "bad",
      hist.state || "Historian …"
    );
    badge(
      document.getElementById("badge-temp"),
      sys.cpu_temp_c != null && sys.cpu_temp_c >= 70 ? "warn" : "",
      sys.cpu_temp_c != null ? sys.cpu_temp_c.toFixed(1) + " °C" : "Temp —"
    );
    const voltEl = document.getElementById("badge-volt");
    if (power.ext5v_v != null) {
      const voltTxt =
        power.ext5v_v.toFixed(2) +
        " V" +
        (power.undervoltage_now ? " UV" : "");
      badge(voltEl, power.level || "", voltTxt);
    } else if (power.available) {
      badge(
        voltEl,
        power.level || "",
        power.undervoltage_now ? "Undervolt" : "Volts —"
      );
    } else {
      badge(voltEl, "", "Volts —");
    }

    const tb = document.querySelector("#svc-table tbody");
    tb.innerHTML = "";
    services.forEach((s) => {
      const tr = document.createElement("tr");
      const ok = s.active === "active";
      tr.innerHTML = `<td>${esc(shortUnit(s.unit))}</td>
        <td><span class="badge ${ok ? "ok" : "bad"}">${esc(s.active)}</span></td>
        <td>${esc(s.enabled)}</td>`;
      tb.appendChild(tr);
    });

    kv(document.getElementById("overview-kv"), [
      ["Hostname", sys.hostname],
      ["UTC", sys.time_utc],
      ["Uptime", fmtUptime(sys.uptime_s)],
      ["Load avg", (sys.loadavg || []).map((x) => Number(x).toFixed(2)).join(" / ") || null],
    ]);

    kv(document.getElementById("gps-kv"), [
      ["Connected", gps.GPS_connected ? "yes" : "no"],
      ["Solution", gps.GPS_solution],
      ["Fix quality", gps.fix_quality],
      ["Latitude", gps.lat],
      ["Longitude", gps.lon],
      ["Alt MSL (ft)", gps.alt_msl != null ? Number(gps.alt_msl).toFixed(1) : null],
      ["Groundspeed", gps.gs != null ? Number(gps.gs).toFixed(2) : null],
      ["Track", gps.track],
      ["Sats locked / tracked / seen",
        [gps.GPS_satellites_locked, gps.GPS_satellites_tracked, gps.GPS_satellites_seen]
          .map((x) => (x == null ? "—" : x))
          .join(" / ")],
      ["AHRS pitch / roll",
        gps.pitch != null && gps.roll != null
          ? Number(gps.pitch).toFixed(2) + " / " + Number(gps.roll).toFixed(2)
          : null],
      ["IMU / BMP",
        (gps.IMUConnected ? "IMU yes" : "IMU no") +
          " · " +
          (gps.BMPConnected ? "BMP yes" : "BMP no")],
    ]);

    kv(document.getElementById("fix-kv"), [
      ["Reachable", fix.reachable ? "yes" : "no"],
      ["Endpoint", (fix.host || "") + ":" + (fix.port || "")],
      ["Sample PITCH", samples.pitch ?? fix.sample_pitch],
      ["Sample ROLL", samples.roll ?? fix.sample_roll],
      ["Sample LAT", samples.lat ?? fix.sample_lat],
      ["Sample LONG", samples.long ?? fix.sample_long],
      ["Sample GS", samples.gs ?? fix.sample_gs],
      ["Error", fix.error],
    ]);

    const db = hist.database || {};
    kv(document.getElementById("hist-kv"), [
      ["State", hist.state],
      ["Flight", hist.flight_id],
      ["Database", db.path],
      ["DB exists", db.exists ? "yes" : "no"],
      ["Flights (rows)", db.rows_flight],
      ["10 Hz frames (rows)", db.rows_historian_10hz],
      ["Daemon error", hist.daemon && hist.daemon.error],
    ]);

    const ntb = document.querySelector("#net-table tbody");
    ntb.innerHTML = "";
    (wifi.interfaces || []).forEach((iface) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(iface.iface)}</td>
        <td>${esc(iface.role)}</td>
        <td>${esc(iface.state || "—")}</td>
        <td>${esc(iface.ssid || "—")}</td>
        <td>${esc(iface.ip_address || "—")}</td>`;
      ntb.appendChild(tr);
    });
    const ap = document.getElementById("net-ap");
    if (wifi.ap_ssid) {
      ap.textContent =
        "Stratux AP: " + wifi.ap_ssid + " (mode " + (wifi.wifi_mode ?? "—") + ")";
    } else {
      ap.textContent = "";
    }

    const sambaActive = smbd.active === "active";
    const sambaListen = samba.listening_445;
    let sambaCls = "";
    let sambaTxt = "Samba —";
    if (sambaActive && sambaListen !== false) {
      sambaCls = "ok";
      sambaTxt = "Samba up";
    } else if (sambaActive && sambaListen === false) {
      sambaCls = "warn";
      sambaTxt = "Samba not listening";
    } else if (smbd.active && smbd.active !== "unknown") {
      sambaCls = "bad";
      sambaTxt = "Samba " + smbd.active;
    }
    badge(document.getElementById("badge-samba"), sambaCls, sambaTxt);
    kv(document.getElementById("samba-kv"), [
      ["smbd", smbd.active],
      ["Enabled", smbd.enabled],
      ["Share", samba.share],
      ["Path", samba.path],
      [
        "Port 445",
        sambaListen == null ? null : sambaListen ? "listening" : "not listening",
      ],
    ]);

    const disk = sys.disk || {};
    const yn = (v) => (v == null ? null : v ? "yes" : "no");
    kv(document.getElementById("host-kv"), [
      ["CPU temp", sys.cpu_temp_c != null ? sys.cpu_temp_c.toFixed(1) + " °C" : null],
      [
        "EXT5V",
        power.ext5v_v != null ? power.ext5v_v.toFixed(2) + " V" : null,
      ],
      [
        "Power",
        power.undervoltage_now
          ? "undervoltage now"
          : power.level === "ok"
            ? "ok"
            : power.ext5v_v != null && power.ext5v_v < 4.95
              ? "low"
              : power.undervoltage_occurred
                ? "UV earlier this boot"
                : power.level === "warn"
                  ? "warning"
                  : power.level === "bad"
                    ? "undervoltage"
                    : null,
      ],
      ["Throttled", power.throttled],
      ["Flags", (power.flags || []).join(", ") || null],
      ["Undervoltage now", yn(power.undervoltage_now)],
      ["Undervoltage this boot", yn(power.undervoltage_occurred)],
      ["Throttled now", yn(power.throttled_now)],
      ["Fan state",
        fan.cur_state != null
          ? fan.cur_state + " / " + fan.max_state + " (" + (fan.cooling_type || "fan") + ")"
          : null],
      ["Fan RPM", fan.rpm],
      ["Fan PWM", fan.pwm],
      ["Disk free",
        disk.free_bytes != null
          ? fmtBytes(disk.free_bytes) + " / " + fmtBytes(disk.total_bytes)
          : null],
      ["Disk path", disk.path],
    ]);

    const sync = ext.last_sync || {};
    const routes = sync.routes || {};
    kv(document.getElementById("ext-kv"), [
      ["Collection state", ext.collection_state],
      ["Service installed", ext.installed ? "yes" : "no"],
      ["Card mounted", ext.card_mounted ? "yes" : "no"],
      ["Last sync UTC", sync.timestamp_utc],
      ["Last device", sync.device],
      ["Routes written", routes.gpx_count != null ? String(routes.gpx_count) : null],
      ["Old routes removed", Array.isArray(routes.routes_removed) ? String(routes.routes_removed.length) : null],
      ["User waypoints appended", routes.ewd_added != null ? String(routes.ewd_added) : null],
      ["Route conversion", routes.ok === false ? (routes.error || "failed") : routes.ok ? "ok" : null],
      ["Enigma import", ext.import_enigma],
    ]);
  }

  function load() {
    fetch("/api/status")
      .then((r) => r.json())
      .then(render)
      .catch((e) => {
        badge(document.getElementById("badge-overall"), "bad", "Error");
        document.getElementById("overview-kv").innerHTML =
          "<dt>Error</dt><dd>" + esc(e) + "</dd>";
      });
  }

  load();
  setInterval(load, 5000);
})();
