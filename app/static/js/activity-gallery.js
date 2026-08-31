(function () {
  'use strict';
  var gallery = document.querySelector('[data-activity-gallery]');
  if (!gallery) return;
  var thumbs = Array.prototype.slice.call(gallery.querySelectorAll('[data-gallery-index]'));
  var images = thumbs.map(function (thumb) { return thumb.querySelector('img').src; });
  var hero = gallery.querySelector('[data-gallery-hero]');
  var lightbox = gallery.querySelector('[data-gallery-lightbox]');
  var lightboxImage = gallery.querySelector('[data-gallery-lightbox-image]');
  var counter = gallery.querySelector('[data-gallery-counter]');
  var current = 0;
  function select(index) {
    current = (index + images.length) % images.length;
    counter.textContent = (current + 1) + ' / ' + images.length;
    hero.src = images[current];
    lightboxImage.src = images[current];
    thumbs.forEach(function (thumb, i) {
      thumb.classList.toggle('is-selected', i === current);
      thumb.setAttribute('aria-pressed', i === current ? 'true' : 'false');
    });
  }
  function close() { lightbox.hidden = true; document.body.classList.remove('has-agenda-lightbox'); gallery.querySelector('[data-gallery-open]').focus(); }
  thumbs.forEach(function (thumb) { thumb.addEventListener('click', function () { select(Number(thumb.dataset.galleryIndex)); }); });
  gallery.querySelector('[data-gallery-open]').addEventListener('click', function () { lightbox.hidden = false; document.body.classList.add('has-agenda-lightbox'); gallery.querySelector('[data-gallery-close]').focus(); });
  gallery.querySelector('[data-gallery-close]').addEventListener('click', close);
  gallery.querySelector('[data-gallery-prev]').addEventListener('click', function () { select(current - 1); });
  gallery.querySelector('[data-gallery-next]').addEventListener('click', function () { select(current + 1); });
  lightbox.addEventListener('click', function (event) { if (event.target === lightbox) close(); });
  document.addEventListener('keydown', function (event) {
    if (lightbox.hidden) return;
    if (event.key === 'Escape') close();
    if (event.key === 'ArrowLeft') select(current - 1);
    if (event.key === 'ArrowRight') select(current + 1);
  });
  select(0);
}());
