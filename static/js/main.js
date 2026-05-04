/**
 * Sistema de Memorial Digital — JavaScript
 * Animações, interações e utilidades do frontend.
 */

document.addEventListener('DOMContentLoaded', () => {
    initFlashMessages();
    initFormValidation();
    initScrollAnimations();
});

/**
 * Auto-dismiss flash messages after 6 seconds.
 */
function initFlashMessages() {
    const msgs = document.querySelectorAll('.flash-msg');
    msgs.forEach(msg => {
        setTimeout(() => {
            msg.style.animation = 'slideOut 0.3s ease forwards';
            setTimeout(() => msg.remove(), 300);
        }, 6000);
    });
}

/**
 * Form validation & UX enhancements.
 */
function initFormValidation() {
    const form = document.getElementById('formGerar');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        const input = document.getElementById('urlLattes');
        const btn = document.getElementById('btnGerar');

        if (!input.value.trim()) {
            e.preventDefault();
            input.classList.add('input-error');
            input.focus();
            return;
        }

        // Disable button to prevent double submit
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-text">Iniciando...</span> <span class="btn-spinner"></span>';
    });

    const input = document.getElementById('urlLattes');
    if (input) {
        input.addEventListener('input', () => {
            input.classList.remove('input-error');
        });
    }
}

/**
 * Scroll-triggered fade-in animations.
 */
function initScrollAnimations() {
    const elements = document.querySelectorAll(
        '.step-card, .memorial-card, .secao-card, .memorial-list-item, .dados-card'
    );

    if (!elements.length) return;

    // Add initial hidden state
    elements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry, idx) => {
            if (entry.isIntersecting) {
                setTimeout(() => {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }, idx * 80);
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    elements.forEach(el => observer.observe(el));
}

// Add CSS for slideOut animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(30px); }
    }
    .input-error {
        border-color: var(--color-error) !important;
        box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.15) !important;
    }
    .btn-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255,255,255,0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 0.6s linear infinite;
        display: inline-block;
    }
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
`;
document.head.appendChild(style);
