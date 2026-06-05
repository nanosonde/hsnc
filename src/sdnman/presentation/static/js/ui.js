/*
 * ui.js — the only hand-written JavaScript on the site (no framework, no build).
 *
 * Its single job: when the user clicks the hamburger button, toggle the sidebar
 * between full width and an icon-only rail, and remember that choice across page
 * loads via localStorage. Everything else is plain server-rendered HTML (see
 * base.html), with a little HTMX for the client search/pagination.
 */
(function () {
  var KEY = "sdnman.nav.collapsed";
  var shell = document.getElementById("app-shell");
  var toggle = document.getElementById("nav-toggle");
  if (!shell || !toggle) return;

  function apply(collapsed) {
    shell.classList.toggle("nav-collapsed", collapsed);
    toggle.setAttribute("aria-pressed", collapsed ? "true" : "false");
    toggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  }

  toggle.addEventListener("click", function () {
    var collapsed = !shell.classList.contains("nav-collapsed");
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
    apply(collapsed);
  });
})();
