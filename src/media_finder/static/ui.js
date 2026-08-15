"use strict";

function focusFeedback(root) {
  const message = root.querySelector("[data-autofocus]");
  if (message) {
    message.focus();
  }
}

function bindPosterFallbacks(root) {
  root.querySelectorAll("img[data-poster]").forEach((image) => {
    if (image.complete && image.naturalWidth === 0) {
      image.remove();
      return;
    }
    image.addEventListener("error", () => image.remove(), { once: true });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  focusFeedback(document);
  bindPosterFallbacks(document);
});
document.addEventListener("htmx:afterSwap", (event) => {
  focusFeedback(event.detail.target);
  bindPosterFallbacks(event.detail.target);
});
