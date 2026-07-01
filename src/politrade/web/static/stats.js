(function () {
  if (!document.getElementById("chart-win-loss")) return;

  let currentTrack = "champion";
  let statsData = null;
  let charts = { winLoss: null, money: null, timeline: null };

  function fmtMoney(v) {
    if (v == null) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function escapeHtml(s) {
    var el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function trackData() {
    if (!statsData) return null;
    if (currentTrack === "variants") return statsData.variants;
    if (currentTrack === "combined") return statsData.combined;
    return statsData.champion;
  }

  function renderKpi() {
    var t = trackData();
    if (!t) return;
    var wr = document.getElementById("kpi-win-rate");
    var inv = document.getElementById("kpi-invested");
    var pnl = document.getElementById("kpi-pnl");
    var bets = document.getElementById("kpi-bets");
    if (wr) {
      wr.textContent = (t.win_rate_pct || 0).toFixed(1) + "%";
      wr.className = "big " + ((t.win_rate_pct || 0) >= 50 ? "ok" : "err");
    }
    if (inv) inv.textContent = fmtMoney(t.total_invested_usd);
    if (pnl) {
      var p = t.total_pnl_usd || 0;
      pnl.textContent = (p >= 0 ? "+" : "") + fmtMoney(p);
      pnl.className = "big " + (p >= 0 ? "ok" : "err");
    }
    if (bets) {
      bets.textContent = (t.wins || 0) + " / " + (t.losses || 0) + " (" + (t.resolved || 0) + " סגור)";
    }
  }

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      charts[key] = null;
    }
  }

  function renderWinLossChart() {
    var t = trackData();
    if (!t) return;
    var c = t.charts.win_loss_counts;
    destroyChart("winLoss");
    var ctx = document.getElementById("chart-win-loss");
    charts.winLoss = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["הצלחה", "כשלון", "פתוח"],
        datasets: [{
          data: [c.wins, c.losses, c.open],
          backgroundColor: ["#22c55e", "#ef4444", "#f59e0b"],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { position: "bottom", rtl: true, labels: { font: { size: 13 } } },
        },
      },
    });
    var cap = document.getElementById("win-loss-caption");
    if (cap) {
      cap.textContent = c.wins + " הצלחות · " + c.losses + " כשלונות · " + c.open + " פתוחות · Win rate "
        + (t.win_rate_pct || 0).toFixed(1) + "%";
    }
  }

  function renderMoneyChart() {
    var t = trackData();
    if (!t) return;
    var m = t.charts.money;
    destroyChart("money");
    var ctx = document.getElementById("chart-money");
    charts.money = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["הושקע (סגור)", "רווח מזכיות", "הפסדים", "PnL נטו"],
        datasets: [{
          label: "$",
          data: [m.invested, m.profit, m.loss, m.net_pnl],
          backgroundColor: ["#6366f1", "#22c55e", "#ef4444", m.net_pnl >= 0 ? "#22c55e" : "#ef4444"],
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { callback: function (v) { return "$" + v; } },
          },
        },
      },
    });
    var cap = document.getElementById("money-caption");
    if (cap) {
      cap.textContent = "הושקע בסך " + fmtMoney(m.invested) + " · רווח " + fmtMoney(m.profit)
        + " · הפסד " + fmtMoney(m.loss) + " · נטו " + (m.net_pnl >= 0 ? "+" : "") + fmtMoney(m.net_pnl);
    }
  }

  function renderTimelineChart() {
    if (!statsData || !statsData.timeline) return;
    var tl = statsData.timeline;
    destroyChart("timeline");
    var ctx = document.getElementById("chart-timeline");
    charts.timeline = new Chart(ctx, {
      type: "line",
      data: {
        labels: tl.map(function (p) { return p.label; }),
        datasets: [
          {
            label: "PnL מצטבר",
            data: tl.map(function (p) { return p.cumulative_pnl; }),
            borderColor: "#6366f1",
            backgroundColor: "rgba(99, 102, 241, 0.15)",
            fill: true,
            tension: 0.25,
            yAxisID: "y",
          },
          {
            label: "PnL סיבוב",
            data: tl.map(function (p) { return p.cycle_pnl; }),
            borderColor: "#22c55e",
            backgroundColor: "rgba(34, 197, 94, 0.2)",
            type: "bar",
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            type: "linear",
            position: "left",
            title: { display: true, text: "מצטבר $" },
          },
          y1: {
            type: "linear",
            position: "right",
            grid: { drawOnChartArea: false },
            title: { display: true, text: "סיבוב $" },
          },
        },
      },
    });
  }

  function renderAssetTable() {
    var body = document.getElementById("stats-by-asset");
    if (!body || !statsData) return;
    var rows = statsData.by_asset || [];
    if (!rows.length) {
      body.innerHTML = "<tr><td colspan='7' class='muted'>אין עסקאות עדיין</td></tr>";
      return;
    }
    body.innerHTML = rows.map(function (r) {
      var pnlCls = r.pnl >= 0 ? "ok" : "err";
      return "<tr>" +
        "<td><strong>" + escapeHtml(r.asset) + "</strong></td>" +
        "<td>" + r.bets + "</td>" +
        "<td class='ok'>" + r.wins + "</td>" +
        "<td class='err'>" + r.losses + "</td>" +
        "<td>" + r.win_rate_pct.toFixed(0) + "%</td>" +
        "<td>" + fmtMoney(r.invested) + "</td>" +
        "<td class='" + pnlCls + "'>" + (r.pnl >= 0 ? "+" : "") + fmtMoney(r.pnl) + "</td>" +
        "</tr>";
    }).join("");
  }

  function renderAll() {
    renderKpi();
    renderWinLossChart();
    renderMoneyChart();
    renderTimelineChart();
    renderAssetTable();
  }

  function load() {
    fetch("/api/sim/stats", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        statsData = data;
        renderAll();
        var ind = document.getElementById("stats-refresh");
        if (ind) ind.textContent = "עודכן " + new Date().toLocaleTimeString("he-IL");
      })
      .catch(function () {
        var ind = document.getElementById("stats-refresh");
        if (ind) ind.textContent = "שגיאת טעינה";
      });
  }

  document.querySelectorAll(".stats-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".stats-tab").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      currentTrack = btn.getAttribute("data-track") || "champion";
      renderAll();
    });
  });

  load();
  setInterval(load, 15000);
})();
