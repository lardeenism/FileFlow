"use strict";

const themeButton = document.querySelector("#landingTheme");

function applyLandingTheme(lightMode) {
  document.body.classList.toggle("light-mode", lightMode);
  const icon = themeButton?.querySelector("span");
  if (icon) icon.textContent = lightMode ? "☾" : "☀";
  if (themeButton) {
    const target = lightMode ? "dark" : "light";
    themeButton.setAttribute("aria-label", `Switch to ${target} mode`);
    themeButton.title = `Switch to ${target} mode`;
  }
}

applyLandingTheme(localStorage.getItem("fileflow-theme") === "light");
themeButton?.addEventListener("click", () => {
  const lightMode = !document.body.classList.contains("light-mode");
  applyLandingTheme(lightMode);
  localStorage.setItem("fileflow-theme", lightMode ? "light" : "dark");
});

function initLandingParticles() {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) return null;

  const layer = document.createElement("div");
  layer.className = "landing-particles";
  layer.setAttribute("aria-hidden", "true");
  const count = window.matchMedia("(pointer: fine)").matches ? 16 : 8;
  const fragment = document.createDocumentFragment();

  for (let index = 0; index < count; index++) {
    const particle = document.createElement("i");
    particle.style.setProperty("--particle-x", `${(11 + index * 37) % 100}%`);
    particle.style.setProperty("--particle-y", `${(17 + index * 29) % 100}%`);
    particle.style.setProperty("--particle-size", `${2 + index % 3}px`);
    particle.style.setProperty("--particle-duration", `${9 + index % 5 * 2}s`);
    particle.style.setProperty("--particle-delay", `${-(index * 1.15)}s`);
    particle.style.setProperty("--particle-drift-x", `${(index % 2 ? 1 : -1) * (18 + index % 4 * 9)}px`);
    particle.style.setProperty("--particle-drift-y", `${-(35 + index % 5 * 13)}px`);
    if (index % 5 === 0) particle.classList.add("violet");
    fragment.append(particle);
  }

  layer.append(fragment);
  document.body.insertBefore(layer, document.body.firstChild);
  return layer;
}
function initPointerGlow(particleLayer) {
  const precisePointer = window.matchMedia("(pointer: fine)").matches;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!precisePointer || reducedMotion) return;

  const glow = document.createElement("div");
  glow.className = "landing-pointer-glow";
  glow.setAttribute("aria-hidden", "true");
  document.body.insertBefore(glow, document.body.firstChild);

  let currentX = window.innerWidth * 0.68;
  let currentY = window.innerHeight * 0.28;
  let targetX = currentX;
  let targetY = currentY;
  let frame = null;

  const draw = () => {
    currentX += (targetX - currentX) * 0.12;
    currentY += (targetY - currentY) * 0.12;
    glow.style.transform = `translate3d(${currentX.toFixed(1)}px,${currentY.toFixed(1)}px,0) translate(-50%,-50%)`;
    if (Math.abs(targetX - currentX) > 0.15 || Math.abs(targetY - currentY) > 0.15) {
      frame = requestAnimationFrame(draw);
    } else {
      frame = null;
    }
  };

  const requestDraw = () => {
    if (frame === null) frame = requestAnimationFrame(draw);
  };

  window.addEventListener("pointermove", event => {
    targetX = event.clientX;
    targetY = event.clientY;
    glow.classList.add("active");
    if (particleLayer) {
      const parallaxX = (event.clientX / window.innerWidth - 0.5) * -18;
      const parallaxY = (event.clientY / window.innerHeight - 0.5) * -12;
      particleLayer.style.setProperty("--parallax-x", `${parallaxX.toFixed(1)}px`);
      particleLayer.style.setProperty("--parallax-y", `${parallaxY.toFixed(1)}px`);
    }
    requestDraw();
  }, {passive: true});

  document.documentElement.addEventListener("mouseleave", () => {
    glow.classList.remove("active");
    if (particleLayer) {
      particleLayer.style.setProperty("--parallax-x", "0px");
      particleLayer.style.setProperty("--parallax-y", "0px");
    }
    targetX = window.innerWidth * 0.68;
    targetY = window.innerHeight * 0.28;
    requestDraw();
  });

  window.addEventListener("blur", () => glow.classList.remove("active"));
  glow.style.transform = `translate3d(${currentX.toFixed(1)}px,${currentY.toFixed(1)}px,0) translate(-50%,-50%)`;
}

const particleLayer = initLandingParticles();
initPointerGlow(particleLayer);
const demoButton = document.querySelector("#landingDemo");
const notice = document.querySelector("#landingNotice");
demoButton?.addEventListener("click", async () => {
  demoButton.disabled = true;
  demoButton.innerHTML = "<span>◌</span> Preparing demo…";
  notice.textContent = "Creating sample files and starting five real worker threads…";
  notice.className = "landing-notice visible";
  try {
    const response = await fetch("/api/demo/start", {method: "POST"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Demo could not start.");
    notice.textContent = data.message;
    notice.className = "landing-notice visible success";
    window.setTimeout(() => {
      if (window.FileFlowNavigation) window.FileFlowNavigation.navigate("/threads");
      else window.location.href = "/threads";
    }, 650);
  } catch (error) {
    notice.textContent = error.message;
    notice.className = "landing-notice visible error";
    demoButton.disabled = false;
    demoButton.innerHTML = "<span>▶</span> Run 5-thread demo";
  }
});
