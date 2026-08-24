(() => {
  const hero = document.querySelector("[data-hero-rotator]");
  const slides = hero ? [...hero.querySelectorAll(".destination-hero-slide")] : [];
  if (!hero || slides.length < 2) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const caption = hero.querySelector("[data-hero-caption]");
  let usableSlides = [];
  let active = 0;
  let timer;
  let transitioning = false;

  const verifyImage = (image) => new Promise((resolve) => {
    const finish = (loaded) => {
      window.clearTimeout(timeout);
      image.removeEventListener("load", onLoad);
      image.removeEventListener("error", onError);
      resolve(loaded);
    };
    const decodeLoadedImage = () => {
      if (typeof image.decode !== "function") {
        finish(image.naturalWidth > 0);
        return;
      }
      image.decode()
        .then(() => finish(image.naturalWidth > 0))
        .catch(() => finish(image.naturalWidth > 0));
    };
    const onLoad = () => decodeLoadedImage();
    const onError = () => finish(false);
    const timeout = window.setTimeout(() => finish(false), 15000);

    if (image.complete) {
      if (image.naturalWidth > 0) decodeLoadedImage();
      else finish(false);
      return;
    }
    image.addEventListener("load", onLoad, { once: true });
    image.addEventListener("error", onError, { once: true });
  });

  const selectInitialSlide = () => {
    const firstValid = usableSlides[0];
    slides.forEach((slide) => {
      const selected = slide === firstValid;
      slide.classList.toggle("is-active", selected);
      slide.classList.remove("is-incoming");
      slide.setAttribute("aria-hidden", selected ? "false" : "true");
    });
    active = 0;
    if (caption && firstValid) caption.textContent = firstValid.dataset.caption;
  };

  const showNext = () => {
    if (transitioning || usableSlides.length < 2) return;
    transitioning = true;
    const current = usableSlides[active];
    const nextIndex = (active + 1) % usableSlides.length;
    const next = usableSlides[nextIndex];

    // Keep the current image rendered underneath while the next one fades in.
    next.classList.remove("is-active");
    next.setAttribute("aria-hidden", "false");
    void next.offsetWidth;
    next.classList.add("is-incoming");

    const completeCrossfade = (event) => {
      if (event.target !== next || event.propertyName !== "opacity") return;
      next.removeEventListener("transitionend", completeCrossfade);
      current.classList.remove("is-active");
      current.setAttribute("aria-hidden", "true");
      next.classList.remove("is-incoming");
      next.classList.add("is-active");
      active = nextIndex;
      transitioning = false;
      if (caption) caption.textContent = next.dataset.caption;
    };
    next.addEventListener("transitionend", completeCrossfade);
  };

  const stop = () => {
    if (timer !== undefined) window.clearInterval(timer);
    timer = undefined;
  };
  const start = () => {
    stop();
    if (!document.hidden && usableSlides.length > 1 && !reduceMotion.matches) {
      timer = window.setInterval(showNext, 8000);
    }
  };

  Promise.all(slides.map(verifyImage)).then((results) => {
    usableSlides = slides.filter((slide, index) => {
      const usable = results[index];
      slide.classList.toggle("is-unusable", !usable);
      return usable;
    });
    if (!usableSlides.length) return;
    selectInitialSlide();
    start();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else start();
  });
})();
