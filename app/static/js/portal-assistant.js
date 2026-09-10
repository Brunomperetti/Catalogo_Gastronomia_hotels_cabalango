(function () {
  "use strict";

  var assistant = document.querySelector("[data-cabalango-assistant]");
  if (!assistant) return;

  var trigger = assistant.querySelector(".cabalango-assistant-trigger");
  var panel = assistant.querySelector("#cabalango-assistant");
  var backdrop = assistant.querySelector("[data-assistant-backdrop]");
  var closeButton = assistant.querySelector("[data-assistant-close]");
  var firstOption = panel.querySelector(".cabalango-assistant-options a");
  var closeTimer;

  function openAssistant() {
    window.clearTimeout(closeTimer);
    panel.hidden = false;
    backdrop.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    document.body.classList.add("assistant-is-open");
    window.requestAnimationFrame(function () {
      panel.classList.add("is-visible");
      backdrop.classList.add("is-visible");
      firstOption.focus();
    });
  }

  function closeAssistant() {
    panel.classList.remove("is-visible");
    backdrop.classList.remove("is-visible");
    trigger.setAttribute("aria-expanded", "false");
    document.body.classList.remove("assistant-is-open");
    closeTimer = window.setTimeout(function () {
      panel.hidden = true;
      backdrop.hidden = true;
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220);
    trigger.focus();
  }

  trigger.addEventListener("click", openAssistant);
  closeButton.addEventListener("click", closeAssistant);
  backdrop.addEventListener("click", closeAssistant);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) closeAssistant();
  });
}());
