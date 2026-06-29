(function () {
  const windowsEl = document.getElementById("crypto-windows");
  if (!windowsEl) return;

  let pollTimer = null;
  let defaultBetUsd = 5;

  function pollIntervalMs(state) {
    const windows = (state && state.windows) || [];
    const inBet = windows.some(function (item) {
      return item.window && item.window.phase === "bet";
    });
    return inBet ? 1000 : 2000;
  }

  function fmtMoney(v) {
    if (v == null) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function fmtCents(price) {
    if (price == null) return "—";
    return Math.round(Number(price) * 100) + "¢";
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

  /** Polymarket: buy at ask, each winning share pays $1.00 */
  function polymarketPayout(investUsd, askPrice) {
    if (!investUsd || investUsd <= 0 || askPrice == null || askPrice <= 0 || askPrice >= 1) {
      return null;
    }
    const shares = investUsd / askPrice;
    const payoutWin = shares * 1.0;
    const profitWin = payoutWin - investUsd;
    const roiWin = (profitWin / investUsd) * 100;
    return {
      invest: investUsd,
      price: askPrice,
      shares: shares,
      payoutWin: payoutWin,
      profitWin: profitWin,
      roiWin: roiWin,
      payoutLose: 0,
      profitLose: -investUsd,
    };
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

  function renderPayoutSide(label, ask, betUsd, isSuggested) {
    const p = polymarketPayout(betUsd, ask);
    const cls = isSuggested ? " payout-card suggested" : " payout-card";
    if (!p) {
      return '<div class="' + cls.trim() + '"><h3>' + label + '</h3><p class="muted">אין מחיר</p></div>';
    }
    return (
      '<div class="' + cls.trim() + '">' +
      "<h3>" + label + (isSuggested ? ' <span class="ok">← מומלץ</span>' : "") + "</h3>" +
      '<div class="payout-row"><span class="muted">מחיר מניה (ask)</span><strong>' + fmtCents(p.price) + "</strong></div>" +
      '<div class="payout-row"><span class="muted">מניות ב-$' + betUsd + "</span><strong>" + p.shares.toFixed(2) + "</strong></div>" +
      '<div class="payout-outcome win">' +
      '<span class="muted">אם צודק → מקבל</span>' +
      "<strong>" + fmtMoney(p.payoutWin) + "</strong>" +
      '<span class="ok small">(+' + fmtMoney(p.profitWin) + " · +" + fmtPct(p.roiWin) + ")</span>" +
      "</div>" +
      '<div class="payout-outcome lose">' +
      '<span class="muted">אם טועה → מקבל</span>' +
      "<strong>" + fmtMoney(p.payoutLose) + "</strong>" +
      '<span class="err small">(' + fmtMoney(p.profitLose) + ")</span>" +
      "</div>" +
      '<div class="payout-formula small muted">' +
      fmtMoney(betUsd) + " ÷ " + fmtCents(p.price) + " = " + p.shares.toFixed(2) + " מניות × $1 = " + fmtMoney(p.payoutWin) +
      "</div>" +
      "</div>"
    );
  }

  function renderWindow(item, betUsd) {
    const w = item.window || {};
    const o = item.oracle || {};
    const t = item.tokens || {};
    const d = item.decision || {};
    const placed = item.bet_placed;
    const highlight = placed ? " crypto-window-bet" : d.action === "bet" ? " crypto-window-ready" : "";
    const side = d.side ? d.side.toUpperCase() : "—";
    const suggestUp = d.side === "up";
    const suggestDown = d.side === "down";

    let html = '<div class="card crypto-window' + highlight + '">';
    html += '<div class="crypto-window-head">';
    html += "<h2>" + (w.asset_label || w.asset || "?") + " · " + (w.title || w.slug || "") + "</h2>";
    html += '<span class="phase-badge ' + phaseClass(w.phase) + '">' + phaseLabel(w.phase) + "</span>";
    html += "</div>";

    html += '<div class="grid crypto-stats">';
    html += stat("זמן", fmtTime(w.seconds_remaining || 0) + " נותר");
    html += stat("Chainlink", priceLine(o));
    html += stat("Price to Beat", o.open_price != null ? "$" + Number(o.open_price).toFixed(2) : "—");
    html += stat("כיוון", directionLabel(o));
    html += "</div>";

    html += '<div class="payout-grid">';
    html += renderPayoutSide("Up ↑", t.up_ask || t.up_mid, betUsd, suggestUp && d.action === "bet");
    html += renderPayoutSide("Down ↓", t.down_ask || t.down_mid, betUsd, suggestDown && d.action === "bet");
    html += "</div>";

    html += '<canvas class="sparkline" data-slug="' + escapeAttr(w.slug || "") + '" width="600" height="60"></canvas>';

    html += '<div class="crypto-decision">';
    html += "<strong>החלטה:</strong> " + escapeHtml(d.reason || "—");
    if (d.edge_pct != null) html += " · רווח פוטנציאלי " + fmtPct(d.edge_pct);
    if (placed) html += ' <span class="ok">✓ הימור בוצע</span>';
    html += "</div>";

    if (w.phase === "bet" && d.action === "bet" && !placed) {
      html += '<form class="crypto-manual-bet btn-row" data-asset="' + escapeAttr(w.asset) + '" data-side="' + escapeAttr(d.side) + '">';
      html += '<label class="small">סכום<input type="number" name="amount" min="1" step="1" value="' + betUsd + '" class="bet-amount" style="width:5rem;margin-right:0.5rem"></label>';
      html += '<button type="submit" class="btn primary">המר ' + side + " עכשיו</button>";
      html += "</form>";
    }

    html += "</div>";
    return html;
  }

  function directionLabel(o) {
    if (o.direction === "up") return '<span class="ok">עולה ↑</span>';
    if (o.direction === "down") return '<span class="err">יורד ↓</span>';
    return "שטוח";
  }

  function stat(label, value) {
    return '<div class="crypto-stat"><span class="muted small">' + label + '</span><strong>' + value + "</strong></div>";
  }

  function priceLine(o) {
    if (!o.open_price && !o.current_price) return "—";
    let s = o.current_price != null ? "$" + Number(o.current_price).toFixed(2) : "?";
    if (o.delta_pct != null) {
      const cls = o.delta_pct >= 0 ? "ok" : "err";
      s += ' <span class="' + cls + '">(' + fmtPct(o.delta_pct) + ")</span>";
    }
    return s;
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
      body.innerHTML = '<tr><td colspan="8" class="muted">אין הימורים עדיין</td></tr>';
      return;
    }
    body.innerHTML = bets.map(function (b) {
      const p = polymarketPayout(b.bet_usd, b.entry_price);
      const payoutStr = p
        ? fmtMoney(b.bet_usd) + " → " + fmtMoney(p.payoutWin) + " (+" + fmtPct(p.roiWin) + ")"
        : fmtMoney(b.bet_usd);
      const pnl = b.realized_pnl != null ? fmtMoney(b.realized_pnl) : "—";
      const pnlCls = (b.realized_pnl || 0) >= 0 ? "ok" : "err";
      return "<tr>" +
        "<td>" + escapeHtml(b.asset) + "</td>" +
        "<td class='mono small'>" + escapeHtml(b.slug) + "</td>" +
        "<td>" + escapeHtml(b.side) + "</td>" +
        "<td>" + payoutStr + "</td>" +
        "<td>" + (b.entry_price != null ? fmtCents(b.entry_price) : "—") + "</td>" +
        "<td>" + (b.edge_pct != null ? fmtPct(b.edge_pct) : "—") + "</td>" +
        "<td>" + escapeHtml(b.status) + "</td>" +
        "<td class='" + pnlCls + "'>" + pnl + "</td>" +
        "</tr>";
    }).join("");
  }

  function scheduleNextRefresh(state) {
    if (pollTimer) clearTimeout(pollTimer);
    const ms = pollIntervalMs(state);
    const el = document.getElementById("refresh-indicator");
    if (el) {
      el.textContent = "מתעדכן כל " + (ms / 1000) + " שניות · " + new Date().toLocaleTimeString("he-IL");
    }
    pollTimer = setTimeout(refresh, ms);
  }

  function fmtCentsPrice(cents) {
    if (cents == null) return "—";
    return Number(cents).toFixed(1) + "¢";
  }

  function outcomeClass(outcome) {
    const o = (outcome || "").toLowerCase();
    if (o === "yes" || o === "up") return "yes";
    if (o === "no" || o === "down") return "no";
    return "";
  }

  function bindWalletTabs() {
    document.querySelectorAll(".wallet-tab").forEach(function (btn) {
      btn.onclick = function () {
        document.querySelectorAll(".wallet-tab").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        const tab = btn.getAttribute("data-tab");
        document.getElementById("wallet-tab-positions").style.display = tab === "positions" ? "block" : "none";
        document.getElementById("wallet-tab-history").style.display = tab === "history" ? "block" : "none";
      };
    });
  }

  function renderWalletPositions(positions) {
    const body = document.getElementById("wallet-positions-body");
    if (!body) return;
    if (!positions || !positions.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">אין פוזיציות פתוחות</td></tr>';
      return;
    }
    body.innerHTML = positions.map(function (p) {
      const oc = outcomeClass(p.outcome);
      const pnlCls = (p.cash_pnl || 0) >= 0 ? "ok" : "err";
      const sign = (p.cash_pnl || 0) >= 0 ? "+" : "";
      return "<tr>" +
        "<td><div class='pm-market-title'>" + escapeHtml(p.title) + "</div>" +
        "<div class='pm-market-outcome'><span class='" + oc + "'>" + escapeHtml(p.outcome) + "</span> · " +
        Number(p.size).toFixed(1) + " shares</div></td>" +
        "<td class='pm-price-arrow'>" + fmtCentsPrice(p.avg_cents) + " → " + fmtCentsPrice(p.cur_cents) + "</td>" +
        "<td>" + fmtMoney(p.traded_usd) + "</td>" +
        "<td>" + fmtMoney(p.to_win_usd) + "</td>" +
        "<td class='pm-value-cell'><strong>" + fmtMoney(p.current_value) + "</strong>" +
        "<span class='pnl " + pnlCls + "'>" + sign + fmtMoney(p.cash_pnl) + " (" + sign + fmtPct(p.percent_pnl) + ")</span></td>" +
        "</tr>";
    }).join("");
  }

  function renderWalletCube(wallet) {
    const w = wallet || {};
    const cashEl = document.getElementById("wallet-cash");
    const totalEl = document.getElementById("wallet-total");
    const pnlEl = document.getElementById("wallet-pnl");
    const addrEl = document.getElementById("wallet-address");
    const errEl = document.getElementById("wallet-error");
    const statsEl = document.getElementById("wallet-stats");
    const histBody = document.getElementById("wallet-history-body");

    if (!cashEl) return;

    if (!w.configured) {
      if (totalEl) totalEl.textContent = "—";
      cashEl.textContent = "—";
      cashEl.className = "big err";
      if (pnlEl) pnlEl.textContent = "—";
      if (addrEl) addrEl.textContent = "ארנק לא מוגדר";
      renderWalletPositions([]);
      if (histBody) histBody.innerHTML = '<tr><td colspan="6" class="muted"><a href="/wallet">חבר ארנק</a></td></tr>';
      return;
    }

    if (addrEl) addrEl.textContent = w.funder_address || "—";
    if (totalEl) totalEl.textContent = fmtMoney(w.total_value_usd);
    cashEl.textContent = w.cash_usd != null ? fmtMoney(w.cash_usd) : "לא זמין*";
    cashEl.className = "big " + (w.cash_usd != null ? "ok" : "warn");
    if (w.cash_usd == null && w.positions_value_usd > 0) {
      cashEl.title = "Cash דורש CLOB — פוזיציות נטענו מ-Polymarket Data API";
    }

    const pnl = w.total_pnl_usd != null ? w.total_pnl_usd : 0;
    if (pnlEl) {
      pnlEl.textContent = (pnl >= 0 ? "+" : "") + fmtMoney(pnl);
      pnlEl.className = "big " + (pnl >= 0 ? "ok" : "err");
    }

    if (errEl) {
      if (w.error) {
        errEl.textContent = w.error;
        errEl.style.display = "block";
      } else {
        errEl.style.display = "none";
      }
    }

    if (statsEl) {
      statsEl.innerHTML =
        '<span class="wallet-stat-chip">שווי פוזיציות: <strong>' + fmtMoney(w.positions_value_usd) + "</strong></span>" +
        '<span class="wallet-stat-chip">PnL לא ממומש: <strong class="' + ((w.unrealized_pnl_usd || 0) >= 0 ? "ok" : "err") + '">' + fmtMoney(w.unrealized_pnl_usd) + "</strong></span>" +
        '<span class="wallet-stat-chip">PnL ממומש: <strong>' + fmtMoney(w.realized_pnl_usd) + "</strong></span>" +
        '<span class="wallet-stat-chip">הזמנות פתוחות: <strong>' + (w.open_orders_count || 0) + "</strong></span>";
    }

    renderWalletPositions(w.positions || []);

    const items = (w.items || []).slice(0, 30);
    if (!histBody) return;
    if (!items.length) {
      histBody.innerHTML = '<tr><td colspan="6" class="muted">אין היסטוריה</td></tr>';
      return;
    }
    histBody.innerHTML = items.map(function (row) {
      const stCls = row.status === "success" ? "ok" : row.status === "failed" ? "err" : "";
      const srcCls = row.source === "polymarket" ? "src-pm" : row.source === "crypto" ? "src-crypto" : "src-bot";
      return "<tr>" +
        "<td class='small'>" + escapeHtml(row.at) + "</td>" +
        "<td><span class='source-tag " + srcCls + "'>" + escapeHtml(row.source_label) + "</span></td>" +
        "<td>" + escapeHtml(row.side) + "</td>" +
        "<td class='small'>" + escapeHtml(row.title) + "</td>" +
        "<td>" + (row.amount_usd ? fmtMoney(row.amount_usd) : "—") + "</td>" +
        "<td class='" + stCls + "'>" + escapeHtml(row.status_label) + "</td>" +
        "</tr>";
    }).join("");
  }

  function render(data) {
    const state = data.state || {};
    const summary = data.summary || {};
    const runner = data.runner || {};
    const settings = data.settings || {};
    const wallet = data.wallet || {};
    defaultBetUsd = Number(settings.bet_usd) || 5;

    document.getElementById("sum-portfolio").textContent = fmtMoney(wallet.total_value_usd);
    document.getElementById("sum-cash").textContent = fmtMoney(wallet.cash_usd);
    const topPnl = document.getElementById("sum-pnl");
    const tp = wallet.total_pnl_usd != null ? wallet.total_pnl_usd : 0;
    topPnl.textContent = (tp >= 0 ? "+" : "") + fmtMoney(tp);
    topPnl.className = "big " + (tp >= 0 ? "ok" : "err");
    document.getElementById("sum-runner").textContent = runner.running ? "פעיל" : "כבוי";

    document.getElementById("sum-runner").className = "big " + (runner.running ? "ok" : "muted");

    document.getElementById("auto-label").textContent = state.auto_bet ? "פעיל" : "כבוי";

    const items = state.windows || [];
    windowsEl.innerHTML = items.length
      ? items.map(function (item) { return renderWindow(item, defaultBetUsd); }).join("")
      : '<p class="muted">אין חלונות פעילים — בודק שווקים…</p>';

    drawSparklines(state);
    renderBets(data.bets || []);
    renderWalletCube(wallet);
    bindManualForms();
    scheduleNextRefresh(state);
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
        scheduleNextRefresh(null);
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
  bindWalletTabs();
})();
