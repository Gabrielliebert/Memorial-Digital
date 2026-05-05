"""
Fonte Manual: dados informados pelo próprio titular ou por familiar/herdeiro.

Aceita tanto formulário simples (nome + texto livre por seção) quanto upload
de JSON estruturado. Esta fonte respeita melhor o princípio de volição
(Maciel et al., 2019) por colocar o titular no controle do conteúdo.
"""
import json
from typing import Iterable

CHAVES_LISTA = (
    "formacao", "atuacao_profissional", "areas_atuacao",
    "producoes_bibliograficas", "orientacoes", "projetos", "premios", "idiomas",
)


def construir_dados_manuais(form: dict) -> dict:
    """
    Constrói o dicionário canônico a partir de um dict de formulário.

    Cada campo de lista vem como texto livre (uma entrada por linha).
    Campos vazios são omitidos para que o gerador não os mencione.
    """
    nome = (form.get("nome") or "").strip()
    if not nome:
        raise ValueError("O campo 'nome' é obrigatório.")

    dados: dict = {"nome": nome}

    resumo = (form.get("resumo") or "").strip()
    if resumo:
        dados["resumo"] = resumo

    for chave in CHAVES_LISTA:
        valor_bruto = (form.get(chave) or "").strip()
        itens = _parse_linhas(valor_bruto)
        if itens:
            dados[chave] = [{"descricao": item} for item in itens]

    dados["_fonte"] = "manual"
    dados["_origem"] = "formulario"
    return dados


def construir_dados_de_json(payload: str | dict) -> dict:
    """Aceita JSON cru e devolve dicionário canônico, validando o mínimo."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido: {e}") from e

    if not isinstance(payload, dict):
        raise ValueError("O JSON precisa ser um objeto no nível raiz.")

    nome = (payload.get("nome") or "").strip()
    if not nome:
        raise ValueError("O JSON deve conter o campo 'nome'.")

    dados: dict = {"nome": nome}
    if payload.get("resumo"):
        dados["resumo"] = str(payload["resumo"]).strip()

    for chave in CHAVES_LISTA:
        valor = payload.get(chave)
        if not valor:
            continue
        dados[chave] = _normalizar_lista(valor)

    dados["_fonte"] = "json"
    dados["_origem"] = "upload"
    return dados


def validar_dados_manuais(dados: dict) -> list[str]:
    """Retorna lista de problemas encontrados (vazia se tudo OK)."""
    problemas = []
    if not dados.get("nome"):
        problemas.append("Nome é obrigatório.")
    tem_conteudo = (
        dados.get("resumo")
        or any(dados.get(c) for c in CHAVES_LISTA)
    )
    if not tem_conteudo:
        problemas.append(
            "Pelo menos uma seção (resumo, formação, atuação...) "
            "precisa ser preenchida."
        )
    return problemas


def _parse_linhas(texto: str) -> list[str]:
    """Quebra texto em linhas, descartando vazias e marcadores comuns."""
    if not texto:
        return []
    linhas = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        # Remover marcadores que o usuário possa ter colado (-, *, •, 1.)
        linha = linha.lstrip("-•* ").strip()
        if linha and linha[0].isdigit() and len(linha) > 2 and linha[1] in ".)":
            linha = linha[2:].strip()
        if linha:
            linhas.append(linha)
    return linhas


def _normalizar_lista(valor: Iterable) -> list[dict]:
    """Aceita lista de strings ou lista de dicts; devolve lista de dicts."""
    if isinstance(valor, str):
        return [{"descricao": valor}]
    resultado = []
    for item in valor:
        if isinstance(item, dict):
            if "descricao" in item:
                resultado.append(item)
            else:
                resultado.append({"descricao": str(item)})
        else:
            resultado.append({"descricao": str(item)})
    return resultado
