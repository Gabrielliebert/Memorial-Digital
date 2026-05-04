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
    Inclui estratégias anti-alucinação e diretrizes empáticas.
    """
    nome = dados.get("nome", "Pesquisador(a)")

    # Preparar seções de dados
    secoes_dados = []

    if dados.get("resumo"):
        secoes_dados.append(f"<RESUMO>\n{dados['resumo']}\n</RESUMO>")

    if dados.get("formacao"):
        formacoes_texto = "\n".join(
            f"- {f.get('descricao', f)}"
            for f in dados["formacao"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(f"<FORMACAO_ACADEMICA>\n{formacoes_texto}\n</FORMACAO_ACADEMICA>")

    if dados.get("atuacao_profissional"):
        atuacoes_texto = "\n".join(
            f"- {a.get('descricao', a)}"
            for a in dados["atuacao_profissional"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(
            f"<ATUACAO_PROFISSIONAL>\n{atuacoes_texto}\n</ATUACAO_PROFISSIONAL>")

    if dados.get("areas_atuacao"):
        areas_texto = "\n".join(
            f"- {a}" if isinstance(a, str) else f"- {a.get('descricao', a)}"
            for a in dados["areas_atuacao"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(f"<AREAS_ATUACAO>\n{areas_texto}\n</AREAS_ATUACAO>")

    if dados.get("producoes_bibliograficas"):
        prods = dados["producoes_bibliograficas"][:config.MAX_PRODUCOES_NO_PROMPT]
        prods_texto = "\n".join(
            f"- {p.get('descricao', p)}"
            for p in prods
        )
        secoes_dados.append(
            f"<PRODUCOES_BIBLIOGRAFICAS>\n{prods_texto}\n</PRODUCOES_BIBLIOGRAFICAS>")

    if dados.get("orientacoes"):
        orient_texto = "\n".join(
            f"- {o.get('descricao', o)}"
            for o in dados["orientacoes"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(f"<ORIENTACOES>\n{orient_texto}\n</ORIENTACOES>")

    if dados.get("projetos"):
        proj_texto = "\n".join(
            f"- {p.get('descricao', p)}"
            for p in dados["projetos"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(f"<PROJETOS>\n{proj_texto}\n</PROJETOS>")

    if dados.get("premios"):
        prem_texto = "\n".join(
            f"- {p.get('descricao', p)}"
            for p in dados["premios"][:config.MAX_ITENS_POR_SECAO]
        )
        secoes_dados.append(f"<PREMIOS>\n{prem_texto}\n</PREMIOS>")

    dados_completos = "\n\n".join(secoes_dados)

    prompt = f"""Você é um redator especializado em memoriais digitais acadêmicos.
Sua tarefa é criar um memorial respeitoso e empático para o(a) pesquisador(a) {nome},
utilizando EXCLUSIVAMENTE os dados fornecidos abaixo.

═══════════════════════════════════════════════
REGRAS OBRIGATÓRIAS (ANTI-ALUCINAÇÃO):
═══════════════════════════════════════════════
1. Use APENAS as informações contidas nos dados abaixo. NÃO INVENTE nenhum dado.
2. Se uma informação não estiver nos dados, NÃO a mencione. Omita em vez de inventar.
3. NÃO crie nomes de instituições, datas, títulos de trabalhos ou qualquer dado factual
   que não esteja explicitamente nos dados fornecidos.
4. NÃO use frases como "entre outros trabalhos" ou "diversas publicações" se não houver
   dados que sustentem isso.
5. Cada afirmação do texto DEVE ter respaldo direto nos dados abaixo.

═══════════════════════════════════════════════
DIRETRIZES DE ESTILO (baseadas em heurísticas de usabilidade para luto):
═══════════════════════════════════════════════
- IDIOMA: GERE TODO O SEU CONTEÚDO FINAL EXCLUSIVA E OBRIGATORIAMENTE EM PORTUGUÊS DO BRASIL (pt-BR). É ESTRITAMENTE PROIBIDO gerar resumos em Inglês, Coreano, ou qualquer outro idioma que não seja Português. Ignore traduções, fale em Português.
- Escreva na TERCEIRA PESSOA. O texto é um tributo biográfico feito por terceiros baseando-se nos dados públicos do Lattes (ex: "{nome} foi um pesquisador e professor que...", "Sua trajetória foi marcada por...").
- Tom respeitoso, empático e celebratório do legado acadêmico e profissional.
- Linguagem acessível, evitando jargão excessivo.
- ESTRUTURA DO TEXTO PRINCIPAL: O campo "texto_principal" DEVE conter UMA ÚNICA HISTÓRIA NARRATIVA contínua (exatamente 3 a 5 parágrafos tradicionais). É ESTABELECIDA A PROIBIÇÃO ABSOLUTA do uso de marcações Markdown (como **, ##) e listas/tópicos (como 1., 2., -). O "texto_principal" deve ser somente texto puro e discursivo. Se você incluir qualquer item de lista nesse campo, a geração falhará. Reserve todo detalhamento em formato de tópicos para o array de "secoes".
- Representatividade cultural: respeite o contexto brasileiro/latino-americano.

═══════════════════════════════════════════════
FORMATO DE SAÍDA:
═══════════════════════════════════════════════
Responda EXATAMENTE neste formato JSON:

{{
  "titulo": "Memorial de [Nome do Pesquisador]",
  "texto_principal": "Texto contínuo sem NENHUM markdown. O(a) pesquisador(a) X foi... Ele atuou fortemente na área de Y. Sua carreira foi construída sobre...",
  "secoes": [
    {{
      "titulo": "Formação Acadêmica",
      "conteudo": "Texto sobre formação..."
    }},
    {{
      "titulo": "Atuação Profissional",
      "conteudo": "Texto sobre atuação..."
    }},
    {{
      "titulo": "Contribuições Científicas",
      "conteudo": "Texto sobre produções..."
    }}
  ]
}}

IMPORTANTE: Retorne APENAS o JSON, sem markdown, sem ```json, sem texto antes ou depois.
Inclua apenas seções para as quais há dados disponíveis.

═══════════════════════════════════════════════
DADOS DO PESQUISADOR — {nome}:
═══════════════════════════════════════════════

{dados_completos}
"""
    return prompt


def _processar_resposta(texto_bruto: str, dados: dict) -> dict:
    """Processa a resposta bruta do Gemini/Ollama em dicionário estruturado."""
    texto = texto_bruto.strip()
    
    # Remover blocos de raciocínio (<think>...</think>) característicos de modelos como DeepSeek-R1 / QwQ
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()
    
    # Limpar possíveis marcadores de código
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)

    try:
        resultado = json.loads(texto)
    except json.JSONDecodeError:
        # Tentar extrair JSON do meio do texto
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try:
                resultado = json.loads(match.group())
            except json.JSONDecodeError:
                resultado = _fallback_resultado(texto, dados)
        else:
            resultado = _fallback_resultado(texto, dados)

    # Garantir estrutura mínima
    if "titulo" not in resultado:
        resultado["titulo"] = f"Memorial de {dados.get('nome', 'Pesquisador(a)')}"
    if "texto_principal" not in resultado:
        resultado["texto_principal"] = texto
    if "secoes" not in resultado:
        resultado["secoes"] = []

    return resultado


def _fallback_resultado(texto: str, dados: dict) -> dict:
    """Cria resultado estruturado quando o JSON falha."""
    return {
        "titulo": f"Memorial de {dados.get('nome', 'Pesquisador(a)')}",
        "texto_principal": texto,
        "secoes": [],
    }


def _validar_resultado(resultado: dict, dados: dict, modelo_usado: str = None):
    """
    Validação pós-geração para detectar possíveis alucinações.
    Loga warnings mas não bloqueia o resultado.
    """
    nome = dados.get("nome", "")
    texto_completo = resultado.get("texto_principal", "")
    for secao in resultado.get("secoes", []):
        texto_completo += " " + secao.get("conteudo", "")

    # Verificar se o nome está correto no texto
    if nome and nome.lower() not in texto_completo.lower():
        print(f"[Gerador] ⚠ O nome '{nome}' não aparece no texto gerado.")

    # Verificar anos mencionados no texto vs. dados originais
    anos_texto = set(re.findall(r"\b(19\d{2}|20\d{2})\b", texto_completo))
    anos_dados = set()
    dados_str = json.dumps(dados, ensure_ascii=False)
    anos_dados = set(re.findall(r"\b(19\d{2}|20\d{2})\b", dados_str))

    anos_inventados = anos_texto - anos_dados
    if anos_inventados:
        print(f"[Gerador] ⚠ Anos no texto não encontrados nos dados: {anos_inventados}")
        print("[Gerador]   Possível alucinação — revisar manualmente.")

    resultado["metadata"] = {
        "modelo": modelo_usado or config.GEMINI_MODEL,
        "temperatura": config.GEMINI_TEMPERATURE,
        "anos_validados": len(anos_inventados) == 0,
        "alertas": list(anos_inventados) if anos_inventados else [],
    }
