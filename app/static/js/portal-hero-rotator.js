(() => {
  const hero = document.querySelector("[data-hero-rotator]");
  const slides = hero ? [...hero.querySelectorAll(".destination-hero-slide")] : [];
  if (!hero || slides.length < 2) return;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  // The server-rendered slide is the sovereign fallback. Reduced motion must not
  // alter it, and candidate preparation must never decide whether it can stay.
  if (reduceMotion.matches) return;

  const initialSlide = hero.querySelector(".destination-hero-slide.is-active") || slides[0];
  // Be defensive if markup is ever malformed: enhancement may restore the
  // fallback, but it must never clear or hide it while candidates are pending.
  initialSlide.classList.add("is-active");
  initialSlide.setAttribute("aria-hidden", "false");
  const captionCategory = hero.querySelector("[data-hero-caption-category]");
  const captionTitle = hero.querySelector("[data-hero-caption-title]");
  const confirmedSlides = new Set([initialSlide]);
  const getRotationSlides = () => slides.filter((slide) => confirmedSlides.has(slide));
  let activeSlide = initialSlide;
  let timer;
  let transitioning = false;

  const prepareCandidate = (image) => new Promise((resolve) => {
    let settled = false;
    const finish = (loaded) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      image.removeEventListener("load", onLoad);
      image.removeEventListener("error", onError);
      resolve(loaded);
    };
    const onLoad = () => finish(image.naturalWidth > 0);
    const onError = () => finish(false);
    // A timeout means "not ready", not "broken". Do not change the slide DOM.
    const timeout = window.setTimeout(() => finish(false), 15000);

    if (image.complete) {
      finish(image.naturalWidth > 0);
      return;
    }
    image.addEventListener("load", onLoad, { once: true });
    image.addEventListener("error", onError, { once: true });
  });

  const showNext = () => {
    const orderedSlides = getRotationSlides();
    if (transitioning || orderedSlides.length < 2) return;
    transitioning = true;
    const currentIndex = orderedSlides.indexOf(activeSlide);
    const current = activeSlide;
    const next = orderedSlides[(currentIndex + 1) % orderedSlides.length];

    // The confirmed candidate fades over the current image; current stays visible
    // until the crossfade has conclusively finished.
    next.classList.remove("is-active");
    next.setAttribute("aria-hidden", "false");
    void next.offsetWidth;
    next.classList.add("is-incoming");
    // Keep the label tied to the image being revealed, rather than waiting for
    // the outgoing image to be removed at the end of the crossfade.
    if (captionCategory) captionCategory.textContent = next.dataset.captionCategory;
    if (captionTitle) captionTitle.textContent = next.dataset.captionTitle;

    let finalized = false;
    let fallback;
    const finalizeCrossfade = () => {
      if (finalized) return;
      finalized = true;
      window.clearTimeout(fallback);
      next.removeEventListener("transitionend", onTransitionEnd);
      current.classList.remove("is-active");
      current.setAttribute("aria-hidden", "true");
      next.classList.remove("is-incoming");
      next.classList.add("is-active");
      activeSlide = next;
      transitioning = false;
    };
    const onTransitionEnd = (event) => {
      if (event.target === next && event.propertyName === "opacity") finalizeCrossfade();
    };
    next.addEventListener("transitionend", onTransitionEnd);
    fallback = window.setTimeout(finalizeCrossfade, 1900);
  };

  const stop = () => {
    if (timer !== undefined) window.clearInterval(timer);
    timer = undefined;
  };
  const start = () => {
    stop();
    if (!document.hidden && getRotationSlides().length >= 2) {
      timer = window.setInterval(showNext, 3000);
    }
  };

  // Prepare future slides independently: a slow candidate cannot block a ready one.
  slides.filter((slide) => slide !== initialSlide).forEach((slide) => {
    prepareCandidate(slide).then((confirmed) => {
      if (!confirmed) return;
      confirmedSlides.add(slide);
      start();
    });
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else start();
  });
})();
