(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '—';
    var total = Math.round(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    }
    return m + ':' + String(s).padStart(2, '0');
  }

  ready(function () {
    var toolbar = document.getElementById('whitepaper-listen');
    if (!toolbar) return;

    var audio = toolbar.querySelector('audio.whitepaper-audio');
    var statusEl = toolbar.querySelector('[data-listen-status]');
    if (!audio) return;

    function setStatus(msg) {
      if (statusEl) statusEl.textContent = msg;
    }

    audio.addEventListener('loadedmetadata', function () {
      setStatus('Neural narration · ' + formatTime(audio.duration));
    });
    audio.addEventListener('play', function () {
      setStatus('Playing · ' + formatTime(audio.currentTime) + ' / ' + formatTime(audio.duration));
    });
    audio.addEventListener('timeupdate', function () {
      if (!audio.paused) {
        setStatus('Playing · ' + formatTime(audio.currentTime) + ' / ' + formatTime(audio.duration));
      }
    });
    audio.addEventListener('pause', function () {
      if (audio.currentTime > 0 && !audio.ended) {
        setStatus('Paused · ' + formatTime(audio.currentTime) + ' / ' + formatTime(audio.duration));
      }
    });
    audio.addEventListener('ended', function () {
      setStatus('Finished · ' + formatTime(audio.duration));
    });
    audio.addEventListener('error', function () {
      setStatus('Audio failed to load. Try refreshing the page.');
    });

    setStatus('Neural narration — press play to listen');
  });
})();
