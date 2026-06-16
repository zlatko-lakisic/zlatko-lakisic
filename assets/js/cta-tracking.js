(function () {
  'use strict';

  var measurementId = document.body && document.body.getAttribute('data-ga-id');
  var THEME_FOOTER_PATH = '/orderedlist';
  var NAVIGATION_TIMEOUT_MS = 500;

  function hasGtag() {
    return typeof gtag === 'function';
  }

  function init() {
    if (!hasGtag()) {
      return;
    }

    document.addEventListener('click', onDocumentClick);
  }

  function onDocumentClick(event) {
    var anchor = event.target.closest('a[href]');
    if (!anchor || !anchor.closest('.wrapper')) {
      return;
    }

    if (isThemeFooterLink(anchor)) {
      return;
    }

    var href = anchor.getAttribute('href');
    if (!href || href === '#') {
      return;
    }

    var meta = buildEventMeta(anchor, href);

    if (shouldDeferNavigation(event, anchor, href)) {
      event.preventDefault();
      sendEvent(meta, function () {
        window.location.assign(anchor.href);
      });
      return;
    }

    sendEvent(meta);
  }

  function sendEvent(meta, onComplete) {
    var payload = {
      transport_type: 'beacon',
      cta_type: meta.cta_type,
      link_url: meta.link_url,
      link_text: meta.link_text,
      link_section: meta.link_section,
      page_path: meta.page_path,
      page_title: meta.page_title
    };

    if (measurementId) {
      payload.send_to = measurementId;
    }

    var completed = false;

    function finish() {
      if (completed) {
        return;
      }

      completed = true;

      if (typeof onComplete === 'function') {
        onComplete();
      }
    }

    if (typeof onComplete === 'function') {
      payload.event_callback = finish;
      window.setTimeout(finish, NAVIGATION_TIMEOUT_MS);
    }

    gtag('event', 'cta_click', payload);
  }

  function shouldDeferNavigation(event, anchor, href) {
    if (event.defaultPrevented) {
      return false;
    }

    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return false;
    }

    if (anchor.target && anchor.target.toLowerCase() === '_blank') {
      return false;
    }

    if (href.indexOf('mailto:') === 0 || href.indexOf('tel:') === 0) {
      return false;
    }

    if (href.charAt(0) === '#') {
      return false;
    }

    return true;
  }

  function isThemeFooterLink(anchor) {
    if (!anchor.closest('footer')) {
      return false;
    }

    try {
      var url = new URL(anchor.href, window.location.href);
      return url.hostname === 'github.com' && url.pathname === THEME_FOOTER_PATH;
    } catch (error) {
      return false;
    }
  }

  function buildEventMeta(anchor, href) {
    var linkText = normalizeText(
      anchor.getAttribute('aria-label') || anchor.textContent || ''
    );

    var absoluteUrl;
    try {
      absoluteUrl = new URL(href, window.location.href).href;
    } catch (error) {
      return baseParams('unknown', href, linkText, anchor);
    }

    var url;
    try {
      url = new URL(absoluteUrl);
    } catch (error) {
      return baseParams('unknown', absoluteUrl, linkText, anchor);
    }

    if (url.protocol === 'mailto:') {
      return baseParams('email', absoluteUrl, linkText || url.pathname, anchor);
    }

    if (url.protocol === 'tel:') {
      return baseParams('phone', absoluteUrl, linkText || url.pathname, anchor);
    }

    if (anchor.closest('.sidebar-connect')) {
      return baseParams(getSidebarType(anchor, url), absoluteUrl, linkText, anchor);
    }

    if (anchor.closest('header')) {
      if (url.hostname.indexOf('github.com') !== -1) {
        return baseParams('github_profile', absoluteUrl, linkText, anchor);
      }

      if (isHomeLink(url)) {
        return baseParams('home', absoluteUrl, linkText, anchor);
      }
    }

    if (url.hostname.indexOf('linkedin.com') !== -1) {
      return baseParams('linkedin', absoluteUrl, linkText, anchor);
    }

    if (url.hostname.indexOf('orcid.org') !== -1) {
      return baseParams('orcid', absoluteUrl, linkText, anchor);
    }

    if (url.hostname.indexOf('omegacms.io') !== -1) {
      return baseParams('omega_cms', absoluteUrl, linkText, anchor);
    }

    if (url.hostname.indexOf('github.com') !== -1) {
      return baseParams(getGithubType(url), absoluteUrl, linkText, anchor);
    }

    if (isInternal(url)) {
      return baseParams(
        url.hash ? 'internal_anchor' : 'internal_page',
        absoluteUrl,
        linkText,
        anchor
      );
    }

    return baseParams('outbound', absoluteUrl, linkText, anchor);
  }

  function baseParams(ctaType, linkUrl, linkText, anchor) {
    return {
      cta_type: ctaType,
      link_url: linkUrl,
      link_text: linkText,
      link_section: getLinkSection(anchor),
      page_path: window.location.pathname,
      page_title: document.title
    };
  }

  function getSidebarType(anchor, url) {
    if (url.protocol === 'mailto:') {
      return 'email';
    }

    if (url.protocol === 'tel:') {
      return 'phone';
    }

    if (url.hostname.indexOf('linkedin.com') !== -1) {
      return 'linkedin';
    }

    if (url.hostname.indexOf('github.com') !== -1) {
      return 'github';
    }

    if (url.hostname.indexOf('orcid.org') !== -1) {
      return 'orcid';
    }

    if (url.pathname.indexOf('Technical-Strategy') !== -1) {
      return 'cv';
    }

    if (url.pathname.indexOf('Recommendations') !== -1) {
      return 'recommendations';
    }

    return 'sidebar';
  }

  function getGithubType(url) {
    var segments = url.pathname.split('/').filter(Boolean);

    if (segments.length >= 2) {
      return 'github_repo';
    }

    return 'github_profile';
  }

  function isInternal(url) {
    return url.origin === window.location.origin;
  }

  function isHomeLink(url) {
    var path = url.pathname.replace(/\/index\.html$/, '').replace(/\/$/, '') || '/';
    var currentPath = window.location.pathname.replace(/\/index\.html$/, '').replace(/\/$/, '') || '/';

    return path === currentPath || path === '/zlatko-lakisic' || path === '/';
  }

  function getLinkSection(anchor) {
    if (anchor.closest('.sidebar-connect')) {
      return 'sidebar';
    }

    if (anchor.closest('header')) {
      return 'header';
    }

    if (anchor.closest('footer')) {
      return 'footer';
    }

    if (anchor.closest('table')) {
      return 'table';
    }

    return nearestSectionId(anchor);
  }

  function nearestSectionId(anchor) {
    var section = anchor.closest('section');
    if (!section) {
      return 'content';
    }

    var headings = section.querySelectorAll('h2[id], h3[id]');
    if (!headings.length) {
      return 'content';
    }

    var anchorTop = anchor.getBoundingClientRect().top;
    var current = 'top';

    for (var i = 0; i < headings.length; i++) {
      if (headings[i].getBoundingClientRect().top <= anchorTop + 5) {
        current = headings[i].id;
      }
    }

    return current;
  }

  function normalizeText(text) {
    var normalized = text.replace(/\s+/g, ' ').trim();

    if (normalized.length > 120) {
      return normalized.substring(0, 117) + '...';
    }

    return normalized;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
