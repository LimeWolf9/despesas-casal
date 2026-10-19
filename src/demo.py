"""
Cria data/demo.db com seis meses de movimentos inventados, para experimentar a app sem extractos.

    python src/demo.py
    DESPESAS_DB=data/demo.db streamlit run app.py          (Windows: set DESPESAS_DB=data\\demo.db)

Nada aqui é real: comerciantes genéricos, valores sorteados com semente fixa (dá sempre o mesmo).
Os descritivos batem com as regras de exemplo em config/categorias.exemplo.yaml; dois ficam de propósito
por categorizar, para se ver a fila a funcionar.
"""

from __future__ import annotations

import random
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from categorizador import Categorizador          # noqa: E402
from db import ligar, guardar_extracto           # noqa: E402
from parser import Extracto, Movimento           # noqa: E402

DEMO = RAIZ / "data" / "demo.db"
MESES = [(2026, m) for m in range(4, 10)]        # abril a setembro de 2026

# (dia, descritivo, valor mínimo, valor máximo). Negativo = saída.
FIXOS = [
    (1, "TRF A CREDITO SEPA+ - EMPRESA EXEMPLO", 2900, 2900),
    (2, "EMPRESTIMO 00000000000-COB", -550, -550),
    (5, "DD EDP COMERCIAL", -60, -95),
    (8, "DD VODAFONE", -45, -45),
    (28, "COMISSAO MANUTENCAO CONTA", -5, -5),
]
VARIAVEIS = [
    ("COMPRA 1234567 MERCADONA", -25, -90, 4),
    ("COMPRA 1234567 CONTINENTE", -15, -70, 3),
    ("COMPRA 1234567 LIDL", -10, -40, 2),
    ("COMPRA 1234567 UBER EATS", -12, -30, 2),
    ("COMPRA 1234567 RESTAURANTE EXEMPLO", -20, -60, 2),
    ("COMPRA 1234567 GALP", -40, -65, 2),
    ("DD VIA VERDE", -8, -30, 1),
    ("COMPRA 1234567 FARMACIA CENTRAL", -6, -25, 1),
    ("COMPRA 1234567 CINEMAS", -12, -20, 1),
]
OCASIONAIS = {
    5: [(12, "COMPRA 1234567 IKEA", -180), (20, "COMPRA 1234567 LEROY MERLIN", -64)],
    6: [(15, "PAGAMENTO DE SEGUROS", -420)],
    8: [(3, "COMPRA 1234567 BOOKING.COM", -310), (22, "COMPRA 1234567 LOJA DESCONHECIDA", -37)],
    9: [(18, "TRANSF IMEDIATA P/ FULANO", -50)],
}


def movimentos_do_mes(ano: int, mes: int, rnd: random.Random) -> list[tuple[int, str, Decimal]]:
    linhas = []
    for dia, desc, a, b in FIXOS:
        linhas.append((dia, desc, Decimal(str(round(rnd.uniform(a, b), 2)))))
    for desc, a, b, vezes in VARIAVEIS:
        for _ in range(vezes):
            linhas.append((rnd.randint(1, 28), desc, Decimal(str(round(rnd.uniform(a, b), 2)))))
    for dia, desc, v in OCASIONAIS.get(mes, []):
        linhas.append((dia, desc, Decimal(v)))
    return sorted(linhas, key=lambda x: x[0])


def main():
    DEMO.unlink(missing_ok=True)
    rnd = random.Random(2026)
    cat = Categorizador(RAIZ / "config" / "categorias.exemplo.yaml")   # nunca as regras reais
    saldo = Decimal("1500.00")
    with ligar(DEMO) as con:
        for ano, mes in MESES:
            abertura = saldo
            movs = []
            for dia, desc, valor in movimentos_do_mes(ano, mes, rnd):
                saldo += valor
                d = date(ano, mes, dia)
                movs.append(Movimento(d, d, desc, valor, saldo, f"demo_{ano}_{mes:02}.pdf"))
            ext = Extracto(date(ano, mes, 1), date(ano, mes, 28), abertura, saldo, movs,
                           f"demo_{ano}_{mes:02}.pdf")
            guardar_extracto(con, ext, cat)
    print(f"Demo criada em {DEMO}: {len(MESES)} meses de dados inventados.")


if __name__ == "__main__":
    main()
