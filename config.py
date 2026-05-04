"""
Configurações do Sistema de Memorial Digital.
Carrega variáveis de ambiente e define constantes do projeto.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── API ──────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GEMINI_MODEL = "qwen3:14b" # Re-aproveitaremos esta variável para indicar o modelo Ollama
GEMINI_TEMPERATURE = 0.3  # Baixa para minimizar alucinações

# ── Flask ────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "memorial-system-dev-key-2026")
DEBUG = os.getenv("FLASK_DEBUG", "True").lower() == "true"

# ── Banco de Dados ───────────────────────────────────
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data", "memorial.db")

# ── Scraper ──────────────────────────────────────────
CAPTCHA_TIMEOUT = 120  # Segundos para resolver CAPTCHA
PAGE_LOAD_TIMEOUT = 30  # Segundos para carregamento de página

# ── Gerador ──────────────────────────────────────────
MAX_PRODUCOES_NO_PROMPT = 100  # Aumentado para refletir o grande limite de contexto dos modelos atuais
MAX_ITENS_POR_SECAO = 50       # Novo limite generoso para demais seções, evitando truncamento severo
