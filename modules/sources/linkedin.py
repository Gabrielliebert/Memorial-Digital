"""
Fonte LinkedIn — processa o export oficial dos dados do usuário.

Como obter o ZIP:
  1. https://www.linkedin.com/mypreferences/d/download-my-data
  2. Solicitar "Want something in particular? Select the data files you're
     most interested in." → marcar pelo menos:
       - Profile, Positions, Education, Skills, Languages, Honors,
         Publications, Projects, Patents
  3. Aguardar e-mail (pode levar até 24h)
  4. Baixar o ZIP

Por que não scraping ou API?
  - Scraping fere o ToS do LinkedIn (terminação de conta, base legal contra)
  - API oficial requer aprovação como parceiro (Marketing Developer Program /
    Sales Navigator) — inviável para projeto acadêmico
  - O export oficial é a solução ética e robusta: o titular controla
    integralmente os dados que entram (alinhado ao princípio de volição,
    Maciel et al., 2019)
"""
import csv
import io
import re
import zipfile
from typing import Iterable


# ── Mapeamento dos arquivos CSV principais do export ──
# Os nomes podem variar levemente conforme idioma do export. Tentamos
# múltiplas variações case-insensitive.
ARQUIVOS_PROCURADOS = {
    "profile": ["Profile.csv", "profile.csv"],
    "positions": ["Positions.csv", "positions.csv"],
    "education": ["Education.csv", "education.csv"],
    "skills": ["Skills.csv", "skills.csv"],
    "languages": ["Languages.csv", "languages.csv"],
    "honors": ["Honors.csv", "honors.csv"],
    "publications": ["Publications.csv", "publications.csv"],
    "projects": ["Projects.csv", "projects.csv"],
    "patents": ["Patents.csv", "patents.csv"],
    "courses": ["Courses.csv", "courses.csv"],
    "certifications": ["Certifications.csv", "certifications.csv"],
    "volunteering": ["Volunteering.csv", "volunteering.csv"],
}


def processar_export_linkedin(arquivo) -> dict:
    """
    Lê um arquivo ZIP exportado do LinkedIn e retorna o dicionário
    canônico consumido pelo gerador.

    Args:
        arquivo: file-like (FileStorage do Werkzeug ou caminho).

    Returns:
        Dicionário com chaves: nome, resumo, formacao,
        atuacao_profissional, areas_atuacao, idiomas,
        producoes_bibliograficas, projetos, premios, _fonte.

    Raises:
        ValueError: se o ZIP for inválido ou não contiver Profile.csv.
    """
    # Aceita FileStorage (Flask) ou path
    if hasattr(arquivo, "read"):
        conteudo = arquivo.read()
        zip_buffer = io.BytesIO(conteudo)
    else:
        with open(arquivo, "rb") as f:
            zip_buffer = io.BytesIO(f.read())

    try:
        zf = zipfile.ZipFile(zip_buffer)
    except zipfile.BadZipFile as e:
        raise ValueError(
            "Arquivo enviado não é um ZIP válido. "
            "Use o ZIP recebido por e-mail do LinkedIn."
        ) from e

    # Indexa nomes dos arquivos no ZIP (case-insensitive)
    nomes_no_zip = {n.lower(): n for n in zf.namelist()}

    def _ler_csv(chave: str) -> list[dict]:
        """Lê um dos arquivos esperados; retorna lista de dicts."""
        for candidato in ARQUIVOS_PROCURADOS.get(chave, []):
            real = nomes_no_zip.get(candidato.lower())
            if real:
                try:
                    with zf.open(real) as f:
                        # CSV do LinkedIn: utf-8 com BOM
                        text = f.read().decode("utf-8-sig", errors="replace")
                        reader = csv.DictReader(io.StringIO(text))
                        return list(reader)
                except Exception as e:
                    print(f"[LinkedIn] ⚠ Erro ao ler {real}: {e}")
                    return []
        return []

    profile = _ler_csv("profile")
    if not profile:
        raise ValueError(
            "Profile.csv não encontrado no ZIP. "
            "Verifique se você exportou o pacote completo de dados "
            "do LinkedIn (precisa marcar 'Profile' antes de solicitar)."
        )

    perfil = profile[0] if profile else {}
    nome = _coalesce(perfil, ["First Name", "Nome"], "") + " " + \
           _coalesce(perfil, ["Last Name", "Sobrenome"], "")
    nome = nome.strip()
    if not nome:
        nome = _coalesce(perfil, ["Full Name", "Nome completo"], "Sem nome")

    resumo = _coalesce(perfil, ["Summary", "Resumo", "About"], "").strip()
    headline = _coalesce(perfil, ["Headline", "Título profissional"], "").strip()
    if headline and not resumo:
        resumo = headline

    dados = {
        "nome": nome,
        "_fonte": "linkedin",
        "_origem": "export_oficial",
    }
    if resumo:
        dados["resumo"] = resumo

    # Foto: o export inclui uma pasta de mídia mas o caminho varia.
    # Procura imagem com nome contendo "profile" ou "photo" no ZIP.
    foto = _extrair_foto_zip(zf)
    if foto:
        dados["foto_url"] = foto

    # Formação acadêmica
    educacao = _ler_csv("education")
    if educacao:
        dados["formacao"] = [
            {
                "descricao": _formatar_educacao(e),
                "tipo": _coalesce(e, ["Degree Name", "Grau"], ""),
            }
            for e in educacao
            if _coalesce(e, ["School Name", "Instituição"], "").strip()
        ]

    # Atuação profissional (positions)
    posicoes = _ler_csv("positions")
    if posicoes:
        dados["atuacao_profissional"] = [
            {"descricao": _formatar_posicao(p)}
            for p in posicoes
            if _coalesce(p, ["Company Name", "Empresa"], "").strip()
        ]

    # Áreas de atuação (a partir de Skills)
    skills = _ler_csv("skills")
    if skills:
        nomes_skills = [_coalesce(s, ["Name", "Skill"], "").strip() for s in skills]
        nomes_skills = [n for n in nomes_skills if n]
        if nomes_skills:
            dados["areas_atuacao"] = [{"descricao": n} for n in nomes_skills[:30]]

    # Idiomas
    idiomas = _ler_csv("languages")
    if idiomas:
        dados["idiomas"] = [
            {
                "descricao": _formatar_idioma(i),
                "nivel": _coalesce(i, ["Proficiency", "Nível"], ""),
            }
            for i in idiomas
            if _coalesce(i, ["Name", "Idioma"], "").strip()
        ]

    # Prêmios e honrarias
    honors = _ler_csv("honors")
    if honors:
        dados["premios"] = [
            {
                "descricao": _formatar_honra(h),
                "ano": _extrair_ano(_coalesce(h, ["Issued On", "Data"], "")),
            }
            for h in honors
            if _coalesce(h, ["Title", "Título"], "").strip()
        ]

    # Produções bibliográficas (publications)
    publicacoes = _ler_csv("publications")
    if publicacoes:
        dados["producoes_bibliograficas"] = [
            {"descricao": _formatar_publicacao(p)}
            for p in publicacoes
            if _coalesce(p, ["Name", "Title", "Título"], "").strip()
        ]

    # Projetos
    projetos = _ler_csv("projects")
    if projetos:
        dados["projetos"] = [
            {"descricao": _formatar_projeto(p)}
            for p in projetos
            if _coalesce(p, ["Title", "Name", "Nome"], "").strip()
        ]

    # Patentes (entram em projetos pra simplificar)
    patentes = _ler_csv("patents")
    if patentes:
        dados.setdefault("projetos", []).extend(
            {"descricao": f"Patente: {_formatar_patente(p)}"}
            for p in patentes
            if _coalesce(p, ["Title", "Name"], "").strip()
        )

    return dados


# ── Helpers de formatação ─────────────────────────────

def _coalesce(d: dict, chaves: Iterable[str], default: str = "") -> str:
    """Retorna o primeiro valor não-vazio entre as chaves possíveis."""
    for k in chaves:
        v = d.get(k, "")
        if v:
            return str(v).strip()
    return default


def _formatar_educacao(e: dict) -> str:
    parts = []
    grau = _coalesce(e, ["Degree Name", "Grau"], "")
    if grau:
        parts.append(grau)
    escola = _coalesce(e, ["School Name", "Instituição"], "")
    if escola:
        parts.append(escola)
    inicio = _extrair_ano(_coalesce(e, ["Start Date", "Início"], ""))
    fim = _extrair_ano(_coalesce(e, ["End Date", "Término"], ""))
    if inicio or fim:
        parts.append(f"({inicio or '?'} – {fim or 'atual'})")
    return " - ".join(parts) if parts else escola


def _formatar_posicao(p: dict) -> str:
    parts = []
    cargo = _coalesce(p, ["Title", "Cargo"], "")
    if cargo:
        parts.append(cargo)
    empresa = _coalesce(p, ["Company Name", "Empresa"], "")
    if empresa:
        parts.append(empresa)
    inicio = _extrair_ano(_coalesce(p, ["Started On", "Início"], ""))
    fim = _extrair_ano(_coalesce(p, ["Finished On", "Término"], ""))
    if inicio or fim:
        parts.append(f"({inicio or '?'} – {fim or 'atual'})")
    return " - ".join(parts) if parts else empresa


def _formatar_idioma(i: dict) -> str:
    nome = _coalesce(i, ["Name", "Idioma"], "")
    nivel = _coalesce(i, ["Proficiency", "Nível"], "")
    if nivel:
        return f"{nome} ({nivel})"
    return nome


def _formatar_honra(h: dict) -> str:
    titulo = _coalesce(h, ["Title", "Título"], "")
    issuer = _coalesce(h, ["Issuer", "Concedido por"], "")
    ano = _extrair_ano(_coalesce(h, ["Issued On", "Data"], ""))
    parts = [titulo]
    if issuer:
        parts.append(issuer)
    if ano:
        parts.append(ano)
    return " - ".join(parts)


def _formatar_publicacao(p: dict) -> str:
    titulo = _coalesce(p, ["Name", "Title", "Título"], "")
    pub = _coalesce(p, ["Publication", "Publisher"], "")
    ano = _extrair_ano(_coalesce(p, ["Date", "Published On", "Data"], ""))
    parts = [titulo]
    if pub:
        parts.append(pub)
    if ano:
        parts.append(ano)
    return " - ".join(parts)


def _formatar_projeto(p: dict) -> str:
    titulo = _coalesce(p, ["Title", "Name", "Nome"], "")
    descr = _coalesce(p, ["Description", "Descrição"], "")
    if descr and len(descr) > 0:
        descr_short = descr[:120] + ("..." if len(descr) > 120 else "")
        return f"{titulo}: {descr_short}"
    return titulo


def _formatar_patente(p: dict) -> str:
    titulo = _coalesce(p, ["Title", "Name"], "")
    numero = _coalesce(p, ["Application Number", "Patent Number"], "")
    if numero:
        return f"{titulo} ({numero})"
    return titulo


def _extrair_ano(data_str: str) -> str:
    """Extrai o primeiro ano de 4 dígitos de uma string de data."""
    if not data_str:
        return ""
    m = re.search(r"\b(19|20)\d{2}\b", data_str)
    return m.group(0) if m else ""


def _extrair_foto_zip(zf: zipfile.ZipFile) -> str | None:
    """
    Procura por uma foto de perfil dentro do ZIP.
    Retorna data URI base64 (já que não temos servidor de arquivos
    persistente para o conteúdo do ZIP).
    """
    import base64
    candidatos = [
        n for n in zf.namelist()
        if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        and ("profile" in n.lower() or "photo" in n.lower() or "perfil" in n.lower())
    ]
    if not candidatos:
        # Fallback: qualquer imagem no diretório raiz
        candidatos = [
            n for n in zf.namelist()
            if n.lower().endswith((".jpg", ".jpeg", ".png"))
            and "/" not in n.strip("/")
        ]

    if not candidatos:
        return None

    try:
        with zf.open(candidatos[0]) as f:
            data = f.read()
        if len(data) > 5 * 1024 * 1024:  # > 5 MB, ignora
            return None
        ext = candidatos[0].rsplit(".", 1)[-1].lower()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/{mime};base64,{b64}"
    except Exception:
        return None
