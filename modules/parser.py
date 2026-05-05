"""
Módulo de Parsing — Extração estruturada de dados do Currículo Lattes.

Recebe HTML bruto e retorna dicionário JSON com as categorias
do memorial, baseado na taxonomia de Ueda et al. (2022).
"""
from bs4 import BeautifulSoup
import re
import json


def parse_lattes(html: str) -> dict:
    """
    Extrai dados estruturados do HTML do currículo Lattes.

    Args:
        html: HTML bruto da página do Lattes.

    Returns:
        Dicionário com dados estruturados do pesquisador.
    """
    soup = BeautifulSoup(html, "lxml")
    dados = {
        "nome": _extrair_nome(soup),
        "foto_url": _extrair_foto(soup),
        "resumo": _extrair_resumo(soup),
        "formacao": _extrair_formacao(soup),
        "atuacao_profissional": _extrair_atuacao(soup),
        "areas_atuacao": _extrair_areas(soup),
        "producoes_bibliograficas": _extrair_producoes(soup),
        "orientacoes": _extrair_orientacoes(soup),
        "projetos": _extrair_projetos(soup),
        "premios": _extrair_premios(soup),
        "idiomas": _extrair_idiomas(soup),
    }
    return dados


def _extrair_foto(soup: BeautifulSoup) -> str | None:
    """
    Extrai a URL da foto do pesquisador no Lattes.

    O Lattes serve fotos via servletrecuperafoto?id=XXXX. Tenta vários
    seletores comuns e retorna a URL absoluta. Retorna None se não encontrar.
    """
    # Seletor principal: img com class "foto" ou dentro de div.foto
    candidatos = [
        soup.select_one("img.foto"),
        soup.select_one("div.foto img"),
        soup.select_one("div.foto-perfil img"),
        soup.select_one("img[src*='servletrecuperafoto']"),
        soup.select_one("img[src*='foto']"),
    ]
    for img in candidatos:
        if img and img.get("src"):
            src = img["src"].strip()
            # Construir URL absoluta se for relativa
            if src.startswith("//"):
                return "https:" + src
            if src.startswith("/"):
                return "http://buscatextual.cnpq.br" + src
            if src.startswith("http"):
                return src
    return None


def _extrair_nome(soup: BeautifulSoup) -> str:
    """Extrai o nome completo do pesquisador."""
    # Tentar seletor principal
    nome_tag = soup.select_one("h2.nome")
    if nome_tag:
        return _limpar_texto(nome_tag.get_text())

    # Alternativa: buscar no título da página
    title = soup.find("title")
    if title:
        texto = title.get_text()
        if " - " in texto:
            return _limpar_texto(texto.split(" - ")[0])

    # Alternativa: primeiro h2 com conteúdo significativo
    for h2 in soup.find_all("h2"):
        texto = h2.get_text().strip()
        if texto and len(texto) > 3 and len(texto) < 100:
            return texto

    return "Nome não encontrado"


def _extrair_resumo(soup: BeautifulSoup) -> str:
    """Extrai o resumo/biografia do pesquisador."""
    # Buscar pela seção de resumo do Lattes
    resumo_div = soup.find("p", class_="resumo")
    if resumo_div:
        return _limpar_texto(resumo_div.get_text())

    # Alternativa: buscar div com id relacionado
    for div_id in ["resumo", "mini-bio", "biography"]:
        div = soup.find(id=re.compile(div_id, re.I))
        if div:
            return _limpar_texto(div.get_text())

    # Alternativa: buscar por texto após "Resumo" header
    headers = soup.find_all(["h3", "h4", "div"],
                            string=re.compile(r"Resumo", re.I))
    for header in headers:
        next_el = header.find_next_sibling()
        if next_el:
            texto = next_el.get_text()
            if len(texto) > 50:
                return _limpar_texto(texto)

    return ""


def _extrair_formacao(soup: BeautifulSoup) -> list:
    """Extrai formação acadêmica."""
    formacoes = []

    # Procurar seção de formação acadêmica
    secao = _encontrar_secao(soup, r"Forma[çc][aã]o\s*(acad[eê]mica|complementar)?")
    if not secao:
        return formacoes

    # Extrair itens da formação
    itens = secao.find_all(["div", "li"], class_=re.compile(
        r"formacao|cris-list|artigo", re.I))

    if not itens:
        # Tentar pegar todos os blocos de texto dentro da seção
        itens = secao.find_all("div", recursive=False)

    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 10:
            formacoes.append(_parse_formacao_item(texto))

    # Se não encontrou itens estruturados, pegar texto bruto
    if not formacoes:
        texto_bruto = _limpar_texto(secao.get_text())
        linhas = [l.strip() for l in texto_bruto.split("\n") if l.strip() and len(l.strip()) > 15]
        for linha in linhas[:10]:
            formacoes.append({"descricao": linha})

    return formacoes


def _parse_formacao_item(texto: str) -> dict:
    """Parseia um item de formação extraindo nível, instituição e período."""
    item = {"descricao": texto}

    # Tentar extrair período (anos)
    periodo = re.findall(r"(\d{4})\s*[-–]\s*(\d{4}|[Aa]tual)", texto)
    if periodo:
        item["inicio"] = periodo[0][0]
        item["fim"] = periodo[0][1]

    # Tentar identificar nível
    niveis = {
        "doutorado": "Doutorado",
        "mestrado": "Mestrado",
        "graduação": "Graduação",
        "graduacao": "Graduação",
        "especialização": "Especialização",
        "pos-doutorado": "Pós-Doutorado",
        "pós-doutorado": "Pós-Doutorado",
    }
    for chave, valor in niveis.items():
        if chave in texto.lower():
            item["nivel"] = valor
            break

    return item


def _extrair_atuacao(soup: BeautifulSoup) -> list:
    """Extrai atuação profissional."""
    atuacoes = []
    secao = _encontrar_secao(soup, r"Atua[çc][aã]o\s*[Pp]rofissional")
    if not secao:
        return atuacoes

    itens = secao.find_all(["div", "li"], recursive=False)
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 10:
            atuacoes.append({"descricao": texto})

    if not atuacoes:
        texto_bruto = _limpar_texto(secao.get_text())
        linhas = [l.strip() for l in texto_bruto.split("\n") if l.strip() and len(l.strip()) > 15]
        for linha in linhas[:10]:
            atuacoes.append({"descricao": linha})

    return atuacoes


def _extrair_areas(soup: BeautifulSoup) -> list:
    """Extrai áreas de atuação."""
    areas = []
    secao = _encontrar_secao(soup, r"[ÁA]reas?\s*de\s*[Aa]tua[çc][aã]o")
    if not secao:
        return areas

    itens = secao.find_all(["div", "li"])
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 5:
            areas.append(texto)

    if not areas:
        texto_bruto = _limpar_texto(secao.get_text())
        linhas = [l.strip() for l in texto_bruto.split("\n") if l.strip() and len(l.strip()) > 5]
        areas = linhas[:10]

    return areas


def _extrair_producoes(soup: BeautifulSoup) -> list:
    """Extrai produções bibliográficas (artigos, livros, capítulos)."""
    producoes = []
    secao = _encontrar_secao(soup, r"Produ[çc][oõ]es|Artigos|Publica[çc][oõ]es")
    if not secao:
        return producoes

    # Buscar artigos e outras produções
    itens = secao.find_all(["div", "li", "p"],
                           class_=re.compile(r"artigo|producao|item", re.I))

    if not itens:
        itens = secao.find_all(["li"])

    if not itens:
        itens = secao.find_all(["div"], recursive=False)

    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 20:
            producoes.append(_parse_producao_item(texto))

    return producoes


def _parse_producao_item(texto: str) -> dict:
    """Parseia um item de produção extraindo tipo e dados."""
    item = {"descricao": texto}

    # Tentar extrair ano
    anos = re.findall(r"\b(19\d{2}|20\d{2})\b", texto)
    if anos:
        item["ano"] = anos[-1]  # Pegar o último ano (mais provável ser o de publicação)

    # Classificar tipo
    texto_lower = texto.lower()
    if any(w in texto_lower for w in ["artigo", "journal", "revista", "periódico"]):
        item["tipo"] = "Artigo"
    elif any(w in texto_lower for w in ["livro", "book"]):
        item["tipo"] = "Livro"
    elif any(w in texto_lower for w in ["capítulo", "chapter"]):
        item["tipo"] = "Capítulo"
    elif any(w in texto_lower for w in ["congresso", "conference", "anais", "simpósio", "proceedings"]):
        item["tipo"] = "Congresso"
    else:
        item["tipo"] = "Outro"

    return item


def _extrair_orientacoes(soup: BeautifulSoup) -> list:
    """Extrai orientações (concluídas e em andamento)."""
    orientacoes = []
    secao = _encontrar_secao(soup, r"Orienta[çc][oõ]es")
    if not secao:
        return orientacoes

    itens = secao.find_all(["div", "li"])
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 20:
            orientacoes.append({"descricao": texto})

    return orientacoes


def _extrair_projetos(soup: BeautifulSoup) -> list:
    """Extrai projetos de pesquisa."""
    projetos = []
    secao = _encontrar_secao(soup, r"Projetos?\s*de\s*[Pp]esquisa")
    if not secao:
        return projetos

    itens = secao.find_all(["div", "li"])
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 15:
            projetos.append({"descricao": texto})

    return projetos


def _extrair_premios(soup: BeautifulSoup) -> list:
    """Extrai prêmios e títulos."""
    premios = []
    secao = _encontrar_secao(soup, r"Pr[êe]mios|T[ií]tulos|Honrarias")
    if not secao:
        return premios

    itens = secao.find_all(["div", "li"])
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 10:
            premios.append({"descricao": texto})

    return premios


def _extrair_idiomas(soup: BeautifulSoup) -> list:
    """Extrai idiomas, removendo duplicatas e fragmentos sub-aninhados."""
    idiomas_brutos = []
    secao = _encontrar_secao(soup, r"Idiomas")
    if not secao:
        return idiomas_brutos

    itens = secao.find_all(["div", "li"])
    for item in itens:
        texto = _limpar_texto(item.get_text())
        if texto and len(texto) > 3:
            idiomas_brutos.append(texto)

    # Deduplicação: o Lattes tem divs aninhadas que duplicam conteúdo.
    # Remove (a) duplicatas exatas e (b) strings que são SUBSTRING de outra.
    return _deduplicar_lista(idiomas_brutos)


def _deduplicar_lista(itens: list) -> list:
    """
    Remove duplicatas e elementos contidos dentro de outros maiores.
    Útil para o HTML do Lattes que aninha divs com conteúdo repetido.
    """
    if not itens:
        return []

    # Ordena por tamanho decrescente: queremos manter os mais completos
    ordenados = sorted(set(itens), key=len, reverse=True)
    resultado = []
    for item in ordenados:
        # Só adiciona se não for substring de algo já adicionado
        if not any(item != j and item in j for j in resultado):
            resultado.append(item)
    return resultado


# ── Utilitários ──────────────────────────────────────────

def _encontrar_secao(soup: BeautifulSoup, padrao_titulo: str):
    """
    Encontra uma seção do Lattes pelo título.
    Retorna o container pai da seção.
    """
    # Buscar em headers e divs de título
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "div", "span", "a"],
                             string=re.compile(padrao_titulo, re.I)):
        # Tentar retornar o pai significativo
        parent = tag.find_parent(["div", "section"])
        if parent:
            return parent

    # Buscar por class ou id
    for el in soup.find_all(["div", "section"],
                            class_=re.compile(padrao_titulo.replace(r"\s*", ""), re.I)):
        return el

    return None


def _limpar_texto(texto: str) -> str:
    """Limpa texto removendo espaços extras, zero-width chars e tags residuais."""
    if not texto:
        return ""
    # Remover zero-width spaces e chars invisíveis
    texto = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", texto)
    # Normalizar espaços e quebras de linha
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def dados_para_json(dados: dict) -> str:
    """Converte o dicionário de dados para JSON formatado."""
    return json.dumps(dados, ensure_ascii=False, indent=2)
