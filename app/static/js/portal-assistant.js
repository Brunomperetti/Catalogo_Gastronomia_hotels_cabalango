(function () {
  "use strict";

  var assistant = document.querySelector("[data-cabalango-assistant]");
  if (!assistant) return;

  var trigger = assistant.querySelector(".cabalango-assistant-trigger");
  var panel = assistant.querySelector("#cabalango-assistant");
  var backdrop = assistant.querySelector("[data-assistant-backdrop]");
  var closeButton = assistant.querySelector("[data-assistant-close]");
  var views = panel.querySelectorAll("[data-assistant-view]");
  var targetButtons = panel.querySelectorAll("[data-assistant-target]");
  var backButtons = panel.querySelectorAll("[data-assistant-back]");
  var firstOption = panel.querySelector('[data-assistant-view="root"] .cabalango-assistant-options button');
  var currentView = "root";
  var originatingButton = null;
  var closeTimer;

  function showView(viewName, moveFocus) {
    var selectedView = panel.querySelector('[data-assistant-view="' + viewName + '"]');
    if (!selectedView) return;
    views.forEach(function (view) {
      view.hidden = view !== selectedView;
    });
    currentView = viewName;
    panel.scrollTop = 0;
    if (moveFocus) {
      var heading = selectedView.querySelector("h3[tabindex='-1']");
      if (heading) heading.focus();
    }
  }

  function resetToRoot() {
    showView("root", false);
    originatingButton = null;
  }

  function openAssistant() {
    window.clearTimeout(closeTimer);
    resetToRoot();
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
      resetToRoot();
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220);
    trigger.focus();
  }

  targetButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      originatingButton = button;
      showView(button.getAttribute("data-assistant-target"), true);
    });
  });

  backButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var returnFocus = originatingButton;
      showView("root", false);
      originatingButton = null;
      if (returnFocus) returnFocus.focus();
    });
  });

  trigger.addEventListener("click", openAssistant);
  closeButton.addEventListener("click", closeAssistant);
  backdrop.addEventListener("click", closeAssistant);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) closeAssistant();
  });
}());
