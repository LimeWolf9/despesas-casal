"""
O teste que interessa: todos os extractos em input/ têm de fechar os saldos.

    python -m pytest tests/ -v
    python tests/test_parser.py        # sem pytest instalado

Se um extracto novo falhar aqui, o parser não aguentou o layout e tens de olhar
para ele. Melhor saber à primeira do que descobrir daqui a seis meses que as
médias estão erradas.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from parser import ler_extracto, ErroDeParsing  # noqa: E402

EXTRACTOS = sorted((RAIZ / "input").glob("*.pdf")) + sorted((RAIZ / "input").glob("*.PDF"))


# Os extractos são dados bancários reais e não estão no repositório: sem eles, os testes saltam.
try:
    import pytest
    pytestmark = pytest.mark.skipif(not EXTRACTOS, reason="Não há extractos em input/ para testar.")
except ImportError:   # sem pytest: corre pelo __main__ em baixo
    pass


def test_todos_os_extractos_fecham():
    for caminho in EXTRACTOS:
        ext = ler_extracto(caminho)       # ler_extracto já valida; levanta se falhar
        assert ext.movimentos, f"{caminho.name}: zero movimentos extraídos."
        assert ext.inicio < ext.fim


def test_hash_e_estavel():
    ext = ler_extracto(EXTRACTOS[0])
    outra = ler_extracto(EXTRACTOS[0])
    assert [m.id_mov for m in ext.movimentos] == [m.id_mov for m in outra.movimentos]


def test_hash_distingue_movimentos_iguais():
    """Duas devoluções iguais no mesmo dia são movimentos distintos.
    O saldo entra no hash exactamente para isto."""
    ids = set()
    for caminho in EXTRACTOS:
        for m in ler_extracto(caminho).movimentos:
            assert m.id_mov not in ids, f"Hash repetido: {m.descritivo}"
            ids.add(m.id_mov)


if __name__ == "__main__":
    falhou = False
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            try:
                fn()
                print(f"  OK      {nome}")
            except (AssertionError, ErroDeParsing) as e:
                falhou = True
                print(f"  FALHOU  {nome}: {e}")
    sys.exit(1 if falhou else 0)
