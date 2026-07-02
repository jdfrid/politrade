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
    if (item.bet_status === "won") return '<span class="ok"><strong>הצלחה</strong></span>';
    if (item.bet_status === "lost") return '<span class="err"><strong>כשלון</strong></span>';
    if (item.bet_status === "open" || item.bet_placed) return '<span class="warn"><strong>פתוח</strong></span>';
    const w = item.window || {};
    if (w.phase === "closed") return '<span class="muted">נסגר</span>';
    return '<span class="muted">מנטר</span>';
  }

  function renderBetTransactionCard(b) {
    const stCls = b.status_class || "muted";
    const pnl = b.realized_pnl != null ? (" · PnL " + fmtMoney(b.realized_pnl)) : "";
    const variant = b.variant_label ? (" · " + escapeHtml(b.variant_label)) : "";
    return "<div class='rationale-card bet-tx-card'>" +
      "<div class='bet-tx-head'>" +
      "<div class='bet-tx-title'>" + escapeHtml(b.market_title || b.asset || "?") + variant + "</div>" +
      "<div class='bet-tx-meta small muted'>" +
      "חלון: " + escapeHtml(b.window_period_he || "—") +
      " · הימור: " + escapeHtml(b.placed_at_he || "—") +
      (b.side ? " · " + escapeHtml(String(b.side).toUpperCase()) + " $" + Number(b.bet_usd || 0).toFixed(0) : "") +
      pnl +
      "</div>" +
      "<div class='bet-tx-status " + stCls + "'><strong>" + escapeHtml(b.status_label_he || b.status || "—") + "</strong></div>" +
      "</div>" +
      "<pre class='cycle-summary small'>" + escapeHtml(b.rationale_he || b.decision_reason || "—") + "</pre>" +
      renderFactorList(b.factors) +
      "</div>";
  }

  function renderFactorList(factors) {
    if (!factors || !factors.length) return "";
    return "<ul class='factor-list small'>" + factors.map(function (f) {
      const cls = f.status === "fail" ? "err" : (f.status === "pass" ? "ok" : "muted");
      return "<li class='" + cls + "'><strong>" + escapeHtml(f.category_he || f.category) + "</strong>: "
        + escapeHtml(f.label_he) + " — " + escapeHtml(f.detail_he) + "</li>";
    }).join("") + "</ul>";
  }

  function renderVariantAggregate(agg) {
    if (!agg) return "";
    const ba = agg.by_action || {};
    const bb = agg.by_blocker || {};
    let blockers = Object.keys(bb).map(function (k) {
      return k + ":" + bb[k];
    }).join(", ");
    return "<p class='small muted'>36 גרסאות: bet " + (ba.bet || 0) +
      " · wait " + (ba.wait || 0) + " · skip " + (ba.skip || 0) +
      " · בוצעו " + (agg.executed || 0) +
      (blockers ? " · חוסמים: " + escapeHtml(blockers) : "") + "</p>";
  }

  function renderMarkets(data) {
    const markets = (data.state && data.state.markets) || [];
    const summary = document.getElementById("sim-markets-summary");
    if (summary) {
      const cur = markets.filter(function (m) {
        return (m.window || {}).window_ts === data.window_ts;
      });
      summary.textContent = markets.length + " שווקים · " +
        cur.length + " בחלון נוכחי · לחץ על שורה לפירוט 36 גרסאות";
    }
    if (!markets.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted">אין שווקים — בודק Gamma…</td></tr>';
      return;
    }
    let html = "";
    markets.forEach(function (item) {
      const w = item.window || {};
      const d = item.decision || {};
      const isCurrent = w.window_ts === data.window_ts;
      const rowCls = isCurrent ? "market-current" : "";
      const edge = d.edge_pct != null ? fmtPct(d.edge_pct) : "—";
      const rec = item.recommended_usd > 0 ? fmtMoney(item.recommended_usd) : "—";
      const slug = (d.slug || w.slug || "").replace(/[^a-z0-9]/gi, "");
      html += "<tr class='" + rowCls + "'>" +
        "<td><strong>" + escapeHtml(w.title || w.asset_label || w.asset || "?") + "</strong>" +
        (w.title ? "<br><span class='muted small'>" + escapeHtml(w.asset_label || w.asset || "") + "</span>" : "") +
        "</td>" +
        "<td><span class='muted small'>" + fmtTime(w.seconds_remaining || 0) + " נותר</span></td>" +
        "<td>" + worthLabel(item) + "</td>" +
        "<td>" + escapeHtml(item.entry_timing || "—") + "</td>" +
        "<td>" + rec + "</td>" +
        "<td>" + edge + "</td>" +
        "<td>" + statusLabel(item) + "</td>" +
        "<td class='small'>" + escapeHtml(d.reason || "—") + "</td>" +
        "</tr>";
      if (isCurrent && (d.rationale_he || item.variant_decisions)) {
        html += "<tr class='rationale-row'><td colspan='8'>" +
          "<details open><summary><strong>Champion — למה " +
          (item.bet_placed ? "בוצע" : (d.action === "bet" ? "מומלץ" : "לא בוצע")) + "?</strong></summary>" +
          renderVariantAggregate(item.variant_aggregate) +
          "<pre class='cycle-summary small'>" + escapeHtml(d.rationale_he || "") + "</pre>" +
          renderFactorList(d.factors) +
          "<details><summary class='small'>כל 36 הגרסאות לשוק זה</summary>" +
          "<div class='variant-decisions-grid'>" +
          (item.variant_decisions || []).map(function (vd) {
            const act = vd.executed ? "✓ בוצע" : (vd.action === "bet" ? "→ לא בוצע" : vd.action);
            const cls = vd.executed ? "ok" : (vd.action === "skip" ? "err" : "warn");
            return "<div class='variant-decision-card " + cls + "'>" +
              "<div class='small'><strong>" + escapeHtml(vd.variant_label || "") + "</strong> · " + act + "</div>" +
              "<pre class='small muted'>" + escapeHtml(vd.rationale_he || "") + "</pre>" +
              "</div>";
          }).join("") +
          "</div></details></details></td></tr>";
      }
    });
    body.innerHTML = html;
  }

  function renderRecentBets(data) {
    const el = document.getElementById("sim-recent-bets");
    if (!el) return;
    const bets = (data.recent_variant_bets || []).concat(data.recent_bets || []);
    if (!bets.length) {
      el.innerHTML = "<p class='muted'>אין עסקאות עדיין</p>";
      return;
    }
    el.innerHTML = bets.slice(0, 20).map(function (b) {
      return renderBetTransactionCard(b);
    }).join("");
  }

  function renderVariants(data) {
    const variants = data.variants || {};
    const list = variants.leaderboard || [];
    const champion = variants.champion;
    const summary = document.getElementById("sim-variants-summary");
    const body = document.getElementById("sim-variants-body");
    const champCard = document.getElementById("sim-champion-card");
    const champLabel = document.getElementById("sim-champion-label");
    const champStats = document.getElementById("sim-champion-stats");

    if (summary) {
      const betsTick = (data.state && data.state.variant_bets_last_tick) || 0;
      summary.textContent = (variants.count || list.length) + " גרסאות · "
        + betsTick + " הימורים בטיק אחרון · סימולציה מבצעת הימורים וירטואליים";
    }

    if (champion && champCard) {
      champCard.style.display = "block";
      if (champLabel) champLabel.textContent = champion.label || "—";
      if (champStats) {
        const rb = champion.rank_breakdown || {};
        champStats.textContent = "PnL " + fmtMoney(champion.cumulative_pnl) +
          " · יתרה " + fmtMoney(champion.balance) +
          " · WR " + (champion.win_rate || 0).toFixed(0) + "%" +
          " · ציון " + (champion.rank_score || 0).toFixed(1) +
          " (PnL " + (rb.pnl || 0).toFixed(1) +
          " + WR×0.5 " + (rb.win_rate_bonus || 0).toFixed(1) +
          " + יתרה " + (rb.balance_bonus || 0).toFixed(1) + ")";
      }
      const champNote = document.getElementById("sim-champion-note");
      const sel = (data.champion_selection || {});
      if (champNote) {
        champNote.textContent = sel.note_he ||
          "הגרסה עם הציון הגבוה ביותר מבין הגרסאות הפעילות — לא בהכרח האופטימום הגלובלי.";
      }
    }

    if (!body) return;
    if (!list.length) {
      body.innerHTML = '<tr><td colspan="6" class="muted">אין גרסאות — הפעל סימולציה</td></tr>';
      return;
    }
    body.innerHTML = list.map(function (v, i) {
      const rowCls = v.is_champion ? "market-current" : "";
      const pnl = v.cumulative_pnl || 0;
      const pnlCls = pnl >= 0 ? "ok" : "err";
      return "<tr class='" + rowCls + "'>" +
        "<td>" + (i + 1) + (v.is_champion ? " ★" : "") + "</td>" +
        "<td class='small'>" + escapeHtml(v.label || "—") + "</td>" +
        "<td>" + fmtMoney(v.balance) + "</td>" +
        "<td class='" + pnlCls + "'>" + (pnl >= 0 ? "+" : "") + fmtMoney(pnl) + "</td>" +
        "<td>" + (v.win_rate || 0).toFixed(0) + "%</td>" +
        "<td>" + (v.rank_score || 0).toFixed(1) + "</td>" +
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
      renderVariants(results[0]);
      renderMarkets(results[0]);
      renderRecentBets(results[0]);
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
