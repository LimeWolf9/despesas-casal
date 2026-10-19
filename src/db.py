"""
Armazenamento em SQLite. Um ficheiro, zero manutenção.

Deduplicação pelo hash de (data + descritivo + valor + saldo): podes voltar a
carregar o mesmo extracto as vezes que quiseres. E vais — por engano, mais do
que uma vez.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# DESPESAS_DB troca de base de dados (ex.: data/demo.db, criada por src/demo.py)
DB_PATH = Path(os.environ.get("DESPESAS_DB") or RAIZ / "data" / "despesas.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS movimentos (
    id_mov       TEXT PRIMARY KEY,
    data         TEXT NOT NULL,
    data_valor   TEXT NOT NULL,
    descritivo   TEXT NOT NULL,
    valor        REAL NOT NULL,
    saldo        REAL NOT NULL,
    categoria    TEXT NOT NULL,
    subcategoria TEXT,
    sub_manual   INTEGER NOT NULL DEFAULT 0,
    tipo         TEXT NOT NULL DEFAULT 'recorrente',
    etiqueta     TEXT,
    manual       INTEGER NOT NULL DEFAULT 0,
    ficheiro     TEXT NOT NULL,
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mov_data      ON movimentos(data);
CREATE INDEX IF NOT EXISTS idx_mov_categoria ON movimentos(categoria);
CREATE INDEX IF NOT EXISTS idx_mov_etiqueta  ON movimentos(etiqueta);

CREATE TABLE IF NOT EXISTS extractos (
    ficheiro        TEXT PRIMARY KEY,
    inicio          TEXT NOT NULL,
    fim             TEXT NOT NULL,
    saldo_abertura  REAL NOT NULL,
    saldo_fecho     REAL NOT NULL,
    n_movimentos    INTEGER NOT NULL,
    importado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _migrar(con) -> None:
    """Acrescenta colunas novas a bases de dados já existentes.
    Sem isto, quem já tinha dados ficava com o esquema antigo em silêncio."""
    colunas = {r["name"] for r in con.execute("PRAGMA table_info(movimentos)")}
    if "subcategoria" not in colunas:
        con.execute("ALTER TABLE movimentos ADD COLUMN subcategoria TEXT")
    if "sub_manual" not in colunas:
        con.execute("ALTER TABLE movimentos ADD COLUMN sub_manual INTEGER NOT NULL DEFAULT 0")


def renomear_categoria(con, antiga: str, nova: str) -> int:
    """Muda o nome de uma categoria em todos os movimentos já guardados.
    O YAML trata do futuro; isto trata do passado."""
    cur = con.execute("UPDATE movimentos SET categoria = ? WHERE categoria = ?",
                      (nova, antiga))
    return cur.rowcount


@contextmanager
def ligar(caminho: str | Path = DB_PATH):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        _migrar(con)
        yield con
        con.commit()
    finally:
        con.close()


def guardar_extracto(con, ext, categorizador) -> tuple[int, int]:
    """Devolve (novos, duplicados_ignorados)."""
    novos = dupes = 0
    for m in ext.movimentos:
        cat, tipo, sub = categorizador.classificar(m.descritivo)
        try:
            con.execute(
                """INSERT INTO movimentos
                   (id_mov, data, data_valor, descritivo, valor, saldo,
                    categoria, subcategoria, tipo, ficheiro)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (m.id_mov, m.data.isoformat(), m.data_valor.isoformat(),
                 m.descritivo, float(m.valor), float(m.saldo), cat, sub, tipo,
                 m.ficheiro),
            )
            novos += 1
        except sqlite3.IntegrityError:
            dupes += 1

    con.execute(
        """INSERT INTO extractos
           (ficheiro, inicio, fim, saldo_abertura, saldo_fecho, n_movimentos)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(ficheiro) DO UPDATE SET
             inicio=excluded.inicio, fim=excluded.fim,
             saldo_abertura=excluded.saldo_abertura,
             saldo_fecho=excluded.saldo_fecho,
             n_movimentos=excluded.n_movimentos,
             importado_em=datetime('now')""",
        (ext.ficheiro, ext.inicio.isoformat(), ext.fim.isoformat(),
         float(ext.saldo_abertura), float(ext.saldo_fecho), len(ext.movimentos)),
    )
    return novos, dupes


def recategorizar_tudo(con, categorizador) -> int:
    """
    Reaplica as regras a tudo o que ainda não foi tocado à mão.
    Corre depois de aprender uma regra nova.
    """
    alterados = 0
    for linha in con.execute(
        "SELECT id_mov, descritivo, categoria, subcategoria FROM movimentos "
        "WHERE manual = 0 AND sub_manual = 0"
    ).fetchall():
        cat, tipo, sub = categorizador.classificar(linha["descritivo"])
        if cat != linha["categoria"] or sub != linha["subcategoria"]:
            con.execute(
                "UPDATE movimentos SET categoria = ?, subcategoria = ?, tipo = ? "
                "WHERE id_mov = ?",
                (cat, sub, tipo, linha["id_mov"]),
            )
            alterados += 1
    return alterados


def definir_subcategoria(con, id_mov: str, subcategoria: str | None) -> None:
    """
    Subcategoria aplicada a UM movimento, sem criar regra.

    Existe por causa de sítios como a Amazon: o descritivo é
    'www.amazon xxxx' e não diz se foram facas ou um cabo HDMI. Uma regra
    por comerciante não resolve, e uma regra com a referência da encomenda só
    serviria para essa compra. Aqui marca-se o movimento e pronto.
    """
    con.execute(
        "UPDATE movimentos SET subcategoria = ?, sub_manual = 1 WHERE id_mov = ?",
        (subcategoria, id_mov),
    )


def aplicar_subcategorias(con, categorizador) -> int:
    """Reaplica as subcategorias por regra, respeitando as postas à mão."""
    alterados = 0
    for linha in con.execute(
        "SELECT id_mov, descritivo, categoria, subcategoria FROM movimentos "
        "WHERE sub_manual = 0"
    ).fetchall():
        sub = categorizador.subcategoria(linha["categoria"], linha["descritivo"])
        if sub != linha["subcategoria"]:
            con.execute("UPDATE movimentos SET subcategoria = ? WHERE id_mov = ?",
                        (sub, linha["id_mov"]))
            alterados += 1
    return alterados


def definir_categoria(con, id_mov: str, categoria: str, tipo: str = "recorrente") -> None:
    """Categoria posta à mão. `manual = 1` protege-a de futuras recategorizações."""
    con.execute(
        "UPDATE movimentos SET categoria = ?, tipo = ?, manual = 1 WHERE id_mov = ?",
        (categoria, tipo, id_mov),
    )


def definir_etiqueta(con, ids: list[str], etiqueta: str | None) -> None:
    """
    Etiqueta livre (ex.: 'Férias verão/26'), independente da categoria.

    É isto que resolve o problema das viagens: o jantar continua a ser
    'Restaurantes', mas podes tirar a viagem toda das médias de uma vez.
    """
    con.executemany(
        "UPDATE movimentos SET etiqueta = ? WHERE id_mov = ?",
        [(etiqueta, i) for i in ids],
    )
