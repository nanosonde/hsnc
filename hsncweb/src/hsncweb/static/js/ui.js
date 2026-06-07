/*
 * ui.js — the only hand-written JavaScript on the site (no framework, no build).
 *
 * Its single job: when the user clicks the hamburger button, toggle the sidebar
 * between full width and an icon-only rail, and remember that choice across page
 * loads via localStorage. Everything else is plain server-rendered HTML (see
 * base.html), with a little HTMX for the client search/pagination.
 */
(function () {
  var KEY = "hsnc.nav.collapsed";
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

/*
 * Modal helpers — used by the device "View SSH connection" terminal popup.
 * openModal()/closeModal() toggle the [hidden] attribute on an overlay; the
 * HTMX hx-get on the trigger button fills the modal body separately. Pressing
 * Escape or clicking the backdrop closes whichever modal is open.
 */
function openModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  el.hidden = false;
  document.body.classList.add("modal-open");
}

function closeModal(id) {
  var el = document.getElementById(id);
  if (!el) return;
  el.hidden = true;
  document.body.classList.remove("modal-open");
}

(function () {
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var open = document.querySelector(".modal-overlay:not([hidden])");
    if (open) closeModal(open.id);
  });

  document.addEventListener("click", function (e) {
    // Click on the backdrop (the overlay itself, not its content) closes it.
    if (e.target.classList && e.target.classList.contains("modal-overlay")) {
      closeModal(e.target.id);
    }
  });
})();
