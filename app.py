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
    moderar_tributo, deletar_tributo, contar_tributos_pendentes, \
    adicionar_foto, listar_fotos, deletar_foto, atualizar_legenda_foto, \
    convidar_colaborador, listar_colaboradores, buscar_colaborador_por_token, \
    aceitar_convite, revogar_colaborador
from modules.sources import coletar_lattes_completo, processar_export_linkedin, \
    coletar_escavador
from modules.sources.manual import construir_dados_manuais, construir_dados_de_json
from modules.generator import gerar_memorial, sugerir_tributos

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


@app.route("/gerar_linkedin", methods=["POST"])
def gerar_linkedin():
    """Inicia o pipeline a partir do ZIP exportado do LinkedIn."""
    arquivo = request.files.get("linkedin_zip")
    if not arquivo or not arquivo.filename:
        flash("Envie o ZIP do export do LinkedIn.", "erro")
        return redirect(url_for("criar"))

    if not arquivo.filename.lower().endswith(".zip"):
        flash("O arquivo deve ser um ZIP (.zip).", "erro")
        return redirect(url_for("criar"))

    memorial_status = request.form.get("memorial_status", "ativo")
    data_nascimento = request.form.get("data_nascimento") or None
    data_falecimento = request.form.get("data_falecimento") or None

    try:
        dados = processar_export_linkedin(arquivo)
    except ValueError as e:
        flash(f"Erro no ZIP: {e}", "erro")
        return redirect(url_for("criar"))
    except Exception as e:
        print(f"[LinkedIn] ✗ {e}")
        flash(f"Erro ao processar export: {e}", "erro")
        return redirect(url_for("criar"))

    return _iniciar_pipeline(
        fonte="linkedin", origem="export_oficial",
        dados_pre_coletados=dados,
        memorial_status=memorial_status,
        data_nascimento=data_nascimento,
        data_falecimento=data_falecimento,
    )


@app.route("/gerar_escavador", methods=["POST"])
def gerar_escavador():
    """Inicia o pipeline a partir da API do Escavador (sem CAPTCHA)."""
    query = (request.form.get("query") or "").strip()
    if not query:
        flash("Informe o nome ou ID Lattes para buscar no Escavador.", "erro")
        return redirect(url_for("criar"))

    memorial_status = request.form.get("memorial_status", "ativo")
    data_nascimento = request.form.get("data_nascimento") or None
    data_falecimento = request.form.get("data_falecimento") or None

    try:
        dados = coletar_escavador(query)
    except ValueError as e:
        flash(str(e), "erro")
        return redirect(url_for("criar"))
    except Exception as e:
        print(f"[Escavador] ✗ {e}")
        flash(f"Erro ao consultar Escavador: {e}", "erro")
        return redirect(url_for("criar"))

    return _iniciar_pipeline(
        fonte="escavador", origem=query,
        dados_pre_coletados=dados,
        memorial_status=memorial_status,
        data_nascimento=data_nascimento,
        data_falecimento=data_falecimento,
    )


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

    # Privacidade: memoriais privados só são acessíveis com chave
    if memorial.get("visibilidade") == "privado":
        chave = request.args.get("k", "")
        if chave != f"k{memorial_id * 7919}":  # placeholder simples
            flash("Este memorial é privado.", "erro")
            return redirect(url_for("index"))

    # Modo moderador: ?mod=1 ativa ferramentas de edição/configuração
    # OU acesso por token de colaborador (?col=<token>)
    # Embasamento: separação entre visualização e curadoria
    # (Trevisan et al., 2021; Verhalen et al., 2021).
    # Brubaker et al. (2013) — papéis em memoriais.
    is_moderador = request.args.get("mod") == "1"
    col_token = request.args.get("col", "")
    colaborador = None
    if col_token:
        colaborador = buscar_colaborador_por_token(col_token)
        # Token só vale para o memorial certo
        if colaborador and colaborador["memorial_id"] == memorial_id:
            if colaborador["status"] == "pendente":
                aceitar_convite(col_token)
            # Colaborador com papel "moderador" tem acesso completo
            if colaborador["papel"] == "moderador":
                is_moderador = True
        else:
            colaborador = None

    tributos = listar_tributos(memorial_id, apenas_aprovados=True)
    pendentes = contar_tributos_pendentes(memorial_id) if is_moderador else 0
    fotos = listar_fotos(memorial_id)
    return render_template("memorial.html", memorial=memorial,
                           tributos=tributos, is_moderador=is_moderador,
                           tributos_pendentes=pendentes, fotos=fotos,
                           colaborador=colaborador)


@app.route("/memorial/<int:memorial_id>/painel")
def painel_memorial(memorial_id):
    """
    Painel administrativo do memorial — central de moderação.
    Substitui o "modo moderador" sobreposto à página do visitante:
    aqui o moderador tem todas as ações em uma tela limpa, sem
    repetir o conteúdo do memorial.

    Embasamento: Trevisan et al. (2021) — separação clara entre
    visualização e curadoria. Brubaker et al. (2013) — papéis em
    memoriais.
    """
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    pendentes = contar_tributos_pendentes(memorial_id)
    fotos = listar_fotos(memorial_id)
    colaboradores = listar_colaboradores(memorial_id)

    return render_template(
        "painel.html",
        memorial=memorial,
        tributos_pendentes=pendentes,
        total_fotos=len(fotos),
        total_colaboradores=len(colaboradores),
    )


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
            auto_aprovar_tributos=1 if request.form.get("auto_aprovar_tributos") else 0,
        )
        flash("Privacidade atualizada.", "sucesso")
        return redirect(url_for("painel_memorial", memorial_id=memorial_id))

    return render_template("configurar.html", memorial=memorial)


@app.route("/memorial/<int:memorial_id>/colaboradores", methods=["GET", "POST"])
def colaboradores_memorial(memorial_id):
    """
    Página de gestão de colaboradores.
    Embasamento: plano de trabalho — painel de revisão colaborativa que
    permite a familiares validar/ajustar homenagens. Verhalen et al. (2021)
    sobre design participativo. Brubaker et al. (2013) sobre papéis.
    """
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip()
        papel = request.form.get("papel", "colaborador")

        if not email or "@" not in email:
            flash("Informe um e-mail válido.", "erro")
            return redirect(url_for("colaboradores_memorial",
                                    memorial_id=memorial_id))

        _id, token = convidar_colaborador(memorial_id, email, papel, nome)
        # Constrói o link mágico — o usuário copia e envia manualmente
        link = url_for("ver_memorial", memorial_id=memorial_id,
                       col=token, _external=True)
        flash(
            f"✓ Convite criado para {email}. "
            f"Copie o link abaixo e envie a essa pessoa.",
            "sucesso"
        )
        # Passa o link via query para mostrar destacado
        return redirect(url_for("colaboradores_memorial",
                                memorial_id=memorial_id,
                                novo_link=link, novo_email=email))

    colaboradores = listar_colaboradores(memorial_id)
    novo_link = request.args.get("novo_link")
    novo_email = request.args.get("novo_email")
    return render_template("colaboradores.html", memorial=memorial,
                           colaboradores=colaboradores,
                           novo_link=novo_link, novo_email=novo_email)


@app.route("/colaborador/<int:colaborador_id>/revogar", methods=["POST"])
def revogar_colaborador_route(colaborador_id):
    """Revoga acesso de um colaborador."""
    memorial_id = int(request.form.get("memorial_id", 0))
    if revogar_colaborador(colaborador_id):
        flash("Acesso revogado.", "info")
    return redirect(url_for("colaboradores_memorial", memorial_id=memorial_id))


@app.route("/memorial/<int:memorial_id>/galeria", methods=["GET", "POST"])
def galeria_memorial(memorial_id):
    """
    Página de gestão da galeria de fotos.
    Embasamento: plano de trabalho — coleta multimodal (texto + imagem).
    Walter (2015) — luto contemporâneo é multimídia.
    """
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        flash("Memorial não encontrado.", "erro")
        return redirect(url_for("index"))

    if request.method == "POST":
        # Upload de uma ou múltiplas fotos
        arquivos = request.files.getlist("fotos")
        legenda_default = (request.form.get("legenda") or "").strip()
        adicionadas = 0
        for arq in arquivos:
            if arq and arq.filename:
                url = _salvar_foto_upload(arq)
                if url:
                    adicionar_foto(memorial_id, url, legenda_default)
                    adicionadas += 1
        if adicionadas:
            flash(f"{adicionadas} foto(s) adicionada(s) à galeria.", "sucesso")
        else:
            flash("Nenhuma foto válida enviada (use jpg/png/webp/gif).", "erro")
        return redirect(url_for("galeria_memorial", memorial_id=memorial_id))

    fotos = listar_fotos(memorial_id)
    return render_template("galeria.html", memorial=memorial, fotos=fotos)


@app.route("/foto/<int:foto_id>/deletar", methods=["POST"])
def remover_foto(foto_id):
    """Remove uma foto da galeria."""
    memorial_id = int(request.form.get("memorial_id", 0))
    if deletar_foto(foto_id):
        flash("Foto removida.", "info")
    return redirect(url_for("galeria_memorial", memorial_id=memorial_id))


@app.route("/foto/<int:foto_id>/legenda", methods=["POST"])
def editar_legenda_foto(foto_id):
    """Atualiza a legenda de uma foto."""
    memorial_id = int(request.form.get("memorial_id", 0))
    legenda = request.form.get("legenda", "")
    if atualizar_legenda_foto(foto_id, legenda):
        flash("Legenda atualizada.", "sucesso")
    return redirect(url_for("galeria_memorial", memorial_id=memorial_id))


@app.route("/memorial/<int:memorial_id>/sugerir-tributos", methods=["POST"])
def api_sugerir_tributos(memorial_id):
    """
    Retorna JSON com sugestões de mensagens de tributo geradas pela IA.
    Embasamento: plano de trabalho — composição assistida (Monteiro et al.).
    """
    memorial = buscar_memorial(memorial_id)
    if not memorial:
        return jsonify({"erro": "Memorial não encontrado"}), 404

    relacao = ""
    if request.is_json:
        relacao = (request.json or {}).get("relacao", "")
    if not relacao:
        relacao = request.form.get("relacao", "")
    sugestoes = sugerir_tributos(memorial, relacao.strip(), n=3)
    if not sugestoes:
        return jsonify({"erro": "Não foi possível gerar sugestões agora"}), 503
    return jsonify({"sugestoes": sugestoes})


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

    auto = bool(memorial.get("auto_aprovar_tributos"))
    _id, status_final = adicionar_tributo(memorial_id, autor, mensagem,
                                          auto_aprovar=auto)
    if status_final == "aprovado":
        flash("Mensagem publicada!", "sucesso")
    else:
        flash(
            "Mensagem recebida! Aguardando moderação do criador do memorial "
            "antes de aparecer publicamente.",
            "info"
        )
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

        # Destaques dinâmicos (substituem as antigas "seções")
        destaques = []
        idx = 0
        tipos_validos = {"premio", "projeto", "formacao", "atuacao",
                         "producao", "legado"}
        while True:
            tipo = request.form.get(f"destaque_tipo_{idx}")
            titulo = request.form.get(f"destaque_titulo_{idx}")
            descricao = request.form.get(f"destaque_descricao_{idx}")
            ano = request.form.get(f"destaque_ano_{idx}")
            # Sai do loop quando não há mais campos
            if (tipo is None and titulo is None and
                    descricao is None and ano is None):
                break
            if titulo and titulo.strip():
                t_lim = (tipo or "legado").strip().lower()
                if t_lim not in tipos_validos:
                    t_lim = "legado"
                destaques.append({
                    "tipo": t_lim,
                    "titulo": titulo.strip()[:200],
                    "descricao": (descricao or "").strip()[:300],
                    "ano": (ano or "").strip()[:20],
                })
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
            "destaques": destaques,
            "data_nascimento": data_nascimento,
            "data_falecimento": data_falecimento,
        }
        if foto_url is not None:
            kwargs["foto_url"] = foto_url

        if atualizar_memorial(memorial_id, **kwargs):
            flash("Memorial atualizado com sucesso!", "sucesso")
        else:
            flash("Nenhuma alteração foi feita.", "info")

        return redirect(url_for("painel_memorial", memorial_id=memorial_id))

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
            destaques=resultado.get("destaques"),
        )
        flash("Memorial regenerado com sucesso!", "sucesso")
    except Exception as e:
        print(f"[Regenerar] ✗ Erro: {e}")
        flash(f"Erro ao regenerar: {e}", "erro")

    return redirect(url_for("painel_memorial", memorial_id=memorial_id))


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
    print("  PIBIC 2025/2026 — UFMT/LAVI")
    print("=" * 55)
    print(f"  Provider: {config.LLM_PROVIDER}")
    if config.LLM_PROVIDER == "gemini":
        ok = config.GEMINI_API_KEY and config.GEMINI_API_KEY != "sua_chave_aqui"
        print(f"  Modelo:   {config.GEMINI_MODEL}")
        print(f"  API key:  {'✓ Configurada' if ok else '✗ NÃO configurada — pegue em https://aistudio.google.com/apikey'}")
    else:
        print(f"  Modelo:   {config.OLLAMA_MODEL}")
        print(f"  URL:      {config.OLLAMA_BASE_URL}")
    print(f"  Banco:    {config.DATABASE_PATH}")
    print("=" * 55)
    app.run(debug=config.DEBUG, port=5000)
