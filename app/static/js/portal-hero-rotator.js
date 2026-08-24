(() => {
  const hero = document.querySelector("[data-hero-rotator]");
  const slides = hero ? [...hero.querySelectorAll(".destination-hero-slide")] : [];
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (!hero || slides.length < 2 || reduceMotion.matches) return;

  const caption = hero.querySelector("[data-hero-caption]");
  let active = 0;
  let timer;

  const showNext = () => {
    slides[active].classList.remove("is-active");
    slides[active].setAttribute("aria-hidden", "true");
    active = (active + 1) % slides.length;
    slides[active].classList.add("is-active");
    slides[active].setAttribute("aria-hidden", "false");
    if (caption) caption.textContent = slides[active].dataset.caption;
  };
  const start = () => { timer = window.setInterval(showNext, 8000); };
  const stop = () => window.clearInterval(timer);

  start();
  document.addEventListener("visibilitychange", () => {
    stop();
    if (!document.hidden) start();
  });
})();
