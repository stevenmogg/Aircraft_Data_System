(function () {
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  fetch("/api/configuration")
    .then((r) => r.json())
    .then((d) => {
      const wifi = d.wifi || {};
      document.getElementById("wifi-note").textContent = wifi.note || "";

      const ol = document.getElementById("wifi-priority");
      ol.innerHTML = "";
      (wifi.priority_order || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        ol.appendChild(li);
      });

      const tbNet = document.querySelector("#wifi-nets tbody");
      tbNet.innerHTML = "";
      (wifi.interfaces || []).forEach((iface) => {
        (iface.networks || []).forEach((n) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `<td>${esc(n.ssid)}</td>
            <td>${esc(n.priority)}</td>
            <td>${esc(iface.iface)}</td>`;
          tbNet.appendChild(tr);
        });
      });

      const st = wifi.stratux || {};
      const ap = document.getElementById("wifi-ap");
      if (st.ok) {
        ap.innerHTML = `
          <div>AP SSID: <strong>${esc(st.ap_ssid)}</strong></div>
          <div>Mode: ${esc(st.wifi_mode)} (2 = AP+Client)</div>
          <div>Channel: ${esc(st.ap_channel)} · Country: ${esc(st.wifi_country)}</div>
          <div>Internet passthrough: ${esc(st.internet_passthrough)}</div>
          <div>Client networks in Stratux settings: ${esc(
            (st.client_networks || []).map((n) => n.ssid).join(", ")
          )}</div>`;
      } else {
        ap.textContent = "Stratux settings unavailable: " + (st.error || "");
      }

      document.getElementById("aircraft").textContent = JSON.stringify(
        { aircraft: d.aircraft, items: d.configuration_items },
        null,
        2
      );
      const hs = d.historian_signals || {};
      document.getElementById("signals-summary").textContent =
        `${hs.signal_count ?? 0} FIX keys · ${hs.fast_count ?? 0} at ${hs.fast_rate_hz ?? 10} Hz · ` +
        `${hs.slow_count ?? 0} at ${hs.slow_rate_hz ?? 1} Hz. Units are the values stored in FIX.`;
      const tb = document.querySelector("#signals-table tbody");
      tb.innerHTML = "";
      const signals = hs.signals || {};
      Object.keys(signals)
        .sort()
        .forEach((key) => {
          const s = signals[key] || {};
          const tr = document.createElement("tr");
          tr.innerHTML = `<td>${esc(key)}</td>
            <td>${esc(s.column)}</td>
            <td>${esc(s.units ?? "")}</td>
            <td>${esc(s.type)}</td>
            <td>${esc(s.rate_hz)}</td>
            <td>${esc(s.min ?? "")}</td>
            <td>${esc(s.max ?? "")}</td>
            <td>${esc(s.source)}</td>
            <td>${esc(s.description ?? "")}</td>`;
          tb.appendChild(tr);
        });
    })
    .catch((e) => {
      document.getElementById("wifi-note").textContent = String(e);
    });
})();
