/**
 * SubHero — Global JavaScript
 * ============================
 * Vanilla JS only — no jQuery, no frameworks (PRD constraint).
 * Total budget: under 5KB for this file.
 */

(function () {
  "use strict";

  // =============================================================
  // HTMX — CSRF Token Auto-injection
  // =============================================================
  document.addEventListener("DOMContentLoaded", function () {
    // Get CSRF token from cookie
    var csrfToken = getCookie("csrftoken");

    // Configure HTMX to include CSRF token in all requests
    if (typeof htmx !== "undefined") {
      document.body.addEventListener("htmx:configRequest", function (event) {
        event.detail.headers["X-CSRFToken"] = csrfToken;
      });
    }

    // Auto-dismiss messages after 5 seconds
    var messages = document.querySelectorAll("[data-message]");
    messages.forEach(function (msg) {
      setTimeout(function () {
        msg.style.opacity = "0";
        msg.style.transform = "translateY(-10px)";
        msg.style.transition = "opacity 300ms, transform 300ms";
        setTimeout(function () {
          msg.remove();
        }, 300);
      }, 5000);
    });

    // =============================================================
    // Balance Masking Controller
    // =============================================================
    var balanceToggles = document.querySelectorAll("#balance-toggle");
    var balanceAmounts = document.querySelectorAll(".balance-display-amount");
    
    if (balanceAmounts.length > 0) {
      var isHidden = localStorage.getItem("hideBalance") === "true";

      var updateBalanceUI = function (hidden) {
        balanceAmounts.forEach(function (amountEl) {
          var rawBalance = amountEl.getAttribute("data-raw-balance") || "0.00";
          if (hidden) {
            amountEl.textContent = "••••";
          } else {
            amountEl.textContent = rawBalance;
          }
        });

        balanceToggles.forEach(function (toggleBtn) {
          if (hidden) {
            toggleBtn.innerHTML = '<i data-feather="eye-off" class="w-[18px] h-[18px]"></i>';
          } else {
            toggleBtn.innerHTML = '<i data-feather="eye" class="w-[18px] h-[18px]"></i>';
          }
        });

        if (typeof feather !== "undefined") {
          feather.replace();
        }
      };

      // Apply initial state
      updateBalanceUI(isHidden);

      balanceToggles.forEach(function (toggleBtn) {
        toggleBtn.addEventListener("click", function (e) {
          e.preventDefault();
          isHidden = !isHidden;
          localStorage.setItem("hideBalance", isHidden);
          updateBalanceUI(isHidden);
        });
      });
    }
  });

  // =============================================================
  // Cookie Helper
  // =============================================================
  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      var cookies = document.cookie.split(";");
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(
            cookie.substring(name.length + 1)
          );
          break;
        }
      }
    }
    return cookieValue;
  }

  // =============================================================
  // Bottom Sheet Modal Controller
  // =============================================================
  window.openPinSheet = function (formAction) {
    var overlay = document.getElementById("pin-overlay");
    var sheet = document.getElementById("pin-sheet");
    var form = document.getElementById("pin-form");

    if (formAction) {
      form.action = formAction;
    }

    overlay.classList.add("active");
    sheet.classList.add("active");
    document.body.style.overflow = "hidden";

    // Focus first PIN box
    var firstBox = sheet.querySelector('[data-pin-box="0"]');
    if (firstBox) {
      setTimeout(function () {
        firstBox.focus();
      }, 300);
    }
  };

  window.closePinSheet = function () {
    var overlay = document.getElementById("pin-overlay");
    var sheet = document.getElementById("pin-sheet");

    if (overlay) overlay.classList.remove("active");
    if (sheet) sheet.classList.remove("active");
    document.body.style.overflow = "";

    // Clear PIN boxes
    var boxes = document.querySelectorAll("[data-pin-box]");
    boxes.forEach(function (box) {
      box.value = "";
    });

    var hiddenInput = document.getElementById("pin-hidden-input");
    if (hiddenInput) hiddenInput.value = "";

    var submitBtn = document.getElementById("pin-submit-btn");
    if (submitBtn) submitBtn.disabled = true;

    var errorEl = document.getElementById("pin-error");
    if (errorEl) errorEl.classList.add("hidden");
  };

  // =============================================================
  // Loading State on Form Submit
  // =============================================================
  document.addEventListener("submit", function (e) {
    var btn = e.target.querySelector('button[type="submit"]');
    if (btn && !btn.disabled) {
      btn.disabled = true;
      btn.classList.add("opacity-70");
      // Re-enable after 10s as safety net
      setTimeout(function () {
        btn.disabled = false;
        btn.classList.remove("opacity-70");
      }, 10000);
    }
  });
  // =============================================================
  // OTP Input Controller
  // =============================================================
  var otpContainer = document.getElementById("otp-inputs");
  if (otpContainer) {
    var otpInputs = otpContainer.querySelectorAll('input[type="text"]');
    var hiddenOtpInput = document.getElementById("hidden-otp-input");
    var otpSubmitBtn = document.getElementById("otp-submit");

    function checkOtpComplete() {
      var val = "";
      otpInputs.forEach(function (input) {
        val += input.value;
      });
      if (hiddenOtpInput) hiddenOtpInput.value = val;
      if (otpSubmitBtn) otpSubmitBtn.disabled = val.length !== 6;
    }

    otpInputs.forEach(function (input, index) {
      // Focus first empty box on click
      input.addEventListener("focus", function () {
        for (var i = 0; i < otpInputs.length; i++) {
          if (!otpInputs[i].value) {
            if (i !== index) {
              otpInputs[i].focus();
            }
            return;
          }
        }
      });

      input.addEventListener("input", function (e) {
        // Strip non-numeric
        this.value = this.value.replace(/[^0-9]/g, "");

        if (this.value) {
          if (index < otpInputs.length - 1) {
            otpInputs[index + 1].focus();
          } else {
            this.blur();
          }
        }
        checkOtpComplete();
      });

      input.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && !this.value && index > 0) {
          otpInputs[index - 1].focus();
          otpInputs[index - 1].value = "";
          checkOtpComplete();
        }
      });

      input.addEventListener("paste", function (e) {
        e.preventDefault();
        var pastedData = e.clipboardData
          .getData("text")
          .replace(/[^0-9]/g, "")
          .slice(0, 6);
        if (pastedData) {
          for (var i = 0; i < pastedData.length; i++) {
            if (otpInputs[i]) otpInputs[i].value = pastedData[i];
          }
          if (pastedData.length === 6) {
            otpInputs[5].focus();
            otpInputs[5].blur();
          } else {
            otpInputs[pastedData.length].focus();
          }
          checkOtpComplete();
        }
      });
    });

    // Auto-focus first input slightly after load
    setTimeout(function () {
      if (otpInputs.length > 0) otpInputs[0].focus();
    }, 300);
  }
})();
