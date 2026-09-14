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
      document.getElementById("signals").textContent = JSON.stringify(
        d.historian_signals,
        null,
        2
      );
    })
    .catch((e) => {
      document.getElementById("wifi-note").textContent = String(e);
    });
})();
