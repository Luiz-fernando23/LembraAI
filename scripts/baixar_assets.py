"""Baixa assets SVG do Figma (URLs temporarias validas por 7 dias) para static/img/<tela>/."""
import os
import urllib.request

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img")

AMIGOS = "https://www.figma.com/api/mcp/asset/43aafac4-3eae-4266-9877-5fc6728e92e5"
CAD = "https://www.figma.com/api/mcp/asset/4da6b2d0-5903-4b7e-a1d6-4ab4520aac78"
DET = "https://www.figma.com/api/mcp/asset/f1826f73-9b08-44f9-9eb9-ca59382f9053"

# (tela, nome_arquivo, url)
ARQUIVOS = [
    # amigos (2:2070)
    ("amigos", "search.svg", AMIGOS + "/cc0ea.svg"),
    ("amigos", "chevron-right.svg", AMIGOS + "/612e8.svg"),
    ("amigos", "plus.svg", AMIGOS + "/80c03.svg"),
    ("amigos", "house.svg", AMIGOS + "/71463.svg"),
    ("amigos", "users.svg", AMIGOS + "/ff727.svg"),
    ("amigos", "bell.svg", AMIGOS + "/082e7.svg"),
    # cadastrar (2:2161)
    ("cadastrar", "arrow-left.svg", CAD + "/61e0d.svg"),
    ("cadastrar", "calendar.svg", CAD + "/6ee0f.svg"),
    ("cadastrar", "bell-ring.svg", CAD + "/485e2.svg"),
    ("cadastrar", "check.svg", CAD + "/bf953.svg"),
    # detalhe (2:2226)
    ("detalhe", "arrow-left.svg", DET + "/61e0d.svg"),
    ("detalhe", "heart.svg", DET + "/823f8.svg"),
    ("detalhe", "cake.svg", DET + "/27ab7.svg"),
    ("detalhe", "bell-ring.svg", DET + "/83472.svg"),
    ("detalhe", "book.svg", DET + "/f4b82.svg"),
    ("detalhe", "ellipsis.svg", DET + "/69f85.svg"),
    ("detalhe", "coffee.svg", DET + "/62dad.svg"),
    ("detalhe", "plus.svg", DET + "/a1cf4.svg"),
    # reutilizados em outras telas (mesmos icones do Figma)
    ("boas-vindas", "plus.svg", AMIGOS + "/80c03.svg"),
    ("boas-vindas", "bell.svg", AMIGOS + "/082e7.svg"),
    ("login", "bell.svg", AMIGOS + "/082e7.svg"),
    ("inicio", "bell.svg", AMIGOS + "/082e7.svg"),
    ("inicio", "house.svg", AMIGOS + "/71463.svg"),
    ("inicio", "users.svg", AMIGOS + "/ff727.svg"),
    ("inicio", "plus.svg", AMIGOS + "/80c03.svg"),
    ("lembretes", "bell-ring.svg", DET + "/83472.svg"),
    ("lembretes", "check.svg", CAD + "/bf953.svg"),
]

ok, falha = 0, 0
for tela, nome, url in ARQUIVOS:
    pasta = os.path.join(BASE, tela)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, nome)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LembraAI/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            corpo = resp.read()
        if not corpo or len(corpo) == 0:
            raise ValueError("resposta vazia")
        with open(destino, "wb") as f:
            f.write(corpo)
        print("OK %s/%s (%d bytes)" % (tela, nome, len(corpo)))
        ok += 1
    except Exception as e:  # noqa: BLE001
        print("FALHA %s/%s: %s" % (tela, nome, e))
        falha += 1
print("baixados=%d falhas=%d" % (ok, falha))
