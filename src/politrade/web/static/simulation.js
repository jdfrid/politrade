(function () {
  const body = document.getElementById("sim-markets-body");
  if (!body) return;

  let pollTimer = null;

  function fmtMoney(v) {
    if (v == null) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function fmtPct(v) {
    if (v == null) return "—";
    return Number(v).toFixed(1) + "%";
  }

  function fmtTime(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function escapeHtml(s) {
    const el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function worthLabel(item) {
    if (item.bet_placed) return '<span class="ok">הימור בוצע</span>';
    if (item.worth_investing) return '<span class="ok">כן ✓</span>';
    const a = (item.decision && item.decision.action) || "wait";
    if (a === "skip") return '<span class="muted">לא</span>';
    if (a === "wait") return '<span class="warn">ממתין</span>';
    return '<span class="muted">—</span>';
  }

  function statusLabel(item) {
    if (item.bet_status === "won") return '<span class="ok">זכייה</span>';
    if (item.bet_status === "lost") return '<span class="err">הפסד</span>';
    if (item.bet_status === "open" || item.bet_placed) return '<span class="warn">פתוח</span>';
    const w = item.window || {};
    if (w.phase === "closed") return '<span class="muted">נסגר</span>';
    return '<span class="muted">מנטר</span>';
  }

  function renderMarkets(data) {
    const markets = (data.state && data.state.markets) || [];
    const summary = document.getElementById("sim-markets-summary");
    if (summary) {
      summary.textContent = markets.length + " שווקים · " +
        markets.filter(function (m) { return m.worth_investing; }).length + " הזדמנויות";
    }
    if (!markets.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted">אין שווקים — בודק Gamma…</td></tr>';
      return;
    }
    body.innerHTML = markets.map(function (item) {
      const w = item.window || {};
      const d = item.decision || {};
      const isCurrent = w.window_ts === data.window_ts;
      const rowCls = isCurrent ? "market-current" : "";
      const edge = d.edge_pct != null ? fmtPct(d.edge_pct) : "—";
      const rec = item.recommended_usd > 0 ? fmtMoney(item.recommended_usd) : "—";
      return "<tr class='" + rowCls + "'>" +
        "<td><strong>" + escapeHtml(w.asset_label || w.asset || "?") + "</strong></td>" +
        "<td><span class='muted small'>" + fmtTime(w.seconds_remaining || 0) + " נותר</span></td>" +
        "<td>" + worthLabel(item) + "</td>" +
        "<td>" + escapeHtml(item.entry_timing || "—") + "</td>" +
        "<td>" + rec + "</td>" +
        "<td>" + edge + "</td>" +
        "<td>" + statusLabel(item) + "</td>" +
        "<td class='small'>" + escapeHtml(d.reason || "—") + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderSummary(data) {
    const bal = document.getElementById("sim-balance");
    const pnl = document.getElementById("sim-cumulative-pnl");
    const ready = document.getElementById("sim-readiness");
    const wt = document.getElementById("sim-window-time");
    const auto = document.getElementById("sim-auto-label");
    const mode = document.getElementById("sim-mode-label");

    if (bal) bal.textContent = fmtMoney(data.sim_balance);
    const cp = data.cumulative_pnl || 0;
    if (pnl) {
      pnl.textContent = (cp >= 0 ? "+" : "") + fmtMoney(cp);
      pnl.className = "big " + (cp >= 0 ? "ok" : "err");
    }
    if (ready) ready.textContent = (data.readiness_score || 0).toFixed(0) + "/100";
    if (wt) wt.textContent = fmtTime(data.seconds_remaining || 0) + " נותר";
    if (auto) auto.textContent = (data.state && data.state.auto_sim) ? "פעיל" : "מושהה";
    if (mode) mode.textContent = data.live_enabled ? "לייב" : "סימולציה בלבד";

    const cycle = data.latest_cycle;
    const panel = document.getElementById("sim-latest-cycle");
    if (cycle && panel) {
      panel.style.display = "block";
      document.getElementById("sim-latest-summary").textContent = cycle.summary_he || "";
      document.getElementById("sim-latest-lessons").textContent = cycle.lessons_he || "";
      let delta = "";
      if (cycle.win_rate_delta != null) delta += "Win rate Δ " + cycle.win_rate_delta + "% · ";
      if (cycle.pnl_delta != null) delta += "PnL Δ " + fmtMoney(cycle.pnl_delta);
      document.getElementById("sim-progress-delta").textContent = delta;
    }

    const ind = document.getElementById("sim-refresh-indicator");
    if (ind) ind.textContent = "עודכן " + new Date().toLocaleTimeString("he-IL");
  }

  function renderCycles(cyclesData) {
    const el = document.getElementById("sim-cycles-list");
    if (!el) return;
    const cycles = (cyclesData && cyclesData.cycles) || [];
    if (!cycles.length) {
      el.innerHTML = "<p class='muted'>אין סיבובים סגורים עדיין — המתן לסיום חלון 5 דק'</p>";
      return;
    }
    el.innerHTML = cycles.map(function (c) {
      const delta = [];
      if (c.win_rate_delta != null) delta.push("WR Δ" + c.win_rate_delta + "%");
      if (c.pnl_delta != null) delta.push("PnL Δ" + fmtMoney(c.pnl_delta));
      return "<div class='cycle-card'>" +
        "<div class='cycle-head'><strong>חלון " + c.window_ts + "</strong> · PnL " + fmtMoney(c.cycle_pnl) +
        " · מצטבר " + fmtMoney(c.cumulative_pnl) + " · readiness " + c.readiness_score + "</div>" +
        "<pre class='cycle-summary small'>" + escapeHtml(c.summary_he || "") + "</pre>" +
        "<p class='muted small'>" + escapeHtml(c.lessons_he || "") + "</p>" +
        (delta.length ? "<p class='small ok'>" + delta.join(" · ") + "</p>" : "") +
        "</div>";
    }).join("");
  }

  function refresh() {
    Promise.all([
      fetch("/api/sim/live", { credentials: "same-origin" }).then(function (r) { return r.json(); }),
      fetch("/api/sim/cycles", { credentials: "same-origin" }).then(function (r) { return r.json(); }),
    ]).then(function (results) {
      renderSummary(results[0]);
      renderMarkets(results[0]);
      renderCycles(results[1]);
      scheduleNext(results[0]);
    }).catch(function () {
      body.innerHTML = '<tr><td colspan="8" class="err">שגיאת טעינה</td></tr>';
      scheduleNext(null);
    });
  }

  function scheduleNext(data) {
    if (pollTimer) clearTimeout(pollTimer);
    const ms = 1500;
    pollTimer = setTimeout(refresh, ms);
  }

  document.getElementById("btn-sim-on").onclick = function () {
    fetch("/api/sim/start", { method: "POST", credentials: "same-origin" }).then(refresh);
  };
  document.getElementById("btn-sim-off").onclick = function () {
    fetch("/api/sim/stop", { method: "POST", credentials: "same-origin" }).then(refresh);
  };

  refresh();
})();
