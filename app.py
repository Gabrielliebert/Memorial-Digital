"""
Sistema de Memorial Digital — Aplicação Flask.

Gerador automatizado de memoriais digitais acadêmicos
a partir de currículos Lattes, utilizando IA (Gemini API).

Baseado na pesquisa PIBIC 2025/2026 de Monteiro e Maciel (UFMT/LAVI).
"""
import sys
import os

# Garantir encoding UTF-8 no Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import threading
import traceback
import time

import config
from models import init_db, salvar_memorial, buscar_memorial, listar_memoriais, \
    atualizar_memorial, deletar_memorial, buscar_memoriais_por_nome
from modules.scraper import coletar_lattes
from modules.parser import parse_lattes
from modules.generator import gerar_memorial

# ── Inicialização ────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Inicializar banco de dados
init_db()

# Estado global para tarefas em andamento
tarefas = {}
_tarefas_lock = threading.Lock()
TAREFA_TTL = 3600  # segundos antes de limpar tarefas concluídas/com erro


def _limpar_tarefas_antigas():
    """Remove tarefas finalizadas mais antigas que TAREFA_TTL segundos."""
    agora = time.time()
    with _tarefas_lock:
        expiradas = [
            tid for tid, t in tarefas.items()
            if t.get("status") in ("concluido", "erro")
            and agora - t.get("_timestamp", agora) > TAREFA_TTL
        ]
        for tid in expiradas:
            del tarefas[tid]


# ── Rotas ────────────────────────────────────────────

@app.route("/")
def index():
    """Página inicial — formulário de URL do Lattes."""
    memoriais = listar_memoriais()
    return render_template("index.html", memoriais=memoriais)


@app.route("/gerar", methods=["POST"])
def gerar():
    """Inicia o pipeline de geração do memorial."""
    url_lattes = request.form.get("url_lattes", "").strip()

    if not url_lattes:
        flash("Por favor, insira a URL do currículo Lattes.", "erro")
        return redirect(url_for("index"))

    # Validar URL básica
    if "lattes.cnpq" not in url_lattes and "localhost" not in url_lattes:
        flash("A URL deve ser de um currículo Lattes (lattes.cnpq.br).", "erro")
        return redirect(url_for("index"))

    # Limpar tarefas antigas antes de criar nova
    _limpar_tarefas_antigas()

    # Iniciar processamento em thread separada
    import uuid
    task_id = str(uuid.uuid4())[:8]
    tarefas[task_id] = {
        "status": "coletando",
        "progresso": 10,
        "mensagem": "Abrindo navegador para coleta do Lattes...",
        "memorial_id": None,
        "erro": None,
        "_timestamp": time.time(),
    }

    thread = threading.Thread(
        target=_pipeline_memorial,
        args=(task_id, url_lattes),
        daemon=True,
    )
    thread.start()

    return render_template("loading.html", task_id=task_id)


@app.route("/status/<task_id>")
def status_tarefa(task_id):
    """Retorna o status da tarefa de geração (para polling via JS)."""
    tarefa = tarefas.get(task_id)
    if not tarefa:
        return jsonify({"status": "erro", "mensagem": "Tarefa não encontrada."}), 404
    return jsonify(tarefa)


@app.route("/memorial/<int:memorial_id>")
def ver_memorial(memorial_id):
    """Exibe o memorial gerado."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))
    return render_template("memorial.html", memorial=memorial)


@app.route("/memoriais")
def lista_memoriais():
    """Lista todos os memoriais salvos, com suporte a busca."""
    q = request.args.get("q", "").strip()
    if q:
        memoriais = buscar_memoriais_por_nome(q)
    else:
        memoriais = listar_memoriais()
    return render_template("memoriais.html", memoriais=memoriais, query=q)


@app.route("/memorial/<int:memorial_id>/editar", methods=["POST"])
def editar_memorial(memorial_id):
    """Atualiza o texto do memorial (edição manual)."""
    titulo = request.form.get("titulo")
    texto_principal = request.form.get("texto_principal")

    if atualizar_memorial(memorial_id, titulo=titulo, texto_principal=texto_principal):
        flash("Memorial atualizado com sucesso!", "sucesso")
    else:
        flash("Erro ao atualizar o memorial.", "erro")

    return redirect(url_for("ver_memorial", memorial_id=memorial_id))


@app.route("/memorial/<int:memorial_id>/deletar", methods=["POST"])
def remover_memorial(memorial_id):
    """Remove um memorial."""
    if deletar_memorial(memorial_id):
        flash("Memorial removido.", "info")
    else:
        flash("Memorial não encontrado.", "erro")
    return redirect(url_for("index"))


@app.route("/memorial/<int:memorial_id>/dados")
def ver_dados(memorial_id):
    """Exibe os dados brutos extraídos do Lattes (debug/transparência)."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))
    return render_template("dados.html", memorial=memorial)


# ── Pipeline ─────────────────────────────────────────

def _pipeline_memorial(task_id: str, url_lattes: str):
    """
    Pipeline completo de geração do memorial.
    Executado em thread separada.
    """
    try:
        # Etapa 1: Coleta
        tarefas[task_id]["status"] = "coletando"
        tarefas[task_id]["progresso"] = 20
        tarefas[task_id]["mensagem"] = (
            "Navegador aberto — resolva o CAPTCHA na janela do Chromium."
        )

        html = coletar_lattes(url_lattes)

        # Etapa 2: Parsing
        tarefas[task_id]["status"] = "extraindo"
        tarefas[task_id]["progresso"] = 50
        tarefas[task_id]["mensagem"] = "Extraindo dados do currículo..."

        dados = parse_lattes(html)
        nome = dados.get("nome", "Pesquisador(a)")
        print(f"[Pipeline] Dados extraídos para: {nome}")

        # Etapa 3: Geração
        tarefas[task_id]["status"] = "gerando"
        tarefas[task_id]["progresso"] = 70
        tarefas[task_id]["mensagem"] = (
            f"Gerando memorial para {nome} via Gemini API..."
        )

        resultado = gerar_memorial(dados)

        # Etapa 4: Salvamento
        tarefas[task_id]["status"] = "salvando"
        tarefas[task_id]["progresso"] = 90
        tarefas[task_id]["mensagem"] = "Salvando memorial no banco de dados..."

        memorial_id = salvar_memorial(nome, url_lattes, dados, resultado)

        # Concluído
        tarefas[task_id]["status"] = "concluido"
        tarefas[task_id]["progresso"] = 100
        tarefas[task_id]["mensagem"] = "Memorial gerado com sucesso!"
        tarefas[task_id]["memorial_id"] = memorial_id
        tarefas[task_id]["_timestamp"] = time.time()

    except Exception as e:
        print(f"[Pipeline] ✗ Erro: {e}")
        traceback.print_exc()
        tarefas[task_id]["status"] = "erro"
        tarefas[task_id]["progresso"] = 0
        tarefas[task_id]["mensagem"] = f"Erro: {str(e)}"
        tarefas[task_id]["erro"] = str(e)
        tarefas[task_id]["_timestamp"] = time.time()


# ── Iniciar ──────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Sistema de Memorial Digital")
    print("  PIBIC 2025/2026 — Monteiro & Maciel (UFMT/LAVI)")
    print("=" * 55)
    print(f"  Modelo: {config.GEMINI_MODEL}")
    print(f"  Banco:  {config.DATABASE_PATH}")
    print(f"  API:    {'✓ Configurada' if config.GEMINI_API_KEY and config.GEMINI_API_KEY != 'sua_chave_aqui' else '✗ Não configurada'}")
    print("=" * 55)
    app.run(debug=config.DEBUG, port=5000)
