(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  ready(function () {
    var figures = document.querySelectorAll('.whitepaper-figure');
    if (!figures.length) return;

    var overlay = document.createElement('div');
    overlay.className = 'whitepaper-lightbox';
    overlay.setAttribute('hidden', '');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Expanded figure');
    overlay.innerHTML =
      '<div class="whitepaper-lightbox__panel">' +
      '<button type="button" class="whitepaper-lightbox__close" aria-label="Close">×</button>' +
      '<img class="whitepaper-lightbox__image" alt="" />' +
      '<p class="whitepaper-lightbox__caption"></p>' +
      '</div>';
    document.body.appendChild(overlay);

    var panel = overlay.querySelector('.whitepaper-lightbox__panel');
    var image = overlay.querySelector('.whitepaper-lightbox__image');
    var caption = overlay.querySelector('.whitepaper-lightbox__caption');
    var closeBtn = overlay.querySelector('.whitepaper-lightbox__close');
    var lastFocus = null;

    function openLightbox(img, captionText) {
      lastFocus = document.activeElement;
      image.src = img.currentSrc || img.src;
      image.alt = img.alt || '';
      caption.textContent = captionText || '';
      caption.hidden = !captionText;
      overlay.removeAttribute('hidden');
      document.body.classList.add('whitepaper-lightbox-open');
      closeBtn.focus();
    }

    function closeLightbox() {
      if (overlay.hasAttribute('hidden')) return;
      overlay.setAttribute('hidden', '');
      document.body.classList.remove('whitepaper-lightbox-open');
      image.removeAttribute('src');
      if (lastFocus && typeof lastFocus.focus === 'function') {
        lastFocus.focus();
      }
    }

    figures.forEach(function (figure) {
      var img = figure.querySelector('img');
      if (!img) return;

      img.classList.add('whitepaper-figure__zoomable');
      img.setAttribute('tabindex', '0');
      img.setAttribute('role', 'button');
      img.setAttribute('aria-label', (img.alt ? img.alt + ' — ' : '') + 'Expand image');

      var captionEl = figure.querySelector('figcaption');
      var captionText = captionEl ? captionEl.textContent.trim() : '';

      function activate(event) {
        event.preventDefault();
        openLightbox(img, captionText);
      }

      img.addEventListener('click', activate);
      img.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          activate(event);
        }
      });
    });

    closeBtn.addEventListener('click', closeLightbox);
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) closeLightbox();
    });
    panel.addEventListener('click', function (event) {
      event.stopPropagation();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeLightbox();
    });
  });
})();
