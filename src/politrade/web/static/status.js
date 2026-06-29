(function () {
  const bar = document.getElementById("live-status-bar");
  if (!bar) return;

  function pill(label, value, state, title) {
    const cls = state === "ok" ? "ok" : state === "off" ? "muted" : "err";
    const tip = title ? ' title="' + escapeHtml(title) + '"' : "";
    return '<span class="status-pill ' + cls + '"' + tip + '><span class="status-dot"></span>' +
      label + ': <strong>' + value + '</strong></span>';
  }

  function money(v) {
    if (v === null || v === undefined) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function render(d) {
    const c = d.connections || {};
    const w = d.wallet || {};
    const t = d.trades || {};
    let html = "";
    html += pill("DB", c.database === "ok" ? "תקין" : "שגיאה", c.database);
    html += pill(
      "Polymarket",
      c.data_api === "ok" ? "מחובר" : "שגיאה",
      c.data_api,
      c.data_api_error || ""
    );
    html += pill(
      "CLOB",
      c.clob === "ok" ? "מחובר" : c.clob === "off" ? "לא מוגדר" : "שגיאה",
      c.clob,
      c.clob_error || ""
    );
    html += pill(
      "מעקב",
      c.position_monitor === "ok" ? "פעיל" : "כבוי",
      c.position_monitor
    );
    html += pill(
      "Crypto",
      c.crypto_runner === "ok" ? "פעיל" : "כבוי",
      c.crypto_runner
    );
    html += pill(
      "ארנק",
      w.label || "—",
      w.configured ? "ok" : "err",
      (w.errors || []).join(" · ")
    );
    html += pill("Cash", money(w.cash_usd), w.cash_usd != null ? "ok" : "off");
    html += pill("פוזיציות", String(t.open_positions || 0), "ok");
    const pnl = t.live_pnl_usd || 0;
    html += pill("PnL חי", money(pnl), pnl >= 0 ? "ok" : "err");
    if (t.open_orders) {
      html += pill("הזמנות פתוחות", String(t.open_orders), "ok");
    }
    const botLabel = t.bot_running ? "רץ (" + (t.bot_mode || "watch") + ")" : "כבוי";
    html += pill("בוט", botLabel, t.bot_running ? "ok" : "off");
    if (t.kill_switch) {
      html += pill("Kill switch", "פעיל", "err");
    }
    if (t.last_failure) {
      html += pill("כשלון אחרון", "!", "err", t.last_failure);
    }
    html += '<span class="status-time muted small">עודכן: ' + (d.updated_at || "").slice(11, 19) + " UTC</span>";
    bar.innerHTML = html;
  }

  function escapeHtml(s) {
    const el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function refresh() {
    fetch("/api/status/live", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then(render)
      .catch(function () {
        bar.innerHTML = '<span class="status-pill err"><span class="status-dot"></span>לא ניתן לטעון סטטוס</span>';
      });
  }

  refresh();
  setInterval(refresh, 10000);
})();
