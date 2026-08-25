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
  constructor(captionTitle, { active = false, captionCategory = "Río y naturaleza", complete = false, naturalWidth = 0 } = {}) {
    this.classList = new FakeClassList(active ? ["is-active"] : []);
    this.complete = complete;
    this.dataset = { captionCategory, captionTitle };
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
  const captionCategory = { textContent: slides[0].dataset.captionCategory };
  const captionTitle = { textContent: slides[0].dataset.captionTitle };
  const documentListeners = new Map();
  const intervals = [];
  const timeouts = [];
  const hero = {
    querySelector(selector) {
      if (selector === ".destination-hero-slide.is-active") {
        return slides.find((slide) => slide.classList.contains("is-active")) || null;
      }
      if (selector === "[data-hero-caption-category]") return captionCategory;
      if (selector === "[data-hero-caption-title]") return captionTitle;
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
  return { captionCategory, captionTitle, intervals, timeouts };
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
    assert.equal(runtime.captionTitle.textContent, "A");
    assert.equal(runtime.intervals.length, 0);
  }
});

test("the incoming slide updates category and title when its crossfade starts", async () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const secondary = new FakeSlide("Feria de Artesanos", { captionCategory: "Eventos y ferias", complete: true, naturalWidth: 100 });
  const runtime = createRuntime([initial, secondary]);
  await nextTurn();

  assert.equal(runtime.intervals.length, 1);
  assert.equal(runtime.intervals[0].delay, 3000);
  runtime.intervals[0].callback();
  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(secondary.classList.contains("is-incoming"), true);
  assert.equal(runtime.captionCategory.textContent, "Eventos y ferias");
  assert.equal(runtime.captionTitle.textContent, "Feria de Artesanos");
  secondary.listeners.get("transitionend")({ target: secondary, propertyName: "opacity" });
  assert.equal(secondary.classList.contains("is-active"), true);
  assert.equal(runtime.captionCategory.textContent, "Eventos y ferias");
  assert.equal(runtime.captionTitle.textContent, "Feria de Artesanos");

  runtime.intervals[0].callback();
  assert.equal(secondary.classList.contains("is-active"), true);
  assert.equal(initial.classList.contains("is-incoming"), true);
  assert.equal(runtime.captionCategory.textContent, "Río y naturaleza");
  assert.equal(runtime.captionTitle.textContent, "A");
  initial.listeners.get("transitionend")({ target: initial, propertyName: "opacity" });
  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(runtime.captionCategory.textContent, "Río y naturaleza");
  assert.equal(runtime.captionTitle.textContent, "A");
});

test("candidate resolution speed never changes DOM editorial order", async () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const second = new FakeSlide("B");
  const third = new FakeSlide("C");
  const runtime = createRuntime([initial, second, third]);

  third.naturalWidth = 100;
  third.listeners.get("load")();
  await nextTurn();
  second.naturalWidth = 100;
  second.listeners.get("load")();
  await nextTurn();

  const visited = [runtime.captionTitle.textContent];
  for (const next of [second, third, initial]) {
    runtime.intervals.at(-1).callback();
    next.listeners.get("transitionend")({ target: next, propertyName: "opacity" });
    visited.push(runtime.captionTitle.textContent);
  }

  assert.deepEqual(visited, ["A", "B", "C", "A"]);
});

test("a newly confirmed earlier slide does not desynchronize the active slide", async () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const second = new FakeSlide("B");
  const third = new FakeSlide("C");
  const runtime = createRuntime([initial, second, third]);

  third.naturalWidth = 100;
  third.listeners.get("load")();
  await nextTurn();
  runtime.intervals.at(-1).callback();
  third.listeners.get("transitionend")({ target: third, propertyName: "opacity" });
  assert.equal(third.classList.contains("is-active"), true);

  second.naturalWidth = 100;
  second.listeners.get("load")();
  await nextTurn();
  assert.equal(third.classList.contains("is-active"), true);

  runtime.intervals.at(-1).callback();
  assert.equal(initial.classList.contains("is-incoming"), true);
  assert.equal(second.classList.contains("is-incoming"), false);
  initial.listeners.get("transitionend")({ target: initial, propertyName: "opacity" });
  assert.equal(runtime.captionTitle.textContent, "A");
});

test("reduced motion leaves the server-rendered state untouched", () => {
  const initial = new FakeSlide("A", { active: true, complete: true, naturalWidth: 100 });
  const secondary = new FakeSlide("B", { complete: true, naturalWidth: 100 });
  const runtime = createRuntime([initial, secondary], { reducedMotion: true });

  assert.equal(initial.classList.contains("is-active"), true);
  assert.equal(secondary.classList.contains("is-active"), false);
  assert.equal(runtime.captionCategory.textContent, "Río y naturaleza");
  assert.equal(runtime.captionTitle.textContent, "A");
  assert.equal(runtime.intervals.length, 0);
  assert.equal(runtime.timeouts.length, 0);
});
