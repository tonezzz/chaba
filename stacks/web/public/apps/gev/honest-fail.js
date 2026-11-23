/* God's Eye View — honest-fail watchdog (vendored, no deps).
 *
 * Injected into dist/index.html by scripts/gev/patch-gev-dist.sh after
 * every `npm run build` in ~/gods-eye-view.
 *
 * Contract (card gev-map): a pane that cannot render must surface a
 * visible failure state instead of a black pane. This script watches the
 * Cesium boot and runtime, and on failure:
 *   - shows #gev-honest-fail — a full-viewport overlay naming the reason
 *   - sets window.__gevHonestFail (same-origin parent probe, e.g. the
 *     vcast display's armFrameProbe, reads this flag directly)
 *   - posts {type:"gev-honest-fail", reason} to window.parent so a
 *     cross-origin host pane can badge the frame too
 * On success it sets window.__gevRenderOk and posts "gev-honest-ok",
 * which clears the host-side overlay.
 *
 * Failure signals:
 *   - no .cesium-widget canvas after BOOT_MS (the iPad WebGL crash class
 *     — CesiumWidget constructor throws before any canvas exists)
 *   - a boot-window window error / unhandled rejection naming WebGL or
 *     Cesium — reported as the reason hint
 *   - webglcontextlost at runtime (recovered by webglcontextrestored)
 */
(function () {
  "use strict";

  var OVERLAY_ID = "gev-honest-fail";
  var BOOT_MS = 25000;          // Cesium boot budget (module fetch + GL init)
  var ok = false;
  var failed = null;
  var bootErrs = [];

  function canvas() {
    return document.querySelector(
      "#cesiumContainer canvas, .cesium-widget canvas");
  }

  function note(msg) {
    if (msg && bootErrs.length < 8) bootErrs.push(String(msg).slice(0, 160));
  }
  window.addEventListener("error", function (e) {
    note(e.message || (e.error && e.error.message) || e.error);
  });
  window.addEventListener("unhandledrejection", function (e) {
    note("rejection: " + (e.reason && (e.reason.message || e.reason)));
  });

  function esc(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  function show(reason) {
    var el = document.getElementById(OVERLAY_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = OVERLAY_ID;
      el.setAttribute("data-gev-fail", "");
      el.style.cssText =
        "position:fixed;inset:0;z-index:2147483000;display:flex;" +
        "flex-direction:column;align-items:center;justify-content:center;" +
        "gap:14px;text-align:center;padding:24px;box-sizing:border-box;" +
        "background:#14080d;color:#f8fafc;" +
        "font:600 17px system-ui,-apple-system,'Segoe UI',sans-serif";
      document.body.appendChild(el);
    }
    el.innerHTML =
      '<div style="font-size:46px;line-height:1">⚠</div>' +
      "<div>God’s Eye View can’t render on this device</div>" +
      '<div style="font-size:13px;font-weight:400;color:#94a3b8;' +
      'max-width:36em;word-break:break-word">' + esc(reason) + "</div>";
    el.style.display = "flex";
  }

  function hide() {
    var el = document.getElementById(OVERLAY_ID);
    if (el) el.style.display = "none";
  }

  // Host pane channel — postMessage is origin-safe, so this reaches a
  // vcast display frame even when the frame is treated cross-origin.
  function tell(msg) {
    try {
      if (window.parent && window.parent !== window)
        window.parent.postMessage(msg, "*");
    } catch (e) { /* detached frame */ }
  }

  function fail(reason) {
    failed = String(reason || "render failure");
    window.__gevHonestFail = failed;
    show(failed);
    tell({ type: "gev-honest-fail", reason: failed });
  }

  function renderOk() {
    var wasFailed = !!failed;
    ok = true;
    failed = null;
    window.__gevRenderOk = true;
    try { delete window.__gevHonestFail; } catch (e) {
      window.__gevHonestFail = undefined;
    }
    hide();
    if (wasFailed || !renderOk._sent) {
      renderOk._sent = true;
      tell({ type: "gev-honest-ok" });
    }
  }

  function watchCanvas(cv) {
    cv.addEventListener("webglcontextlost", function (e) {
      e.preventDefault();   // allow Cesium's own restore attempt
      ok = false;
      fail("WebGL context lost");
    });
    cv.addEventListener("webglcontextrestored", renderOk);
  }

  var sawCanvas = false;
  var t0 = Date.now();
  var tick = setInterval(function () {
    if (!sawCanvas) {
      var cv = canvas();
      if (cv) {
        sawCanvas = true;
        watchCanvas(cv);
        renderOk();
        clearInterval(tick);
        return;
      }
      if (Date.now() - t0 > BOOT_MS) {
        clearInterval(tick);
        var hint = null;
        for (var i = 0; i < bootErrs.length; i++) {
          if (/webgl|cesium|context|gpu/i.test(bootErrs[i])) {
            hint = bootErrs[i];
            break;
          }
        }
        fail("3D engine did not start" +
             (hint ? " — " + hint
                   : " — no render canvas after " + BOOT_MS / 1000 +
                     "s (WebGL unavailable or blocked)"));
      }
    }
  }, 500);
})();
