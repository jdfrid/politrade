(function () {
  const body = document.getElementById("live-opportunities-body");
  if (!body) return;

  let pollTimer = null;

  function fmtMoney(v) {
    if (v == null) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function fmtPct(v) {
    if (v == null || v === "") return "—";
    return Number(v).toFixed(1) + "%";
  }

  function fmtTime(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m + ":" + String(s).padStart(2, "0");
  }

  function escapeHtml(s) {
    const el = document.createElement("span");
    el.textContent = s == null ? "" : String(s);
    return el.innerHTML;
  }

  function actionCls(action) {
    const a = (action || "").toLowerCase();
    if (a === "bet") return "ok";
    if (a === "wait") return "warn";
    if (a === "skip") return "err";
    return "muted";
  }

  function renderSummary(d) {
    const mode = document.getElementById("live-dash-mode");
    const cash = document.getElementById("live-dash-cash");
    const budget = document.getElementById("live-dash-budget");
    const opps = document.getElementById("live-dash-opps");
    const updated = document.getElementById("live-dash-updated");
    const banner = document.getElementById("live-dash-banner");
    const bannerText = document.getElementById("live-dash-banner-text");

    if (mode) {
      const r = d.runner || {};
      mode.textContent = d.live_enabled
        ? (r.running ? "לייב · פעיל" : "לייב · runner כבוי")
        : "סימולציה בלבד";
      mode.className = "big " + (d.live_enabled && r.running ? "ok" : "warn");
    }
    if (cash) cash.textContent = fmtMoney((d.catalog || {}).cash_usd);
    const b = d.budget || {};
    if (budget) {
      budget.textContent = b.cap_usd > 0
        ? fmtMoney(b.remaining_usd) + " / " + fmtMoney(b.cap_usd)
        : "ללא תקרה";
    }
    const op = d.opportunities || [];
    const current = op.filter(function (r) { return r.is_current; });
    if (opps) opps.textContent = current.length + " פעיל · " + op.length + " סה\"כ";

    if (updated) {
      updated.textContent = "עודכן " + new Date().toLocaleTimeString("he-IL") +
        " · חלון " + fmtTime(d.seconds_remaining || 0) + " נותר";
    }

    if (banner && bannerText) {
      if (!d.live_enabled) {
        banner.style.display = "block";
        bannerText.textContent = "מסחר אמיתי כבוי — מוצגות הזדמנויות לקריאה בלבד. הפעל לייב בהגדרות.";
      } else if (!(d.runner || {}).running) {
        banner.style.display = "block";
        bannerText.textContent = "Crypto runner לא פעיל — רענן או הפעל מחדש לייב מההגדרות.";
      } else if (!(d.catalog || {}).trading_ready) {
        banner.style.display = "block";
        bannerText.textContent = "CLOB לא מוכן — בדוק חיבור ארנק.";
      } else {
        banner.style.display = "none";
      }
    }

    const opSummary = document.getElementById("live-dash-opps-summary");
    if (opSummary) {
      const cat = d.catalog || {};
      const s = d.settings || {};
      opSummary.textContent =
        "auto: " + ((d.runner || {}).auto_bet ? "פעיל" : "כבוי") +
        " · $" + (s.bet_usd || 5) + " · edge≥" + (s.min_edge_pct || 0) + "%" +
        " · " + (cat.buyable_count || 0) + " ניתנים לקנייה · Cash " + fmtMoney(cat.cash_usd);
    }
  }

  function renderOpportunities(d) {
    const rows = d.opportunities || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="11" class="muted">אין שווקים — בודק Gamma…</td></tr>';
      return;
    }

    body.innerHTML = rows.map(function (r) {
      const rowCls = r.is_current ? "market-current" : "";
      const actCls = actionCls(r.action);
      const status = r.bet_placed
        ? ("<span class='ok'><strong>בוצע</strong></span>")
        : ("<span class='" + actCls + "'>" + escapeHtml(r.progress_label || r.bet_status || "—") + "</span>");
      return "<tr class='" + rowCls + "' data-slug='" + escapeHtml(r.slug || "") + "'>" +
        "<td class='small'><strong>" + escapeHtml(r.title || "—") + "</strong></td>" +
        "<td>" + escapeHtml(r.asset || "—") + "</td>" +
        "<td class='small muted'>" + escapeHtml(r.window_time || "—") + "</td>" +
        "<td>" + fmtTime(r.seconds_remaining || 0) + "</td>" +
        "<td class='" + actCls + "'><strong>" + escapeHtml(r.action_he || "—") + "</strong></td>" +
        "<td>" + escapeHtml(r.worth_he || "—") + "</td>" +
        "<td>" + escapeHtml(r.side ? String(r.side).toUpperCase() : "—") + "</td>" +
        "<td>" + fmtPct(r.edge_pct) + "</td>" +
        "<td>" + fmtPct(r.oracle_delta_pct) + "</td>" +
        "<td>" + status + "</td>" +
        "<td class='small'>" + escapeHtml(r.reason || "—") + "</td>" +
        "</tr>";
    }).join("");

    const current = rows.filter(function (r) { return r.is_current; })[0];
    const detail = document.getElementById("live-decision-detail");
    if (detail && current) {
      let html = "<p><strong>" + escapeHtml(current.title) + "</strong> · " +
        escapeHtml(current.action_he) + " · " + escapeHtml(current.worth_he) + "</p>";
      if (current.rationale_he) {
        html += "<pre class='cycle-summary small'>" + escapeHtml(current.rationale_he) + "</pre>";
      }
      const factors = current.factors || [];
      if (factors.length) {
        html += "<ul class='factor-list small'>" + factors.map(function (f) {
          const cls = f.status === "fail" ? "err" : (f.status === "pass" ? "ok" : "muted");
          return "<li class='" + cls + "'><strong>" + escapeHtml(f.category_he || f.category) + "</strong>: " +
            escapeHtml(f.detail_he || f.label_he || "") + "</li>";
        }).join("") + "</ul>";
      }
      detail.innerHTML = html;
    } else if (detail) {
      detail.textContent = "אין חלון נוכחי פעיל.";
    }
  }

  function renderBets(d) {
    const openBody = document.getElementById("live-open-bets-body");
    const recentBody = document.getElementById("live-recent-bets-body");
    const open = d.open_bets || [];
    const recent = d.recent_bets || [];

    if (openBody) {
      if (!open.length) {
        openBody.innerHTML = '<tr><td colspan="7" class="muted">אין הימורים פתוחים</td></tr>';
      } else {
        openBody.innerHTML = open.map(function (b) {
          return "<tr>" +
            "<td class='small'>" + escapeHtml(b.market_title || "—") + "</td>" +
            "<td class='small muted'>" + escapeHtml(b.window_period_he || "—") + "</td>" +
            "<td class='small muted'>" + escapeHtml(b.placed_at_he || "—") + "</td>" +
            "<td>" + escapeHtml(String(b.side || "").toUpperCase()) + "</td>" +
            "<td>" + fmtMoney(b.bet_usd) + "</td>" +
            "<td>" + fmtPct(b.edge_pct) + "</td>" +
            "<td class='" + (b.status_class || "muted") + "'><strong>" + escapeHtml(b.status_label_he || b.status) + "</strong></td>" +
            "</tr>";
        }).join("");
      }
    }

    if (recentBody) {
      if (!recent.length) {
        recentBody.innerHTML = '<tr><td colspan="6" class="muted">אין היסטוריה</td></tr>';
      } else {
        recentBody.innerHTML = recent.slice(0, 30).map(function (b) {
          const pnl = b.realized_pnl != null ? fmtMoney(b.realized_pnl) : "—";
          const pnlCls = (b.realized_pnl || 0) >= 0 ? "ok" : "err";
          return "<tr>" +
            "<td class='small'>" + escapeHtml(b.market_title || "—") + "</td>" +
            "<td class='small muted'>" + escapeHtml(b.window_period_he || "—") + "</td>" +
            "<td>" + escapeHtml(String(b.side || "").toUpperCase()) + "</td>" +
            "<td>" + fmtMoney(b.bet_usd) + "</td>" +
            "<td class='" + pnlCls + "'>" + pnl + "</td>" +
            "<td class='" + (b.status_class || "muted") + "'>" + escapeHtml(b.status_label_he || b.status) + "</td>" +
            "</tr>";
        }).join("");
      }
    }

    const expCard = document.getElementById("live-experience-card");
    const expLesson = document.getElementById("live-experience-lesson");
    const exp = d.experience || {};
    if (expCard && exp.total_resolved > 0) {
      expCard.style.display = "block";
      if (expLesson) expLesson.textContent = exp.lesson_he || "—";
    } else if (expCard) {
      expCard.style.display = "none";
    }
  }

  function refresh() {
    fetch("/api/live/dashboard", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(function (d) {
        renderSummary(d);
        renderOpportunities(d);
        renderBets(d);
        scheduleNext();
      })
      .catch(function () {
        body.innerHTML = '<tr><td colspan="11" class="err">שגיאת טעינה</td></tr>';
        scheduleNext();
      });
  }

  function scheduleNext() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(refresh, 1500);
  }

  refresh();
})();
