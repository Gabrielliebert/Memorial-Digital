"""
Configurações do Sistema de Memorial Digital.
Carrega variáveis de ambiente e define constantes do projeto.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Backend de IA ────────────────────────────────────
# Escolha qual provider usar para gerar o texto do memorial.
# Opções: "gemini" (Google, recomendado), "ollama" (local/Colab)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# ── Gemini (recomendado) ─────────────────────────────
# Tier gratuito generoso (15 req/min). Pegue chave em: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

# ── Ollama (alternativa) ─────────────────────────────
# Para uso com Colab+Ngrok ou Ollama local.
# RECOMENDADO: llama3.1:8b ou mistral:7b (NÃO use qwen3 — é reasoning model)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ── Geração ──────────────────────────────────────────
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))

# ── Flask ────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "memorial-system-dev-key-2026")
DEBUG = os.getenv("FLASK_DEBUG", "True").lower() == "true"

# ── Banco de Dados ───────────────────────────────────
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data", "memorial.db")

# ── Scraper ──────────────────────────────────────────
CAPTCHA_TIMEOUT = 120  # Segundos para resolver CAPTCHA
PAGE_LOAD_TIMEOUT = 30  # Segundos para carregamento de página

# ── Limites de prompt ────────────────────────────────
MAX_PRODUCOES_NO_PROMPT = 50
MAX_ITENS_POR_SECAO = 30

# ── Escavador (alternativa ao Lattes via Playwright) ─
# API que processa currículos Lattes e devolve JSON estruturado,
# eliminando a necessidade de scraping com CAPTCHA.
# Documentação: https://api.escavador.com/docs/
# Como obter chave: https://api.escavador.com/
ESCAVADOR_API_KEY = os.getenv("ESCAVADOR_API_KEY", "")
