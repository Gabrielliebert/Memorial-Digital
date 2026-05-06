"""
Módulo de Scraping — Coleta de dados do Currículo Lattes.

Utiliza Playwright para abrir o navegador, permitir resolução
manual de CAPTCHA e extrair o HTML completo do currículo.
"""
import asyncio
import sys
from playwright.async_api import async_playwright
import config


def _avisar_captcha():
    """Toca beep, traz a janela do Chromium pra frente e avisa via console."""
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
        # Força a janela do Chromium ao primeiro plano via Win32 API.
        # Usa ctypes para evitar dependência externa (pywin32).
        _forcar_foco_chromium_windows()
    print("\n" + "=" * 60)
    print(" 🔔 RESOLVA O CAPTCHA NA JANELA DO CHROMIUM AGORA")
    print("=" * 60 + "\n")


def _forcar_foco_chromium_windows():
    """
    No Windows, busca a janela do Chromium (título contém "RESOLVA O CAPTCHA")
    e força ela ao primeiro plano via SetForegroundWindow + ShowWindow.

    Workaround: o Windows protege contra "foco-roubo", então precisamos
    "destravar" anexando à thread do foreground atual (AttachThreadInput).
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Buscar janela cujo título começa com o nosso marcador
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )
        encontrada = []

        def callback(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if "RESOLVA O CAPTCHA" in buf.value:
                        encontrada.append(hwnd)
                        return False
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)

        if not encontrada:
            return

        hwnd = encontrada[0]

        # AttachThreadInput trick para contornar proteção anti-foco-roubo
        SW_RESTORE = 9
        fg = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0

        user32.AttachThreadInput(current_thread, target_thread, True)
        if fg_thread and fg_thread != current_thread:
            user32.AttachThreadInput(fg_thread, target_thread, True)

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)

        user32.AttachThreadInput(current_thread, target_thread, False)
        if fg_thread and fg_thread != current_thread:
            user32.AttachThreadInput(fg_thread, target_thread, False)

    except Exception as e:
        print(f"[Scraper] ⚠ Não consegui forçar foco do Chromium: {e}")


async def scrape_lattes(url: str) -> str:
    """
    Abre o navegador Chromium, navega até a URL do Lattes,
    aguarda o usuário resolver o CAPTCHA e retorna o HTML da página.

    Args:
        url: URL completa do currículo Lattes.

    Returns:
        HTML bruto da página do currículo.

    Raises:
        TimeoutError: Se o CAPTCHA não for resolvido no tempo limite.
        Exception: Outros erros de navegação.
    """
    async with async_playwright() as p:
        # Argumentos para garantir que a janela apareça em primeiro plano
        # e o usuário possa resolver o CAPTCHA imediatamente
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--window-position=0,0",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"[Scraper] Abrindo URL: {url}")
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=config.PAGE_LOAD_TIMEOUT * 1000)

        # Forçar a janela do Chromium para frente (resolver CAPTCHA sem
        # ter que clicar manualmente)
        try:
            await page.bring_to_front()
        except Exception as e:
            print(f"[Scraper] ⚠ bring_to_front falhou: {e}")

        # Tentativa adicional: usar JavaScript para chamar atenção
        try:
            await page.evaluate("""() => {
                window.focus();
                document.title = '⚠️ RESOLVA O CAPTCHA — ' + document.title;
            }""")
        except Exception:
            pass

        # Aguardar resolução do CAPTCHA — detecta quando o conteúdo
        # do currículo aparece na página (elemento com dados do pesquisador)
        _avisar_captcha()

        try:
            # O Lattes mostra o nome do pesquisador em <h2 class="nome">
            # ou dentro de um elemento com a classe "title-wrapper"
            # Tenta múltiplos seletores para maior robustez
            await page.wait_for_selector(
                "h2.nome, .nome, #curriculum-header, .title-wrapper",
                timeout=config.CAPTCHA_TIMEOUT * 1000
            )
            print("[Scraper] ✓ CAPTCHA resolvido! Extraindo dados...")
        except Exception:
            # Tentativa alternativa: esperar qualquer conteúdo substancial
            await page.wait_for_selector(
                "body:has-text('Formação')",
                timeout=30_000
            )
            print("[Scraper] ✓ Página carregada (detecção alternativa).")

        # Aguardar um pouco para carregamento completo
        await page.wait_for_timeout(2000)

        # Scroll para carregar conteúdo lazy-loaded
        await _scroll_completo(page)

        # Extrair HTML completo
        html = await page.content()
        print(f"[Scraper] ✓ HTML extraído ({len(html)} caracteres)")

        await browser.close()
        return html


async def _scroll_completo(page):
    """Faz scroll até o final da página para carregar todo o conteúdo."""
    prev_height = 0
    for _ in range(10):
        curr_height = await page.evaluate("document.body.scrollHeight")
        if curr_height == prev_height:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)
        prev_height = curr_height


def coletar_lattes(url: str) -> str:
    """
    Wrapper síncrono para scrape_lattes.
    Facilita o uso em contextos não-async (Flask).
    """
    return asyncio.run(scrape_lattes(url))
