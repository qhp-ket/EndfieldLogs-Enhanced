(function () {
  function apply(config) {
    if (config.theme !== undefined) document.documentElement.dataset.theme = ["dark", "transparent"].includes(config.theme) ? config.theme : "light";
    // The Qt host combines window size and the user's font multiplier.
    if (!window.endfieldOverlay?.config && config.fontScale !== undefined) document.documentElement.style.setProperty("--overlay-font-scale", Math.max(.5, Math.min(3, Number(config.fontScale) || 1)));
  }
  const params = new URLSearchParams(window.location.search);
  apply({theme: params.get("theme"), fontScale: params.get("fontScale") || 1});
  window.addEventListener("endfield-overlay-config", event => apply(event.detail || {}));
})();
