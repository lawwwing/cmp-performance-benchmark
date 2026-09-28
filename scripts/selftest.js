"use strict";

var assert = require("assert");
var metrics = require("../src/metrics.js");

function shift(start, value, recent) {
  return { startTime: start, value: value, hadRecentInput: !!recent };
}

var state = metrics.createClsState();
state = metrics.updateCls(state, shift(0, 0.25));
assert.strictEqual(state.cls, 0.25);
state = metrics.updateCls(state, shift(100, 0.125));
assert.strictEqual(state.cls, 0.375);
state = metrics.updateCls(state, shift(1100, 0.0625));
assert.strictEqual(state.sessionValue, 0.0625);
assert.strictEqual(state.cls, 0.375);
state = metrics.updateCls(state, shift(1200, 0.5));
assert.strictEqual(state.cls, 0.5625);
assert.strictEqual(state.counted, 4);

var boundary = metrics.createClsState();
boundary = metrics.updateCls(boundary, shift(0, 0.25));
boundary = metrics.updateCls(boundary, shift(900, 0.25));
boundary = metrics.updateCls(boundary, shift(1800, 0.25));
boundary = metrics.updateCls(boundary, shift(2700, 0.25));
boundary = metrics.updateCls(boundary, shift(3600, 0.25));
boundary = metrics.updateCls(boundary, shift(4500, 0.25));
assert.strictEqual(boundary.cls, 1.5);
boundary = metrics.updateCls(boundary, shift(5400, 0.125));
assert.strictEqual(boundary.sessionValue, 0.125);
assert.strictEqual(boundary.cls, 1.5);

var gap = metrics.createClsState();
gap = metrics.updateCls(gap, shift(0, 0.25));
gap = metrics.updateCls(gap, shift(999, 0.25));
assert.strictEqual(gap.cls, 0.5);
gap = metrics.updateCls(gap, shift(1999, 0.125));
assert.strictEqual(gap.sessionValue, 0.125);
assert.strictEqual(gap.cls, 0.5);

var ignored = metrics.createClsState();
ignored = metrics.updateCls(ignored, shift(0, 0.25));
ignored = metrics.updateCls(ignored, shift(10, 0.5, true));
assert.strictEqual(ignored.cls, 0.25);
assert.strictEqual(ignored.counted, 1);
assert.strictEqual(ignored.ignored, 1);
assert.strictEqual(ignored.sessionEntries.length, 1);

assert.strictEqual(metrics.isJsEntry({ initiatorType: "script", name: "https://cdn.example/widget" }), true);
assert.strictEqual(metrics.isJsEntry({ initiatorType: "other", name: "https://cdn.example/app.js?v=1" }), true);
assert.strictEqual(metrics.isJsEntry({ initiatorType: "img", name: "https://cdn.example/a.jpg" }), false);
assert.strictEqual(metrics.isJsEntry({ initiatorType: "xmlhttprequest", name: "https://cdn.example/config.json" }), false);
assert.strictEqual(metrics.isJsEntry({ initiatorType: "link", name: "https://cdn.example/app.mjs" }), true);

assert.strictEqual(metrics.parseMillis(null, 3000), 3000);
assert.strictEqual(metrics.parseMillis("1000", 0), 1000);
assert.strictEqual(metrics.parseMillis("-1", 5), 5);
assert.strictEqual(metrics.parseMillis("foo", 5), 5);
assert.strictEqual(metrics.parseMillis("0", 5), 0);

assert.strictEqual(metrics.variantFromPath("/lawwwing/"), "lawwwing");
assert.strictEqual(metrics.variantFromPath("/lawwwing/index.html"), "lawwwing");
assert.strictEqual(metrics.variantFromPath("/baseline"), "baseline");
assert.strictEqual(metrics.variantFromPath("/"), "root");

assert.strictEqual(
  metrics.elementLabel({ tagName: "IMG", id: "", getAttribute: function () { return "hero-image"; } }),
  "img.hero-image"
);
assert.strictEqual(
  metrics.elementLabel({ tagName: "H1", id: "story", getAttribute: function () { return ""; } }),
  "h1#story"
);

var report = metrics.summarize({
  variant: "lawwwing",
  phase: "settled",
  url: "http://127.0.0.1:4173/lawwwing/",
  generatedAt: "2026-01-01T00:00:00.000Z",
  navigation: {
    name: "http://127.0.0.1:4173/lawwwing/",
    transferSize: 2000,
    encodedBodySize: 1500,
    decodedBodySize: 4000,
    duration: 200.4,
    domContentLoadedEventEnd: 100.2,
    loadEventEnd: 200.4,
    responseStatus: 200
  },
  resources: [
    { name: "https://cdn.example/w.js", initiatorType: "script", startTime: 10, duration: 20, transferSize: 1000, encodedBodySize: 800, decodedBodySize: 2000, responseStatus: 200 },
    { name: "https://cdn.example/hidden.js", initiatorType: "script", startTime: 12, duration: 5, transferSize: 0, encodedBodySize: 0, decodedBodySize: 0 },
    { name: "/assets/hero.jpg", initiatorType: "img", startTime: 30, duration: 40, transferSize: 500, encodedBodySize: 480, decodedBodySize: 480, responseStatus: 200 },
    { name: "https://cdn.example/cached.js", initiatorType: "script", startTime: 15, duration: 1, transferSize: 0, encodedBodySize: 400, decodedBodySize: 900, responseStatus: 200 }
  ],
  clsState: { sessionValue: 0, sessionEntries: [], cls: 0.01234, counted: 2, ignored: 0 },
  lcp: { startTime: 180.04, size: 10000, url: "http://127.0.0.1:4173/assets/hero.jpg", elementLabel: "img.hero-image" },
  fcp: { startTime: 40.01 },
  longTasks: [
    { name: "self", startTime: 50, duration: 80, attribution: [{ name: "script", containerType: "iframe", containerSrc: "https://cdn.example/w.js", duration: 80 }] },
    { name: "self", startTime: 140, duration: 60, attribution: [] }
  ],
  unsupported: [],
  settleMinMs: 3000,
  settleQuietMs: 1000,
  settleMaxMs: 10000
});

assert.strictEqual(report.requestCount, 5);
assert.strictEqual(report.documentIncluded, true);
assert.strictEqual(report.transferredJsBytes, 1000);
assert.strictEqual(report.hiddenJsResponses, 1);
assert.strictEqual(report.transferredBytes, 3500);
assert.strictEqual(report.hiddenResponses, 1);
assert.strictEqual(report.encodedBodyJsBytes, 1200);
assert.strictEqual(report.encodedBodyBytes, 3180);
assert.strictEqual(report.longTaskCount, 2);
assert.strictEqual(report.longTaskDurationMs, 140);
assert.strictEqual(report.lcpMs, 180);
assert.strictEqual(report.lcpElement, "img.hero-image");
assert.strictEqual(report.fcpMs, 40);
assert.strictEqual(report.domContentLoadedMs, 100.2);
assert.strictEqual(report.loadMs, 200.4);
assert.strictEqual(report.cls, 0.0123);
assert.strictEqual(report.resources.length, 5);
assert.strictEqual(report.resources[0].initiatorType, "navigation");
assert.strictEqual(report.resources[1].name, "https://cdn.example/w.js");
assert.strictEqual(report.resources[1].js, true);
assert.strictEqual(report.resources[2].sizesExposed, false);
assert.strictEqual(report.resources[2].transferSize, null);
assert.strictEqual(report.resources[3].name, "https://cdn.example/cached.js");
assert.strictEqual(report.resources[3].transferSize, 0);
assert.strictEqual(report.resources[3].encodedBodySize, 400);
assert.strictEqual(report.resources[4].js, false);
assert.strictEqual(report.longTasks[0].containerSrc, "https://cdn.example/w.js");
assert.deepStrictEqual(report.hosts, [
  { host: "cdn.example", count: 3 },
  { host: "127.0.0.1", count: 2 }
]);

var line = metrics.formatLine(report);
assert.ok(line.indexOf("variant=lawwwing") !== -1);
assert.ok(line.indexOf("phase=settled") !== -1);
assert.ok(line.indexOf("js_bytes=1000") !== -1);
assert.ok(line.indexOf("js_bytes_hidden=1") !== -1);
assert.ok(line.indexOf("total_bytes=3500") !== -1);

var text = metrics.formatReport(report);
assert.ok(text.indexOf("img.hero-image") !== -1);
assert.ok(text.indexOf("180.0 ms") !== -1);
assert.ok(text.indexOf("Timing-Allow-Origin") !== -1);
assert.ok(text.indexOf("cdn.example (3)") !== -1);
assert.ok(text.indexOf("size hidden") !== -1);
assert.ok(text.indexOf("https://cdn.example/hidden.js") !== -1);
assert.ok(text.indexOf("https://cdn.example/w.js") !== -1);
assert.ok(text.indexOf("/assets/hero.jpg") !== -1);

var early = metrics.summarize({
  variant: "baseline",
  phase: "dom-content-loaded",
  url: "http://127.0.0.1:4173/baseline/",
  navigation: {
    name: "http://127.0.0.1:4173/baseline/",
    transferSize: 10,
    encodedBodySize: 10,
    decodedBodySize: 10,
    domContentLoadedEventEnd: 5,
    loadEventEnd: 0
  },
  resources: [],
  clsState: metrics.createClsState(),
  lcp: null,
  fcp: null,
  longTasks: [],
  unsupported: ["longtask"]
});
assert.strictEqual(early.loadMs, null);
assert.strictEqual(early.lcpMs, null);
assert.strictEqual(early.hiddenResponses, 0);
assert.deepStrictEqual(early.unsupported, ["longtask"]);
assert.ok(metrics.formatReport(early).indexOf("Timing-Allow-Origin") === -1);
assert.ok(metrics.formatReport(early).indexOf("longtask") !== -1);

console.log("selftest ok");
