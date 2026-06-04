(function () {
  var KEY = "omada.nav.collapsed";
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
