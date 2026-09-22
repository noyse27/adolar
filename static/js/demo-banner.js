// Shows a fixed banner when this instance is running in demo mode (see
// adolar/demo_mode.py). Polls the public /api/demo/status endpoint, which
// returns {"active": false} on a normal deployment - in that case this
// renders nothing. Included as a plain <script> (not bundled into
// static/app.js) so it works the same on every standalone template
// (index.html, login.html, setup.html, ...) without each one needing to
// import the main SPA bundle.
(function () {
  function formatMinutes(minutes) {
    if (!minutes) return "regelmäßig";
    return "alle " + minutes + " Minuten";
  }

  function showBanner(status) {
    var banner = document.createElement("div");
    banner.id = "demo-mode-banner";
    banner.setAttribute("role", "status");
    banner.style.cssText = [
      "position:relative", "z-index:9999",
      "background:#4a3d33", "color:#e8dcc8",
      "border-bottom:1px solid #8a6d3b",
      "font:12px/1.5 sans-serif",
      "text-align:center", "padding:8px 16px",
    ].join(";");

    var line1 = document.createElement("div");
    line1.textContent =
      "Dies ist eine öffentliche Demo-Instanz von Adolar mit erfundenen Testdaten. " +
      "Alle Inhalte werden " + formatMinutes(status.reset_interval_minutes) +
      " automatisch zurückgesetzt.";

    var line2 = document.createElement("div");
    var adminLabel = document.createTextNode("Admin-Login: ");
    var adminCode = document.createElement("code");
    adminCode.textContent = status.admin_username + " / " + status.admin_password;
    var sep = document.createTextNode(" · Hörer-Login: ");
    var userCode = document.createElement("code");
    userCode.textContent = status.user_username + " / " + status.user_password;
    line2.append(adminLabel, adminCode, sep, userCode);

    banner.append(line1, line2);
    document.body.insertBefore(banner, document.body.firstChild);
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("/api/demo/status")
      .then(function (res) { return res.json(); })
      .then(function (status) {
        if (status && status.active) showBanner(status);
      })
      .catch(function () {
        // A failed status check should never block the page from
        // rendering - worst case, a demo deployment briefly shows
        // without its banner.
      });
  });
})();
