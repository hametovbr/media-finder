"use strict";

function focusFeedback(root) {
  const message = root.querySelector("[data-autofocus]");
  if (message) {
    message.focus();
  }
}

document.addEventListener("DOMContentLoaded", () => focusFeedback(document));
document.addEventListener("htmx:afterSwap", (event) => focusFeedback(event.detail.target));
