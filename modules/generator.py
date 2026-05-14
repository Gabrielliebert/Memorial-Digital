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
    Gera o memorial. Memorial NÃO é currículo: a IA faz curadoria.

    Estrutura:
    - texto_principal: resumo curto (1 frase) — síntese da identidade
    - destaques: 3 a 5 marcos curados pela IA (não lista completa)
    - titulo: adequado ao status

    Listas completas (formação, atuação, projetos, etc.) NÃO entram
    no memorial — quem quer carreira completa vai no Lattes.

    Args:
        dados: Dicionário canônico com dados do titular.
        status: "ativo" ou "memorializado".
    """
    nome = dados.get("nome", "Pesquisador(a)")
    print(f"[Gerador] === Gerando memorial para {nome} | status={status} | provider={config.LLM_PROVIDER} ===")

    # Etapa 1: a IA gera o resumo curto (síntese da identidade)
    texto_principal, metadata = _gerar_narrativa_via_ia(dados, status)

    # Etapa 2: a IA cura os destaques (3-5 marcos do legado)
    destaques = selecionar_destaques(dados, status)

    # Etapa 3: título adequado ao status
    titulo = (
        f"Em memória de {nome}" if status == "memorializado"
        else f"Memorial de {nome}"
    )

    resultado = {
        "titulo": titulo,
        "texto_principal": texto_principal,
        # 'secoes' (legado) → agora 'destaques' curados pela IA.
        # Para retrocompat com banco/templates antigos, mantemos a chave
        # 'secoes' nula. Templates novos usam 'destaques'.
        "secoes": [],
        "destaques": destaques,
        "metadata": metadata,
    }
    return resultado


def selecionar_destaques(dados: dict, status: str = "ativo",
                          max_destaques: int = 5) -> list[dict]:
    """
    Curadoria pela IA: seleciona os marcos mais definidores do legado.

    A premissa (feedback do orientador Prof. Cristiano Maciel): memorial
    digital NÃO é currículo. Quem quer trajetória completa visita o Lattes.
    O memorial deve apresentar o ESSENCIAL — o que define essa pessoa.

    Categorias possíveis de destaque:
    - formacao: o título acadêmico mais alto
    - atuacao: a função/instituição mais marcante
    - premio: reconhecimento mais relevante (prioridade alta — orientador
      sugeriu que prêmios são bons candidatos)
    - projeto: contribuição prática mais significativa
    - producao: obra de referência (livro, artigo seminal)
    - legado: contribuição definidora (área inovadora, instituição fundada)

    Cada destaque é: {tipo, titulo, descricao, ano?}.

    Se a IA falhar, retorna fallback determinístico (prêmios mais recentes
    + 1 formação + 1 atuação).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    dados_texto = _formatar_dados_para_prompt(dados)

    if status == "memorializado":
        instrucao_tom = "Esta é uma homenagem póstuma. Tom de tributo."
        verbo_legado = "marcou a trajetória de"
    else:
        instrucao_tom = "Este é um perfil ativo, biográfico."
        verbo_legado = "define a trajetória de"

    exemplo_json = (
        '['
        '{"tipo":"premio","titulo":"Prêmio Carreira em IHC",'
        '"descricao":"Reconhecimento da SBC pela contribuição à área","ano":"2023"},'
        '{"tipo":"projeto","titulo":"Grupo DAVI – Dados Além da Vida",'
        '"descricao":"Coordenação de grupo de pesquisa em legado digital pós-morte","ano":"2010"},'
        '{"tipo":"atuacao","titulo":"Professor Titular – UFMT",'
        '"descricao":"Atuação no Instituto de Computação","ano":""},'
        '{"tipo":"producao","titulo":"Livro \\"Legado Digital\\"",'
        '"descricao":"Obra de referência sobre dados pós-morte","ano":"2019"},'
        '{"tipo":"formacao","titulo":"Doutorado em Ciência da Computação",'
        '"descricao":"PUC-Rio","ano":"2008"}'
        ']'
    )

    prompt = f"""/no_think

Tarefa: selecionar de 3 a 5 MARCOS que melhor {verbo_legado} {nome}.

CONTEXTO: você está curando um MEMORIAL DIGITAL, não um currículo.
Quem quer a trajetória completa visita o Lattes. Aqui mostramos APENAS
o essencial — o que esta pessoa tem de mais notável.

{instrucao_tom}

REGRAS RÍGIDAS:
1. SELECIONE entre 3 e 5 destaques. Não menos, não mais.
2. Priorize: PRÊMIOS importantes + projetos/contribuições marcantes +
   o título acadêmico mais alto + 1 atuação principal.
3. NÃO liste todas as produções, todas as orientações, todas as áreas.
4. Cada destaque deve ser INDIVIDUALMENTE notável (não um item qualquer
   da carreira).
5. Use APENAS dados reais dos DADOS abaixo. Nunca invente.
6. Português do Brasil. Sem markdown. Sem aspas decorativas.
7. Cada "descricao" curta: 1 frase, no máximo 20 palavras.
8. tipo deve ser um destes valores exatos: formacao, atuacao, premio,
   projeto, producao, legado.
9. RESPONDA APENAS o JSON (array de objetos). Sem comentários.

EXEMPLO de saída válida (não copie literalmente — adapte aos dados):
{exemplo_json}

DADOS DE {nome.upper()}:

{dados_texto}

Responda APENAS o JSON array dos destaques."""

    try:
        if config.LLM_PROVIDER == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 1200,
                    "responseMimeType": "application/json",
                },
            }
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            partes = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            texto = "".join(p.get("text", "") for p in partes).strip()
        else:
            texto = _chamar_ollama(prompt)

        texto = _strip_thinking(texto)
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

        destaques_raw = json.loads(texto)
        if not isinstance(destaques_raw, list):
            raise ValueError("IA retornou não-lista")

        destaques = []
        tipos_validos = {"formacao", "atuacao", "premio", "projeto",
                         "producao", "legado"}
        for item in destaques_raw[:max_destaques]:
            if not isinstance(item, dict):
                continue
            tipo = str(item.get("tipo", "legado")).lower().strip()
            if tipo not in tipos_validos:
                tipo = "legado"
            titulo = _limpar_markdown(str(item.get("titulo", "")).strip())
            descricao = _limpar_markdown(str(item.get("descricao", "")).strip())
            ano = str(item.get("ano", "")).strip()
            if titulo and len(titulo) <= 200:
                destaques.append({
                    "tipo": tipo,
                    "titulo": titulo,
                    "descricao": descricao[:300],
                    "ano": ano[:20],
                })

        if 3 <= len(destaques) <= max_destaques:
            print(f"[Gerador] ✓ {len(destaques)} destaques curados pela IA")
            return destaques

        print(f"[Gerador] ⚠ Curadoria IA inválida ({len(destaques)} itens). Fallback.")

    except Exception as e:
        print(f"[Gerador] ✗ Erro na curadoria: {e}")

    return _destaques_fallback(dados)


def _destaques_fallback(dados: dict) -> list[dict]:
    """
    Fallback determinístico de destaques quando a IA falha.
    Pega: 1 formação principal + 1 atuação principal + até 3 prêmios.
    """
    destaques = []

    # 1 formação principal (a primeira = mais alta no Lattes)
    formacao = dados.get("formacao", [])
    if formacao:
        primeira = formacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        if descr:
            destaques.append({
                "tipo": "formacao",
                "titulo": descr[:180],
                "descricao": "",
                "ano": "",
            })

    # 1 atuação principal
    atuacao = dados.get("atuacao_profissional", [])
    if atuacao:
        primeira = atuacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        if descr:
            destaques.append({
                "tipo": "atuacao",
                "titulo": descr[:180],
                "descricao": "",
                "ano": "",
            })

    # Até 3 prêmios
    premios = dados.get("premios", [])
    for p in premios[:3]:
        descr = p.get("descricao") if isinstance(p, dict) else str(p)
        if descr:
            destaques.append({
                "tipo": "premio",
                "titulo": descr[:180],
                "descricao": "",
                "ano": "",
            })

    return destaques[:5]


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
            "maxOutputTokens": 100,  # ~25 palavras max — UMA frase
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
    Prompt para resumo ULTRA enxuto: 1 frase começando pela profissão
    (NÃO repete o nome — ele já está em destaque no header acima).

    Embasamento — Lopes, Maciel & Pereira (2014, "Virtual Homage to the Dead"):
    identidade essencial em uma sentença direta. Maciel et al. (2019) —
    progressive disclosure: detalhes vão para camadas expansíveis.

    Formato esperado: "Professor e pesquisador na área de Computação,
    atuou principalmente em ensino superior." (sem repetir nome)
    """
    nome = dados.get("nome", "Pesquisador(a)")
    primeiro_nome = nome.split()[0] if nome else "X"
    dados_texto = _formatar_dados_para_prompt(dados)

    if status == "memorializado":
        verbo_atuar = "Atuou"
        exemplo = "Professor e pesquisador na área de Computação, atuou principalmente em ensino superior e pesquisa em sistemas computacionais."
        contexto_temp = "no PASSADO (atuou, dedicou-se, contribuiu)"
    else:
        verbo_atuar = "Atua"
        exemplo = "Professor e pesquisador na área de Computação, atua principalmente em ensino superior e pesquisa em sistemas computacionais."
        contexto_temp = "no PRESENTE (atua, dedica-se, contribui)"

    prompt = f"""/no_think

Tarefa: escrever DUAS frases curtas descrevendo a trajetória profissional desta pessoa.

FORMATO OBRIGATÓRIO:
"[Profissão] na área de [ÁREA GENERALISTA], {verbo_atuar.lower()} principalmente em [foco principal de atuação]."

REGRAS — viole qualquer uma e a resposta será rejeitada:

1. NÃO COMECE com o nome da pessoa. O nome já aparece em destaque acima.
   Comece DIRETAMENTE com a profissão (ex: "Professor e pesquisador...").

2. Duas frases apenas. Máximo 50 palavras.

3. ÁREA = uma destas categorias generalistas (escolha UMA):
   Computação | Engenharia | Educação | Saúde | Direito | Artes
   Ciências Humanas | Ciências Sociais | Ciências Exatas
   Ciências Biológicas | Ciências Agrárias | Linguística e Letras

   NÃO use sub-áreas (NÃO: "Interação Humano-Computador", "IHC",
   "Engenharia de Software", "Educação Matemática"). SEMPRE generalize
   para a categoria ampla acima.

4. Verbo {contexto_temp}.

5. PROFISSÃO simples: "professor", "pesquisador", "médico", "engenheiro",
   "professor e pesquisador". NÃO use cargos como "Professor Adjunto IV".

6. Em português do Brasil. Sem markdown. Sem aspas. Sem inglês.

7. NÃO acrescente nada além da frase única. Sem "Em resumo", sem
   "destaca-se por", sem segunda frase.

EXEMPLO da única resposta válida:
{exemplo}

DADOS (use apenas para identificar área e foco):

{dados_texto}

Responda APENAS com a frase única, começando pela profissão. Nada mais."""
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
# Sugestão assistida de tributos (Monteiro et al., 2024;
# Maciel et al., 2019 — IA generativa para composição de homenagens)
# ═══════════════════════════════════════════════════════════════════

def sugerir_tributos(memorial: dict, relacao: str, n: int = 3) -> list[str]:
    """
    Pede à IA que sugira N mensagens de tributo curtas para o memorial,
    respeitando a relação informada pelo usuário (colega, ex-aluno,
    familiar, etc.) e o status do memorial (ativo/memorializado).

    Embasamento: plano de trabalho 2025/2026 — "compor mensagens de
    tributo em linguagem natural" (Monteiro). Maciel et al. (2019) —
    composição assistida que reduz fricção sem substituir a curadoria
    humana (usuário sempre edita antes de enviar).

    Args:
        memorial: dict com nome, memorial_status, etc.
        relacao: como o autor se relaciona com a pessoa
                 (ex: "colega", "ex-aluno", "familiar", "amigo")
        n: quantas sugestões gerar (default 3)

    Returns:
        Lista de strings — cada string é uma sugestão de mensagem.
        Se a IA falhar, retorna lista vazia (frontend trata).
    """
    nome = memorial.get("nome", "")
    primeiro_nome = nome.split()[0] if nome else ""
    status = memorial.get("memorial_status", "ativo")
    relacao_limpa = (relacao or "").strip().lower()[:40]

    # Tom conforme status
    if status == "memorializado":
        contexto_tom = (
            "Esta é uma mensagem em memória de alguém que faleceu. "
            "Use tom de despedida e reconhecimento, no PASSADO."
        )
    else:
        contexto_tom = (
            "Esta é uma mensagem para um perfil profissional ativo. "
            "Use tom de reconhecimento e admiração, no PRESENTE."
        )

    # Contexto sobre a pessoa (resumo curto + área se houver)
    resumo_pessoa = (memorial.get("texto_principal") or "")[:300]

    prompt = f"""/no_think

Tarefa: gerar {n} sugestões DIFERENTES de mensagens curtas de tributo
para um memorial digital.

CONTEXTO:
- Nome do(a) homenageado(a): {nome}
- Sobre a pessoa: {resumo_pessoa}
- Sua relação com {primeiro_nome}: {relacao_limpa or 'pessoa próxima'}
- Tom: {contexto_tom}

REGRAS RÍGIDAS:
1. Em português do Brasil. Nunca em inglês.
2. Cada mensagem: 1 a 3 frases. No máximo 60 palavras.
3. Mensagens DIFERENTES entre si — variar tom (formal/afetuoso/breve).
4. Não invente fatos sobre a pessoa. Use APENAS o que está no contexto.
5. Sem markdown. Sem aspas. Sem títulos.
6. Comece direto na mensagem (NÃO escreva "Mensagem 1:" nem numere).

FORMATO DE SAÍDA — separe as {n} mensagens por exatamente:
|||

Exemplo de saída para n=3:
Mensagem mais formal aqui em uma ou duas frases.|||Mensagem mais afetuosa aqui em uma ou duas frases.|||Mensagem mais breve aqui em uma frase.

Responda APENAS as {n} mensagens separadas por |||."""

    try:
        if config.LLM_PROVIDER == "gemini":
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,  # alta: queremos variação
                    "maxOutputTokens": 400,
                    "responseMimeType": "text/plain",
                },
            }
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            partes = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            texto = "".join(p.get("text", "") for p in partes).strip()
        else:
            texto = _chamar_ollama(prompt)

        # Limpar e dividir
        texto = _strip_thinking(texto)
        texto = _limpar_markdown(texto)
        sugestoes = [s.strip() for s in texto.split("|||") if s.strip()]
        # Filtra sugestões muito curtas ou muito longas
        sugestoes = [s for s in sugestoes if 20 <= len(s) <= 500]
        return sugestoes[:n]

    except Exception as e:
        print(f"[Sugerir Tributo] ✗ Erro: {e}")
        return []

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
    Valida que o texto é UMA frase curta (15-300 chars) e em português.
    O nome NÃO precisa estar no texto (agora começa pela profissão).
    Embasamento: Lopes, Maciel & Pereira (2014).
    """
    if not texto or len(texto) < 15:
        return False
    if len(texto) > 300:
        print(f"[Gerador] ⚠ Texto muito longo ({len(texto)} chars), max 300.")
        return False
    # Detectar texto em inglês
    marcadores_en = [" the ", " and ", " his ", " her ", " was ", " were "]
    txt_lower = " " + texto.lower() + " "
    if sum(1 for m in marcadores_en if m in txt_lower) >= 2:
        return False
    # Rejeita se começa com o nome (queremos começar pela profissão)
    primeiro_nome = nome.split()[0] if nome else ""
    if primeiro_nome and texto.strip().lower().startswith(primeiro_nome.lower()):
        print(f"[Gerador] ⚠ Texto começa com o nome — re-tentar")
        return False
    return True


# ═══════════════════════════════════════════════════════════════════
# Fallback determinístico (quando IA falha completamente)
# ═══════════════════════════════════════════════════════════════════

def _montar_texto_fallback(dados: dict, status: str) -> str:
    """
    Fallback determinístico: 1 frase começando pela profissão (sem nome).
    Embasamento: identidade essencial (Lopes, Maciel & Pereira, 2014).
    """
    verbo_atuar = "atuou" if status == "memorializado" else "atua"
    area = _inferir_grande_area(dados)

    if area:
        return (
            f"Profissional na área de {area}, "
            f"{verbo_atuar} em pesquisa e atividades acadêmicas."
        )
    return f"Profissional com trajetória em pesquisa e {'atuação acadêmica passada' if status == 'memorializado' else 'atuação acadêmica em curso'}."


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
    """
    Monta seções estruturadas a partir dos dados extraídos.
    Cada item é limpo (remove ruído do HTML do Lattes) e formatado
    em uma linha legível.
    """
    secoes = []

    def _limpar_item(texto: str) -> str:
        """Remove ruídos comuns do parsing do Lattes."""
        if not texto:
            return ""
        # Normalizar espaços (incluindo NBSP, tabs, múltiplos)
        texto = re.sub(r"[\xa0\t]+", " ", texto)
        texto = re.sub(r"\s{2,}", " ", texto)
        # Inserir espaço entre minúscula+maiúscula coladas (nomes próprios)
        # Ex: "DoutoradoEducação" → "Doutorado Educação"
        texto = re.sub(r"([a-záéíóúâêôãõç])([A-ZÁÉÍÓÚÂÊÔÃÕÇ])", r"\1 \2", texto)
        # Inserir espaço antes de letra maiúscula seguida de minúscula
        # quando precedida de número/parêntese (ex: "2020Doutor" → "2020 Doutor")
        texto = re.sub(r"(\d|\))([A-ZÁÉÍÓÚÂÊÔÃÕÇ])", r"\1 \2", texto)
        # Inserir quebra antes de palavras-chave que indicam novo campo
        for chave in ("Tipo:", "Nível:", "Ano:", "Ano de obtenção:",
                      "Início:", "Fim:", "Período:", "Status:",
                      "Categoria:", "Área:", "Subárea:", "Especialidade:"):
            texto = texto.replace(chave, f"\n  {chave}")
        return texto.strip()

    def _formatar_lista(itens: list, limite: int = 10) -> str:
        """Cada item vira um parágrafo limpo separado por dupla quebra."""
        linhas = []
        for item in itens[:limite]:
            if isinstance(item, dict):
                texto = item.get("descricao", "").strip()
            else:
                texto = str(item).strip()
            if texto:
                texto_limpo = _limpar_item(texto)
                if texto_limpo:
                    linhas.append(texto_limpo)
        # Cada item separado por dupla quebra para virar parágrafo no template
        return "\n\n".join(linhas)

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
            secoes.append({"titulo": titulo, "conteudo": _limpar_item(valor)})

    return secoes
