(() => {
  const guide = document.querySelector('.destination-guide');
  if (!guide) return;

  const reveals = guide.querySelectorAll('[data-home-reveal], .home-reveal');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  if (reducedMotion.matches || !('IntersectionObserver' in window)) {
    reveals.forEach((element) => element.classList.add('is-visible'));
    return;
  }

  guide.classList.add('home-motion-ready');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

  reveals.forEach((element) => observer.observe(element));
})();
