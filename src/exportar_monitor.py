"""
Resumo para o monitor da parede: data/despesas.db -> data/monitor.json.

Só sai daqui o que o ecrã mostra: totais por mês e por categoria, e os
objetivos. Nunca os descritivos dos movimentos nem o saldo em conta, porque o
ecrã está na sala e qualquer visita o vê.

As contas seguem o Resumo do dashboard com os filtros por omissão: sem
transferências internas e sem despesas pontuais (compra da casa, alojamento).
A referência de "normal" é a mediana dos meses anteriores, como no Resumo.

Uso:
    python src/exportar_monitor.py
O MonitorHub corre-o sozinho sempre que abres as Despesas no monitor.
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("DESPESAS_DB") or RAIZ / "data" / "despesas.db")   # o mesmo DESPESAS_DB do db.py
SAIDA = RAIZ / "data" / "monitor.json"
SEM_CATEGORIA = "Por categorizar"
N_MESES = 6                       # meses no gráfico de evolução

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from objetivos import carregar as carregar_objetivos   # noqa: E402
except ImportError:
    # O MonitorHub pode correr isto com um Python sem o PyYAML: lê o formato simples do objetivos.yaml à mão
    def carregar_objetivos() -> dict[str, dict]:
        ficheiro = RAIZ / "config" / "objetivos.yaml"
        alvos: dict[str, dict] = {}
        cat = None
        if not ficheiro.exists():
            return alvos
        for linha in ficheiro.read_text(encoding="utf-8").splitlines():
            if not linha.strip() or linha.lstrip().startswith("#") or linha.startswith("objetivos"):
                continue
            chave, _, valor = linha.strip().partition(":")
            valor = valor.strip().strip("'\"")
            if linha.startswith("  ") and not linha.startswith("    "):
                cat = chave.strip("'\"")
                if valor:                                   # forma curta "Supermercado: 250"
                    alvos[cat] = {"valor": float(valor), "periodo": "mensal"}
                else:
                    alvos[cat] = {"valor": 0.0, "periodo": "mensal"}
            elif cat and chave == "valor":
                alvos[cat]["valor"] = float(valor)
            elif cat and chave == "periodo" and valor in ("mensal", "anual"):
                alvos[cat]["periodo"] = valor
        return {c: v for c, v in alvos.items() if v["valor"] > 0}


def exportar() -> dict:
    con = sqlite3.connect(DB)
    linhas = con.execute(
        "SELECT substr(data, 1, 7), categoria, subcategoria, valor FROM movimentos "
        "WHERE tipo NOT IN ('interno', 'pontual')"
    ).fetchall()
    n_por_cat = con.execute(
        "SELECT count(*) FROM movimentos WHERE categoria = ?", (SEM_CATEGORIA,)
    ).fetchone()[0]
    con.close()

    saidas_mes: dict[str, float] = defaultdict(float)
    entradas_mes: dict[str, float] = defaultdict(float)
    cat_mes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sub_mes: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for mes, cat, sub, valor in linhas:
        if valor < 0:
            saidas_mes[mes] += -valor
            cat_mes[cat][mes] += -valor
            if sub:
                sub_mes[(cat, sub)][mes] += -valor
        else:
            entradas_mes[mes] += valor

    meses = sorted(set(saidas_mes) | set(entradas_mes))
    if not meses:
        return {"gerado_em": agora(), "vazio": True}
    atual, anteriores = meses[-1], meses[:-1]
    ano = atual[:4]
    alvos = carregar_objetivos()

    def mediana(serie: dict[str, float]) -> float | None:
        vals = [serie.get(m, 0.0) for m in anteriores]
        return round(statistics.median(vals), 2) if vals else None

    categorias = []
    for cat, serie in cat_mes.items():
        valor = round(serie.get(atual, 0.0), 2)
        alvo = alvos.get(cat)
        if valor == 0 and not alvo:
            continue
        item = {"nome": cat, "valor": valor, "normal": mediana(serie)}
        if alvo:
            gasto = sum(v for m, v in serie.items() if m.startswith(ano)) if alvo["periodo"] == "anual" else valor
            item["objetivo"] = {
                "valor": alvo["valor"],
                "periodo": alvo["periodo"],
                "gasto": round(gasto, 2),
                "estado": "acima" if gasto > alvo["valor"] else "dentro",
            }
        subs = [{"nome": s, "valor": round(v.get(atual, 0.0), 2)}
                for (c, s), v in sub_mes.items() if c == cat and v.get(atual)]
        if subs:
            item["sub"] = sorted(subs, key=lambda x: -x["valor"])
        categorias.append(item)
    categorias.sort(key=lambda x: -x["valor"])

    return {
        "gerado_em": agora(),
        "mes": atual,
        "saidas": round(saidas_mes.get(atual, 0.0), 2),
        "entradas": round(entradas_mes.get(atual, 0.0), 2),
        "saidas_normal": mediana(saidas_mes),
        "categorias": categorias,
        "evolucao": [{"mes": m, "saidas": round(saidas_mes.get(m, 0.0), 2),
                      "entradas": round(entradas_mes.get(m, 0.0), 2)} for m in meses[-N_MESES:]],
        "por_categorizar": n_por_cat,
    }


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    dados = exportar()
    tmp = SAIDA.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SAIDA)              # troca de uma vez: o ecrã nunca lê um ficheiro a meio
    print(f"Resumo de {dados.get('mes', '—')} escrito em {SAIDA}")
