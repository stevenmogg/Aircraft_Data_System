(() => {
  const $ = (id) => document.getElementById(id);
  const AXIS = {
    roll: {
      name: "Bank / Roll",
      xtreme: "IDENTIFY BANK SERVO",
      expected: 1,
      a: { which: "left", label: "Capture left" },
      b: { which: "right", label: "Capture right" },
    },
    pitch: {
      name: "Pitch",
      xtreme: "IDENTIFY PITCH SERVO",
      expected: 2,
      a: { which: "down", label: "Capture nose down" },
      b: { which: "up", label: "Capture nose up" },
    },
  };

  let snap = null;
  let posTimer = null;

  function axis() {
    return (snap && snap.control && snap.control.axis) || null;
  }

  function meta(key) {
    return AXIS[axis()] || AXIS.roll;
  }

  function badge(el, cls, text) {
    el.className = "badge" + (cls ? " " + cls : "");
    el.textContent = text;
  }

  function kv(el, rows) {
    el.innerHTML = rows
      .map(([k, v]) => `<dt>${k}</dt><dd>${v == null || v === "" ? "—" : v}</dd>`)
      .join("");
  }

  function showStep(step) {
    document.querySelectorAll(".wizard-step").forEach((sec) => {
      sec.hidden = sec.dataset.step !== step;
    });
    document.querySelectorAll(".axis-label").forEach((n) => {
      n.textContent = axis() ? meta().name : "—";
    });
  }

  function yn(v) {
    if (v === true || v === "True" || v === 1) return "yes";
    if (v === false || v === "False" || v === 0) return "no";
    return v == null ? "—" : String(v);
  }

  function num(v, digits) {
    const n = Number(v);
    return Number.isFinite(n) ? (digits == null ? String(n) : n.toFixed(digits)) : "—";
  }

  function xtremeIdentifyNumber() {
    const payload = ((snap.frames || {})["0x010"] || {}).payload || "";
    const bytes = payload.trim().split(/\s+/);
    if (bytes.length >= 3 && bytes[0] === "AA" && bytes[1] === "55") {
      const n = parseInt(bytes[2], 16);
      if (Number.isFinite(n)) return n;
    }
    const last = Number(liveLastId());
    return Number.isFinite(last) && last > 0 ? last : null;
  }

  function liveLastId() {
    return snap && snap.live ? snap.live.last_id : null;
  }

  function identifyName(n) {
    if (n === 1) return "Bank / servo 1";
    if (n === 2) return "Pitch / servo 2";
    return n == null ? "—" : `servo ${n}`;
  }

  function frameLine(id) {
    const f = (snap.frames || {})[id];
    if (!f) return `${id} none`;
    return `${id} n=${f.count} age=${f.age_ms}ms dlc=${f.dlc} ${f.payload || ""}`;
  }

  function render() {
    if (!snap) return;
    const ctrl = snap.control || {};
    const can = snap.can || {};
    const live = snap.live || {};
    const step = ctrl.install_mode ? ctrl.step || "preflight" : "idle";
    showStep(step);
    const rollFrame = (snap.frames || {})["0x101"];
    const pitchFrame = (snap.frames || {})["0x111"];
    const emuLive = !!(
      (rollFrame && rollFrame.age_ms != null && rollFrame.age_ms < 500) ||
      (pitchFrame && pitchFrame.age_ms != null && pitchFrame.age_ms < 500)
    );

    badge(
      $("badge-mode"),
      ctrl.install_mode ? "warn" : emuLive ? "ok" : "",
      ctrl.install_mode ? `install ${ctrl.axis || ""}` : emuLive ? "emulator live" : "idle"
    );
    const lo = can.listen_only;
    badge(
      $("badge-can"),
      can.status === "UP" && !lo ? "ok" : can.status === "UP" ? "warn" : "bad",
      can.status === "UP" ? (lo ? "can0 listen-only" : "can0 TX") : "can0 down"
    );
    const armed =
      live.tx_armed === true ||
      live.tx_armed === "True" ||
      live.tx_armed === 1 ||
      live.tx_armed === "1";
    badge($("badge-tx"), armed ? "ok" : "", armed ? "TX armed" : "TX off");
    const idok =
      live.last_id_ok === true ||
      live.last_id_ok === "True" ||
      live.identified === true ||
      live.identified === "True";
    badge($("badge-id"), idok ? "ok" : ctrl.step === "identify" ? "warn" : "", idok ? `id ${num(live.last_id, 0)}` : "identify");
    const axes = snap.axes || {};
    setEngageBadge($("badge-roll-eng"), "roll", (axes.roll || {}).engage_req);
    setEngageBadge($("badge-pitch-eng"), "pitch", (axes.pitch || {}).engage_req);

    kv($("preflight-kv"), [
      ["Interface", can.interface || "can0"],
      ["Status", can.status],
      ["Bitrate", can.bitrate],
      ["Listen-only", yn(lo)],
      ["FIX", snap.fix && snap.fix.ok ? "up" : (snap.fix && snap.fix.error) || "down"],
    ]);

    $("identify-hint").textContent = axis()
      ? `On the XTreme run ${meta().xtreme} (servo ${meta().expected}). Wait a few seconds for success or “no data has been received”.`
      : "";
    const asked = xtremeIdentifyNumber();
    const warn = $("identify-warn");
    if (asked && axis() && asked !== meta().expected) {
      warn.hidden = false;
      warn.textContent = `XTreme asked for ${identifyName(asked)}, but this page is installing ${meta().name} (servo ${meta().expected}). Exit, choose the matching axis, then identify again.`;
    } else if (asked && live.last_id_ok !== true && live.last_id_ok !== "True" && Number(live.last_id) > 0) {
      warn.hidden = false;
      warn.textContent = `XTreme identify for ${identifyName(asked)} was seen but not accepted. Use Retry identify, then run ${meta().xtreme} immediately.`;
    } else {
      warn.hidden = true;
      warn.textContent = "";
    }
    kv($("identify-kv"), [
      ["Pi expecting", axis() ? `${meta().name} / servo ${meta().expected}` : "—"],
      ["XTreme asked", identifyName(asked)],
      ["Identify armed", yn(live.identify_armed)],
      ["Accepted", yn(live.last_id_ok)],
      ["Assigned number", num(live.num, 0)],
      ["Replies sent", num(live.replies, 0)],
      ["0x101 / 0x111", `${frameLine("0x101")} · ${frameLine("0x111")}`],
    ]);
    $("identify-frames").textContent = [frameLine("0x010"), frameLine("0x011")].join(" · ");

    const pos = Number(ctrl.manual_position);
    if (Number.isFinite(pos) && document.activeElement !== $("pos-range")) {
      $("pos-range").value = String(pos);
      $("pos-value").textContent = signed(pos);
    }
    const a = meta().a;
    const b = meta().b;
    $("btn-lim-a").textContent = a.label;
    $("btn-lim-b").textContent = b.label;
    const lim = ((ctrl.limits || {})[axis() || "roll"] || {});
    kv($("limits-kv"), [
      ["Reported current", num(live.current, 0)],
      ["XTreme target", num(live.target, 0)],
      [a.which, lim[a.which]],
      [b.which, lim[b.which]],
    ]);

    kv($("done-kv"), [
      ["Axis", axis() ? meta().name : "—"],
      ["Servo number", num(live.num, 0)],
      ["Roll left", signed(asS12(((ctrl.limits || {}).roll || {}).left))],
      ["Roll right", signed(asS12(((ctrl.limits || {}).roll || {}).right))],
      ["Pitch down", signed(asS12(((ctrl.limits || {}).pitch || {}).down))],
      ["Pitch up", signed(asS12(((ctrl.limits || {}).pitch || {}).up))],
    ]);

    renderLive();
  }

  function asS12(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    if (n > 2047) {
      const u = n & 4095;
      return u >= 2048 ? u - 4096 : u;
    }
    return n;
  }

  function signed(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n > 0 ? `+${n}` : String(n);
  }

  function limitLabel(role, view) {
    const lim = (view && view.limits) || {};
    if (role === "roll") return `left ${signed(lim.left)} · right ${signed(lim.right)}`;
    return `down ${signed(lim.down)} · up ${signed(lim.up)}`;
  }

  function isOn(v) {
    return v === true || v === "True" || v === 1 || v === "1";
  }

  function setEngageBadge(el, label, on) {
    if (!el) return;
    if (on == null) {
      badge(el, "", `${label} …`);
      return;
    }
    const engaged = isOn(on);
    badge(el, engaged ? "ok" : "", engaged ? `${label} engaged` : `${label} off`);
  }

  function renderLive() {
    const axes = (snap && snap.axes) || {};
    document.querySelectorAll("[data-live-axis]").forEach((card) => {
      const role = card.dataset.liveAxis;
      const view = axes[role] || {};
      const cmd = view.command;
      const resp = view.response;
      card.querySelector(".live-cmd").textContent = signed(cmd);
      card.querySelector(".live-resp").textContent = signed(resp);
      const offEl = card.querySelector(".live-off");
      const slider = card.querySelector(".live-offset");
      const offset = Number(view.offset);
      offEl.textContent = signed(Number.isFinite(offset) ? offset : 0);
      if (slider && document.activeElement !== slider && Number.isFinite(offset)) {
        slider.value = String(offset);
      }
      setEngageBadge(card.querySelector(".live-eng"), "XTreme", view.engage_req);
      const opt = Number(view.options);
      kv(card.querySelector(".live-kv"), [
        ["XTreme engage", view.engage_req == null ? "—" : isOn(view.engage_req) ? "engaged" : "off"],
        ["Reply engaged", view.engaged == null ? "—" : isOn(view.engaged) ? "yes" : "no"],
        ["Options", Number.isFinite(opt) ? `0x${opt.toString(16).toUpperCase().padStart(2, "0")}` : "—"],
        ["Limits", `${signed(view.limit_lo)} … ${signed(view.limit_hi)}`],
        ["Captured", limitLabel(role, view)],
        ["Wire cmd", Number.isFinite(Number(view.command_raw)) ? String(Math.round(Number(view.command_raw))) : "—"],
        ["Reply Hz", num(view.hz, 1)],
      ]);
    });
  }

  async function api(path, body, method) {
    const opt = { method: method || (body == null ? "GET" : "POST") };
    if (body != null) {
      opt.headers = { "Content-Type": "application/json" };
      opt.body = JSON.stringify(body);
    }
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText);
    return data;
  }

  async function refresh() {
    try {
      snap = await api("/api/mgl-servo/snapshot");
      render();
    } catch (e) {
      badge($("badge-mode"), "bad", String(e.message || e));
    }
  }

  async function post(path, body, method) {
    snap = await api(path, body, method || "POST");
    render();
  }

  document.querySelectorAll("[data-axis]").forEach((btn) => {
    btn.addEventListener("click", () => post("/api/mgl-servo/install", { axis: btn.dataset.axis }));
  });
  $("btn-abort").addEventListener("click", () => post("/api/mgl-servo/abort", null, "POST"));
  $("btn-exit").addEventListener("click", () => post("/api/mgl-servo/abort", null, "POST"));
  $("btn-can-tx").addEventListener("click", async () => {
    await api("/api/mgl-servo/can-tx", { enable: true }, "POST");
    await refresh();
  });
  $("btn-listen").addEventListener("click", async () => {
    await api("/api/mgl-servo/can-tx", { enable: false }, "POST");
    await refresh();
  });
  $("btn-identify").addEventListener("click", () => post("/api/mgl-servo/step", { step: "identify" }));
  $("btn-limits").addEventListener("click", () => post("/api/mgl-servo/step", { step: "limits" }));
  $("btn-done").addEventListener("click", () => post("/api/mgl-servo/step", { step: "done" }));
  $("btn-retry-id").addEventListener("click", async () => {
    const ax = axis();
    if (!ax) return;
    await post("/api/mgl-servo/install", { axis: ax });
    await post("/api/mgl-servo/step", { step: "identify" });
  });
  $("btn-other").addEventListener("click", () => {
    const next = axis() === "roll" ? "pitch" : "roll";
    return post("/api/mgl-servo/install", { axis: next });
  });
  $("btn-lim-a").addEventListener("click", () => post("/api/mgl-servo/limit", { which: meta().a.which }));
  $("btn-lim-b").addEventListener("click", () => post("/api/mgl-servo/limit", { which: meta().b.which }));

  $("pos-range").addEventListener("input", () => {
    const v = Number($("pos-range").value);
    $("pos-value").textContent = signed(v);
    clearTimeout(posTimer);
    posTimer = setTimeout(() => post("/api/mgl-servo/position", { position: v }), 80);
  });
  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => post("/api/mgl-servo/position", { position: Number(btn.dataset.preset) }));
  });

  const offsetTimers = {};
  document.querySelectorAll(".live-offset").forEach((slider) => {
    slider.addEventListener("input", () => {
      const card = slider.closest("[data-live-axis]");
      const role = card && card.dataset.liveAxis;
      const v = Number(slider.value);
      if (card) card.querySelector(".live-off").textContent = signed(v);
      if (!role) return;
      clearTimeout(offsetTimers[role]);
      offsetTimers[role] = setTimeout(() => post("/api/mgl-servo/offset", { axis: role, offset: v }), 80);
    });
  });
  document.querySelectorAll("[data-offset-zero]").forEach((btn) => {
    btn.addEventListener("click", () => post("/api/mgl-servo/offset", { axis: btn.dataset.offsetZero, offset: 0 }));
  });

  refresh();
  setInterval(refresh, 500);
})();
