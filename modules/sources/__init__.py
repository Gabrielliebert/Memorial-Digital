"""
Fontes de dados para o Memorial Digital.

Cada fonte implementa um adaptador que produz o dicionário canônico
consumido pelo gerador (chaves: nome, resumo, formacao, atuacao_profissional,
areas_atuacao, producoes_bibliograficas, orientacoes, projetos, premios, idiomas).

A arquitetura plugável permite expansão futura (LinkedIn export, Escavador,
ORCID, etc.) sem alterar o pipeline principal.
"""
from .lattes import coletar_lattes_completo
from .manual import construir_dados_manuais, validar_dados_manuais
from .linkedin import processar_export_linkedin
from .escavador import coletar_escavador

FONTES_DISPONIVEIS = ("lattes", "manual", "linkedin", "escavador")

__all__ = [
    "coletar_lattes_completo",
    "construir_dados_manuais",
    "validar_dados_manuais",
    "processar_export_linkedin",
    "coletar_escavador",
    "FONTES_DISPONIVEIS",
]
