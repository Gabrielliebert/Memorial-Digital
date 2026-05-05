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
    atualizar_memorial, deletar_memorial, buscar_memoriais_por_nome, \
    atualizar_configuracao_memorial, adicionar_tributo, listar_tributos, \
    moderar_tributo, deletar_tributo
from modules.sources import coletar_lattes_completo
from modules.sources.manual import construir_dados_manuais, construir_dados_de_json
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
    """Landing: escolha entre buscar ou criar memorial."""
    memoriais = listar_memoriais()
    return render_template("index.html", memoriais=memoriais,
                           total_memoriais=len(memoriais))


@app.route("/criar")
def criar():
    """Página unificada de criação (Lattes ou Manual com tabs)."""
    return render_template("criar.html")


@app.route("/gerar", methods=["POST"])
def gerar():
    """Inicia o pipeline de geração via Lattes."""
    url_lattes = request.form.get("url_lattes", "").strip()
    memorial_status = request.form.get("memorial_status", "ativo")
    data_nascimento = request.form.get("data_nascimento") or None
    data_falecimento = request.form.get("data_falecimento") or None

    if not url_lattes:
        flash("Por favor, insira a URL do currículo Lattes.", "erro")
        return redirect(url_for("index"))

    if "lattes.cnpq" not in url_lattes and "localhost" not in url_lattes:
        flash("A URL deve ser de um currículo Lattes (lattes.cnpq.br).", "erro")
        return redirect(url_for("index"))

    return _iniciar_pipeline(
        fonte="lattes", origem=url_lattes,
        memorial_status=memorial_status,
        data_nascimento=data_nascimento,
        data_falecimento=data_falecimento,
    )


@app.route("/manual", methods=["GET"])
def formulario_manual():
    """Compat: redireciona para /criar (URL antiga)."""
    return redirect(url_for("criar"))


@app.route("/gerar_manual", methods=["POST"])
def gerar_manual():
    """Inicia o pipeline a partir de dados informados manualmente."""
    payload_json = (request.form.get("dados_json") or "").strip()
    memorial_status = request.form.get("memorial_status", "ativo")
    data_nascimento = request.form.get("data_nascimento") or None
    data_falecimento = request.form.get("data_falecimento") or None

    try:
        if payload_json:
            dados = construir_dados_de_json(payload_json)
        else:
            dados = construir_dados_manuais(request.form)
    except ValueError as e:
        flash(f"Erro nos dados: {e}", "erro")
        return redirect(url_for("criar"))

    # Foto opcional do upload
    foto_url = None
    if "foto" in request.files:
        arquivo = request.files["foto"]
        if arquivo and arquivo.filename:
            foto_url = _salvar_foto_upload(arquivo)
            if foto_url:
                dados["foto_url"] = foto_url

    return _iniciar_pipeline(
        fonte="manual", origem="formulario",
        dados_pre_coletados=dados,
        memorial_status=memorial_status,
        data_nascimento=data_nascimento,
        data_falecimento=data_falecimento,
    )


def _salvar_foto_upload(arquivo) -> str | None:
    """Salva uma foto enviada e retorna a URL relativa."""
    import uuid
    from werkzeug.utils import secure_filename

    extensoes_ok = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    nome_seguro = secure_filename(arquivo.filename or "")
    if not nome_seguro:
        return None

    ext = os.path.splitext(nome_seguro)[1].lower()
    if ext not in extensoes_ok:
        return None

    pasta = os.path.join(os.path.dirname(__file__), "static", "uploads")
    os.makedirs(pasta, exist_ok=True)
    nome_unico = f"{uuid.uuid4().hex[:12]}{ext}"
    caminho = os.path.join(pasta, nome_unico)
    arquivo.save(caminho)
    return url_for("static", filename=f"uploads/{nome_unico}")


def _iniciar_pipeline(fonte: str, origem: str, dados_pre_coletados: dict = None,
                      memorial_status: str = "ativo",
                      data_nascimento: str = None,
                      data_falecimento: str = None):
    """Cria a tarefa e dispara a thread do pipeline."""
    _limpar_tarefas_antigas()

    import uuid
    task_id = str(uuid.uuid4())[:8]
    tarefas[task_id] = {
        "status": "coletando" if not dados_pre_coletados else "extraindo",
        "progresso": 10 if not dados_pre_coletados else 50,
        "mensagem": (
            "Abrindo navegador para coleta do Lattes..."
            if not dados_pre_coletados
            else "Processando dados informados..."
        ),
        "memorial_id": None,
        "erro": None,
        "fonte": fonte,
        "memorial_status": memorial_status,
        "_timestamp": time.time(),
    }

    thread = threading.Thread(
        target=_pipeline_memorial,
        args=(task_id, fonte, origem, dados_pre_coletados,
              memorial_status, data_nascimento, data_falecimento),
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
    """Exibe o memorial gerado, respeitando configuração de visibilidade."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    # Privacidade: memoriais privados só são acessíveis com chave (futuro: auth real)
    if memorial.get("visibilidade") == "privado":
        chave = request.args.get("k", "")
        if chave != f"k{memorial_id * 7919}":  # placeholder simples
            flash("Este memorial é privado.", "erro")
            return redirect(url_for("index"))

    tributos = listar_tributos(memorial_id, apenas_aprovados=True)
    return render_template("memorial.html", memorial=memorial, tributos=tributos)


@app.route("/memorial/<int:memorial_id>/configurar", methods=["GET", "POST"])
def configurar_memorial(memorial_id):
    """UI de configuração: privacidade, status, gestor de legado."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        atualizar_configuracao_memorial(
            memorial_id,
            visibilidade=request.form.get("visibilidade", "publico"),
            memorial_status=request.form.get("memorial_status", "ativo"),
            legacy_manager_email=request.form.get("legacy_manager_email", "").strip() or None,
            consentimento=1 if request.form.get("consentimento") else 0,
            permitir_tributos=1 if request.form.get("permitir_tributos") else 0,
        )
        flash("Configurações atualizadas.", "sucesso")
        return redirect(url_for("configurar_memorial", memorial_id=memorial_id))

    return render_template("configurar.html", memorial=memorial)


@app.route("/memorial/<int:memorial_id>/tributo", methods=["POST"])
def enviar_tributo(memorial_id):
    """Recebe um tributo (entra em moderação antes de aparecer)."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    if not memorial.get("permitir_tributos", 1):
        flash("Este memorial não está aceitando tributos.", "info")
        return redirect(url_for("ver_memorial", memorial_id=memorial_id))

    autor = (request.form.get("autor") or "").strip()
    mensagem = (request.form.get("mensagem") or "").strip()

    if not autor or not mensagem:
        flash("Informe seu nome e mensagem.", "erro")
        return redirect(url_for("ver_memorial", memorial_id=memorial_id))

    if len(mensagem) > 1000:
        flash("Mensagem muito longa (máx. 1000 caracteres).", "erro")
        return redirect(url_for("ver_memorial", memorial_id=memorial_id))

    adicionar_tributo(memorial_id, autor, mensagem)
    flash("Tributo recebido! Aguardando moderação antes de ser publicado.", "sucesso")
    return redirect(url_for("ver_memorial", memorial_id=memorial_id))


@app.route("/memorial/<int:memorial_id>/tributos/moderar")
def moderar_tributos(memorial_id):
    """Painel de moderação de tributos (acesso simples por enquanto)."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    todos = listar_tributos(memorial_id, apenas_aprovados=False)
    return render_template("moderar.html", memorial=memorial, tributos=todos)


@app.route("/tributo/<int:tributo_id>/<acao>", methods=["POST"])
def acao_tributo(tributo_id, acao):
    """Aprova, rejeita ou remove um tributo."""
    memorial_id = int(request.form.get("memorial_id", 0))
    if acao == "aprovar":
        moderar_tributo(tributo_id, "aprovado")
        flash("Tributo aprovado e publicado.", "sucesso")
    elif acao == "rejeitar":
        moderar_tributo(tributo_id, "rejeitado")
        flash("Tributo rejeitado.", "info")
    elif acao == "deletar":
        deletar_tributo(tributo_id)
        flash("Tributo removido.", "info")
    else:
        flash("Ação inválida.", "erro")

    if memorial_id:
        return redirect(url_for("moderar_tributos", memorial_id=memorial_id))
    return redirect(url_for("index"))


@app.route("/memoriais")
def lista_memoriais():
    """Lista todos os memoriais salvos, com suporte a busca."""
    q = request.args.get("q", "").strip()
    if q:
        memoriais = buscar_memoriais_por_nome(q)
    else:
        memoriais = listar_memoriais()
    return render_template("memoriais.html", memoriais=memoriais, query=q)


@app.route("/memorial/<int:memorial_id>/editar", methods=["GET", "POST"])
def editar_memorial(memorial_id):
    """Edição completa: nome, texto, datas, foto, seções."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        # Coletar campos
        nome = (request.form.get("nome") or "").strip()
        titulo = request.form.get("titulo")
        texto_principal = request.form.get("texto_principal")
        data_nascimento = request.form.get("data_nascimento") or ""
        data_falecimento = request.form.get("data_falecimento") or ""

        # Seções dinâmicas
        secoes = []
        idx = 0
        while True:
            t = request.form.get(f"secao_titulo_{idx}")
            c = request.form.get(f"secao_conteudo_{idx}")
            if t is None and c is None:
                break
            if t and c:
                secoes.append({"titulo": t.strip(), "conteudo": c.strip()})
            idx += 1

        # Foto: upload novo, manter, ou limpar
        foto_acao = request.form.get("foto_acao", "manter")
        foto_url = None
        if foto_acao == "upload" and "foto" in request.files:
            arquivo = request.files["foto"]
            if arquivo and arquivo.filename:
                nova = _salvar_foto_upload(arquivo)
                if nova:
                    foto_url = nova
        elif foto_acao == "url":
            foto_url = (request.form.get("foto_url_externa") or "").strip() or ""
        elif foto_acao == "remover":
            foto_url = ""
        # Se foto_acao == "manter", não passa o argumento (mantém atual)

        kwargs = {
            "nome": nome or None,
            "titulo": titulo,
            "texto_principal": texto_principal,
            "secoes": secoes,
            "data_nascimento": data_nascimento,
            "data_falecimento": data_falecimento,
        }
        if foto_url is not None:
            kwargs["foto_url"] = foto_url

        if atualizar_memorial(memorial_id, **kwargs):
            flash("Memorial atualizado com sucesso!", "sucesso")
        else:
            flash("Nenhuma alteração foi feita.", "info")

        return redirect(url_for("ver_memorial", memorial_id=memorial_id))

    return render_template("editar.html", memorial=memorial)


@app.route("/memorial/<int:memorial_id>/regenerar", methods=["POST"])
def regenerar_memorial(memorial_id):
    """Regenera o texto do memorial usando os dados originais armazenados."""
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    dados = memorial.get("dados", {})
    if not dados:
        flash("Dados originais não disponíveis para regenerar.", "erro")
        return redirect(url_for("ver_memorial", memorial_id=memorial_id))

    try:
        resultado = gerar_memorial(dados, status=memorial.get("memorial_status", "ativo"))
        atualizar_memorial(
            memorial_id,
            titulo=resultado.get("titulo"),
            texto_principal=resultado.get("texto_principal"),
            secoes=resultado.get("secoes"),
        )
        flash("Memorial regenerado com sucesso!", "sucesso")
    except Exception as e:
        print(f"[Regenerar] ✗ Erro: {e}")
        flash(f"Erro ao regenerar: {e}", "erro")

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

def _pipeline_memorial(task_id: str, fonte: str, origem: str,
                       dados_pre_coletados: dict = None,
                       memorial_status: str = "ativo",
                       data_nascimento: str = None,
                       data_falecimento: str = None):
    """Pipeline completo de geração. Executado em thread separada."""
    try:
        if dados_pre_coletados is not None:
            dados = dados_pre_coletados
        else:
            tarefas[task_id]["status"] = "coletando"
            tarefas[task_id]["progresso"] = 20
            tarefas[task_id]["mensagem"] = (
                "Navegador aberto — resolva o CAPTCHA na janela do Chromium."
            )
            dados = coletar_lattes_completo(origem)

            tarefas[task_id]["status"] = "extraindo"
            tarefas[task_id]["progresso"] = 50
            tarefas[task_id]["mensagem"] = "Extraindo dados do currículo..."

        nome = dados.get("nome", "Pesquisador(a)")
        print(f"[Pipeline] Dados ({fonte}) preparados para: {nome} | status={memorial_status}")

        tarefas[task_id]["status"] = "gerando"
        tarefas[task_id]["progresso"] = 70
        tarefas[task_id]["mensagem"] = f"Gerando memorial para {nome}..."

        resultado = gerar_memorial(dados, status=memorial_status)

        tarefas[task_id]["status"] = "salvando"
        tarefas[task_id]["progresso"] = 90
        tarefas[task_id]["mensagem"] = "Salvando memorial no banco de dados..."

        memorial_id = salvar_memorial(
            nome, origem, dados, resultado,
            memorial_status=memorial_status,
            data_nascimento=data_nascimento,
            data_falecimento=data_falecimento,
        )

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
