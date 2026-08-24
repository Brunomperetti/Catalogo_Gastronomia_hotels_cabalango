const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const rotatorSource = fs.readFileSync("app/static/js/portal-hero-rotator.js", "utf8");

class FakeClassList {
  constructor(classes = []) {
    this.classes = new Set(classes);
  }

  add(name) { this.classes.add(name); }
  remove(name) { this.classes.delete(name); }
  contains(name) { return this.classes.has(name); }
}

class FakeSlide {
  constructor(caption, { active = false, complete = false, naturalWidth = 0 } = {}) {
    this.classList = new FakeClassList(active ? ["is-active"] : []);
    this.complete = complete;
    this.dataset = { caption };
    this.listeners = new Map();
    this.naturalWidth = naturalWidth;
    this.offsetWidth = 640;
    this.attributes = new Map([["aria-hidden", active ? "false" : "true"]]);
  }

  addEventListener(type, callback) { this.listeners.set(type, callback); }
  removeEventListener(type, callback) {
    if (this.listeners.get(type) === callback) this.listeners.delete(type);
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
}

const nextTurn = () => new Promise((resolve) => setImmediate(resolve));

function createRuntime(slides, { reducedMotion = false } = {}) {
  const caption = { textContent: slides[0].dataset.caption };
  const documentListeners = new Map();
  const intervals = [];
  const timeouts = [];
  const hero = {
    querySelector(selector) {
      if (selector === ".destination-hero-slide.is-active") {
        return slides.find((slide) => slide.classList.contains("is-active")) || null;
      }
      if (selector === "[data-hero-caption]") return caption;
      return null;
    },
    querySelectorAll() { return slides; },
  };
  const document = {
    hidden: false,
    querySelector: () => hero,
    addEventListener: (type, callback) => documentListeners.set(type, callback),
  };
  const window = {
    clearInterval() {},
    clearTimeout(handle) { if (handle) handle.cleared = true; },
    matchMedia: () => ({ matches: reducedMotion }),
    setInterval(callback, delay) {
      const handle = { callback, delay };
      intervals.push(handle);
      return handle;
    },
    setTimeout(callback, delay) {
      const handle = { callback, cleared: false, delay };
      timeouts.push(handle);
      return handle;
    },
  };

  vm.runInNewContext(rotatorSource, { document, window });
  return { caption, intervals, timeouts };
}

test("a failed or timed-out secondary slide never hides the initial slide", async () => {
  for (const outcome of ["error", "timeout"]) {
    const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
    const secondary = new FakeSlide("B");
    const runtime = createRuntime([initial, secondary]);

    if (outcome === "error") secondary.listeners.get("error")();
    else runtime.timeouts.find((timer) => timer.delay === 15000).callback();
    await nextTurn();

    assert.equal(initial.classList.contains("is-active"), true);
    assert.equal(initial.attributes.get("aria-hidden"), "false");
    assert.equal(secondary.classList.contains("is-incoming"), false);
    assert.equal(runtime.caption.textContent, "A");
    assert.equal(runtime.intervals.length, 0);
  }
});

test("two valid slides crossfade both ways without clearing current or caption early", async () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const secondary = new FakeSlide("B", { complete: true, naturalWidth: 100 });
  const runtime = createRuntime([initial, secondary]);
  await nextTurn();

  assert.equal(runtime.intervals.length, 1);
  runtime.intervals[0].callback();
  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(secondary.classList.contains("is-incoming"), true);
  assert.equal(runtime.caption.textContent, "A");
  secondary.listeners.get("transitionend")({ target: secondary, propertyName: "opacity" });
  assert.equal(secondary.classList.contains("is-active"), true);
  assert.equal(runtime.caption.textContent, "B");

  runtime.intervals[0].callback();
  assert.equal(secondary.classList.contains("is-active"), true);
  assert.equal(initial.classList.contains("is-incoming"), true);
  assert.equal(runtime.caption.textContent, "B");
  initial.listeners.get("transitionend")({ target: initial, propertyName: "opacity" });
  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(runtime.caption.textContent, "A");
});

test("reduced motion leaves the server-rendered state untouched", () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const secondary = new FakeSlide("B", { complete: true, naturalWidth: 100 });
  const runtime = createRuntime([initial, secondary], { reducedMotion: true });

  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(secondary.classList.contains("is-active"), false);
  assert.equal(runtime.caption.textContent, "A");
  assert.equal(runtime.intervals.length, 0);
  assert.equal(runtime.timeouts.length, 0);
});
