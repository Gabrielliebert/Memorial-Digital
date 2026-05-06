"""
Modelos do banco de dados — SQLite via sqlite3.

Armazena memoriais gerados, dados extraídos e histórico.
"""
import sqlite3
import json
import os
from datetime import datetime
import config


def get_db():
    """Retorna conexão com o banco de dados SQLite."""
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Cria as tabelas e aplica migrações idempotentes."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memoriais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            url_lattes TEXT,
            dados_json TEXT,
            titulo TEXT,
            texto_principal TEXT,
            secoes_json TEXT,
            metadata_json TEXT,
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memorial_id INTEGER,
            acao TEXT NOT NULL,
            detalhes TEXT,
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (memorial_id) REFERENCES memoriais(id)
        );

        CREATE TABLE IF NOT EXISTS tributos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memorial_id INTEGER NOT NULL,
            autor TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (memorial_id) REFERENCES memoriais(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memorial_id INTEGER NOT NULL,
            foto_url TEXT NOT NULL,
            legenda TEXT,
            ordem INTEGER DEFAULT 0,
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (memorial_id) REFERENCES memoriais(id) ON DELETE CASCADE
        );
    """)

    # Migração: adicionar colunas novas se ainda não existirem.
    # Princípios acadêmicos:
    # - visibilidade: privacidade granular (Maciel 2019)
    # - memorial_status: alive/memorialized (Ueda 2022)
    # - legacy_manager_email: herdeiro / gestor pós-vida
    # - consentimento: registro de autorização
    # - fonte: rastreabilidade da origem dos dados
    colunas_novas = [
        ("visibilidade", "TEXT DEFAULT 'publico'"),
        ("memorial_status", "TEXT DEFAULT 'ativo'"),
        ("legacy_manager_email", "TEXT"),
        ("consentimento", "INTEGER DEFAULT 0"),
        ("fonte", "TEXT DEFAULT 'lattes'"),
        ("permitir_tributos", "INTEGER DEFAULT 1"),
        ("data_nascimento", "TEXT"),
        ("data_falecimento", "TEXT"),
        ("memorializado_em", "TEXT"),
        ("foto_url", "TEXT"),
        ("auto_aprovar_tributos", "INTEGER DEFAULT 0"),
    ]
    cols_existentes = {row["name"] for row in conn.execute("PRAGMA table_info(memoriais)")}
    for nome_col, definicao in colunas_novas:
        if nome_col not in cols_existentes:
            conn.execute(f"ALTER TABLE memoriais ADD COLUMN {nome_col} {definicao}")
            print(f"[DB] + Migração: coluna '{nome_col}' adicionada.")

    conn.commit()
    conn.close()
    print("[DB] ✓ Banco de dados inicializado.")


def salvar_memorial(nome: str, origem: str, dados: dict, resultado: dict,
                    memorial_status: str = "ativo",
                    data_nascimento: str = None,
                    data_falecimento: str = None,
                    foto_url: str = None) -> int:
    """
    Salva um memorial no banco de dados.

    Args:
        nome: Nome do titular.
        origem: URL Lattes ou string identificando a origem (ex: "formulario").
        dados: Dicionário canônico de dados estruturados.
        resultado: Dicionário com título, texto_principal, secoes, metadata.
        memorial_status: "ativo" (vivo) ou "memorializado" (falecido).
        data_nascimento: Data ISO (YYYY-MM-DD) — opcional.
        data_falecimento: Data ISO — só se memorializado.

    Returns:
        ID do memorial salvo.
    """
    fonte = dados.get("_fonte", "lattes")
    memorializado_em = (
        json.dumps({"timestamp": "now"}) if memorial_status == "memorializado"
        else None
    )
    # foto_url tem prioridade do parâmetro explícito, depois dos dados (Lattes)
    foto_final = foto_url or dados.get("foto_url")
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO memoriais (nome, url_lattes, dados_json, titulo,
                               texto_principal, secoes_json, metadata_json,
                               fonte, memorial_status, data_nascimento,
                               data_falecimento, memorializado_em, foto_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nome,
            origem,
            json.dumps(dados, ensure_ascii=False),
            resultado.get("titulo", f"Memorial de {nome}"),
            resultado.get("texto_principal", ""),
            json.dumps(resultado.get("secoes", []), ensure_ascii=False),
            json.dumps(resultado.get("metadata", {}), ensure_ascii=False),
            fonte,
            memorial_status,
            data_nascimento,
            data_falecimento,
            memorializado_em,
            foto_final,
        ),
    )
    memorial_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO logs (memorial_id, acao, detalhes) VALUES (?, ?, ?)",
        (memorial_id, "criado",
         f"Memorial gerado para {nome} | fonte={fonte} | status={memorial_status}"),
    )

    conn.commit()
    conn.close()
    print(f"[DB] ✓ Memorial salvo com ID {memorial_id} (status={memorial_status})")
    return memorial_id


def atualizar_configuracao_memorial(memorial_id: int, **campos) -> bool:
    """
    Atualiza configurações do memorial (privacidade, status, gestor).

    Campos aceitos: visibilidade, memorial_status, legacy_manager_email,
    consentimento, permitir_tributos.
    """
    permitidos = {
        "visibilidade", "memorial_status", "legacy_manager_email",
        "consentimento", "permitir_tributos", "auto_aprovar_tributos",
        "data_nascimento", "data_falecimento",
    }
    updates = []
    params = []
    for chave, valor in campos.items():
        if chave not in permitidos:
            continue
        updates.append(f"{chave} = ?")
        params.append(valor)

    if not updates:
        return False

    updates.append("atualizado_em = datetime('now', 'localtime')")
    params.append(memorial_id)

    conn = get_db()
    conn.execute(
        f"UPDATE memoriais SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.execute(
        "INSERT INTO logs (memorial_id, acao, detalhes) VALUES (?, ?, ?)",
        (memorial_id, "config_alterada", json.dumps(campos, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return True


# ── Tributos ──────────────────────────────────────────

def adicionar_tributo(memorial_id: int, autor: str, mensagem: str,
                      auto_aprovar: bool = False) -> tuple[int, str]:
    """
    Adiciona um tributo. Status inicial:
    - 'aprovado' se auto_aprovar=True (configuração do memorial)
    - 'pendente' caso contrário (aguarda moderação humana)

    Embasamento: Maciel et al. (2019) recomenda curadoria humana para
    espaços de luto, mas usuário pode optar por auto-aprovação para
    memoriais menos sensíveis (ex: perfil profissional ativo).

    Returns:
        Tupla (tributo_id, status_inicial).
    """
    status = "aprovado" if auto_aprovar else "pendente"
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO tributos (memorial_id, autor, mensagem, status)
           VALUES (?, ?, ?, ?)""",
        (memorial_id, autor.strip()[:80], mensagem.strip()[:1000], status),
    )
    tributo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tributo_id, status


def contar_tributos_pendentes(memorial_id: int) -> int:
    """Conta quantos tributos estão aguardando moderação."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM tributos WHERE memorial_id = ? AND status = 'pendente'",
        (memorial_id,),
    ).fetchone()
    conn.close()
    return row["n"] if row else 0


def listar_tributos(memorial_id: int, apenas_aprovados: bool = True) -> list:
    """Lista tributos de um memorial."""
    conn = get_db()
    if apenas_aprovados:
        rows = conn.execute(
            """SELECT * FROM tributos WHERE memorial_id = ? AND status = 'aprovado'
               ORDER BY criado_em DESC""",
            (memorial_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tributos WHERE memorial_id = ? ORDER BY criado_em DESC",
            (memorial_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def moderar_tributo(tributo_id: int, novo_status: str) -> bool:
    """Aprova ou rejeita um tributo."""
    if novo_status not in ("aprovado", "rejeitado", "pendente"):
        return False
    conn = get_db()
    result = conn.execute(
        "UPDATE tributos SET status = ? WHERE id = ?",
        (novo_status, tributo_id),
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0


def deletar_tributo(tributo_id: int) -> bool:
    """Remove um tributo."""
    conn = get_db()
    result = conn.execute("DELETE FROM tributos WHERE id = ?", (tributo_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0


# ── Galeria de fotos ───────────────────────────────────
# Embasamento: plano de trabalho 2025/2026 — "coleta multimodal
# (texto e imagem)". Walter (2015) — luto contemporâneo é multimídia.

def adicionar_foto(memorial_id: int, foto_url: str, legenda: str = "") -> int:
    """Adiciona uma foto à galeria do memorial."""
    conn = get_db()
    # Pega a maior ordem atual + 1
    row = conn.execute(
        "SELECT COALESCE(MAX(ordem), 0) + 1 as proxima FROM fotos WHERE memorial_id = ?",
        (memorial_id,),
    ).fetchone()
    proxima = row["proxima"] if row else 1

    cursor = conn.execute(
        """INSERT INTO fotos (memorial_id, foto_url, legenda, ordem)
           VALUES (?, ?, ?, ?)""",
        (memorial_id, foto_url, (legenda or "").strip()[:200], proxima),
    )
    foto_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return foto_id


def listar_fotos(memorial_id: int) -> list:
    """Lista todas as fotos da galeria, em ordem."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM fotos WHERE memorial_id = ? ORDER BY ordem ASC, criado_em ASC",
        (memorial_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deletar_foto(foto_id: int) -> bool:
    """Remove uma foto da galeria."""
    conn = get_db()
    result = conn.execute("DELETE FROM fotos WHERE id = ?", (foto_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0


def atualizar_legenda_foto(foto_id: int, legenda: str) -> bool:
    """Atualiza a legenda de uma foto."""
    conn = get_db()
    result = conn.execute(
        "UPDATE fotos SET legenda = ? WHERE id = ?",
        ((legenda or "").strip()[:200], foto_id),
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0


def buscar_memorial(memorial_id: int) -> dict | None:
    """Busca um memorial pelo ID."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM memoriais WHERE id = ?", (memorial_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    return _row_to_dict(row)


def listar_memoriais() -> list:
    """Lista todos os memoriais salvos, mais recentes primeiro."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memoriais ORDER BY criado_em DESC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def buscar_memoriais_por_nome(query: str) -> list:
    """Busca memoriais cujo nome contenha a query (case-insensitive)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memoriais WHERE nome LIKE ? ORDER BY criado_em DESC",
        (f"%{query}%",),
    ).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def atualizar_memorial(memorial_id: int, titulo: str = None,
                       texto_principal: str = None,
                       secoes: list = None,
                       foto_url: str = None,
                       data_nascimento: str = None,
                       data_falecimento: str = None,
                       nome: str = None) -> bool:
    """Atualiza campos editáveis de um memorial. Use string vazia para limpar."""
    conn = get_db()
    updates = []
    params = []

    if nome is not None:
        updates.append("nome = ?")
        params.append(nome)
    if titulo is not None:
        updates.append("titulo = ?")
        params.append(titulo)
    if texto_principal is not None:
        updates.append("texto_principal = ?")
        params.append(texto_principal)
    if secoes is not None:
        updates.append("secoes_json = ?")
        params.append(json.dumps(secoes, ensure_ascii=False))
    if foto_url is not None:
        updates.append("foto_url = ?")
        params.append(foto_url or None)
    if data_nascimento is not None:
        updates.append("data_nascimento = ?")
        params.append(data_nascimento or None)
    if data_falecimento is not None:
        updates.append("data_falecimento = ?")
        params.append(data_falecimento or None)

    if not updates:
        conn.close()
        return False

    updates.append("atualizado_em = datetime('now', 'localtime')")
    params.append(memorial_id)

    conn.execute(
        f"UPDATE memoriais SET {', '.join(updates)} WHERE id = ?",
        params,
    )

    conn.execute(
        "INSERT INTO logs (memorial_id, acao, detalhes) VALUES (?, ?, ?)",
        (memorial_id, "editado", "Memorial atualizado pelo usuário"),
    )

    conn.commit()
    conn.close()
    return True


def deletar_memorial(memorial_id: int) -> bool:
    """Remove um memorial do banco de dados."""
    conn = get_db()
    conn.execute("DELETE FROM logs WHERE memorial_id = ?", (memorial_id,))
    result = conn.execute(
        "DELETE FROM memoriais WHERE id = ?", (memorial_id,)
    )
    conn.commit()
    conn.close()
    return result.rowcount > 0


def _row_to_dict(row) -> dict:
    """Converte uma Row do SQLite para dicionário."""
    d = dict(row)
    # Parsear campos JSON
    if d.get("dados_json"):
        try:
            d["dados"] = json.loads(d["dados_json"])
        except json.JSONDecodeError:
            d["dados"] = {}
    if d.get("secoes_json"):
        try:
            d["secoes"] = json.loads(d["secoes_json"])
        except json.JSONDecodeError:
            d["secoes"] = []
    if d.get("metadata_json"):
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except json.JSONDecodeError:
            d["metadata"] = {}
    return d
