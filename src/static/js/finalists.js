// Achievements medal timeline: reveal overlapping medals on hover.
//
// At rest the dots keep their date-aligned horizontal position (matching the header
// time-axis); pile density is conveyed purely in CSS (accumulating shadow + light ring, see
// finalists.css). On hover the container's crowded dots spread apart horizontally into a
// readable row; this file only computes the per-dot `--spread-x` (hover horizontal delta).

(function () {
  var DOT_RADIUS = 5; // half of the 10px dot
  var GAP = 8; // target gap (px) between dots when a cluster is spread on hover

  function clamp(value, lo, hi) {
    return Math.max(lo, Math.min(hi, value));
  }

  function initFinalistTimeline(container) {
    var width = container.clientWidth;
    if (!width) {
      return;
    }

    var items = [];
    container.querySelectorAll(".timeline-dot").forEach(function (el) {
      if (el.dataset.leftPct === undefined) {
        el.dataset.leftPct = parseFloat(el.style.left) || 0;
      }
      // Base center x from the inline `left: X%` — immune to any applied transform.
      var x = (parseFloat(el.dataset.leftPct) / 100) * width + DOT_RADIUS;
      items.push({ el: el, x: x });
    });
    if (!items.length) {
      return;
    }
    items.sort(function (a, b) {
      return a.x - b.x;
    });

    // Reset so recomputation (e.g. on resize) starts clean.
    items.forEach(function (it) {
      it.el.style.removeProperty("--spread-x");
    });

    // Spread (hover): lay dots out with a minimum gap, merging runs that would collide, each
    // run centered on its centroid; well-separated (single) dots keep their place.
    var runs = items.map(function (it, idx) {
      return { sum: it.x, count: 1, first: idx };
    });
    var r = 0;
    while (r < runs.length - 1) {
      var a = runs[r];
      var b = runs[r + 1];
      var aEnd = a.sum / a.count + ((a.count - 1) * GAP) / 2;
      var bStart = b.sum / b.count - ((b.count - 1) * GAP) / 2;
      if (bStart - aEnd < GAP) {
        runs.splice(r, 2, { sum: a.sum + b.sum, count: a.count + b.count, first: a.first });
        if (r > 0) {
          r--;
        }
      } else {
        r++;
      }
    }
    runs.forEach(function (run) {
      var half = ((run.count - 1) * GAP) / 2;
      var center = clamp(run.sum / run.count, DOT_RADIUS + half, width - DOT_RADIUS - half);
      for (var k = 0; k < run.count; k++) {
        var it = items[run.first + k];
        var target = center + (k - (run.count - 1) / 2) * GAP;
        it.el.style.setProperty("--spread-x", (target - it.x).toFixed(1) + "px");
      }
    });
  }

  function initAllFinalistTimelines() {
    document.querySelectorAll(".timeline-container").forEach(initFinalistTimeline);
  }

  var resizeTimer = null;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(initAllFinalistTimelines, 150);
  }

  $(initAllFinalistTimelines);
  $(window).on("load", initAllFinalistTimelines);
  $(window).on("resize", onResize);

  window.initAllFinalistTimelines = initAllFinalistTimelines;
})();
