// Installed by the Qt host before template scripts. Templates use complete states.
(() => {
  const api = window.endfieldOverlay = {config: null, snapshots: {}};
  // Draw inside Chromium, not as a QWidget above its native compositor surface.
  // A shadow root isolates the mark from any built-in/custom template's styles;
  // the Qt host handles its hit target while the page remains mouse-transparent.
  let closeHost;
  function applyClose() {
    if (!document.documentElement || !api.config) return;
    if (!closeHost) {
      closeHost = document.createElement("endfield-host-close");
      closeHost.id = "endfield-host-close";
      closeHost.style.cssText = "all:initial!important;position:fixed!important;right:8px!important;top:max(0px,min(8px,calc(100vh - 26px)))!important;width:26px!important;height:26px!important;z-index:2147483647!important;pointer-events:none!important;";
      const shadow = closeHost.attachShadow({mode: "open"});
      shadow.innerHTML = `<style>
        svg{display:block;width:26px;height:26px;overflow:visible}
        rect{fill:transparent} path{fill:none;stroke-linecap:round}
        .outline{stroke:rgba(0,0,0,.8);stroke-width:3.8}
        .mark{stroke:rgba(255,255,255,.94);stroke-width:1.8}
        :host([hovered]) rect{fill:#cd1e32}
        :host([hovered]) .outline{stroke:transparent}
        :host([hovered]) .mark{stroke:white;stroke-width:2.2}
        </style><svg viewBox="0 0 26 26" aria-label="关闭此悬浮窗"><rect width="26" height="26" rx="4"/><path class="outline" d="M7 7L19 19M19 7L7 19"/><path class="mark" d="M7 7L19 19M19 7L7 19"/></svg>`;
    }
    if (!closeHost.isConnected) document.documentElement.appendChild(closeHost);
    closeHost.style.setProperty("display", api.config.click_through ? "none" : "block", "important");
    closeHost.toggleAttribute("hovered", !!api.config.closeHovered && !api.config.click_through);
  }
  api.setCloseHover = hovered => {
    if (api.config) api.config.closeHovered = !!hovered;
    applyClose();
  };
  for (const type of ["analysis", "combo", "buff", "input"]) {
    window.addEventListener(`endfield-${type}-snapshot`, event => {
      api.snapshots[event.detail && event.detail.type || `${type}_snapshot`] = event.detail;
    });
  }
  let original = new Map();
  let currentScale = 1;
  let scheduled = false;
  function applyFonts() {
    scheduled = false;
    if (!api.config || !document.documentElement) return;
    const fontScale = Math.max(.5, Math.min(3, Number(api.config.fontScale) || 1));
    const reference = api.contentReference || api.config.referenceSize || {};
    const heightScale = window.innerHeight/(reference.height || window.innerHeight);
    const windowScale = reference.scaleAxis === 'height' ? heightScale :
      Math.min(window.innerWidth/(reference.width || window.innerWidth), heightScale);
    const scale = fontScale * windowScale;
    document.documentElement.style.setProperty("--overlay-window-scale", windowScale);
    document.documentElement.style.setProperty("--overlay-user-font-scale", fontScale);
    document.documentElement.style.setProperty("--overlay-font-scale", scale);
    if (api.config.fontMode === "css") return;
    // Legacy HTML may use px fonts. Restore every base before measuring, so
    // inherited sizes never compound on repeat updates or newly added nodes.
    for (const [node, value] of original) {
      if (node.isConnected) {
        if (value) node.style.setProperty("font-size", value[0], value[1]);
        else node.style.removeProperty("font-size");
      }
    }
    original = new Map();
    currentScale = scale;
    if (scale === 1) return;
    const sizes = [...document.querySelectorAll("body, body *")].map(node => [node, getComputedStyle(node).fontSize]);
    for (const [node, size] of sizes) {
      const value = node.style.getPropertyValue("font-size");
      original.set(node, value ? [value, node.style.getPropertyPriority("font-size")] : null);
      node.style.setProperty("font-size", `${parseFloat(size) * scale}px`, "important");
    }
  }
  api.setContentReference = reference => {
    if (!reference || !Number.isFinite(reference.width) || !Number.isFinite(reference.height)
        || reference.width <= 0 || reference.height <= 0) return;
    api.contentReference = reference;
    applyFonts();
  };
  window.addEventListener("endfield-overlay-config", event => {
    api.config = event.detail;
    applyClose();
    applyFonts();
  });
  window.addEventListener("resize", () => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(applyFonts);
    }
  });
  window.addEventListener("DOMContentLoaded", () => {
    new MutationObserver(() => {
      if (!scheduled && currentScale !== 1) {
        scheduled = true;
        requestAnimationFrame(applyFonts);
      }
    }).observe(document.body, {childList: true, subtree: true});
    applyFonts();
    applyClose();
  });
})();
