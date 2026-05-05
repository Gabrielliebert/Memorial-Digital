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
            "temperature": config.LLM_TEMPERATURE,
            "maxOutputTokens": 200,  # ~150 palavras max — força resumo curto
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
    Prompt para gerar um RESUMO ENXUTO (2-3 frases, ~40-60 palavras).

    Embasamento — princípio de "informação essencial primeiro" em memoriais
    digitais (Lopes, Maciel & Pereira, 2014; Maciel et al., 2019). O texto
    inicial deve apresentar a identidade essencial. Detalhes vão para seções
    expansíveis (progressive disclosure — Maciel et al., 2019).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    dados_texto = _formatar_dados_para_prompt(dados)

    if status == "memorializado":
        instrucao_tom = "Escreva no PASSADO. Tom de tributo respeitoso."
        verbo_ex = "foi"
        exemplo = (
            f"{nome} foi professor universitário e pesquisador, "
            "com atuação principal em Educação Matemática. "
            "Deixou contribuições marcantes na formação docente e "
            "na pesquisa em didática da matemática no Brasil."
        )
    else:
        instrucao_tom = "Escreva no PRESENTE para atuação atual."
        verbo_ex = "é"
        exemplo = (
            f"{nome} é professor universitário e pesquisador, "
            "com atuação principal em Interação Humano-Computador. "
            "Tem contribuições reconhecidas em legado digital pós-morte "
            "e memoriais digitais."
        )

    prompt = f"""/no_think

Tarefa: escrever um RESUMO MUITO CURTO de {nome}.

REGRAS CRÍTICAS:
1. APENAS 2 OU 3 FRASES. Total entre 40 e 70 palavras. NÃO ULTRAPASSE.
2. EM PORTUGUÊS DO BRASIL. Nunca em inglês.
3. Estrutura: (a) quem {verbo_ex}; (b) área PRINCIPAL de atuação (escolha apenas 1 ou 2, NÃO liste todas); (c) UMA contribuição/destaque mais relevante.
4. Use APENAS fatos dos DADOS. Nunca invente.
5. {instrucao_tom}
6. NÃO use markdown (sem **, *, #, -, listas).
7. Comece com o nome.
8. Texto corrido, sem títulos, sem despedidas, sem "em conclusão".

EXEMPLO de formato e tamanho esperados:
"{exemplo}"

DADOS DE {nome.upper()}:

{dados_texto}

Responda APENAS com o resumo curto (2-3 frases). Nada mais."""
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
    """Valida que o texto gerado é utilizável (resumo curto: 50-500 chars)."""
    if not texto or len(texto) < 50:
        return False
    if len(texto) > 800:  # se passou muito, IA ignorou a regra de tamanho
        print(f"[Gerador] ⚠ Texto muito longo ({len(texto)} chars). Truncando...")
        # Mantém apenas as primeiras 3 frases
        frases = re.split(r"(?<=[.!?])\s+", texto)
        return False  # rejeita e força regenerar/fallback
    # Detectar texto em inglês (heurística)
    marcadores_en = [" the ", " and ", " his ", " her ", " was ", " were "]
    txt_lower = " " + texto.lower() + " "
    if sum(1 for m in marcadores_en if m in txt_lower) >= 4:
        return False
    # Pelo menos o primeiro nome deve aparecer
    primeiro_nome = nome.split()[0] if nome else ""
    if primeiro_nome and primeiro_nome.lower() not in texto.lower():
        return False
    return True


# ═══════════════════════════════════════════════════════════════════
# Fallback determinístico (quando IA falha completamente)
# ═══════════════════════════════════════════════════════════════════

def _montar_texto_fallback(dados: dict, status: str) -> str:
    """
    Fallback determinístico: monta resumo CURTO (2-3 frases).
    Embasamento: princípio de identidade essencial em memoriais
    digitais (Lopes, Maciel & Pereira, 2014).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    verbo = "foi" if status == "memorializado" else "é"

    # Frase 1: identidade básica + área principal (apenas 1-2 áreas)
    areas = dados.get("areas_atuacao", [])
    nomes_areas = []
    for a in areas[:2]:  # apenas as 2 primeiras
        n = a.get("descricao") if isinstance(a, dict) else str(a)
        if n:
            # Remove códigos como "Grande área:", deixa só o termo principal
            n_limpo = re.sub(r"^[^:]*:\s*", "", n).strip()
            if n_limpo:
                nomes_areas.append(n_limpo)

    if nomes_areas:
        area_str = " e ".join(nomes_areas)
        frase1 = f"{nome} {verbo} pesquisador(a), com atuação principal em {area_str}."
    else:
        frase1 = f"{nome} {verbo} pesquisador(a) e profissional acadêmico(a)."

    # Frase 2: atuação ou formação principal
    partes = [frase1]
    atuacao = dados.get("atuacao_profissional", [])
    if atuacao:
        primeira = atuacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        # Pega apenas a primeira parte da descrição (instituição e cargo principal)
        descr_curta = descr.split(",")[0].strip() if descr else ""
        if descr_curta and len(descr_curta) < 200:
            v = "Atuou" if status == "memorializado" else "Atua"
            partes.append(f"{v} profissionalmente em {descr_curta}.")

    return " ".join(partes)


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
