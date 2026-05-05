"""
Módulo de Geração — Cria o texto do memorial via LLM.

Estratégia:
- Pede TEXTO PURO ao modelo (não JSON estruturado)
- Suporta múltiplos backends: Gemini API (recomendado) ou Ollama
- Prompt simples e direto: "RESUMA estes dados em N parágrafos"
- Seções estruturadas são montadas em código a partir dos dados
- Tempo verbal ajustado conforme status (ativo/memorializado)
"""
import json
import re
import time
import requests
import config

MAX_RETRIES = 3
RETRY_BASE_DELAY = 3


def gerar_memorial(dados: dict, status: str = "ativo") -> dict:
    """
    Gera o texto do memorial. SEMPRE chama a IA para criar uma síntese
    nova — não copia o resumo original. Se a IA falhar, usa fallback
    determinístico simples.

    Args:
        dados: Dicionário canônico com dados do titular.
        status: "ativo" ou "memorializado".
    """
    nome = dados.get("nome", "Pesquisador(a)")
    print(f"[Gerador] === Gerando memorial para {nome} | status={status} | provider={config.LLM_PROVIDER} ===")

    # Etapa 1: a IA gera o texto narrativo (síntese, não cópia)
    texto_principal, metadata = _gerar_narrativa_via_ia(dados, status)

    # Etapa 2: seções são sempre montadas em código (organizadas, sem alucinação)
    secoes = _montar_secoes(dados)

    # Etapa 3: título adequado ao status
    titulo = (
        f"Em memória de {nome}" if status == "memorializado"
        else f"Memorial de {nome}"
    )

    resultado = {
        "titulo": titulo,
        "texto_principal": texto_principal,
        "secoes": secoes,
        "metadata": metadata,
    }
    return resultado


# ═══════════════════════════════════════════════════════════════════
# Geração via IA (multi-backend)
# ═══════════════════════════════════════════════════════════════════

def _gerar_narrativa_via_ia(dados: dict, status: str) -> tuple[str, dict]:
    """Tenta gerar via IA. Se falhar, retorna fallback determinístico."""
    nome = dados.get("nome", "Pesquisador(a)")
    prompt = _construir_prompt_resumo(dados, status)

    print(f"[Gerador] Prompt: {len(prompt)} chars | esperando resposta da IA...")

    provider = config.LLM_PROVIDER
    try:
        if provider == "gemini":
            texto = _chamar_gemini(prompt)
            modelo = config.GEMINI_MODEL
        elif provider == "ollama":
            texto = _chamar_ollama(prompt)
            modelo = config.OLLAMA_MODEL
        else:
            raise ValueError(f"LLM_PROVIDER desconhecido: {provider}")

        texto_limpo = _sanitizar_texto(texto, nome)
        if _texto_valido(texto_limpo, nome):
            print(f"[Gerador] ✓ Texto gerado pela IA ({len(texto_limpo)} chars)")
            return texto_limpo, {
                "modelo": modelo,
                "provider": provider,
                "metodo": "ia_resumo",
                "alertas": [],
            }
        else:
            print(f"[Gerador] ⚠ Texto da IA inválido (curto demais ou sem nome). Fallback.")

    except Exception as e:
        print(f"[Gerador] ✗ Erro chamando {provider}: {e}")

    # Fallback: texto montado em código a partir dos dados
    texto_fb = _montar_texto_fallback(dados, status)
    return texto_fb, {
        "modelo": "fallback_deterministico",
        "provider": "none",
        "metodo": "estruturado_sem_ia",
        "alertas": [f"IA ({provider}) indisponível ou retornou texto inválido"],
    }


def _chamar_gemini(prompt: str) -> str:
    """Chama Gemini API REST. Tier gratuito: 15 req/min."""
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "sua_chave_aqui":
        raise ValueError(
            "GEMINI_API_KEY não configurada. Pegue uma em "
            "https://aistudio.google.com/apikey e defina no .env"
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,  # baixa: queremos formato fixo, não criatividade
            "maxOutputTokens": 80,  # ~25 palavras max — UMA frase
            "responseMimeType": "text/plain",
        },
    }

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Gemini] Tentativa {tentativa}/{MAX_RETRIES}")
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()

            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError(f"Sem candidates: {data}")

            partes = candidates[0].get("content", {}).get("parts", [])
            texto = "".join(p.get("text", "") for p in partes).strip()
            if not texto:
                raise RuntimeError("Resposta vazia do Gemini")
            return texto

        except requests.HTTPError as e:
            print(f"[Gemini] HTTP {e.response.status_code}: {e.response.text[:200]}")
            if e.response.status_code in (429, 503) and tentativa < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * tentativa)
                continue
            raise
        except Exception as e:
            print(f"[Gemini] {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * tentativa)
            else:
                raise


def _chamar_ollama(prompt: str) -> str:
    """Chama Ollama (local ou via ngrok do Colab)."""
    if not config.OLLAMA_BASE_URL:
        raise ValueError("OLLAMA_BASE_URL não configurada no .env")

    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,  # desabilita reasoning se for Qwen3/R1
        "options": {
            "temperature": config.LLM_TEMPERATURE,
            "num_ctx": 8192,
            "stop": ["</think>", "```\n\n", "\n\nUser:"],
        },
    }
    headers = {
        "ngrok-skip-browser-warning": "true",
        "Content-Type": "application/json",
    }

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Ollama] Tentativa {tentativa}/{MAX_RETRIES} ({config.OLLAMA_MODEL})")
            r = requests.post(url, json=payload, headers=headers, timeout=240)
            r.raise_for_status()
            texto = r.json().get("response", "").strip()
            if not texto:
                raise RuntimeError("Resposta vazia do Ollama")
            return texto
        except Exception as e:
            print(f"[Ollama] {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * tentativa)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════
# Prompt — pede TEXTO PURO, não JSON. Foco em SÍNTESE, não cópia.
# ═══════════════════════════════════════════════════════════════════

def _construir_prompt_resumo(dados: dict, status: str) -> str:
    """
    Prompt para resumo ULTRA enxuto: 1 frase, no máximo 2.

    Embasamento — Lopes, Maciel & Pereira (2014, "Virtual Homage to the Dead"):
    a identidade essencial em um memorial digital deve ser breve e direta,
    funcionando como "porta de entrada" para detalhes em camadas (Maciel et
    al., 2019 — progressive disclosure). Excesso de informação inicial gera
    sobrecarga cognitiva e reduz acessibilidade emocional ao memorial.

    Formato esperado: "{Nome} é/foi {profissão genérica}, atua/atuou
    principalmente na área de {área generalista — ex: Computação, Educação,
    Engenharia, Saúde}."
    """
    nome = dados.get("nome", "Pesquisador(a)")
    primeiro_nome = nome.split()[0] if nome else "X"
    dados_texto = _formatar_dados_para_prompt(dados)

    if status == "memorializado":
        verbo_ser = "foi"
        verbo_atuar = "atuou"
        exemplo = f"{nome} foi professor e pesquisador, atuou principalmente na área de Computação."
    else:
        verbo_ser = "é"
        verbo_atuar = "atua"
        exemplo = f"{nome} é professor e pesquisador, atua principalmente na área de Computação."

    prompt = f"""/no_think

Tarefa: escrever UMA ÚNICA FRASE descrevendo {nome}.

FORMATO OBRIGATÓRIO:
"{nome} {verbo_ser} [profissão], {verbo_atuar} principalmente na área de [ÁREA GENERALISTA]."

REGRAS RÍGIDAS — viole qualquer uma e a resposta será rejeitada:

1. APENAS UMA FRASE. No máximo 25 palavras. Ponto final no fim.

2. ÁREA = palavra única e GENERALISTA. Use APENAS uma destas categorias amplas:
   - Computação
   - Engenharia
   - Educação
   - Saúde
   - Ciências Humanas
   - Ciências Sociais
   - Ciências Exatas
   - Ciências Biológicas
   - Direito
   - Artes
   NÃO use sub-áreas (NÃO escreva "Interação Humano-Computador", "Engenharia
   de Software", "Educação Matemática", "Ciência da Computação"). Generalize
   sempre para a categoria ampla acima.

3. PROFISSÃO = palavra simples e clara: "professor", "pesquisador",
   "professor e pesquisador", "médico", "engenheiro", "advogado", etc.
   NÃO use cargos específicos como "Professor Adjunto IV" ou "Coordenador
   do Programa X".

4. EM PORTUGUÊS DO BRASIL. Nunca em inglês.

5. SEM MARKDOWN. Sem aspas. Sem negrito. Sem itálico.

6. NÃO acrescente NADA além da frase única. Nada de "em resumo", nada de
   "destaca-se por", nada de segunda frase.

EXEMPLO da única coisa que você deve responder:
{exemplo}

DADOS DE {nome.upper()} (use apenas para identificar a área generalista):

{dados_texto}

Responda APENAS a frase única. Nada mais."""
    return prompt


def _formatar_dados_para_prompt(dados: dict) -> str:
    """Formata os dados estruturados de forma legível para o prompt."""
    secoes = []

    if dados.get("resumo"):
        secoes.append(f"RESUMO ATUAL DO LATTES (use apenas como referência factual, NÃO copie):\n{dados['resumo']}")

    def _add_lista(titulo: str, chave: str, limite: int = None):
        valores = dados.get(chave) or []
        if not valores or isinstance(valores, str):
            if isinstance(valores, str) and valores.strip():
                secoes.append(f"{titulo}:\n{valores}")
            return
        limite = limite or config.MAX_ITENS_POR_SECAO
        linhas = []
        for item in valores[:limite]:
            if isinstance(item, dict):
                linhas.append(f"- {item.get('descricao', str(item))}")
            else:
                linhas.append(f"- {item}")
        if linhas:
            secoes.append(f"{titulo}:\n" + "\n".join(linhas))

    _add_lista("FORMAÇÃO ACADÊMICA", "formacao", 8)
    _add_lista("ATUAÇÃO PROFISSIONAL", "atuacao_profissional", 8)
    _add_lista("ÁREAS DE ATUAÇÃO", "areas_atuacao", 10)
    _add_lista("PRINCIPAIS PROJETOS", "projetos", 6)
    _add_lista("PRÊMIOS RELEVANTES", "premios", 6)
    _add_lista("ORIENTAÇÕES (resumo)", "orientacoes", 5)
    _add_lista("PRODUÇÕES SELECIONADAS", "producoes_bibliograficas", 8)

    return "\n\n".join(secoes)


# ═══════════════════════════════════════════════════════════════════
# Sanitização e validação
# ═══════════════════════════════════════════════════════════════════

def _sanitizar_texto(texto: str, nome: str) -> str:
    """Limpa o texto bruto da IA: remove markdown, thinking, ruído."""
    if not texto:
        return ""

    # Remover blocos <think>...</think> e </think> sem abertura
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    if "</think>" in texto:
        texto = texto.split("</think>", 1)[1]

    # Remover prefixos comuns de meta-comentário
    prefixos_remover = [
        r"^Aqui está[^:]*:\s*",
        r"^Segue[^:]*:\s*",
        r"^Resumo biográfico[^:]*:\s*",
        r"^Memorial[^:]*:\s*",
    ]
    for padrao in prefixos_remover:
        texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)

    # Remover code fences
    texto = re.sub(r"^```[a-z]*\s*\n?", "", texto)
    texto = re.sub(r"\n?```\s*$", "", texto)

    # Remover markdown
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)  # bold
    texto = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", texto)  # itálico
    texto = re.sub(r"^#{1,6}\s+", "", texto, flags=re.MULTILINE)  # headings
    texto = re.sub(r"`([^`]+)`", r"\1", texto)  # inline code
    texto = re.sub(r"^[\s]*[-•*]\s+", "", texto, flags=re.MULTILINE)  # bullets
    texto = re.sub(r"^[\s]*\d+[.)]\s+", "", texto, flags=re.MULTILINE)  # numerada

    # Normalizar parágrafos
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    paragrafos = [re.sub(r"\s*\n\s*", " ", p) for p in paragrafos]

    return "\n\n".join(paragrafos).strip()


def _texto_valido(texto: str, nome: str) -> bool:
    """
    Valida que o texto é UMA frase curta (15-300 chars).
    Embasamento: identidade essencial em uma sentença
    (Lopes, Maciel & Pereira, 2014).
    """
    if not texto or len(texto) < 15:
        return False
    if len(texto) > 300:  # mais que 300 chars = a IA ignorou as regras
        print(f"[Gerador] ⚠ Texto muito longo ({len(texto)} chars), max 300.")
        return False
    # Detectar texto em inglês
    marcadores_en = [" the ", " and ", " his ", " her ", " was ", " were "]
    txt_lower = " " + texto.lower() + " "
    if sum(1 for m in marcadores_en if m in txt_lower) >= 2:
        return False
    # Primeiro nome deve aparecer
    primeiro_nome = nome.split()[0] if nome else ""
    if primeiro_nome and primeiro_nome.lower() not in texto.lower():
        return False
    return True


# ═══════════════════════════════════════════════════════════════════
# Fallback determinístico (quando IA falha completamente)
# ═══════════════════════════════════════════════════════════════════

def _montar_texto_fallback(dados: dict, status: str) -> str:
    """
    Fallback determinístico: UMA frase com área generalizada.
    Embasamento: identidade essencial (Lopes, Maciel & Pereira, 2014).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    if status == "memorializado":
        verbo_ser, verbo_atuar = "foi", "atuou"
    else:
        verbo_ser, verbo_atuar = "é", "atua"

    # Tenta inferir a "grande área" a partir das áreas detalhadas
    area = _inferir_grande_area(dados)

    if area:
        return f"{nome} {verbo_ser} pesquisador(a), {verbo_atuar} principalmente na área de {area}."
    return f"{nome} {verbo_ser} pesquisador(a) e profissional acadêmico(a)."


# Mapeamento de palavras-chave → grande área (CNPq/CAPES generalizada)
GRANDES_AREAS = {
    "Computação": ["computação", "computador", "informática", "software",
                   "sistemas de informação", "ciência da computação", "ihc",
                   "interação humano", "inteligência artificial",
                   "engenharia de software", "redes", "banco de dados"],
    "Engenharia": ["engenharia", "mecânica", "elétrica", "civil", "produção",
                   "química", "materiais", "naval", "aeronáutica"],
    "Educação": ["educação", "pedagogia", "ensino", "didática", "matemática"],
    "Saúde": ["medicina", "saúde", "enfermagem", "odontologia", "farmácia",
              "fisioterapia", "psicologia clínica", "nutrição"],
    "Ciências Humanas": ["filosofia", "história", "antropologia", "sociologia",
                         "ciência política", "geografia", "teologia"],
    "Ciências Sociais Aplicadas": ["administração", "economia", "contabilidade",
                                   "comunicação", "turismo", "serviço social"],
    "Ciências Exatas": ["matemática", "física", "química", "estatística",
                        "geociências", "astronomia"],
    "Ciências Biológicas": ["biologia", "ecologia", "botânica", "zoologia",
                            "genética", "microbiologia"],
    "Direito": ["direito", "jurídico"],
    "Artes": ["artes", "música", "teatro", "dança", "cinema", "design"],
    "Linguística e Letras": ["linguística", "letras", "literatura"],
    "Ciências Agrárias": ["agronomia", "zootecnia", "veterinária", "florestal"],
}


def _inferir_grande_area(dados: dict) -> str | None:
    """Infere a grande área generalizada a partir das áreas detalhadas."""
    todas_areas_texto = []
    for chave in ("areas_atuacao", "formacao", "atuacao_profissional"):
        valores = dados.get(chave) or []
        for v in valores:
            t = v.get("descricao") if isinstance(v, dict) else str(v)
            if t:
                todas_areas_texto.append(t.lower())
    blob = " ".join(todas_areas_texto)
    if not blob:
        return None

    # Conta hits por grande área
    pontuacao = {}
    for area, keywords in GRANDES_AREAS.items():
        hits = sum(blob.count(kw) for kw in keywords)
        if hits > 0:
            pontuacao[area] = hits

    if not pontuacao:
        return None
    return max(pontuacao, key=pontuacao.get)


# ═══════════════════════════════════════════════════════════════════
# Seções estruturadas (sempre código, sem IA)
# ═══════════════════════════════════════════════════════════════════

def _montar_secoes(dados: dict) -> list[dict]:
    """Monta seções a partir dos dados, sem depender de IA."""
    secoes = []

    def _formatar_lista(itens: list, limite: int = 10) -> str:
        linhas = []
        for item in itens[:limite]:
            if isinstance(item, dict):
                texto = item.get("descricao", "").strip()
            else:
                texto = str(item).strip()
            if texto:
                linhas.append(texto)
        return "\n".join(linhas)

    mapeamento = [
        ("formacao", "Formação Acadêmica", 10),
        ("atuacao_profissional", "Atuação Profissional", 10),
        ("areas_atuacao", "Áreas de Atuação", 15),
        ("projetos", "Projetos", 10),
        ("orientacoes", "Orientações", 10),
        ("producoes_bibliograficas", "Produções Bibliográficas", 15),
        ("premios", "Prêmios e Títulos", 10),
        ("idiomas", "Idiomas", 10),
    ]

    for chave, titulo, limite in mapeamento:
        valor = dados.get(chave)
        if not valor:
            continue
        if isinstance(valor, list) and valor:
            conteudo = _formatar_lista(valor, limite)
            if conteudo:
                secoes.append({"titulo": titulo, "conteudo": conteudo})
        elif isinstance(valor, str) and valor.strip():
            secoes.append({"titulo": titulo, "conteudo": valor.strip()})

    return secoes
