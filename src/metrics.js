"use strict";

/*
 * External page harness. The same bytes are inlined on every variant.
 * It does not patch network APIs, cookies, dataLayer, or gtag.
 *
 * CLS is the session-window score (gap under 1s, window under 5s), the
 * definition Lighthouse uses. Cross-origin responses without
 * Timing-Allow-Origin hide transferSize; those responses are counted
 * and left out of the byte totals rather than recorded as zero.
 */

(function () {
  function roundMetric(value, digits) {
    if (typeof value !== "number" || !isFinite(value)) return null;
    var factor = Math.pow(10, digits);
    return Math.round(value * factor) / factor;
  }

  function parseMillis(content, fallback) {
    if (content == null || content === "") return fallback;
    var value = Number(content);
    if (!isFinite(value) || value < 0) return fallback;
    return value;
  }

  function variantFromPath(pathname) {
    var parts = String(pathname || "").split("/");
    var kept = [];
    var i;
    for (i = 0; i < parts.length; i++) {
      if (parts[i] && parts[i] !== "index.html") kept.push(parts[i]);
    }
    return kept.length ? kept[0] : "root";
  }

  function elementLabel(el) {
    if (!el || !el.tagName) return null;
    var tag = String(el.tagName).toLowerCase();
    if (el.id) return tag + "#" + el.id;
    var raw = "";
    if (typeof el.getAttribute === "function") raw = el.getAttribute("class") || "";
    else if (el.className) raw = String(el.className);
    var cls = String(raw).trim().split(/\s+/)[0] || "";
    return cls ? tag + "." + cls : tag;
  }

  function createClsState() {
    return {
      sessionValue: 0,
      sessionEntries: [],
      cls: 0,
      counted: 0,
      ignored: 0
    };
  }

  // Session rule matches Chrome / web-vitals: a shift joins the current
  // session when it is < 1s after the previous shift and < 5s after the first.
  function updateCls(state, entry) {
    if (!entry || entry.hadRecentInput) {
      return {
        sessionValue: state.sessionValue,
        sessionEntries: state.sessionEntries,
        cls: state.cls,
        counted: state.counted,
        ignored: state.ignored + (entry && entry.hadRecentInput ? 1 : 0)
      };
    }

    var first = state.sessionEntries[0];
    var last = state.sessionEntries[state.sessionEntries.length - 1];
    var continues = state.sessionValue && first && last &&
      (entry.startTime - last.startTime < 1000) &&
      (entry.startTime - first.startTime < 5000);
    var sessionValue;
    var sessionEntries;
    if (continues) {
      sessionValue = state.sessionValue + entry.value;
      sessionEntries = state.sessionEntries.concat([entry]);
    } else {
      sessionValue = entry.value;
      sessionEntries = [entry];
    }
    return {
      sessionValue: sessionValue,
      sessionEntries: sessionEntries,
      cls: sessionValue > state.cls ? sessionValue : state.cls,
      counted: state.counted + 1,
      ignored: state.ignored
    };
  }

  function isJsEntry(entry) {
    if (!entry) return false;
    if (entry.initiatorType === "script") return true;
    var path = String(entry.name || "").split("?")[0].split("#")[0];
    return /\.m?js$/i.test(path);
  }

  function finiteNumber(value) {
    var number = Number(value);
    return isFinite(number) ? number : 0;
  }

  // All-zero sizes are how Chrome represents a cross-origin response that
  // did not opt in with Timing-Allow-Origin. A cached response has
  // transferSize 0 and a non-zero encodedBodySize, so it stays visible.
  function sizeInfo(entry) {
    var transfer = finiteNumber(entry && entry.transferSize);
    var encoded = finiteNumber(entry && entry.encodedBodySize);
    var decoded = finiteNumber(entry && entry.decodedBodySize);
    var exposed = !(transfer === 0 && encoded === 0 && decoded === 0);
    return {
      transfer: transfer,
      encoded: encoded,
      decoded: decoded,
      exposed: exposed
    };
  }

  function hostOf(url, base) {
    try {
      var parsed = new URL(url, base);
      return parsed.hostname || parsed.host || String(url || "");
    } catch (err) {
      return String(url || "");
    }
  }

  function containerSrcs(task) {
    var srcs = [];
    var attribution = task.attribution || [];
    var i;
    for (i = 0; i < attribution.length; i++) {
      if (attribution[i].containerSrc) srcs.push(attribution[i].containerSrc);
    }
    return srcs.join(" ");
  }

  function summarize(input) {
    var navigation = input.navigation || null;
    var resources = input.resources || [];
    var clsState = input.clsState || createClsState();
    var lcp = input.lcp || null;
    var fcp = input.fcp || null;
    var tasks = input.longTasks || [];
    var pageUrl = input.url || "";

    var documentEntry = null;
    if (navigation) {
      documentEntry = {
        name: navigation.name || pageUrl,
        initiatorType: "navigation",
        startTime: 0,
        duration: navigation.duration || 0,
        transferSize: navigation.transferSize,
        encodedBodySize: navigation.encodedBodySize,
        decodedBodySize: navigation.decodedBodySize,
        responseStatus: navigation.responseStatus
      };
    }

    var transferredBytes = 0;
    var transferredJsBytes = 0;
    var encodedBodyBytes = 0;
    var encodedBodyJsBytes = 0;
    var hiddenResponses = 0;
    var hiddenJsResponses = 0;
    var rows = [];

    function account(entry, js) {
      var sizes = sizeInfo(entry);
      if (!sizes.exposed) {
        hiddenResponses += 1;
        if (js) hiddenJsResponses += 1;
      } else {
        transferredBytes += sizes.transfer;
        encodedBodyBytes += sizes.encoded;
        if (js) {
          transferredJsBytes += sizes.transfer;
          encodedBodyJsBytes += sizes.encoded;
        }
      }
      rows.push({
        name: entry.name || "",
        initiatorType: entry.initiatorType || "",
        startMs: roundMetric(entry.startTime || 0, 1),
        durationMs: roundMetric(entry.duration || 0, 1),
        transferSize: sizes.exposed ? sizes.transfer : null,
        encodedBodySize: sizes.exposed ? sizes.encoded : null,
        decodedBodySize: sizes.exposed ? sizes.decoded : null,
        responseStatus: typeof entry.responseStatus === "number" && entry.responseStatus > 0
          ? entry.responseStatus
          : null,
        js: !!js,
        sizesExposed: sizes.exposed
      });
    }

    if (documentEntry) account(documentEntry, false);

    var resourceRows = resources.map(function (entry) {
      return { entry: entry, js: isJsEntry(entry) };
    });
    resourceRows.sort(function (a, b) {
      var startA = a.entry.startTime || 0;
      var startB = b.entry.startTime || 0;
      if (startA !== startB) return startA - startB;
      var nameA = a.entry.name || "";
      var nameB = b.entry.name || "";
      if (nameA < nameB) return -1;
      if (nameA > nameB) return 1;
      return 0;
    });
    var r;
    for (r = 0; r < resourceRows.length; r++) {
      account(resourceRows[r].entry, resourceRows[r].js);
    }

    var longTaskDuration = 0;
    var longTaskRows = [];
    var t;
    for (t = 0; t < tasks.length; t++) {
      longTaskDuration += finiteNumber(tasks[t].duration);
      longTaskRows.push({
        startMs: roundMetric(tasks[t].startTime, 1),
        durationMs: roundMetric(tasks[t].duration, 1),
        name: tasks[t].name || "longtask",
        containerSrc: containerSrcs(tasks[t])
      });
    }

    var hostCounts = {};
    var h;
    for (h = 0; h < rows.length; h++) {
      var host = hostOf(rows[h].name, pageUrl);
      hostCounts[host] = (hostCounts[host] || 0) + 1;
    }
    var hosts = [];
    var hostName;
    for (hostName in hostCounts) {
      if (Object.prototype.hasOwnProperty.call(hostCounts, hostName)) {
        hosts.push({ host: hostName, count: hostCounts[hostName] });
      }
    }
    hosts.sort(function (a, b) {
      if (b.count !== a.count) return b.count - a.count;
      if (a.host < b.host) return -1;
      if (a.host > b.host) return 1;
      return 0;
    });

    var report = {
      variant: input.variant || "",
      phase: input.phase || "",
      url: pageUrl,
      generatedAt: input.generatedAt || null,
      lcpMs: lcp ? roundMetric(lcp.startTime, 1) : null,
      lcpSize: lcp && typeof lcp.size === "number" ? lcp.size : null,
      lcpElement: lcp ? (lcp.elementLabel || null) : null,
      lcpUrl: lcp ? (lcp.url || null) : null,
      fcpMs: fcp ? roundMetric(fcp.startTime, 1) : null,
      cls: roundMetric(clsState.cls || 0, 4),
      clsShifts: clsState.counted || 0,
      clsIgnoredShifts: clsState.ignored || 0,
      longTaskCount: tasks.length,
      longTaskDurationMs: roundMetric(longTaskDuration, 1),
      longTasks: longTaskRows,
      domContentLoadedMs: navigation ? timingMs(navigation.domContentLoadedEventEnd) : null,
      loadMs: navigation ? timingMs(navigation.loadEventEnd) : null,
      requestCount: rows.length,
      documentIncluded: !!navigation,
      transferredJsBytes: transferredJsBytes,
      hiddenJsResponses: hiddenJsResponses,
      transferredBytes: transferredBytes,
      hiddenResponses: hiddenResponses,
      encodedBodyJsBytes: encodedBodyJsBytes,
      encodedBodyBytes: encodedBodyBytes,
      resources: rows,
      hosts: hosts,
      unsupported: (input.unsupported || []).slice(),
      settleMinMs: input.settleMinMs == null ? null : input.settleMinMs,
      settleQuietMs: input.settleQuietMs == null ? null : input.settleQuietMs,
      settleMaxMs: input.settleMaxMs == null ? null : input.settleMaxMs
    };
    return report;
  }

  function timingMs(value) {
    var number = Number(value);
    if (!isFinite(number) || number <= 0) return null;
    return roundMetric(number, 1);
  }

  function shownNumber(value) {
    if (value == null) return "n/a";
    return String(value);
  }

  function shownMs(value) {
    if (value == null) return "n/a";
    var number = Number(value);
    if (!isFinite(number)) return "n/a";
    return number.toFixed(1) + " ms";
  }

  function shownPlainMs(value) {
    if (value == null) return "n/a";
    var number = Number(value);
    if (!isFinite(number)) return "n/a";
    return number.toFixed(1) + "ms";
  }

  function row(label, value) {
    var text = label;
    while (text.length < 22) text += " ";
    return text + value;
  }

  function formatLine(report) {
    return "[cmp-bench]"
      + " variant=" + report.variant
      + " phase=" + report.phase
      + " lcp_ms=" + shownNumber(report.lcpMs)
      + " fcp_ms=" + shownNumber(report.fcpMs)
      + " cls=" + shownNumber(report.cls)
      + " long_tasks=" + report.longTaskCount
      + " long_task_ms=" + shownNumber(report.longTaskDurationMs)
      + " dcl_ms=" + shownNumber(report.domContentLoadedMs)
      + " load_ms=" + shownNumber(report.loadMs)
      + " requests=" + report.requestCount
      + " js_bytes=" + report.transferredJsBytes
      + " total_bytes=" + report.transferredBytes
      + " js_bytes_hidden=" + report.hiddenJsResponses
      + " total_bytes_hidden=" + report.hiddenResponses;
  }

  function hiddenSuffix(hidden, noun) {
    if (!hidden) return "";
    return " (" + hidden + " " + noun + (hidden === 1 ? "" : "s")
      + " hid transferSize; no Timing-Allow-Origin)";
  }

  function formatReport(report) {
    var lcpExtra = [];
    if (report.lcpElement) lcpExtra.push(report.lcpElement);
    if (report.lcpSize != null) lcpExtra.push("size " + report.lcpSize);
    var lcpText = shownMs(report.lcpMs);
    if (lcpExtra.length) lcpText += " (" + lcpExtra.join(", ") + ")";

    var requestText = String(report.requestCount);
    if (report.documentIncluded) {
      requestText += " (1 document + " + Math.max(0, report.requestCount - 1) + " subresources)";
    } else {
      requestText += " (navigation timing unavailable)";
    }

    var hostText = "n/a";
    if (report.hosts && report.hosts.length) {
      hostText = report.hosts.map(function (item) {
        return item.host + " (" + item.count + ")";
      }).join(", ");
    }

    var lines = [];
    lines.push("-------- CMP benchmark: " + report.variant + " (" + report.phase + ") --------");
    if (report.generatedAt) lines.push(row("Recorded", report.generatedAt));
    lines.push(row("URL", report.url || "n/a"));
    lines.push(row("LCP", lcpText));
    lines.push(row("LCP URL", report.lcpUrl || "n/a"));
    lines.push(row("FCP", shownMs(report.fcpMs)));
    lines.push(row("CLS", shownNumber(report.cls) + " (" + (report.clsShifts || 0) + " layout shifts counted)"));
    if (report.clsIgnoredShifts) {
      lines.push(row("Ignored shifts", report.clsIgnoredShifts + " (leave the tab idle while measuring)"));
    }
    lines.push(row("Long tasks", String(report.longTaskCount)));
    lines.push(row("Long task duration", shownMs(report.longTaskDurationMs)));
    lines.push(row("DOMContentLoaded", shownMs(report.domContentLoadedMs)));
    lines.push(row("Load", shownMs(report.loadMs)));
    lines.push(row("Requests", requestText));
    lines.push(row("Transferred JS", report.transferredJsBytes + " bytes known" + hiddenSuffix(report.hiddenJsResponses, "JS response")));
    lines.push(row("Transferred total", report.transferredBytes + " bytes known" + hiddenSuffix(report.hiddenResponses, "response")));
    lines.push(row("Encoded body JS", report.encodedBodyJsBytes + " bytes known (body size, not wire size)"));
    lines.push(row("Encoded body total", report.encodedBodyBytes + " bytes known (body size, not wire size)"));
    lines.push(row("Hosts", hostText));
    if (report.settleMinMs != null) {
      lines.push(row("Settle window", "min " + report.settleMinMs + " ms, quiet " + report.settleQuietMs + " ms, max " + report.settleMaxMs + " ms"));
    }
    if (report.unsupported && report.unsupported.length) {
      lines.push(row("Unsupported entries", report.unsupported.join(", ")));
    }
    lines.push("Resources");
    var index;
    for (index = 0; index < report.resources.length; index++) {
      var item = report.resources[index];
      var sizeText = item.sizesExposed ? item.transferSize + " B" : "size hidden";
      var statusText = item.responseStatus ? " HTTP " + item.responseStatus : "";
      lines.push("  " + shownPlainMs(item.startMs) + "  " + (item.initiatorType || "other") + "  " + sizeText + statusText + "  " + item.name);
    }
    if (report.longTasks && report.longTasks.length) {
      lines.push("Long task list");
      for (index = 0; index < report.longTasks.length; index++) {
        var task = report.longTasks[index];
        lines.push(
          "  " + shownPlainMs(task.startMs)
          + "  " + shownPlainMs(task.durationMs)
          + "  " + (task.name || "longtask")
          + (task.containerSrc ? "  " + task.containerSrc : "")
        );
      }
    }
    lines.push("Byte totals use transferSize and skip responses that hide it.");
    lines.push("Full object: window.__CMP_BENCH__.latest");
    lines.push("--------");
    return lines.join("\n");
  }

  function snapshotLcp(entry) {
    return {
      startTime: entry.startTime,
      size: typeof entry.size === "number" ? entry.size : null,
      url: entry.url || "",
      elementLabel: elementLabel(entry.element)
    };
  }

  function snapshotLongTask(entry) {
    var sources = [];
    var attribution = entry.attribution || [];
    var i;
    for (i = 0; i < attribution.length; i++) {
      var item = attribution[i];
      sources.push({
        name: item.name || "",
        containerType: item.containerType || "",
        containerSrc: item.containerSrc || "",
        duration: item.duration
      });
    }
    return {
      name: entry.name || "longtask",
      startTime: entry.startTime,
      duration: entry.duration,
      attribution: sources
    };
  }

  function observeType(type, onEntry) {
    if (typeof PerformanceObserver !== "function") return null;
    try {
      var observer = new PerformanceObserver(function (list) {
        var entries = list.getEntries();
        var i;
        for (i = 0; i < entries.length; i++) onEntry(entries[i]);
      });
      observer.observe({ type: type, buffered: true });
      return observer;
    } catch (err) {
      return null;
    }
  }

  function entriesOf(type) {
    try {
      return performance.getEntriesByType(type);
    } catch (err) {
      return [];
    }
  }

  function metaContent(name) {
    var el = document.querySelector('meta[name="' + name + '"]');
    return el ? el.getAttribute("content") : null;
  }

  function install() {
    var settleMinMs = parseMillis(metaContent("cmp-bench-settle-min-ms"), 3000);
    var settleQuietMs = parseMillis(metaContent("cmp-bench-settle-quiet-ms"), 1000);
    var settleMaxMs = parseMillis(metaContent("cmp-bench-settle-max-ms"), 10000);
    if (settleMaxMs < settleMinMs) settleMaxMs = settleMinMs;

    try {
      if (typeof performance.setResourceTimingBufferSize === "function") {
        performance.setResourceTimingBufferSize(500);
      }
    } catch (err) {}

    var clsState = createClsState();
    var lcp = null;
    var fcp = null;
    var longTasks = [];
    var unsupported = [];
    var observers = [];
    var lastResourceAt = 0;

    function track(type, onEntry) {
      var observer = observeType(type, onEntry);
      if (observer) observers.push(observer);
      else unsupported.push(type);
    }

    track("largest-contentful-paint", function (entry) {
      lcp = snapshotLcp(entry);
    });
    track("paint", function (entry) {
      if (entry.name === "first-contentful-paint") {
        fcp = { startTime: entry.startTime };
      }
    });
    track("layout-shift", function (entry) {
      clsState = updateCls(clsState, entry);
    });
    track("longtask", function (entry) {
      longTasks.push(snapshotLongTask(entry));
    });
    track("resource", function () {
      lastResourceAt = performance.now();
    });

    var phases = {};
    window.__CMP_BENCH__ = {
      variant: variantFromPath(location.pathname),
      phases: phases,
      latest: null
    };

    function emit(phase) {
      if (phases[phase]) return;
      var navigationEntries = entriesOf("navigation");
      var report = summarize({
        variant: window.__CMP_BENCH__.variant,
        phase: phase,
        url: location.href,
        generatedAt: new Date().toISOString(),
        navigation: navigationEntries.length ? navigationEntries[0] : null,
        resources: entriesOf("resource").slice(),
        clsState: clsState,
        lcp: lcp,
        fcp: fcp,
        longTasks: longTasks.slice(),
        unsupported: unsupported.slice(),
        settleMinMs: settleMinMs,
        settleQuietMs: settleQuietMs,
        settleMaxMs: settleMaxMs
      });
      phases[phase] = report;
      window.__CMP_BENCH__.latest = report;
      console.log(formatLine(report));
      if (phase === "settled") {
        console.log(formatReport(report));
        console.table(report.resources);
        if (report.longTasks.length) console.table(report.longTasks);
        console.log(report);
      }
    }

    document.addEventListener("DOMContentLoaded", function () {
      // domContentLoadedEventEnd is filled in after the event finishes.
      setTimeout(function () { emit("dom-content-loaded"); }, 0);
    });

    window.addEventListener("load", function () {
      setTimeout(function () {
        emit("load");
        var loadMark = performance.now();
        function tick() {
          var sinceLoad = performance.now() - loadMark;
          var sinceResource = performance.now() - lastResourceAt;
          var ready = sinceLoad >= settleMaxMs ||
            (sinceLoad >= settleMinMs && sinceResource >= settleQuietMs);
          if (!ready) {
            setTimeout(tick, 200);
            return;
          }
          emit("settled");
          var i;
          for (i = 0; i < observers.length; i++) {
            try { observers[i].disconnect(); } catch (err) {}
          }
        }
        setTimeout(tick, 200);
      }, 0);
    });
  }

  var api = {
    createClsState: createClsState,
    updateCls: updateCls,
    isJsEntry: isJsEntry,
    summarize: summarize,
    roundMetric: roundMetric,
    parseMillis: parseMillis,
    variantFromPath: variantFromPath,
    formatLine: formatLine,
    formatReport: formatReport,
    elementLabel: elementLabel
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (typeof window !== "undefined" && typeof document !== "undefined") {
    try {
      install();
    } catch (err) {
      window.__CMP_BENCH_ERROR__ = String(err && err.stack ? err.stack : err);
      if (typeof console !== "undefined") console.error("[cmp-bench] harness failed", err);
    }
  }
})();
