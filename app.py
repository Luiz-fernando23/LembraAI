"""LembraAI — Fase 2: 7 telas com fidelidade ao Figma (Flask + Jinja + sqlite3 stdlib)."""

import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    abort,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

GENERIC_AUTH_ERROR = "E-mail ou senha inválidos."
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HORA_RE = re.compile(r"^\d{2}:\d{2}$")

VINCULOS = ["Amizade", "Família", "Trabalho"]
ANTECEDENCIAS = ["No dia", "1 dia antes", "3 dias antes", "7 dias antes"]
ANTECEDENCIA_DIAS = {"No dia": 0, "1 dia antes": 1, "3 dias antes": 3, "7 dias antes": 7}

MESES_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
DIAS_SEMANA_PT = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]

AVATARES = ["#eae3f6", "#e5ebdf", "#f8e4db"]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["DATABASE"] = os.environ.get(
        "DATABASE", os.path.join(app.instance_path, "lembraai.sqlite")
    )
    if test_config:
        app.config.update(test_config)

    db_dir = os.path.dirname(app.config["DATABASE"])
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    if not os.path.exists(app.config["DATABASE"]):
        with app.app_context():
            init_db()

    app.teardown_appcontext(close_db)
    app.add_template_global(hora_sem_zero, "hora_sem_zero")

    @app.cli.command("init-db")
    def init_db_command():
        init_db()
        print("Banco inicializado.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Seed de demonstracao (idempotente): usuario Julia + 6 aniversarios."""
        seed_demo()
        print("Seed de demonstração pronto (demo@lembra.ai).")

    @app.route("/")
    def index():
        if current_user():
            return render_template("home.html", **contexto_home())
        return render_template("boas-vindas.html")

    @app.route("/boas-vindas")
    def boas_vindas():
        return render_template("boas-vindas.html")

    @app.route("/inicio")
    @login_required
    def inicio():
        return render_template("home.html", **contexto_home())

    @app.route("/amigos")
    @login_required
    def amigos():
        busca = (request.args.get("q") or "").strip()
        todos = aniversarios(current_user()["id"])
        if busca:
            todos = [a for a in todos if busca.lower() in a["nome"].lower()]
        grupos = agrupa_por_mes(todos)
        return render_template(
            "amigos.html",
            user=current_user(),
            ativa="amigos",
            busca=busca,
            grupos=grupos,
            total=len(aniversarios(current_user()["id"])),
        )

    @app.route("/lembretes", methods=["GET", "POST"])
    @login_required
    def lembretes():
        user = current_user()
        prefs = get_prefs(user["id"])
        salvo = False
        erro = None
        if request.method == "POST":
            ant = request.form.get("antecedencia") or ""
            hora = (request.form.get("hora") or "").strip()
            if ant not in ANTECEDENCIAS:
                erro = "Escolha uma antecedência válida."
            elif not HORA_RE.match(hora):
                erro = "Informe a hora no formato HH:MM."
            else:
                avisar = 1 if request.form.get("avisar") else 0
                no_dia = 1 if request.form.get("tambem_no_dia") else 0
                db = get_db()
                db.execute(
                    "UPDATE preferences SET antecedencia_padrao = ?, hora = ?,"
                    " avisar = ?, tambem_no_dia = ? WHERE owner_id = ?",
                    (ant, hora, avisar, no_dia, user["id"]),
                )
                db.commit()
                return redirect(url_for("lembretes", salvo="1"))
        prefs = get_prefs(user["id"])
        todos = aniversarios(user["id"])
        exemplo = todos[0] if todos else None
        return render_template(
            "lembretes.html",
            user=user,
            ativa="lembretes",
            prefs=prefs,
            erro=erro,
            salvo=bool(request.args.get("salvo")),
            exemplo=exemplo,
            antecedencias=ANTECEDENCIAS,
        )

    @app.route("/cadastrar", methods=["GET", "POST"])
    def cadastrar():
        # Compat: formulario de conta (name/email/password) continua funcionando
        # aqui; o fluxo novo usa /cadastrar-conta e o form de aniversario.
        if request.method == "POST" and "email" in request.form:
            return registrar_conta()
        if request.method == "POST":
            if current_user() is None:
                return redirect(url_for("login", next=request.path))
            return salvar_aniversario()
        if current_user() is None:
            return redirect(url_for("cadastrar_conta"))
        return render_template(
            "cadastrar-aniversario.html",
            user=current_user(),
            erro=None,
            valores={},
            vinculos=VINCULOS,
            antecedencias=ANTECEDENCIAS,
            antecedencia_padrao=get_prefs(current_user()["id"])["antecedencia_padrao"],
            hora_padrao=get_prefs(current_user()["id"])["hora"],
        )

    @app.route("/cadastrar-conta", methods=["GET", "POST"])
    def cadastrar_conta():
        if current_user():
            return redirect(url_for("inicio"))
        return registrar_conta()

    @app.route("/amiga/<int:bid>", methods=["GET", "POST"])
    @login_required
    def detalhe(bid):
        user = current_user()
        b = get_aniversario(user["id"], bid)
        if b is None:
            abort(404)
        erro_ideia = None
        if request.method == "POST":
            titulo = (request.form.get("titulo") or "").strip()
            anotacao = (request.form.get("anotacao") or "").strip()
            if not titulo:
                erro_ideia = "Dê um título para a ideia."
            else:
                db = get_db()
                db.execute(
                    "INSERT INTO gift_ideas (birthday_id, titulo, anotacao)"
                    " VALUES (?, ?, ?)",
                    (bid, titulo, anotacao or None),
                )
                db.commit()
                return redirect(url_for("detalhe", bid=bid))
        ideias = get_db().execute(
            "SELECT * FROM gift_ideas WHERE birthday_id = ? ORDER BY id", (bid,)
        ).fetchall()
        prefs = get_prefs(user["id"])
        return render_template(
            "detalhe.html",
            user=user,
            b=b,
            ideias=ideias,
            erro_ideia=erro_ideia,
            resumo=resumo_aviso(b["dia"], b["mes"], b["antecedencia"], prefs["hora"]),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user():
            return redirect(url_for("inicio"))
        erro = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            senha = request.form.get("password") or ""
            user = get_user_by_email(email)
            if user is None or not check_password_hash(user["password_hash"], senha):
                erro = GENERIC_AUTH_ERROR  # anti-enumeracao: mesma msg p/ ambos
            else:
                login_session(user)
                return redirect(request.args.get("next") or url_for("inicio"))
        return render_template(
            "auth/login.html", erro=erro, aviso=request.args.get("aviso")
        )

    @app.route("/sair", methods=["GET", "POST"])
    def sair():
        session.clear()
        return redirect(url_for("index"))

    return app


# --- banco (sqlite3 da stdlib, sem ORM) ---

def get_db():
    if "db" not in g:
        from flask import current_app

        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    from flask import current_app

    schema = os.path.join(current_app.root_path, "schema.sql")
    with open(schema, encoding="utf-8") as f:
        get_db().executescript(f.read())


# --- auth helpers ---

def get_user_by_email(email):
    row = (
        get_db()
        .execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))
        .fetchone()
    )
    return dict(row) if row else None


def current_user():
    if "user_id" not in session:
        return None
    row = (
        get_db()
        .execute("SELECT * FROM users WHERE id = ?", (session["user_id"],))
        .fetchone()
    )
    return dict(row) if row else None


def login_session(user):
    session.clear()
    session.permanent = True  # cookie de 30 dias (PERMANENT_SESSION_LIFETIME)
    session["user_id"] = user["id"]


def valida_cadastro(email, senha):
    if not email or not EMAIL_RE.match(email):
        return "Informe um e-mail válido."
    if len(senha) < 8:
        return "A senha deve ter no mínimo 8 caracteres."
    if get_user_by_email(email) is not None:
        return "Este e-mail já está cadastrado."
    return None


def registrar_conta():
    erro = None
    if request.method == "POST":
        nome = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = request.form.get("password") or ""
        erro = valida_cadastro(email, senha)
        if erro is None:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (email, password_hash, name)"
                    " VALUES (?, ?, ?)",
                    (email, generate_password_hash(senha), nome or None),
                )
                db.execute(
                    "INSERT INTO preferences (owner_id) VALUES (?)",
                    (cur.lastrowid,),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                erro = "Este e-mail já está cadastrado."
            else:
                login_session(get_user_by_email(email))
                return redirect(url_for("inicio"))
    return render_template("auth/cadastrar.html", erro=erro)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


# --- regras de data (travadas): idade so com ano; virada de ano; proximo = menor N ---

def data_segura(ano, mes, dia):
    """29/02 em ano nao bissexto cai para 28/02."""
    try:
        return date(ano, mes, dia)
    except ValueError:
        return date(ano, mes, 28)


def proxima_ocorrencia(dia, mes, hoje=None):
    hoje = hoje or date.today()
    data = data_segura(hoje.year, mes, dia)
    if data < hoje:
        data = data_segura(hoje.year + 1, mes, dia)
    return data


def dias_ate(dia, mes, hoje=None):
    hoje = hoje or date.today()
    return (proxima_ocorrencia(dia, mes, hoje) - hoje).days


def idade_no_aniversario(ano, dia, mes, hoje=None):
    """Idade que a pessoa vai fazer na proxima ocorrencia. So existe com ano."""
    if not ano:
        return None
    hoje = hoje or date.today()
    return proxima_ocorrencia(dia, mes, hoje).year - ano


def dia_mes_texto(dia, mes):
    return f"{dia} de {MESES_PT[mes]}"


def iniciais(nome):
    partes = [p for p in (nome or "").split() if p]
    return "".join(p[0] for p in partes[:2]).upper() or "?"


def cor_avatar(chave):
    return AVATARES[abs(hash(str(chave))) % len(AVATARES)]


def prazo_curto(n):
    if n == 0:
        return "hoje"
    if n == 1:
        return "amanhã"
    return f"em {n} dias"


def datas_aviso(dia, mes, antecedencia, hoje=None):
    """Datas em que avisamos: N dias antes + no dia (ou so no dia)."""
    hoje = hoje or date.today()
    niver = proxima_ocorrencia(dia, mes, hoje)
    antes = ANTECEDENCIA_DIAS.get(antecedencia, 3)
    if antes <= 0:
        return [niver]
    return [niver - timedelta(days=antes), niver]


def resumo_aviso(dia, mes, antecedencia, hora="09:00"):
    """Ex.: '15 e 18 de outubro, às 9h' (derivado de antecedencia + preferencias)."""
    datas = datas_aviso(dia, mes, antecedencia)
    if len(datas) == 1:
        base = dia_mes_texto(datas[0].day, datas[0].month)
    elif datas[0].month == datas[1].month:
        base = f"{datas[0].day} e {datas[1].day} de {MESES_PT[datas[1].month]}"
    else:
        base = (f"{datas[0].day} de {MESES_PT[datas[0].month]}"
                f" e {datas[1].day} de {MESES_PT[datas[1].month]}")
    return f"{base}, às {hora_sem_zero(hora)}"


def hora_sem_zero(hora):
    try:
        h, m = hora.split(":")
        texto = f"{int(h)}h" if m == "00" else f"{int(h)}h{m}"
        return texto
    except (ValueError, AttributeError):
        return hora


def texto_antecedencia(antecedencia):
    if antecedencia == "No dia":
        return "No dia"
    return f"{antecedencia} e no dia"


def aniversario_dict(row, hoje=None):
    hoje = hoje or date.today()
    n = dias_ate(row["dia"], row["mes"], hoje)
    prox = proxima_ocorrencia(row["dia"], row["mes"], hoje)
    neste_ano = data_segura(hoje.year, row["mes"], row["dia"])
    return {
        "id": row["id"],
        "nome": row["nome"],
        "dia": row["dia"],
        "mes": row["mes"],
        "ano": row["ano"],
        "vinculo": row["vinculo"],
        "antecedencia": row["antecedencia"] or "3 dias antes",
        "dias_ate": n,
        "prazo": prazo_curto(n),
        "data": prox,
        "data_texto": dia_mes_texto(prox.day, prox.month),
        "data_curta": f"{prox.day:02d} {MESES_PT[prox.month][:3]}",
        "semana": DIAS_SEMANA_PT[prox.weekday()],
        "semana_neste_ano": DIAS_SEMANA_PT[neste_ano.weekday()],
        "idade": idade_no_aniversario(row["ano"], row["dia"], row["mes"], hoje),
        "iniciais": iniciais(row["nome"]),
        "cor": cor_avatar(row["id"]),
    }


def aniversarios(owner_id, hoje=None):
    rows = (
        get_db()
        .execute(
            "SELECT * FROM birthdays WHERE owner_id = ? ORDER BY nome", (owner_id,)
        )
        .fetchall()
    )
    lista = [aniversario_dict(r, hoje) for r in rows]
    lista.sort(key=lambda a: a["dias_ate"])  # proximo = menor N
    return lista


def get_aniversario(owner_id, bid, hoje=None):
    row = (
        get_db()
        .execute(
            "SELECT * FROM birthdays WHERE id = ? AND owner_id = ?", (bid, owner_id)
        )
        .fetchone()
    )
    return aniversario_dict(row, hoje) if row else None


def agrupa_por_mes(lista):
    """Agrupa pela mes da proxima ocorrencia: [(rotulo, contagem, itens)]."""
    grupos = []
    for a in lista:
        chave = (a["data"].year, a["data"].month)
        if grupos and grupos[-1]["chave"] == chave:
            grupos[-1]["itens"].append(a)
        else:
            grupos.append({"chave": chave, "itens": [a]})
    saida = []
    for grp in grupos:
        mes = grp["chave"][1]
        n = len(grp["itens"])
        rotulo = MESES_PT[mes].capitalize()
        contagem = "1 aniversário" if n == 1 else f"{n} aniversários"
        saida.append({"mes": rotulo, "contagem": contagem, "itens": grp["itens"]})
    return saida


def get_prefs(owner_id):
    prefs = (
        get_db()
        .execute("SELECT * FROM preferences WHERE owner_id = ?", (owner_id,))
        .fetchone()
    )
    if prefs is None:
        get_db().execute("INSERT INTO preferences (owner_id) VALUES (?)", (owner_id,))
        get_db().commit()
        prefs = (
            get_db()
            .execute("SELECT * FROM preferences WHERE owner_id = ?", (owner_id,))
            .fetchone()
        )
    return dict(prefs)


def saudacao_data(hoje=None):
    hoje = hoje or date.today()
    linha = f"{DIAS_SEMANA_PT[hoje.weekday()]}, {hoje.day} de {MESES_PT[hoje.month]}"
    return linha.upper()


def primeiro_nome(user):
    if user.get("name"):
        return user["name"].split()[0]
    return (user["email"] or "").split("@")[0]


def contexto_home(hoje=None):
    user = current_user()
    lista = aniversarios(user["id"], hoje)
    proximo = lista[0] if lista else None
    mesmo_mes = []
    if proximo:
        mesmo_mes = [a for a in lista[1:] if a["data"].month == proximo["data"].month]
    n = len(lista)
    if n == 1:
        total_texto = "1 pessoa querida. Nenhuma data esquecida."
    else:
        total_texto = f"{n} pessoas queridas. Nenhuma data esquecida."
    prefs = get_prefs(user["id"])
    proximo, mesmo_mes = _destaques(lista)
    return {
        "user": user,
        "ativa": "inicio",
        "nome": primeiro_nome(user),
        "hoje": saudacao_data(hoje),
        "proximo": proximo,
        "mes_lista": mesmo_mes,
        "mes_nome": MESES_PT[proximo["data"].month] if proximo else "",
        "total_texto": total_texto,
        "hora": prefs["hora"],
        "lembrete_linha": _lembrete_linha(proximo, prefs["hora"]) if proximo else "",
    }


def _destaques(lista):
    if not lista:
        return None, []
    proximo = lista[0]
    mesmo_mes = [a for a in lista[1:] if a["data"].month == proximo["data"].month]
    return proximo, mesmo_mes


def _lembrete_linha(proximo, hora):
    base = f"às {hora_sem_zero(hora)}"
    antes = ANTECEDENCIA_DIAS.get(proximo["antecedencia"], 3)
    if antes <= 0:
        return f"Lembrete no dia, {base}"
    if proximo["dias_ate"] == antes:
        return f"Lembrete hoje e no dia, {base}"
    return f"Lembrete {proximo['antecedencia']} e no dia, {base}"


# --- telas de aniversario / seed ---

def salvar_aniversario():
    user = current_user()
    nome = (request.form.get("nome") or "").strip()
    dia = request.form.get("dia") or ""
    mes = request.form.get("mes") or ""
    ano_txt = (request.form.get("ano") or "").strip()
    vinculo = request.form.get("vinculo") or "Amizade"
    antecedencia = request.form.get("antecedencia") or "3 dias antes"
    erro = None
    try:
        dia_i, mes_i = int(dia), int(mes)
    except (TypeError, ValueError):
        dia_i = mes_i = None
    ano = None
    if ano_txt:
        try:
            ano = int(ano_txt)
        except ValueError:
            ano = -1
    if not nome:
        erro = "Dê um nome para esse alguém."
    elif dia_i is None or mes_i is None or not (1 <= mes_i <= 12 and 1 <= dia_i <= 31):
        erro = "Informe um dia e mês válidos."
    elif ano_txt and not (1900 <= (ano or 0) <= date.today().year):
        erro = "Informe um ano válido (ou deixe em branco)."
    elif vinculo not in VINCULOS:
        erro = "Escolha um vínculo válido."
    elif antecedencia not in ANTECEDENCIAS:
        erro = "Escolha quando quer lembrar."
    else:
        try:
            date(2024, mes_i, dia_i)  # valida dia real (2024 e bissexto: aceita 29/02)
        except ValueError:
            erro = "Informe um dia e mês válidos."
    if erro is not None:
        return render_template(
            "cadastrar-aniversario.html",
            user=user,
            erro=erro,
            valores={"nome": nome, "dia": dia, "mes": mes, "ano": ano_txt,
                     "vinculo": vinculo, "antecedencia": antecedencia},
            vinculos=VINCULOS,
            antecedencias=ANTECEDENCIAS,
            antecedencia_padrao=get_prefs(user["id"])["antecedencia_padrao"],
            hora_padrao=get_prefs(user["id"])["hora"],
        )
    db = get_db()
    cur = db.execute(
        "INSERT INTO birthdays (owner_id, nome, dia, mes, ano, vinculo, antecedencia)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["id"], nome, dia_i, mes_i, ano, vinculo, antecedencia),
    )
    db.commit()
    return redirect(url_for("detalhe", bid=cur.lastrowid))


def seed_demo():
    """Cria usuario demo + 6 aniversarios + ideias da Ana. Idempotente."""
    db = get_db()
    user = get_user_by_email("demo@lembra.ai")
    if user is None:
        cur = db.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            ("demo@lembra.ai", generate_password_hash("lembra123"), "Júlia"),
        )
        db.execute("INSERT INTO preferences (owner_id) VALUES (?)", (cur.lastrowid,))
        db.commit()
        user = get_user_by_email("demo@lembra.ai")
    existentes = {
        r[0]
        for r in db.execute(
            "SELECT nome FROM birthdays WHERE owner_id = ?", (user["id"],)
        ).fetchall()
    }
    seed = [
        ("Ana Costa", 18, 10, 1998, "Amizade", "3 dias antes"),
        ("Bruno Lima", 24, 10, None, "Trabalho", "3 dias antes"),
        ("Clara Alves", 30, 10, None, "Família", "3 dias antes"),
        ("Diego Santos", 12, 11, None, "Amizade", "3 dias antes"),
        ("Luiza Martins", 21, 11, None, "Família", "3 dias antes"),
        ("Rafael Melo", 3, 12, None, "Trabalho", "3 dias antes"),
    ]
    ids = {}
    for nome, dia, mes, ano, vinculo, ant in seed:
        if nome in existentes:
            row = db.execute(
                "SELECT id FROM birthdays WHERE owner_id = ? AND nome = ?",
                (user["id"], nome),
            ).fetchone()
            ids[nome] = row[0]
            continue
        cur = db.execute(
            "INSERT INTO birthdays (owner_id, nome, dia, mes, ano, vinculo,"
            " antecedencia) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], nome, dia, mes, ano, vinculo, ant),
        )
        ids[nome] = cur.lastrowid
    ana_id = ids["Ana Costa"]
    n_ideias = db.execute(
        "SELECT COUNT(*) FROM gift_ideas WHERE birthday_id = ?", (ana_id,)
    ).fetchone()[0]
    if n_ideias == 0:
        db.execute(
            "INSERT INTO gift_ideas (birthday_id, titulo, anotacao) VALUES (?, ?, ?)",
            (ana_id, "Um livro da lista dela",
             "Ela comentou sobre A biblioteca da meia-noite."),
        )
        db.execute(
            "INSERT INTO gift_ideas (birthday_id, titulo, anotacao) VALUES (?, ?, ?)",
            (ana_id, "Café da manhã juntas", "Na padaria da esquina, sem pressa."),
        )
    db.commit()


app = create_app()
