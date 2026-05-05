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
            "maxOutputTokens": 1500,
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
    Prompt direto e simples: "RESUMA estes dados".
    Sem JSON. Sem few-shot longo. Foco em síntese verdadeira.
    """
    nome = dados.get("nome", "Pesquisador(a)")
    dados_texto = _formatar_dados_para_prompt(dados)

    if status == "memorializado":
        instrucao_tom = (
            "Escreva no PASSADO, como tributo respeitoso a alguém que faleceu. "
            "Use 'foi', 'atuou', 'dedicou-se', 'deixou um legado'. "
            "Tom solene mas celebratório da trajetória."
        )
        verbo_principal = "foi"
    else:
        instrucao_tom = (
            "Escreva no PRESENTE para a atuação atual ('é', 'atua', 'coordena') "
            "e no PASSADO para conquistas concluídas ('formou-se', 'recebeu'). "
            "Tom respeitoso e factual, perfil profissional."
        )
        verbo_principal = "é"

    prompt = f"""/no_think

Você é um biógrafo brasileiro experiente. Sua tarefa: escrever um RESUMO BIOGRÁFICO original de {nome}.

{instrucao_tom}

REGRAS RÍGIDAS:
1. Escreva EM PORTUGUÊS DO BRASIL. Nunca em inglês.
2. NÃO COPIE o resumo original. Sintetize com SUAS PALAVRAS.
3. Estruture em 3 a 4 parágrafos curtos (50-80 palavras cada).
4. Mencione: quem {verbo_principal}, formação principal, atuação principal, áreas e contribuições mais relevantes.
5. Use APENAS fatos dos DADOS abaixo. Nunca invente datas, instituições ou trabalhos.
6. NÃO use markdown: nada de **, *, #, -, listas numeradas.
7. Apenas prosa contínua. Sem títulos de seção. Sem despedidas.
8. Comece DIRETAMENTE com o nome (ex: "{nome} {verbo_principal}...")

DADOS DE {nome.upper()}:

{dados_texto}

Agora escreva o resumo biográfico. Apenas o texto, sem comentários."""
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
    """Valida que o texto gerado é utilizável."""
    if not texto or len(texto) < 100:
        return False
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
    """Monta texto curto a partir dos dados estruturados, sem IA."""
    nome = dados.get("nome", "Pesquisador(a)")
    verbo = "foi" if status == "memorializado" else "é"

    partes = []

    # Frase de abertura
    formacao = dados.get("formacao", [])
    if formacao:
        primeira = formacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        partes.append(f"{nome} {verbo} pesquisador(a) com formação em {descr}.")
    else:
        partes.append(f"{nome} {verbo} pesquisador(a) e profissional acadêmico(a).")

    # Atuação
    atuacao = dados.get("atuacao_profissional", [])
    if atuacao:
        primeira = atuacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        v = "Atuou" if status == "memorializado" else "Atua"
        partes.append(f"{v} profissionalmente em {descr}.")

    # Áreas
    areas = dados.get("areas_atuacao", [])
    if areas:
        nomes_areas = []
        for a in areas[:5]:
            n = a.get("descricao") if isinstance(a, dict) else str(a)
            if n:
                nomes_areas.append(n)
        if nomes_areas:
            v = "tinha" if status == "memorializado" else "tem"
            partes.append(f"{v.capitalize()} atuação nas áreas de {', '.join(nomes_areas)}.")

    # Aviso honesto
    partes.append(
        "(Este texto foi montado automaticamente — recomenda-se editar "
        "manualmente para um resumo mais elaborado.)"
    )

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
