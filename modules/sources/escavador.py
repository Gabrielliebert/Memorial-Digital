"""
Fonte Escavador — coleta currículo via API oficial.

O Escavador (https://www.escavador.com) é uma plataforma brasileira que
agrega dados públicos sobre pesquisadores e profissionais. A API oficial
processa currículos Lattes e devolve JSON estruturado, eliminando a
necessidade de scraping com Playwright + CAPTCHA.

Documentação da API: https://api.escavador.com/docs/
Como obter chave: https://api.escavador.com/

Esta implementação tenta endpoints comuns e tem comportamento defensivo
(falha graciosamente se a API key não estiver configurada ou se a API
mudar). Se você precisar adaptar à versão atual da API, ajuste os
endpoints e o mapeamento abaixo.
"""
import re
import requests
import config


BASE_URL = "https://api.escavador.com/api/v2"


def coletar_escavador(query: str) -> dict:
    """
    Busca por nome ou ID Lattes via API do Escavador.

    Args:
        query: nome completo OU URL/ID do Lattes (ex: "0123456789012345"
               ou "http://lattes.cnpq.br/0123456789012345").

    Returns:
        Dicionário canônico (nome, resumo, formacao, etc.).

    Raises:
        ValueError: se a chave da API não estiver configurada.
        RuntimeError: se a API retornar erro inesperado ou nada for encontrado.
    """
    api_key = getattr(config, "ESCAVADOR_API_KEY", "") or ""
    if not api_key or api_key == "sua_chave_aqui":
        raise ValueError(
            "ESCAVADOR_API_KEY não configurada. "
            "Obtenha em https://api.escavador.com/ e defina no .env."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "Memorial-Digital-PIBIC/1.0",
    }

    # Detectar se a query é um ID Lattes (16 dígitos) ou nome
    id_lattes = _extrair_id_lattes(query)

    if id_lattes:
        print(f"[Escavador] Buscando currículo Lattes ID={id_lattes}")
        return _buscar_por_id_lattes(id_lattes, headers)
    else:
        print(f"[Escavador] Buscando por nome: {query}")
        return _buscar_por_nome(query.strip(), headers)


def _extrair_id_lattes(query: str) -> str | None:
    """Extrai o ID Lattes (16 dígitos) de uma URL ou string."""
    if not query:
        return None
    m = re.search(r"\b(\d{16})\b", query)
    return m.group(1) if m else None


def _buscar_por_id_lattes(id_lattes: str, headers: dict) -> dict:
    """Busca currículo direto pelo ID Lattes."""
    # Endpoints possíveis (a API pode mudar — tentamos o mais comum)
    endpoints = [
        f"{BASE_URL}/cnpq/curriculo/{id_lattes}",
        f"{BASE_URL}/curriculo-lattes/{id_lattes}",
        f"https://api.escavador.com/v2/cnpq/curriculo/{id_lattes}",
    ]

    ultimo_erro = None
    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                return _normalizar_resposta(r.json(), origem=url)
            elif r.status_code == 404:
                continue
            elif r.status_code in (401, 403):
                raise ValueError(
                    "Chave da API do Escavador inválida ou sem permissão. "
                    "Verifique seu plano e a chave em api.escavador.com."
                )
            else:
                ultimo_erro = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            ultimo_erro = str(e)
            continue

    raise RuntimeError(
        f"Não foi possível obter currículo do Escavador. "
        f"Último erro: {ultimo_erro or 'endpoint indisponível'}. "
        f"Verifique sua API key e cota."
    )


def _buscar_por_nome(nome: str, headers: dict) -> dict:
    """Busca por nome — pega o primeiro resultado relevante."""
    # Endpoint de busca (a API pode usar diferentes paths)
    url_busca = f"{BASE_URL}/sobre/buscar"
    try:
        r = requests.get(url_busca, headers=headers,
                         params={"nome": nome}, timeout=30)
        r.raise_for_status()
        data = r.json()
        resultados = data.get("items") or data.get("data") or []
        if not resultados:
            raise RuntimeError(
                f"Nenhum currículo encontrado para '{nome}' no Escavador."
            )

        # Pega o primeiro com ID Lattes
        for item in resultados:
            id_lattes = (item.get("id_lattes") or item.get("idLattes")
                         or _extrair_id_lattes(str(item.get("link", ""))))
            if id_lattes:
                return _buscar_por_id_lattes(id_lattes, headers)

        # Sem ID Lattes — tenta normalizar o que veio
        return _normalizar_resposta(resultados[0], origem=url_busca)

    except requests.RequestException as e:
        raise RuntimeError(f"Erro ao buscar no Escavador: {e}") from e


def _normalizar_resposta(payload: dict, origem: str = "") -> dict:
    """
    Normaliza a resposta do Escavador para o formato canônico.

    Como o schema exato pode variar, fazemos coalesce defensivo
    em múltiplas chaves possíveis.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("Resposta do Escavador em formato inesperado.")

    # Algumas APIs aninham os dados em "data" ou "curriculo"
    pessoa = payload.get("data") or payload.get("curriculo") or payload

    nome = _get(pessoa, "nome", "name", "fullName", default="Sem nome")
    resumo = _get(pessoa, "resumo", "summary", "biografia", "about", default="")

    dados = {
        "nome": nome,
        "_fonte": "escavador",
        "_origem": origem,
    }
    if resumo:
        dados["resumo"] = resumo

    # Foto
    foto = _get(pessoa, "foto", "foto_url", "photo", "avatar", default=None)
    if foto:
        dados["foto_url"] = foto

    # Listas
    formacao = pessoa.get("formacao") or pessoa.get("educacao") or pessoa.get("education", [])
    if formacao:
        dados["formacao"] = _normalizar_lista(formacao, ["descricao", "description", "titulo", "title"])

    atuacao = pessoa.get("atuacao_profissional") or pessoa.get("experiencia") or pessoa.get("positions", [])
    if atuacao:
        dados["atuacao_profissional"] = _normalizar_lista(atuacao, ["descricao", "description", "cargo", "title"])

    areas = pessoa.get("areas_atuacao") or pessoa.get("areas") or pessoa.get("skills", [])
    if areas:
        dados["areas_atuacao"] = _normalizar_lista(areas, ["descricao", "name", "nome"])

    producoes = pessoa.get("producoes_bibliograficas") or pessoa.get("publicacoes") or pessoa.get("publications", [])
    if producoes:
        dados["producoes_bibliograficas"] = _normalizar_lista(producoes, ["descricao", "title", "titulo"])

    orientacoes = pessoa.get("orientacoes") or []
    if orientacoes:
        dados["orientacoes"] = _normalizar_lista(orientacoes, ["descricao", "title"])

    projetos = pessoa.get("projetos") or pessoa.get("projects", [])
    if projetos:
        dados["projetos"] = _normalizar_lista(projetos, ["descricao", "title", "nome"])

    premios = pessoa.get("premios") or pessoa.get("honors", [])
    if premios:
        dados["premios"] = _normalizar_lista(premios, ["descricao", "title", "titulo"])

    idiomas = pessoa.get("idiomas") or pessoa.get("languages", [])
    if idiomas:
        dados["idiomas"] = _normalizar_lista(idiomas, ["descricao", "name", "idioma"])

    return dados


def _get(d: dict, *chaves, default=None):
    """Coalesce em múltiplas chaves."""
    for k in chaves:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _normalizar_lista(itens, chaves_descricao: list[str]) -> list[dict]:
    """Garante formato [{descricao: ...}, ...]."""
    if isinstance(itens, str):
        return [{"descricao": itens}]
    resultado = []
    for item in itens:
        if isinstance(item, dict):
            descr = ""
            for k in chaves_descricao:
                v = item.get(k)
                if v:
                    descr = str(v).strip()
                    break
            if not descr:
                # Concatena valores não-vazios como fallback
                descr = " - ".join(str(v) for v in item.values() if v)
            if descr:
                resultado.append({"descricao": descr})
        elif item:
            resultado.append({"descricao": str(item)})
    return resultado
