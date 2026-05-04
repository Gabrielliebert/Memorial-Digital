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
    """Cria as tabelas do banco de dados se não existirem."""
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
    """)
    conn.commit()
    conn.close()
    print("[DB] ✓ Banco de dados inicializado.")


def salvar_memorial(nome: str, url_lattes: str, dados: dict,
                    resultado: dict) -> int:
    """
    Salva um memorial no banco de dados.

    Returns:
        ID do memorial salvo.
    """
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO memoriais (nome, url_lattes, dados_json, titulo,
                               texto_principal, secoes_json, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            nome,
            url_lattes,
            json.dumps(dados, ensure_ascii=False),
            resultado.get("titulo", f"Memorial de {nome}"),
            resultado.get("texto_principal", ""),
            json.dumps(resultado.get("secoes", []), ensure_ascii=False),
            json.dumps(resultado.get("metadata", {}), ensure_ascii=False),
        ),
    )
    memorial_id = cursor.lastrowid

    # Registrar log
    conn.execute(
        "INSERT INTO logs (memorial_id, acao, detalhes) VALUES (?, ?, ?)",
        (memorial_id, "criado", f"Memorial gerado para {nome}"),
    )

    conn.commit()
    conn.close()
    print(f"[DB] ✓ Memorial salvo com ID {memorial_id}")
    return memorial_id


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


def atualizar_memorial(memorial_id: int, titulo: str = None,
                       texto_principal: str = None,
                       secoes: list = None) -> bool:
    """Atualiza campos editáveis de um memorial."""
    conn = get_db()
    updates = []
    params = []

    if titulo is not None:
        updates.append("titulo = ?")
        params.append(titulo)
    if texto_principal is not None:
        updates.append("texto_principal = ?")
        params.append(texto_principal)
    if secoes is not None:
        updates.append("secoes_json = ?")
        params.append(json.dumps(secoes, ensure_ascii=False))

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
