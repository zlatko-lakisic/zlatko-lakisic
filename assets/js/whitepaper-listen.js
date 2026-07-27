(function () {
  'use strict';

  var SUPPORTED = typeof window !== 'undefined' && 'speechSynthesis' in window;

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function textFrom(el) {
    if (!el) return '';
    var clone = el.cloneNode(true);
    clone.querySelectorAll('script, style, .whitepaper-toolbar, .whitepaper-skip-listen').forEach(function (n) {
      n.remove();
    });
    return (clone.innerText || clone.textContent || '')
      .replace(/\s+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  function chunkText(text, maxLen) {
    var chunks = [];
    var remaining = text;
    maxLen = maxLen || 1800;
    while (remaining.length > maxLen) {
      var slice = remaining.slice(0, maxLen);
      var breakAt = Math.max(
        slice.lastIndexOf('. '),
        slice.lastIndexOf('? '),
        slice.lastIndexOf('! '),
        slice.lastIndexOf('\n')
      );
      if (breakAt < maxLen * 0.4) breakAt = maxLen;
      else breakAt += 1;
      chunks.push(remaining.slice(0, breakAt).trim());
      remaining = remaining.slice(breakAt).trim();
    }
    if (remaining) chunks.push(remaining);
    return chunks.filter(Boolean);
  }

  ready(function () {
    var toolbar = document.getElementById('whitepaper-listen');
    var content = document.getElementById('whitepaper-content');
    if (!toolbar || !content) return;

    var playBtn = toolbar.querySelector('[data-listen-play]');
    var pauseBtn = toolbar.querySelector('[data-listen-pause]');
    var stopBtn = toolbar.querySelector('[data-listen-stop]');
    var statusEl = toolbar.querySelector('[data-listen-status]');

    if (!SUPPORTED) {
      toolbar.classList.add('is-unsupported');
      if (statusEl) {
        statusEl.textContent = 'Listening is not supported in this browser. Download the PDF instead.';
      }
      if (playBtn) playBtn.disabled = true;
      if (pauseBtn) pauseBtn.disabled = true;
      if (stopBtn) stopBtn.disabled = true;
      return;
    }

    var synth = window.speechSynthesis;
    var chunks = [];
    var index = 0;
    var paused = false;
    var speaking = false;

    function setStatus(msg) {
      if (statusEl) statusEl.textContent = msg;
    }

    function setPlaying(isPlaying, isPaused) {
      speaking = isPlaying;
      paused = !!isPaused;
      toolbar.classList.toggle('is-playing', isPlaying && !isPaused);
      toolbar.classList.toggle('is-paused', isPlaying && isPaused);
      if (playBtn) playBtn.disabled = isPlaying && !isPaused;
      if (pauseBtn) pauseBtn.disabled = !isPlaying || isPaused;
      if (stopBtn) stopBtn.disabled = !isPlaying && !isPaused;
    }

    function speakNext() {
      if (index >= chunks.length) {
        setPlaying(false, false);
        setStatus('Finished');
        return;
      }
      var utter = new SpeechSynthesisUtterance(chunks[index]);
      utter.rate = 1;
      utter.pitch = 1;
      utter.onend = function () {
        index += 1;
        if (!paused) speakNext();
      };
      utter.onerror = function () {
        setPlaying(false, false);
        setStatus('Playback interrupted');
      };
      setStatus('Playing section ' + (index + 1) + ' of ' + chunks.length);
      synth.speak(utter);
    }

    function start() {
      synth.cancel();
      chunks = chunkText(textFrom(content));
      if (!chunks.length) {
        setStatus('Nothing to read on this page.');
        return;
      }
      index = 0;
      paused = false;
      setPlaying(true, false);
      speakNext();
    }

    function pause() {
      if (!speaking) return;
      synth.pause();
      paused = true;
      setPlaying(true, true);
      setStatus('Paused');
    }

    function resume() {
      if (!paused) return;
      synth.resume();
      paused = false;
      setPlaying(true, false);
      setStatus('Playing section ' + (index + 1) + ' of ' + chunks.length);
    }

    function stop() {
      synth.cancel();
      chunks = [];
      index = 0;
      setPlaying(false, false);
      setStatus('Stopped');
    }

    if (playBtn) {
      playBtn.addEventListener('click', function () {
        if (paused) resume();
        else start();
      });
    }
    if (pauseBtn) pauseBtn.addEventListener('click', pause);
    if (stopBtn) stopBtn.addEventListener('click', stop);

    window.addEventListener('beforeunload', function () {
      synth.cancel();
    });

    setPlaying(false, false);
    setStatus('Ready — uses your browser’s built-in voice');
  });
})();
