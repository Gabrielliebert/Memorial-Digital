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


def gerar_memorial(dados: dict) -> dict:
    """
    Gera o texto do memorial digital a partir dos dados do currículo.

    Args:
        dados: Dicionário com dados estruturados do pesquisador.

    Returns:
        Dicionário com:
            - "titulo": título do memorial
            - "texto_principal": narrativa em primeira pessoa
            - "secoes": seções adicionais estruturadas
            - "metadata": informações sobre a geração
    """
    if not config.OLLAMA_BASE_URL:
        raise ValueError(
            "URL base do Ollama não configurada. "
            "Defina OLLAMA_BASE_URL no arquivo .env apontando pro Ngrok/Localtunnel."
        )

    prompt = _construir_prompt(dados)
    print(f"[Gerador] Tamanho do prompt: {len(prompt)} caracteres")

    texto_bruto = None
    modelo_usado = config.GEMINI_MODEL
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Gerador] Tentativa {tentativa}/{MAX_RETRIES} via Ollama no Colab ({modelo_usado})...")
            
            payload = {
                "model": modelo_usado,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": config.GEMINI_TEMPERATURE,
                    "num_ctx": 16384 # Qwen suporta longo contexto
                }
            }
            
            headers = {
                "ngrok-skip-browser-warning": "true",
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=300) # 5 min timeout pois inferência T4 com contexto grande é lenta
            response.raise_for_status()
            
            resultado_api = response.json()
            texto_bruto = resultado_api.get("response", "")
            
            print(f"[Gerador] ✓ Resposta recebida ({len(texto_bruto)} caracteres)")
            break
            
        except Exception as e:
            print(f"[Gerador] ⚠ Erro ao conectar com Ollama remoto: {e}")
            if tentativa < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * tentativa
                print(f"[Gerador] Aguardando {delay}s antes de tentar novamente...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Falha ao gerar memorial: {e}")

    if not texto_bruto:
        raise RuntimeError("Não foi possível gerar texto. Resposta vazia recebida.")

    # Processar resposta
    resultado = _processar_resposta(texto_bruto, dados)

    # Validar contra alucinações
    _validar_resultado(resultado, dados, modelo_usado)

    return resultado


def _construir_prompt(dados: dict) -> str:
    """
    Constrói o prompt otimizado para geração do memorial.

    Estratégia: prompt curto e enfático, com exemplo few-shot, focado em
    narrativa em prosa contínua. Diretrizes baseadas em Maciel et al. (2019)
    sobre memoriais digitais (tom respeitoso, sem fabulação, contexto cultural).
    """
    nome = dados.get("nome", "Pesquisador(a)")
    dados_completos = _formatar_dados_para_prompt(dados)

    # Few-shot example: mostra ao modelo o formato exato esperado.
    exemplo_json = (
        '{"titulo":"Memorial de Maria Silva",'
        '"texto_principal":"Maria Silva construiu uma trajetória dedicada à '
        'pesquisa em educação matemática. Doutora pela Universidade de São Paulo, '
        'atuou como professora no Instituto de Educação por mais de duas décadas, '
        'orientando dezenas de estudantes e publicando trabalhos que se tornaram '
        'referência na área. Sua carreira foi marcada pelo compromisso com a '
        'formação docente e pelo cuidado com cada aluno que passou por suas '
        'mãos. O legado de Maria permanece nas pesquisas que inspirou e nas '
        'pessoas que ajudou a formar.",'
        '"secoes":[{"titulo":"Formação Acadêmica","conteudo":"Doutorado em '
        'Educação pela USP (2002). Mestrado em Matemática pela UFRJ (1995). '
        'Graduação em Licenciatura em Matemática pela UFMG (1991)."}]}'
    )

    prompt = f"""Você é um biógrafo brasileiro escrevendo um memorial respeitoso sobre {nome}.

REGRAS CRÍTICAS — sua resposta será REJEITADA se violar qualquer uma:
1. IDIOMA: escreva SOMENTE em português do Brasil. Nunca em inglês.
2. SEM MARKDOWN: nunca use **, *, _, #, -, •, 1., 2. no campo texto_principal.
3. SEM INVENÇÃO: use apenas fatos dos DADOS abaixo. Se algo não está lá, não mencione.
4. NARRATIVA: texto_principal deve ser prosa contínua (3 a 5 parágrafos), em terceira pessoa.
5. JSON PURO: responda apenas o JSON, sem ```json, sem comentários.

EXEMPLO de resposta correta:
{exemplo_json}

DADOS DE {nome.upper()}:
{dados_completos}

Agora escreva o JSON do memorial. Lembre-se: português, sem markdown, prosa contínua."""
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


def _processar_resposta(texto_bruto: str, dados: dict) -> dict:
    """Processa a resposta bruta do LLM em dicionário estruturado e sanitizado."""
    texto = texto_bruto.strip()

    # Remover blocos de raciocínio (<think>...</think>) de modelos R1/QwQ
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()

    # Limpar marcadores de código markdown
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)

    try:
        resultado = json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try:
                resultado = json.loads(match.group())
            except json.JSONDecodeError:
                resultado = _fallback_resultado(texto, dados)
        else:
            resultado = _fallback_resultado(texto, dados)

    if "titulo" not in resultado:
        resultado["titulo"] = f"Memorial de {dados.get('nome', 'Pesquisador(a)')}"
    if "texto_principal" not in resultado:
        resultado["texto_principal"] = texto
    if "secoes" not in resultado:
        resultado["secoes"] = []

    # Sanitização defensiva: remove markdown vazado mesmo se o modelo desobedeceu
    resultado["titulo"] = _limpar_markdown(resultado["titulo"])
    resultado["texto_principal"] = _sanitizar_narrativa(resultado["texto_principal"])
    for secao in resultado["secoes"]:
        secao["titulo"] = _limpar_markdown(secao.get("titulo", ""))
        secao["conteudo"] = _limpar_markdown(secao.get("conteudo", ""))

    return resultado


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


def _fallback_resultado(texto: str, dados: dict) -> dict:
    """Cria resultado estruturado quando o JSON falha."""
    return {
        "titulo": f"Memorial de {dados.get('nome', 'Pesquisador(a)')}",
        "texto_principal": texto,
        "secoes": [],
    }


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

    resultado["metadata"] = {
        "modelo": modelo_usado or config.GEMINI_MODEL,
        "temperatura": config.GEMINI_TEMPERATURE,
        "anos_validados": len(anos_inventados) == 0,
        "idioma_ok": idioma is None,
        "alertas": alertas,
    }
