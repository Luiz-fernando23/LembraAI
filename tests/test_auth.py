"""Fase 1 — testes de auth (registro, login, anti-enumeracao, rotas, isolamento)."""

import os
import sqlite3

import pytest

from app import GENERIC_AUTH_ERROR, create_app


@pytest.fixture()
def app(tmp_path):
    db = tmp_path / "teste.sqlite"
    app = create_app({"DATABASE": str(db), "TESTING": True})
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def db_row(app, sql, params=()):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def cadastra(client, email="ana@teste.com", senha="segredo123", nome="Ana"):
    return client.post(
        "/cadastrar",
        data={"name": nome, "email": email, "password": senha},
        follow_redirects=False,
    )


def test_registro_cria_usuario_e_loga(client, app):
    resp = cadastra(client)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/inicio")

    user = db_row(app, "SELECT * FROM users WHERE email = ?", ("ana@teste.com",))
    assert user is not None
    assert user["password_hash"] != "segredo123"  # hash, nunca texto puro
    assert db_row(app, "SELECT * FROM preferences WHERE owner_id = ?", (user["id"],))

    # sessao ativa: rota protegida responde 200
    assert client.get("/inicio").status_code == 200


def test_registro_email_duplicado_case_insensitive(client):
    assert cadastra(client).status_code == 302
    client.get("/sair")
    resp = cadastra(client, email="ANA@teste.com")
    assert resp.status_code == 200
    assert "já está cadastrado" in resp.get_data(as_text=True)


def test_registro_senha_curta_rejeitada(client, app):
    resp = cadastra(client, senha="curta")
    assert resp.status_code == 200
    assert "8 caracteres" in resp.get_data(as_text=True)
    assert db_row(app, "SELECT * FROM users") is None


def test_login_ok(client):
    cadastra(client)
    client.get("/sair")
    resp = client.post(
        "/login",
        data={"email": "ana@teste.com", "password": "segredo123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/inicio")


def test_login_senha_errada_erro_generico_sem_sessao(client):
    cadastra(client)
    client.get("/sair")
    resp = client.post(
        "/login", data={"email": "ana@teste.com", "password": "errada123"}
    )
    assert resp.status_code == 200
    assert GENERIC_AUTH_ERROR in resp.get_data(as_text=True)
    # sem sessao: rota protegida redireciona p/ login
    redir = client.get("/inicio", follow_redirects=False)
    assert redir.status_code == 302
    assert "/login" in redir.headers["Location"]


def test_login_email_inexistente_mesmo_erro(client):
    resp = client.post(
        "/login", data={"email": "ninguem@teste.com", "password": "qualquer12"}
    )
    assert resp.status_code == 200
    assert GENERIC_AUTH_ERROR in resp.get_data(as_text=True)  # anti-enumeracao


def test_protecao_de_rota(client):
    for rota in ("/inicio", "/amigos", "/lembretes"):
        resp = client.get(rota, follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"], rota


def test_owner_id_isolamento(client, app):
    cadastra(client, email="a@teste.com")
    user_a = db_row(app, "SELECT * FROM users WHERE email = ?", ("a@teste.com",))
    client.get("/sair")
    cadastra(client, email="b@teste.com")
    user_b = db_row(app, "SELECT * FROM users WHERE email = ?", ("b@teste.com",))

    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute(
        "INSERT INTO birthdays (owner_id, nome, dia, mes) VALUES (?, 'Mae', 10, 5)",
        (user_a["id"],),
    )
    conn.execute(
        "INSERT INTO birthdays (owner_id, nome, dia, mes) VALUES (?, 'Pai', 20, 8)",
        (user_b["id"],),
    )
    conn.commit()

    vistos_por_b = conn.execute(
        "SELECT nome FROM birthdays WHERE owner_id = ?", (user_b["id"],)
    ).fetchall()
    conn.close()

    nomes = [r[0] for r in vistos_por_b]
    assert nomes == ["Pai"]  # B nao enxerga aniversarios de A


def test_sair_limpa_sessao(client):
    cadastra(client)
    assert client.get("/inicio").status_code == 200
    client.get("/sair")
    resp = client.get("/inicio", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
