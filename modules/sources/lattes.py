"""
Fonte Lattes: wraps scraper + parser existentes em uma única chamada.
"""
from modules.scraper import coletar_lattes
from modules.parser import parse_lattes


def coletar_lattes_completo(url: str) -> dict:
    """Coleta + parsing do Lattes em um único passo. Retorna dict canônico."""
    html = coletar_lattes(url)
    dados = parse_lattes(html)
    dados["_fonte"] = "lattes"
    dados["_origem"] = url
    return dados
