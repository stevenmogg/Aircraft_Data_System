(function () {
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtBytes(n) {
    if (n == null) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }

  function stateBadge(state) {
    const map = {
      card_mounted: ["ok", "Card mounted"],
      idle_last_ok: ["ok", "Last sync OK"],
      idle_last_failed: ["bad", "Last sync failed"],
      ready_no_sync_yet: ["warn", "Ready — no sync yet"],
      not_installed: ["bad", "Not installed"],
    };
    const [cls, label] = map[state] || ["", state || "unknown"];
    return { cls, label };
  }

  function renderExternal(d) {
    const root = document.getElementById("external-data");
    const badge = document.getElementById("ext-badge");
    const st = stateBadge(d.collection_state);
    badge.className = "badge " + st.cls;
    badge.textContent = "External: " + st.label;

    const sync = d.last_sync || null;
    const inbox = d.inbox || {};
    const enigmaFiles = inbox.enigma || [];
    const xtFiles = inbox.xtflight || [];

    const planItems = (d.flight_plans_on_pi || [])
      .map((n) => `<li>${esc(n)}</li>`)
      .join("");
    const enigmaItems = enigmaFiles
      .map(
        (f) =>
          `<li>${esc(f.name)} <span class="muted">(${fmtBytes(f.bytes)})</span></li>`
      )
      .join("");
    const xtItems = xtFiles
      .map(
        (f) =>
          `<li>${esc(f.name)} <span class="muted">(${fmtBytes(f.bytes)})</span></li>`
      )
      .join("");

    const routes = (sync && sync.routes) || {};
    const routeRows = (routes.routes || [])
      .map((r) => {
        const db = (r.db_waypoints || []).join(", ") || "—";
        const user = (r.user_waypoints || []).join(", ") || "—";
        return `<tr>
          <td>${esc(r.gpx)}</td>
          <td><code>${esc(r.ert)}</code></td>
          <td>${esc(db)}</td>
          <td>${esc(user)}</td>
        </tr>`;
      })
      .join("");
    const removed = (routes.routes_removed || [])
      .map((n) => `<li><code>${esc(n)}</code></li>`)
      .join("");
    const routeErrors = (routes.errors || [])
      .map((e) => `<li>${esc(e.gpx || "")}: ${esc(e.error || e)}</li>`)
      .join("");

    root.innerHTML = `
      <div class="status-line" style="margin-bottom:0.75rem;">
        <span class="badge ${st.cls}">${esc(st.label)}</span>
        <span class="badge ${d.installed ? "ok" : "bad"}">${
          d.installed ? "Service installed" : "Service missing"
        }</span>
        <span class="badge ${d.card_mounted ? "ok" : ""}">${
          d.card_mounted ? "MGL card present" : "No card mounted"
        }</span>
      </div>

      <div class="inner-card">
        <h3>Last sync</h3>
        ${
          sync
            ? `<dl class="kv">
            <dt>Time (UTC)</dt><dd>${esc(sync.timestamp_utc || "—")}</dd>
            <dt>Device</dt><dd>${esc(sync.device || "—")}</dd>
            <dt>AvPlan files removed from card</dt><dd>${esc(sync.plans_deleted)}</dd>
            <dt>ENIGMA.REC → Pi</dt><dd>${esc(sync.enigma || "—")}</dd>
            <dt>XTFLIGHT.CSV → Pi</dt><dd>${esc(sync.xtflight || "—")}</dd>
            <dt>Enigma import</dt><dd>${esc(d.import_enigma || sync.import_enigma || "pending")}</dd>
          </dl>`
            : `<p class="muted">No sync has run yet. Insert an MGL-labelled SD card to collect files.</p>`
        }
      </div>

      <div class="inner-card">
        <h3>Routes on card</h3>
        ${
          routes.error
            ? `<p class="muted">Conversion error: ${esc(routes.error)}</p>`
            : ""
        }
        ${
          routeErrors
            ? `<ul class="file-list">${routeErrors}</ul>`
            : ""
        }
        ${
          routeRows
            ? `<p class="muted">AvPlan GPX on the Pi → Extreme <code>.ert</code> on the SD card (8.3 names). Old routes were removed first.</p>
              <table class="data">
                <thead><tr><th>AvPlan (Pi)</th><th>Route (card)</th><th>Navidata waypoints</th><th>User waypoints added</th></tr></thead>
                <tbody>${routeRows}</tbody>
              </table>`
            : `<p class="muted">No GPX converted on last sync.</p>`
        }
        <dl class="kv" style="margin-top:0.75rem;">
          <dt>Navidata used</dt><dd>${esc(routes.navidata || "—")}</dd>
          <dt>WAYPOINT.EWD</dt><dd>${esc(routes.ewd || "—")}</dd>
          <dt>User waypoints appended</dt><dd>${esc(
            routes.ewd_added != null ? String(routes.ewd_added) : "—"
          )} (file now ${esc(routes.ewd_total != null ? String(routes.ewd_total) : "—")})</dd>
        </dl>
        ${
          removed
            ? `<p class="muted" style="margin-top:0.5rem;">Removed from card before write:</p><ul class="file-list">${removed}</ul>`
            : ""
        }
      </div>

      <div class="inner-card">
        <h3>Flight plans on Pi (${esc(d.flight_plans_count || 0)})</h3>
        ${
          planItems
            ? `<ul class="file-list">${planItems}</ul>`
            : `<p class="muted">None — place AvPlan GPX in ${esc(
                (d.paths && d.paths.flight_plans) || "/cozy-data-system/data/flight-plans"
              )}</p>`
        }
      </div>

      <div class="inner-card">
        <h3>Inbox — Enigma</h3>
        ${
          enigmaItems
            ? `<ul class="file-list">${enigmaItems}</ul>`
            : `<p class="muted">Empty</p>`
        }
      </div>

      <div class="inner-card">
        <h3>Inbox — XTFLIGHT</h3>
        ${
          xtItems
            ? `<ul class="file-list">${xtItems}</ul>`
            : `<p class="muted">Empty</p>`
        }
      </div>

      ${
        d.card_mounted
          ? `<div class="inner-card">
              <h3>Card root (mounted)</h3>
              <ul class="file-list">${(d.card_root_files || [])
                .map((n) => `<li>${esc(n)}</li>`)
                .join("") || "<li class='muted'>empty</li>"}</ul>
            </div>`
          : ""
      }
    `;
  }

  function fetchJson(url) {
    return fetch(url).then((r) =>
      r.text().then((text) => {
        if (!text) {
          throw new Error(url + " empty (HTTP " + r.status + ")");
        }
        try {
          return JSON.parse(text);
        } catch (e) {
          const snippet = text.replace(/\s+/g, " ").slice(0, 120);
          throw new Error(url + " HTTP " + r.status + " — " + snippet);
        }
      })
    );
  }

  fetchJson("/api/flights")
    .then((d) => {
      const tb = document.getElementById("flights-body");
      const flights = d.flights || [];
      document.getElementById("flights-count").textContent =
        "Flights: " + flights.length;
      document.getElementById("flights-meta").textContent =
        flights.length + " recorded";
      tb.innerHTML = "";
      if (!flights.length) {
        tb.innerHTML =
          '<tr><td colspan="4" class="muted">No flights recorded yet</td></tr>';
        return;
      }
      flights.forEach((f) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><a href="/flights/${esc(f.flight_id)}">${esc(
          f.flight_id
        )}</a></td>
        <td>${esc(f.flight_date || "")}</td>
        <td>${esc(f.historian_start_utc || "")}</td>
        <td>${esc(f.actual_10hz_frames ?? "")}</td>`;
        tb.appendChild(tr);
      });
    })
    .catch((e) => {
      document.getElementById("flights-body").innerHTML =
        '<tr><td colspan="4" class="muted">' + esc(e) + "</td></tr>";
    });

  fetchJson("/api/external-data")
    .then(renderExternal)
    .catch((e) => {
      document.getElementById("ext-badge").className = "badge bad";
      document.getElementById("ext-badge").textContent = "External: error";
      document.getElementById("external-data").innerHTML =
        '<p class="muted">' + esc(e) + "</p>";
    });
})();
