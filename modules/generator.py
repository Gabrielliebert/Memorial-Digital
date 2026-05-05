"""
Módulo de Geração — Criação do texto memorial via API Gemini.

Recebe dados estruturados do currículo e gera texto biográfico
em primeira pessoa usando engenharia de prompt robusta para
mitigar alucinações (Silva, 2024).
"""
import requests
import json
import re
import time
import config

MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # segundos


def gerar_memorial(dados: dict, status: str = "ativo") -> dict:
    """
    Gera o texto do memorial. Estratégia em camadas:

    1. Se o Lattes já tem um resumo bom (>200 chars), usa ele direto.
       Só pede para a IA AJUSTAR o tempo verbal conforme o status.
       Isso é muito mais confiável que pedir para a IA inventar.
    2. Se a IA falhar, retorna o resumo original (texto útil garantido).
    3. Se não houver resumo, monta um texto simples a partir dos dados
       estruturados (formação principal + atuação atual).

    Args:
        dados: Dicionário canônico com dados do titular.
        status: "ativo" ou "memorializado".

    Returns:
        Dicionário com titulo, texto_principal, secoes, metadata.
    """
    nome = dados.get("nome", "Pesquisador(a)")
    resumo_original = (dados.get("resumo") or "").strip()

    # Caminho A: resumo bom existe → ajusta verbo via IA, fallback = resumo direto
    if len(resumo_original) >= 200:
        texto_final, metadata = _adaptar_resumo(resumo_original, nome, status)
    # Caminho B: sem resumo → monta texto curto a partir dos dados estruturados
    else:
        texto_final = _montar_texto_estruturado(dados, status)
        metadata = {
            "modelo": "deterministico",
            "metodo": "estruturado_sem_ia",
            "alertas": [],
        }

    titulo = (
        f"Em memória de {nome}" if status == "memorializado"
        else f"Memorial de {nome}"
    )

    secoes = _montar_secoes(dados)

    resultado = {
        "titulo": titulo,
        "texto_principal": texto_final,
        "secoes": secoes,
        "metadata": metadata,
    }
    _validar_resultado(resultado, dados, metadata.get("modelo"))
    return resultado


def _adaptar_resumo(resumo: str, nome: str, status: str) -> tuple[str, dict]:
    """
    Pede para a IA APENAS ajustar o tempo verbal do resumo conforme status.
    Tarefa simples e bem definida — muito menos propensa a falha que gerar tudo.
    Se falhar, retorna o resumo original (que já é útil).
    """
    if not config.OLLAMA_BASE_URL:
        # Sem IA disponível, retorna o resumo direto
        return _ajuste_simples_verbo(resumo, status), {
            "modelo": "sem_ia",
            "metodo": "resumo_lattes_direto",
            "alertas": ["IA não configurada — usando resumo do Lattes"],
        }

    prompt = _construir_prompt_adaptacao(resumo, nome, status)
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    modelo = config.GEMINI_MODEL

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Gerador] Adaptando resumo (tentativa {tentativa}/{MAX_RETRIES})")
            payload = {
                "model": modelo,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0.2,  # baixa: queremos fidelidade
                    "num_ctx": 8192,
                    "stop": ["</think>", "```", "\n\n\n"],
                },
            }
            headers = {
                "ngrok-skip-browser-warning": "true",
                "Content-Type": "application/json",
            }
            r = requests.post(url, json=payload, headers=headers, timeout=180)
            r.raise_for_status()
            texto_bruto = r.json().get("response", "")
            texto_limpo = _strip_thinking(texto_bruto)
            texto_limpo = _limpar_markdown(texto_limpo).strip()

            # Validação mínima: precisa ter o nome e tamanho razoável
            if (nome.split()[0].lower() in texto_limpo.lower()
                    and len(texto_limpo) >= 100):
                print(f"[Gerador] ✓ Resumo adaptado com IA ({len(texto_limpo)} chars)")
                return texto_limpo, {
                    "modelo": modelo,
                    "metodo": "adaptacao_ia",
                    "alertas": [],
                }
            else:
                print(f"[Gerador] ⚠ Adaptação inválida (sem nome ou curta), retry...")

        except Exception as e:
            print(f"[Gerador] ⚠ Erro na adaptação: {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * tentativa)

    # Todas as tentativas falharam: usa resumo original com ajuste mecânico de verbo
    print("[Gerador] ✗ IA falhou — usando resumo original com ajuste mecânico")
    return _ajuste_simples_verbo(resumo, status), {
        "modelo": "fallback_deterministico",
        "metodo": "resumo_lattes_com_ajuste_verbo",
        "alertas": ["IA falhou — usando resumo do Lattes diretamente"],
    }


def _ajuste_simples_verbo(resumo: str, status: str) -> str:
    """
    Ajuste mecânico mínimo: se memorializado, troca alguns verbos no presente
    por passado. Não é perfeito mas evita "É professor titular" para alguém
    falecido. Para "ativo", retorna o resumo intacto.
    """
    if status != "memorializado":
        return resumo

    # Substituições básicas (palavra inteira, case-insensitive na primeira letra)
    substituicoes = [
        (r"\bAtualmente, é\b", "Foi"),
        (r"\bAtualmente é\b", "Foi"),
        (r"\bÉ Professor\b", "Foi Professor"),
        (r"\bÉ professor\b", "Foi professor"),
        (r"\bÉ Bolsista\b", "Foi Bolsista"),
        (r"\bÉ bolsista\b", "Foi bolsista"),
        (r"\bÉ vice-presidente\b", "Foi vice-presidente"),
        (r"\bÉ coordenador\b", "Foi coordenador"),
        (r"\bÉ coordenadora\b", "Foi coordenadora"),
        (r"\bÉ pesquisador\b", "Foi pesquisador"),
        (r"\bÉ pesquisadora\b", "Foi pesquisadora"),
        (r"\bé Professor\b", "foi Professor"),
        (r"\bé professor\b", "foi professor"),
        (r"\bé pesquisador\b", "foi pesquisador"),
        (r"\bé do Conselho\b", "foi do Conselho"),
        (r"\bSeus interesses são\b", "Seus interesses eram"),
    ]
    texto = resumo
    for padrao, troca in substituicoes:
        texto = re.sub(padrao, troca, texto)
    return texto


def _construir_prompt_adaptacao(resumo: str, nome: str, status: str) -> str:
    """Prompt focado APENAS em ajustar o tempo verbal — tarefa simples."""
    if status == "memorializado":
        instrucao = (
            "REESCREVA o texto abaixo no PASSADO (era, foi, atuou, dedicou-se), "
            "como tributo a alguém que faleceu. Mantenha TODOS os fatos exatamente "
            "iguais. Apenas mude os tempos verbais e o tom. Use 'foi' ao invés de "
            "'é', 'atuou' ao invés de 'atua', etc."
        )
    else:
        instrucao = (
            "REESCREVA o texto abaixo de forma fluida e respeitosa, mantendo "
            "TODOS os fatos exatamente iguais. Use o tempo presente para a "
            "atuação atual. Não invente nada que não esteja no texto."
        )

    return f"""/no_think

{instrucao}

REGRAS:
- Português do Brasil. Nunca inglês.
- Sem markdown (nada de **, *, #, -, listas).
- Apenas texto corrido em parágrafos.
- Não adicione fatos novos. Não remova fatos existentes.
- Responda APENAS o texto reescrito. Nada mais.

TEXTO ORIGINAL sobre {nome}:
\"\"\"
{resumo}
\"\"\"

Texto reescrito (apenas o texto, sem comentários):"""


def _montar_texto_estruturado(dados: dict, status: str) -> str:
    """
    Sem resumo? Monta um texto curto e útil a partir dos dados estruturados.
    Sempre funciona, sem depender de IA.
    """
    nome = dados.get("nome", "Pesquisador(a)")
    verbo = "foi" if status == "memorializado" else "é"

    partes = [f"{nome} {verbo} pesquisador(a) e profissional acadêmico(a)."]

    # Formação principal (a primeira é geralmente a mais alta)
    formacao = dados.get("formacao", [])
    if formacao:
        primeira = formacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        if descr:
            verbo_form = "Possuía" if status == "memorializado" else "Possui"
            partes.append(f"{verbo_form} formação: {descr}.")

    # Atuação atual ou principal
    atuacao = dados.get("atuacao_profissional", [])
    if atuacao:
        primeira = atuacao[0]
        descr = primeira.get("descricao") if isinstance(primeira, dict) else str(primeira)
        if descr:
            verbo_at = "Atuou" if status == "memorializado" else "Atua"
            partes.append(f"{verbo_at} profissionalmente: {descr}.")

    # Áreas de atuação
    areas = dados.get("areas_atuacao", [])
    if areas:
        nomes_areas = []
        for a in areas[:5]:
            n = a.get("descricao") if isinstance(a, dict) else str(a)
            if n:
                nomes_areas.append(n)
        if nomes_areas:
            verbo_a = "Suas áreas de atuação eram" if status == "memorializado" else "Suas áreas de atuação são"
            partes.append(f"{verbo_a}: {', '.join(nomes_areas)}.")

    return " ".join(partes)


def _montar_secoes(dados: dict) -> list[dict]:
    """
    Monta seções estruturadas a partir dos dados. Não depende da IA —
    apresenta os dados de forma organizada e legível.
    """
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


def _construir_prompt(dados: dict, status: str = "ativo") -> str:
    """
    Constrói o prompt otimizado, adaptado ao status do memorial.

    Status "ativo" → tempo presente, perfil profissional vivo.
    Status "memorializado" → tempo passado, tom de tributo, "deixou um legado".

    Estratégia anti-vazamento: prompt curto, exemplo few-shot, instrução
    /no_think explícita para modelos de raciocínio (Qwen3, DeepSeek R1).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    dados_completos = _formatar_dados_para_prompt(dados)

    # Tom e tempo verbal mudam conforme o status
    if status == "memorializado":
        instrucao_tom = (
            "Este é um memorial PÓSTUMO. Escreva no PASSADO, com tom de tributo "
            "respeitoso. Use expressões como 'deixou um legado', 'sua trajetória '"
            "marcou', 'será lembrado(a) por'. Foque na permanência da contribuição."
        )
        exemplo_texto = (
            "Maria Silva dedicou sua vida à pesquisa em educação matemática. "
            "Doutora pela Universidade de São Paulo, atuou como professora no "
            "Instituto de Educação por mais de duas décadas, orientando dezenas "
            "de estudantes e publicando trabalhos que se tornaram referência. "
            "Sua trajetória foi marcada pelo compromisso com a formação docente "
            "e pelo cuidado com cada aluno. O legado de Maria permanece nas "
            "pesquisas que inspirou e nas pessoas que ajudou a formar."
        )
        titulo_exemplo = "Em memória de Maria Silva"
    else:
        instrucao_tom = (
            "Este é um perfil biográfico de uma pessoa em ATIVIDADE. Escreva no "
            "PRESENTE quando descrever atuação atual e no PASSADO para fatos "
            "concluídos. Tom respeitoso e factual, sem ser fúnebre."
        )
        exemplo_texto = (
            "Maria Silva é pesquisadora dedicada à educação matemática. Doutora "
            "pela Universidade de São Paulo, atua como professora no Instituto "
            "de Educação há mais de duas décadas, orientando estudantes e "
            "publicando trabalhos de referência na área. Sua carreira tem sido "
            "marcada pelo compromisso com a formação docente e pelo cuidado com "
            "cada aluno que passa por suas mãos."
        )
        titulo_exemplo = "Memorial de Maria Silva"

    exemplo_json = json.dumps({
        "titulo": titulo_exemplo,
        "texto_principal": exemplo_texto,
        "secoes": [{
            "titulo": "Formação Acadêmica",
            "conteudo": "Doutorado em Educação pela USP (2002). Mestrado em "
                        "Matemática pela UFRJ (1995). Graduação em Licenciatura "
                        "em Matemática pela UFMG (1991).",
        }],
    }, ensure_ascii=False)

    prompt = f"""/no_think

Você é um biógrafo brasileiro. Escreva um memorial respeitoso sobre {nome}.

{instrucao_tom}

REGRAS — viole qualquer uma e a resposta será rejeitada:
1. SOMENTE português do Brasil. Nunca inglês.
2. NUNCA use markdown: nada de **, *, _, #, -, •, 1., 2., listas.
3. SEM INVENÇÃO: use apenas os DADOS abaixo. O que não está lá, omita.
4. texto_principal: prosa contínua, 3 a 5 parágrafos, terceira pessoa.
5. RESPONDA APENAS o JSON. Sem explicar. Sem ```json. Sem texto antes ou depois.
6. NÃO PENSE EM VOZ ALTA. Não escreva "Okay, I need to..." nem nada parecido.

EXEMPLO da única coisa que você deve responder (apenas o JSON):
{exemplo_json}

DADOS DE {nome.upper()}:
{dados_completos}

Responda agora APENAS o JSON do memorial. Português, sem markdown, prosa."""
    return prompt


def _formatar_dados_para_prompt(dados: dict) -> str:
    """Formata os dados estruturados em texto para o prompt."""
    secoes = []

    def _add(titulo: str, chave: str, limite: int = None):
        valores = dados.get(chave) or []
        if not valores:
            return
        limite = limite or config.MAX_ITENS_POR_SECAO
        if isinstance(valores, str):
            secoes.append(f"[{titulo}]\n{valores}")
            return
        linhas = []
        for item in valores[:limite]:
            if isinstance(item, dict):
                linhas.append(item.get("descricao", str(item)))
            else:
                linhas.append(str(item))
        if linhas:
            secoes.append(f"[{titulo}]\n" + "\n".join(linhas))

    if dados.get("resumo"):
        secoes.append(f"[RESUMO]\n{dados['resumo']}")
    _add("FORMAÇÃO ACADÊMICA", "formacao")
    _add("ATUAÇÃO PROFISSIONAL", "atuacao_profissional")
    _add("ÁREAS DE ATUAÇÃO", "areas_atuacao")
    _add("PRODUÇÕES BIBLIOGRÁFICAS", "producoes_bibliograficas",
         config.MAX_PRODUCOES_NO_PROMPT)
    _add("ORIENTAÇÕES", "orientacoes")
    _add("PROJETOS", "projetos")
    _add("PRÊMIOS E TÍTULOS", "premios")
    _add("IDIOMAS", "idiomas")

    return "\n\n".join(secoes)


def _processar_resposta(texto_bruto: str, dados: dict, status: str = "ativo") -> dict:
    """Processa a resposta bruta do LLM em dicionário estruturado e sanitizado."""
    texto = _strip_thinking(texto_bruto)

    # Limpar marcadores de código markdown
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)

    resultado = _extrair_json_valido(texto, dados, status)

    # Sanitização defensiva: remove markdown vazado mesmo se o modelo desobedeceu
    resultado["titulo"] = _limpar_markdown(resultado["titulo"])
    resultado["texto_principal"] = _sanitizar_narrativa(resultado["texto_principal"])
    for secao in resultado["secoes"]:
        secao["titulo"] = _limpar_markdown(secao.get("titulo", ""))
        secao["conteudo"] = _limpar_markdown(secao.get("conteudo", ""))

    return resultado


def _strip_thinking(texto: str) -> str:
    """
    Remove blocos de chain-of-thought de modelos de raciocínio (Qwen3, R1, QwQ).

    Trata três casos:
    1. <think>...</think> completo
    2. Apenas </think> de fechamento (modelo "esqueceu" de abrir o tag)
    3. Texto em inglês começando com "Okay,", "Let me", "I need to" (CoT sem tag)
    """
    if not texto:
        return texto
    texto = texto.strip()

    # Caso 1: bloco completo
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)

    # Caso 2: só </think> — corta tudo até o primeiro </think>
    if "</think>" in texto:
        texto = texto.split("</think>", 1)[1]

    # Caso 3: CoT em inglês sem tags. Detecta se começa com indicadores claros
    # e procura o primeiro `{` (início do JSON real).
    texto_lstripped = texto.lstrip()
    indicadores_cot = (
        "okay,", "let me", "i need to", "i'll start", "first,", "i should",
        "alright,", "i'll structure", "the user provided",
    )
    if texto_lstripped[:30].lower().startswith(indicadores_cot):
        idx = texto.find("{")
        if idx > 0:
            print(f"[Gerador] ⚠ Chain-of-thought sem tags detectado, removendo {idx} chars de prefácio")
            texto = texto[idx:]

    return texto.strip()


def _extrair_json_valido(texto: str, dados: dict, status: str) -> dict:
    """
    Tenta extrair JSON válido com as chaves esperadas. Se falhar, retorna
    um fallback estruturado com mensagem de erro clara (não despeja lixo).
    """
    nome = dados.get("nome", "Pesquisador(a)")

    # Tentativa 1: JSON puro
    candidato = _tentar_json(texto)
    if candidato and _tem_chaves_esperadas(candidato):
        return _normalizar_resultado(candidato, nome, status)

    # Tentativa 2: JSON no meio do texto
    match = re.search(r"\{[\s\S]*\}", texto)
    if match:
        candidato = _tentar_json(match.group())
        if candidato and _tem_chaves_esperadas(candidato):
            return _normalizar_resultado(candidato, nome, status)

    # Tentativa 3: JSON parseou mas com chaves erradas (camelCase, etc)
    if candidato:
        print(f"[Gerador] ⚠ JSON sem chaves esperadas. Chaves: {list(candidato.keys())}")

    # Fallback: marca claramente como falha
    print(f"[Gerador] ✗ Falha ao gerar JSON válido. Usando fallback.")
    return _fallback_resultado_estruturado(nome, status)


def _tentar_json(texto: str) -> dict | None:
    """Tenta json.loads, retorna None se falhar ou se não for dict."""
    try:
        obj = json.loads(texto)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _tem_chaves_esperadas(d: dict) -> bool:
    """JSON é considerado válido se tiver pelo menos texto_principal."""
    texto = d.get("texto_principal", "")
    return isinstance(texto, str) and len(texto.strip()) > 50


def _normalizar_resultado(d: dict, nome: str, status: str) -> dict:
    """Garante a estrutura mínima e tipos corretos."""
    titulo_default = (
        f"Em memória de {nome}" if status == "memorializado"
        else f"Memorial de {nome}"
    )
    return {
        "titulo": str(d.get("titulo") or titulo_default).strip(),
        "texto_principal": str(d.get("texto_principal") or "").strip(),
        "secoes": [
            {
                "titulo": str(s.get("titulo", "")).strip(),
                "conteudo": str(s.get("conteudo", "")).strip(),
            }
            for s in (d.get("secoes") or [])
            if isinstance(s, dict) and s.get("conteudo")
        ],
    }


def _fallback_resultado_estruturado(nome: str, status: str) -> dict:
    """
    Fallback honesto quando a IA falhou: gera memorial mínimo a partir
    dos dados estruturados, sem inventar nada e SEM despejar lixo do LLM.
    """
    titulo = (
        f"Em memória de {nome}" if status == "memorializado"
        else f"Memorial de {nome}"
    )
    if status == "memorializado":
        texto = (
            f"Este memorial preserva a memória de {nome}. A geração automática "
            f"do texto narrativo falhou nesta tentativa. Use o botão Editar "
            f"para escrever o texto manualmente, ou regenere o memorial."
        )
    else:
        texto = (
            f"Este é o perfil biográfico de {nome}. A geração automática do "
            f"texto narrativo falhou nesta tentativa. Use o botão Editar para "
            f"escrever o texto manualmente, ou regenere o memorial."
        )
    return {
        "titulo": titulo,
        "texto_principal": texto,
        "secoes": [],
        "_falha_geracao": True,
    }


def _limpar_markdown(texto: str) -> str:
    """Remove marcações de markdown comuns que vazam do output do LLM."""
    if not texto:
        return texto
    # Negrito **texto** e __texto__
    texto = re.sub(r"\*\*([^*]+)\*\*", r"\1", texto)
    texto = re.sub(r"__([^_]+)__", r"\1", texto)
    # Itálico *texto* e _texto_ (cuidado para não comer asteriscos isolados)
    texto = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", texto)
    texto = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", texto)
    # Headings ## ### no início de linha
    texto = re.sub(r"^#{1,6}\s+", "", texto, flags=re.MULTILINE)
    # Inline code `texto`
    texto = re.sub(r"`([^`]+)`", r"\1", texto)
    # Asteriscos ou underscores soltos remanescentes
    texto = texto.replace("**", "").replace("__", "")
    return texto.strip()


def _sanitizar_narrativa(texto: str) -> str:
    """
    Limpa o texto_principal: remove markdown E converte listas em prosa contínua.

    O texto_principal precisa ser narrativo. Se o modelo gerou bullets ou
    numeração, achatamos para parágrafos.
    """
    if not texto:
        return texto

    texto = _limpar_markdown(texto)

    # Remover bullets no início de linha (- item, • item, * item)
    texto = re.sub(r"^[\s]*[-•*]\s+", "", texto, flags=re.MULTILINE)
    # Remover numeração no início de linha (1. item, 2) item)
    texto = re.sub(r"^[\s]*\d+[.)]\s+", "", texto, flags=re.MULTILINE)

    # Colapsar múltiplas linhas vazias em parágrafos limpos
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    # Dentro de cada parágrafo, juntar quebras simples em espaço (vira prosa)
    paragrafos = [re.sub(r"\s*\n\s*", " ", p) for p in paragrafos]

    return "\n\n".join(paragrafos).strip()


def _detectar_idioma_estrangeiro(texto: str) -> str | None:
    """Heurística simples: detecta se o texto está predominantemente em inglês."""
    if not texto or len(texto) < 50:
        return None
    # Palavras comuns em inglês que dificilmente aparecem em texto pt-BR formal
    marcadores_en = [
        " the ", " and ", " his ", " her ", " was ", " were ", " research ",
        " professor ", " award ", " contributions ", " summary ", " professional ",
    ]
    texto_lower = " " + texto.lower() + " "
    hits = sum(1 for m in marcadores_en if m in texto_lower)
    if hits >= 4:
        return "en"
    return None


def _validar_resultado(resultado: dict, dados: dict, modelo_usado: str = None):
    """
    Validação pós-geração: detecta possíveis alucinações e idioma estrangeiro.
    Loga warnings e popula metadata.alertas (não bloqueia o resultado).
    """
    nome = dados.get("nome", "")
    texto_completo = resultado.get("texto_principal", "")
    for secao in resultado.get("secoes", []):
        texto_completo += " " + secao.get("conteudo", "")

    alertas = []

    if nome and nome.lower() not in texto_completo.lower():
        alerta = f"Nome '{nome}' não aparece no texto"
        print(f"[Gerador] ⚠ {alerta}")
        alertas.append(alerta)

    anos_texto = set(re.findall(r"\b(19\d{2}|20\d{2})\b", texto_completo))
    dados_str = json.dumps(dados, ensure_ascii=False)
    anos_dados = set(re.findall(r"\b(19\d{2}|20\d{2})\b", dados_str))

    anos_inventados = anos_texto - anos_dados
    if anos_inventados:
        alerta = f"Anos não encontrados nos dados: {sorted(anos_inventados)}"
        print(f"[Gerador] ⚠ {alerta} (possível alucinação)")
        alertas.append(alerta)

    idioma = _detectar_idioma_estrangeiro(texto_completo)
    if idioma:
        alerta = f"Texto parece estar em '{idioma}', não em português"
        print(f"[Gerador] ⚠ {alerta} — recomenda-se regenerar")
        alertas.append(alerta)

    falha = bool(resultado.pop("_falha_geracao", False))
    if falha:
        alertas.insert(0, "Geração automática falhou — texto editável manualmente")

    resultado["metadata"] = {
        "modelo": modelo_usado or config.GEMINI_MODEL,
        "temperatura": config.GEMINI_TEMPERATURE,
        "anos_validados": len(anos_inventados) == 0,
        "idioma_ok": idioma is None,
        "falha_geracao": falha,
        "alertas": alertas,
    }
