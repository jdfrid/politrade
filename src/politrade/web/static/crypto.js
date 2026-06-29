(function () {
  const windowsEl = document.getElementById("crypto-windows");
  if (!windowsEl) return;

  let pollMs = 2000;

  function fmtMoney(v) {
    if (v == null) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function fmtPct(v) {
    if (v == null) return "—";
    return Number(v).toFixed(2) + "%";
  }

  function fmtTime(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function phaseLabel(phase) {
    const map = {
      early: "מוקדם (לא מהמרים)",
      bet: "חלון הימור ✓",
      late: "מאוחר (לא מהמרים)",
      closed: "נסגר",
    };
    return map[phase] || phase;
  }

  function phaseClass(phase) {
    if (phase === "bet") return "ok";
    if (phase === "closed") return "muted";
    return "warn";
  }

  function renderWindow(item) {
    const w = item.window || {};
    const o = item.oracle || {};
    const t = item.tokens || {};
    const d = item.decision || {};
    const placed = item.bet_placed;
    const highlight = placed ? " crypto-window-bet" : d.action === "bet" ? " crypto-window-ready" : "";
    const side = d.side ? d.side.toUpperCase() : "—";

    let html = '<div class="card crypto-window' + highlight + '">';
    html += '<div class="crypto-window-head">';
    html += "<h2>" + (w.asset_label || w.asset || "?") + " · " + (w.title || w.slug || "") + "</h2>";
    html += '<span class="phase-badge ' + phaseClass(w.phase) + '">' + phaseLabel(w.phase) + "</span>";
    html += "</div>";

    html += '<div class="grid crypto-stats">';
    html += stat("זמן", fmtTime(w.seconds_remaining || 0) + " נותר");
    html += stat("Chainlink", priceLine(o));
    html += stat("Up", tokenLine(t.up_bid, t.up_ask, t.up_mid));
    html += stat("Down", tokenLine(t.down_bid, t.down_ask, t.down_mid));
    html += "</div>";

    html += '<canvas class="sparkline" data-slug="' + escapeAttr(w.slug || "") + '" width="600" height="60"></canvas>';

    html += '<div class="crypto-decision">';
    html += "<strong>החלטה:</strong> " + escapeHtml(d.reason || "—");
    if (d.edge_pct != null) html += " · edge " + fmtPct(d.edge_pct);
    if (placed) html += ' <span class="ok">✓ הימור בוצע</span>';
    html += "</div>";

    if (w.phase === "bet" && d.action === "bet" && !placed) {
      html += '<form class="crypto-manual-bet btn-row" data-asset="' + escapeAttr(w.asset) + '" data-side="' + escapeAttr(d.side) + '">';
      html += '<input type="number" name="amount" min="1" step="1" value="5" class="bet-amount" style="width:5rem">';
      html += '<button type="submit" class="btn primary">המר ' + side + " עכשיו</button>";
      html += "</form>";
    }

    html += "</div>";
    return html;
  }

  function stat(label, value) {
    return '<div class="crypto-stat"><span class="muted small">' + label + '</span><strong>' + value + "</strong></div>";
  }

  function priceLine(o) {
    if (!o.open_price && !o.current_price) return "—";
    let s = (o.current_price != null ? Number(o.current_price).toFixed(2) : "?");
    if (o.delta_pct != null) {
      const cls = o.delta_pct >= 0 ? "ok" : "err";
      s += ' <span class="' + cls + '">(' + fmtPct(o.delta_pct) + ")</span>";
    }
    if (o.open_price) s += '<br><span class="small muted">open ' + Number(o.open_price).toFixed(2) + "</span>";
    return s;
  }

  function tokenLine(bid, ask, mid) {
    if (ask == null && mid == null) return "—";
    return "ask " + (ask != null ? Number(ask).toFixed(3) : "?") +
      " · mid " + (mid != null ? Number(mid).toFixed(3) : "?");
  }

  function escapeHtml(s) {
    const el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, "&quot;");
  }

  function drawSparklines(state) {
    (state.windows || []).forEach(function (item, idx) {
      const hist = (item.oracle && item.oracle.history) || [];
      const canvas = document.querySelectorAll(".sparkline")[idx];
      if (!canvas || !hist.length) return;
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const prices = hist.map(function (p) { return p.price; });
      const min = Math.min.apply(null, prices);
      const max = Math.max.apply(null, prices);
      const range = max - min || 1;
      ctx.strokeStyle = "#3b82f6";
      ctx.beginPath();
      prices.forEach(function (p, i) {
        const x = (i / (prices.length - 1 || 1)) * w;
        const y = h - ((p - min) / range) * (h - 4) - 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });
  }

  function renderBets(bets) {
    const body = document.getElementById("crypto-bets-body");
    if (!body) return;
    if (!bets.length) {
      body.innerHTML = '<tr><td colspan="7" class="muted">אין הימורים עדיין</td></tr>';
      return;
    }
    body.innerHTML = bets.map(function (b) {
      const pnl = b.realized_pnl != null ? fmtMoney(b.realized_pnl) : "—";
      const pnlCls = (b.realized_pnl || 0) >= 0 ? "ok" : "err";
      return "<tr>" +
        "<td>" + escapeHtml(b.asset) + "</td>" +
        "<td class='mono small'>" + escapeHtml(b.slug) + "</td>" +
        "<td>" + escapeHtml(b.side) + "</td>" +
        "<td>" + fmtMoney(b.bet_usd) + "</td>" +
        "<td>" + (b.edge_pct != null ? fmtPct(b.edge_pct) : "—") + "</td>" +
        "<td>" + escapeHtml(b.status) + "</td>" +
        "<td class='" + pnlCls + "'>" + pnl + "</td>" +
        "</tr>";
    }).join("");
  }

  function render(data) {
    const state = data.state || {};
    const summary = data.summary || {};
    const runner = data.runner || {};

    document.getElementById("sum-cash").textContent = fmtMoney(data.wallet && data.wallet.cash_usd);
    document.getElementById("sum-runner").textContent = runner.running ? "פעיל" : "כבוי";
    document.getElementById("sum-runner").className = "big " + (runner.running ? "ok" : "muted");
    document.getElementById("sum-wl").textContent = summary.wins + " / " + summary.losses;
    const pnlEl = document.getElementById("sum-pnl");
    pnlEl.textContent = fmtMoney(summary.total_pnl);
    pnlEl.className = "big " + ((summary.total_pnl || 0) >= 0 ? "ok" : "err");

    document.getElementById("auto-label").textContent = state.auto_bet ? "פעיל" : "כבוי";

    const items = state.windows || [];
    windowsEl.innerHTML = items.length
      ? items.map(renderWindow).join("")
      : '<p class="muted">אין חלונות פעילים — בודק שווקים…</p>';

    drawSparklines(state);
    renderBets(data.bets || []);

    bindManualForms();
  }

  function bindManualForms() {
    document.querySelectorAll(".crypto-manual-bet").forEach(function (form) {
      form.onsubmit = function (e) {
        e.preventDefault();
        const asset = form.getAttribute("data-asset");
        const side = form.getAttribute("data-side");
        const amount = form.querySelector(".bet-amount").value;
        const fd = new FormData();
        fd.append("asset", asset);
        fd.append("side", side);
        fd.append("amount", amount);
        fetch("/api/crypto/bet", { method: "POST", body: fd, credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function () { refresh(); })
          .catch(function () { alert("הימור נכשל"); });
      };
    });
  }

  function refresh() {
    fetch("/api/crypto/live", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(render)
      .catch(function () {
        windowsEl.innerHTML = '<p class="err">לא ניתן לטעון נתונים</p>';
      });
  }

  document.getElementById("btn-auto-on").onclick = function () {
    setAuto(true);
  };
  document.getElementById("btn-auto-off").onclick = function () {
    setAuto(false);
  };

  function setAuto(on) {
    const fd = new FormData();
    fd.append("enabled", on ? "1" : "0");
    fetch("/api/crypto/auto", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function () { refresh(); });
  }

  refresh();
  setInterval(refresh, pollMs);
})();
