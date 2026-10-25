
/* ========================================
   TRUSTVAULT - MAIN JAVASCRIPT
======================================== */

document.addEventListener("DOMContentLoaded", function () {
    // 1. Mobile navigation toggle
    const navToggle = document.querySelector(".nav-toggle");
    const navLinks = document.querySelector(".nav-links");

    if (navToggle && navLinks) {
        navToggle.addEventListener("click", function () {
            const isOpen = navLinks.classList.toggle("open");

            navToggle.setAttribute("aria-expanded", String(isOpen));
            navToggle.setAttribute(
                "aria-label",
                isOpen ? "Close navigation menu" : "Open navigation menu"
            );
        });

        // Close mobile navigation after selecting a link
        navLinks.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                navLinks.classList.remove("open");
                navToggle.setAttribute("aria-expanded", "false");
            });
        });
    }

    // 2. Automatically hide flash messages
    const flashMessages = document.querySelectorAll(
        ".flash, .alert, .flash-messages .alert"
    );

    flashMessages.forEach(function (message) {
        // Allow the user to read the message first
        window.setTimeout(function () {
            message.style.transition = "opacity 0.4s ease";
            message.style.opacity = "0";

            window.setTimeout(function () {
                if (message.parentNode) {
                    message.remove();
                }
            }, 450);
        }, 5000);
    });

    // 3. Confirm actions marked as destructive
    document.querySelectorAll("[data-confirm]").forEach(function (element) {
        element.addEventListener("click", function (event) {
            const message =
                element.getAttribute("data-confirm") ||
                "Are you sure you want to continue?";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    // 4. File upload validation
    const uploadForms = document.querySelectorAll(
        'form[data-upload-form], form[action="/upload"]'
    );

    uploadForms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const fileInput = form.querySelector(
                'input[type="file"][name="document"]'
            );

            if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
                // Let HTML required validation or the Flask route handle this
                return;
            }

            const file = fileInput.files[0];
            const allowedExtensions = ["pdf", "doc", "docx", "txt"];
            const extension = file.name.split(".").pop().toLowerCase();
            const maxSize = 5 * 1024 * 1024; // 5 MB

            if (!allowedExtensions.includes(extension)) {
                event.preventDefault();
                window.alert(
                    "Invalid file type. Please select a PDF, DOC, DOCX, or TXT file."
                );
                fileInput.focus();
                return;
            }

            if (file.size > maxSize) {
                event.preventDefault();
                window.alert("File size must not exceed 5 MB.");
                fileInput.focus();
            }
        });
    });

    // 5. Show selected file name and size
    document.querySelectorAll('input[type="file"]').forEach(function (input) {
        input.addEventListener("change", function () {
            const file = input.files && input.files[0];
            const outputId = input.getAttribute("data-file-output");
            const output = outputId
                ? document.getElementById(outputId)
                : input.parentElement.querySelector(".file-name");

            if (!output) {
                return;
            }

            if (!file) {
                output.textContent = "";
                return;
            }

            const sizeInKB = Math.max(1, Math.round(file.size / 1024));
            output.textContent = file.name + " (" + sizeInKB + " KB)";
        });
    });

    // 6. Password visibility toggle
    document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
        button.addEventListener("click", function () {
            const targetId = button.getAttribute("data-toggle-password");
            const passwordInput = document.getElementById(targetId);

            if (!passwordInput) {
                return;
            }

            const showPassword = passwordInput.type === "password";
            passwordInput.type = showPassword ? "text" : "password";

            button.textContent = showPassword ? "Hide" : "Show";
            button.setAttribute(
                "aria-label",
                showPassword ? "Hide password" : "Show password"
            );
        });
    });

    // 7. Prevent accidental double submission
    document.querySelectorAll("form[data-prevent-double-submit]").forEach(
        function (form) {
            form.addEventListener("submit", function (event) {
                if (!form.checkValidity()) {
                    return;
                }

                if (form.dataset.submitting === "true") {
                    event.preventDefault();
                    return;
                }

                form.dataset.submitting = "true";

                const submitButton = form.querySelector(
                    'button[type="submit"], input[type="submit"]'
                );

                if (submitButton) {
                    submitButton.disabled = true;

                    if (submitButton.tagName === "BUTTON") {
                        submitButton.dataset.originalText =
                            submitButton.textContent;
                        submitButton.textContent = "Please wait...";
                    }
                }
            });
        }
    );

    // 8. Search input clear button support
    document.querySelectorAll("[data-clear-target]").forEach(function (button) {
        button.addEventListener("click", function () {
            const targetId = button.getAttribute("data-clear-target");
            const target = document.getElementById(targetId);

            if (target) {
                target.value = "";
                target.focus();
            }
        });
    });

    // 9. Highlight current navigation link
    const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";

    document.querySelectorAll(".nav-links a").forEach(function (link) {
        try {
            const linkUrl = new URL(link.href, window.location.origin);
            const linkPath = linkUrl.pathname.replace(/\/+$/, "") || "/";

            if (linkPath === currentPath) {
                link.classList.add("active");
                link.setAttribute("aria-current", "page");
            }
        } catch (error) {
            // Ignore malformed navigation URLs
        }
    });

    // 10. Update character counters for text fields
    document.querySelectorAll("[data-maxlength]").forEach(function (input) {
        const maxLength = Number(input.getAttribute("data-maxlength"));
        const counterId = input.getAttribute("data-counter");
        const counter = counterId
            ? document.getElementById(counterId)
            : input.parentElement.querySelector(".character-counter");

        if (!counter || !Number.isFinite(maxLength) || maxLength <= 0) {
            return;
        }

        function updateCounter() {
            counter.textContent =
                input.value.length + " / " + maxLength + " characters";
        }

        input.setAttribute("maxlength", String(maxLength));
        input.addEventListener("input", updateCounter);
        updateCounter();
    });

    // 11. Set current year in footer, if a year element exists
    const yearElement = document.querySelector("[data-current-year]");

    if (yearElement) {
        yearElement.textContent = new Date().getFullYear();
    }
});
