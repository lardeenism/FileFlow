"use strict";

(() => {
  const body = document.body;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let navigationStarted = false;

  const loader = document.createElement("div");
  loader.className = "navigation-loader";
  loader.setAttribute("aria-hidden", "true");
  loader.innerHTML = `
    <div class="navigation-loader-card" role="status" aria-live="polite">
      <span class="navigation-loader-visual" aria-hidden="true">
        <span class="navigation-loader-track"></span>
        <span class="navigation-loader-logo"><i></i><i></i><i></i></span>
      </span>
      <strong>FileFlow</strong>
      <small>LOADING SYSTEM</small>
    </div>`;
  body.append(loader);

  function navigate(destination) {
    if (navigationStarted) return;
    navigationStarted = true;
    loader.setAttribute("aria-hidden", "false");
    body.classList.add("page-leaving");
    body.setAttribute("aria-busy", "true");
    window.setTimeout(() => window.location.assign(destination), reducedMotion ? 0 : 60);
  }

  window.FileFlowNavigation = {navigate};

  requestAnimationFrame(() => body.classList.add("page-mounted"));

  // Application pages render immediately; only the long landing page reveals sections on scroll.
  const revealTargets = body.matches(".landing-page")
    ? document.querySelectorAll(".landing-metrics, .landing-section, .landing-final")
    : [];

  revealTargets.forEach((element, index) => {
    element.classList.add("reveal-on-scroll");
    element.style.setProperty("--reveal-order", String(index));
  });

  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealTargets.forEach(element => element.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, {threshold: 0.08, rootMargin: "0px 0px -35px"});
    revealTargets.forEach(element => observer.observe(element));
  }

  document.addEventListener("click", event => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target === "_blank" || link.hasAttribute("download") || link.dataset.noTransition !== undefined) return;

    const destination = new URL(link.href, window.location.href);
    if (destination.origin !== window.location.origin || !["http:", "https:"].includes(destination.protocol)) return;

    const sameDocument = destination.pathname === window.location.pathname && destination.search === window.location.search;
    if (sameDocument && destination.hash) {
      const target = document.querySelector(destination.hash);
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({behavior: reducedMotion ? "auto" : "smooth", block: "start"});
      history.pushState(null, "", destination.hash);
      return;
    }

    // File responses and API endpoints should begin immediately without fading the page.
    if (destination.pathname.startsWith("/api/") || navigationStarted) return;

    event.preventDefault();
    navigate(destination.href);
  });

  window.addEventListener("pageshow", () => {
    navigationStarted = false;
    body.classList.remove("page-leaving");
    body.removeAttribute("aria-busy");
    loader.setAttribute("aria-hidden", "true");
  });
})();
