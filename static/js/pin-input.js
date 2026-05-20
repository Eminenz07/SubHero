/**
 * SubHero — PIN Input Component
 * ==============================
 * 4-box masked PIN input with auto-advance.
 * Vanilla JS — no library (PRD Section 9.4).
 * Budget: under 2KB.
 */

(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var boxes = document.querySelectorAll("[data-pin-box]");
    if (boxes.length === 0) return;

    var hiddenInput = document.getElementById("pin-hidden-input");
    var submitBtn = document.getElementById("pin-submit-btn");

    boxes.forEach(function (box, index) {
      // Only allow digits
      box.addEventListener("input", function (e) {
        var value = e.target.value.replace(/\D/g, "");
        e.target.value = value;

        if (value.length === 1 && index < boxes.length - 1) {
          boxes[index + 1].focus();
        }

        updateHiddenInput();
      });

      // Handle backspace
      box.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && !e.target.value && index > 0) {
          boxes[index - 1].focus();
          boxes[index - 1].value = "";
          updateHiddenInput();
        }
      });

      // Handle paste
      box.addEventListener("paste", function (e) {
        e.preventDefault();
        var pasted = (e.clipboardData || window.clipboardData)
          .getData("text")
          .replace(/\D/g, "")
          .substring(0, 4);

        for (var i = 0; i < pasted.length && i < boxes.length; i++) {
          boxes[i].value = pasted[i];
        }

        if (pasted.length > 0) {
          var focusIndex = Math.min(pasted.length, boxes.length - 1);
          boxes[focusIndex].focus();
        }

        updateHiddenInput();
      });

      // Select on focus for easy replacement
      box.addEventListener("focus", function () {
        e.target.select();
      });
    });

    function updateHiddenInput() {
      var pin = "";
      boxes.forEach(function (box) {
        pin += box.value;
      });

      if (hiddenInput) {
        hiddenInput.value = pin;
      }

      if (submitBtn) {
        submitBtn.disabled = pin.length !== 4;
      }
    }
  });
})();
