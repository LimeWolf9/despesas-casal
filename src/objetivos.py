"""
Objetivos de gasto por categoria.

Ficheiro próprio (config/objetivos.yaml) e não dentro do categorias.yaml:
esse é reescrito pela app sempre que aprendes uma regra nova, e misturar as
duas coisas era pedir para um dia perderes os objetivos sem dar por isso.

Dois períodos:
  mensal -> compara-se mês a mês (supermercado, restaurantes, combustível)
  anual  -> compara-se o acumulado do ano (seguros, que saem de uma vez)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
FICHEIRO = RAIZ / "config" / "objetivos.yaml"
# Os objetivos de cada um ficam fora do git: na primeira vez, partem do exemplo.
EXEMPLO = RAIZ / "config" / "objetivos.exemplo.yaml"
if not FICHEIRO.exists() and EXEMPLO.exists():
    shutil.copyfile(EXEMPLO, FICHEIRO)

CABECALHO = """\
# Objetivos de gasto por categoria.
#
# periodo: mensal -> o alvo vale para cada mês
# periodo: anual  -> o alvo vale para o ano inteiro (seguros, IUC, etc.)
#
# Editas aqui ou no separador Resumo do dashboard. Uma categoria sem linha
# neste ficheiro simplesmente não tem objetivo — e não é pintada.
"""


def carregar() -> dict[str, dict]:
    if not FICHEIRO.exists():
        return {}
    with open(FICHEIRO, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}
    objetivos = dados.get("objetivos", {}) or {}

    limpos: dict[str, dict] = {}
    for cat, cfg in objetivos.items():
        if isinstance(cfg, (int, float)):          # forma curta: "Supermercado: 250"
            cfg = {"valor": float(cfg), "periodo": "mensal"}
        valor = cfg.get("valor")
        if valor is None or float(valor) <= 0:
            continue
        limpos[cat] = {
            "valor": float(valor),
            "periodo": cfg.get("periodo", "mensal") if cfg.get("periodo") in ("mensal", "anual") else "mensal",
        }
    return limpos


def guardar(objetivos: dict[str, dict]) -> None:
    FICHEIRO.parent.mkdir(parents=True, exist_ok=True)
    corpo = yaml.safe_dump(
        {"objetivos": {c: dict(v) for c, v in sorted(objetivos.items())}},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    with open(FICHEIRO, "w", encoding="utf-8") as f:
        f.write(CABECALHO + "\n" + corpo)


def estado(gasto: float, alvo: float | None) -> str:
    """'acima' | 'dentro' | 'sem_alvo'. Zero gasto nunca é 'acima'."""
    if not alvo:
        return "sem_alvo"
    return "acima" if gasto > alvo else "dentro"
