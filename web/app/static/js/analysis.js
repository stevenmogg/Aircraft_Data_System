(function () {
  const sel = document.getElementById("flight-select");
  const msg = document.getElementById("analysis-msg");
  const canvas = document.getElementById("chart");
  const ctx = canvas.getContext("2d");

  function drawSeries(series) {
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#101820";
    ctx.fillRect(0, 0, w, h);
    const t = series.flight_time_s || [];
    const pitch = series.fix_pitch || [];
    const roll = series.fix_roll || [];
    if (!t.length) {
      msg.textContent = "No samples";
      return;
    }
    const ys = pitch.concat(roll).filter((v) => v !== null && v !== undefined);
    let ymin = Math.min(...ys), ymax = Math.max(...ys);
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const pad = 40;
    const x0 = pad, y0 = h - pad, x1 = w - 10, y1 = 10;
    const tx = (i) => x0 + (i / (t.length - 1 || 1)) * (x1 - x0);
    const ty = (v) => y0 - ((v - ymin) / (ymax - ymin)) * (y0 - y1);

    function stroke(arr, color) {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      let started = false;
      for (let i = 0; i < arr.length; i++) {
        if (arr[i] === null || arr[i] === undefined) { started = false; continue; }
        const x = tx(i), y = ty(arr[i]);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    stroke(pitch, "#7ddeb8");
    stroke(roll, "#7db0de");
    ctx.fillStyle = "#8fa3b3";
    ctx.font = "14px sans-serif";
    ctx.fillText("pitch", pad, 20);
    ctx.fillStyle = "#7db0de";
    ctx.fillText("roll", pad + 60, 20);
    msg.textContent = `${series.returned_rows} points (of ${series.total_rows})  t=${t[0]?.toFixed?.(1)}–${t[t.length-1]?.toFixed?.(1)}s`;
  }

  async function loadFlights() {
    const d = await fetch("/api/flights").then((r) => r.json());
    sel.innerHTML = "";
    (d.flights || []).forEach((f) => {
      const o = document.createElement("option");
      o.value = f.flight_id;
      o.textContent = f.flight_id + (f.actual_10hz_frames != null ? ` (${f.actual_10hz_frames} f)` : "");
      sel.appendChild(o);
    });
    updateExport();
  }

  function updateExport() {
    const id = sel.value;
    document.getElementById("btn-export").href = id ? `/api/export/${id}` : "#";
  }

  document.getElementById("btn-plot").onclick = async () => {
    const id = sel.value;
    if (!id) return;
    msg.textContent = "Loading…";
    const d = await fetch(`/api/flights/${id}/series?columns=fix_pitch,fix_roll,fix_alt`).then((r) => r.json());
    if (!d.ok) { msg.textContent = d.detail || "error"; return; }
    drawSeries(d.series);
  };
  sel.onchange = updateExport;
  loadFlights();
})();
