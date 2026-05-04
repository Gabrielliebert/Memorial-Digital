/**
 * Sistema de Memorial Digital — JavaScript
 * Animações, interações e utilidades do frontend.
 */

document.addEventListener('DOMContentLoaded', () => {
    initFlashMessages();
    initFormValidation();
    initScrollAnimations();
    initParticles();
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

        btn.disabled = true;
        btn.innerHTML = '<span class="btn-text">Iniciando...</span> <span class="btn-spinner"></span>';
    });

    const input = document.getElementById('urlLattes');
    if (input) {
        input.addEventListener('input', () => input.classList.remove('input-error'));
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
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

    elements.forEach(el => observer.observe(el));
}

/**
 * Canvas particle animation for background.
 */
function initParticles() {
    const container = document.getElementById('bgParticles');
    if (!container) return;

    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
    container.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    let W, H, particles;

    const PARTICLE_COUNT = 60;
    const ACCENT = [139, 124, 245]; // --accent-primary rgb

    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = Math.max(document.body.scrollHeight, window.innerHeight);
    }

    function createParticle() {
        return {
            x: Math.random() * W,
            y: Math.random() * H,
            r: Math.random() * 1.8 + 0.4,
            opacity: Math.random() * 0.35 + 0.05,
            vx: (Math.random() - 0.5) * 0.25,
            vy: (Math.random() - 0.5) * 0.25,
        };
    }

    function init() {
        resize();
        particles = Array.from({ length: PARTICLE_COUNT }, createParticle);
    }

    function draw() {
        ctx.clearRect(0, 0, W, H);
        particles.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${ACCENT[0]},${ACCENT[1]},${ACCENT[2]},${p.opacity})`;
            ctx.fill();

            p.x += p.vx;
            p.y += p.vy;

            if (p.x < 0) p.x = W;
            if (p.x > W) p.x = 0;
            if (p.y < 0) p.y = H;
            if (p.y > H) p.y = 0;
        });
        requestAnimationFrame(draw);
    }

    window.addEventListener('resize', () => { resize(); });
    init();
    draw();
}

// CSS dinâmico para animações inline
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
