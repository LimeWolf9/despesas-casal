"""
Ingestão: PDFs em input/ -> base de dados.

Uso:
    python src/ingest.py                 # tudo o que estiver em input/
    python src/ingest.py ficheiro.pdf    # um ficheiro específico
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from categorizador import Categorizador          # noqa: E402
from db import ligar, guardar_extracto           # noqa: E402
from parser import ler_extracto, ErroDeParsing   # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
INPUT = RAIZ / "input"


def importar(caminhos: list[Path]) -> None:
    cat = Categorizador()
    total_novos = total_dupes = 0
    falhas: list[str] = []

    with ligar() as con:
        for caminho in caminhos:
            try:
                ext = ler_extracto(caminho)
            except ErroDeParsing as e:
                falhas.append(str(e))
                print(f"  FALHOU  {caminho.name}: {e}")
                continue

            novos, dupes = guardar_extracto(con, ext, cat)
            total_novos += novos
            total_dupes += dupes
            print(f"  OK      {caminho.name}: {novos} novos, {dupes} repetidos "
                  f"({ext.inicio} a {ext.fim})")

    print(f"\n{total_novos} movimentos novos, {total_dupes} já existiam.")
    if falhas:
        print(f"\n{len(falhas)} ficheiro(s) falharam a validação de saldos. "
              f"Não foi importado nada deles — melhor isso do que importar mal.")


if __name__ == "__main__":
    alvos = [Path(a) for a in sys.argv[1:]] or sorted(INPUT.glob("*.pdf")) + sorted(INPUT.glob("*.PDF"))
    if not alvos:
        print(f"Nada para importar. Põe os extractos em {INPUT}/")
        sys.exit(0)
    print(f"A importar {len(alvos)} ficheiro(s):")
    importar(alvos)
