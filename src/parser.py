"""
Parser de extractos Bankinter (PDF) -> lista de movimentos.

Regra de ouro: o parser valida-se a si próprio pela coluna Saldo.
Se saldo_abertura + soma(movimentos) != saldo_fecho, o parser falhou
e nós ficamos a saber logo, em vez de descobrirmos daqui a 6 meses.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------- padrões

# 01/09 Compra 1234567 loja exemplo 01/09 -42,50 1.257,50
LINHA_MOV = re.compile(
    r"^(?P<dia>\d{2}/\d{2})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<dia_valor>\d{2}/\d{2})\s+"
    r"(?P<valor>-?[\d.]+,\d{2})\s+"
    r"(?P<saldo>-?[\d.]+,\d{2})\s*$"
)

# Saldo em 2026/09/01 1.300,00
LINHA_SALDO = re.compile(r"^Saldo em (?P<data>\d{4}/\d{2}/\d{2})\s+(?P<saldo>-?[\d.]+,\d{2})\s*$")

# Período a que se referem as informações prestadas no presente extrato: de 2026/09/01 a 2026/09/30
LINHA_PERIODO = re.compile(r"presente extrato:\s*de\s*(\d{4}/\d{2}/\d{2})\s*a\s*(\d{4}/\d{2}/\d{2})")

# Secções que terminam o bloco de conta à ordem
FIM_SECCAO = ("FACILIDADES DE DESCOBERTO", "EMPRÉSTIMOS E CRÉDITOS", "EXTRACTO DE POSIÇÕES")

# Linhas de ruído dentro do bloco de movimentos.
# Comparadas SEMPRE com startswith: um "in" apanharia "16/09 Pag. servico ... -12,34"
# por causa do rodapé "Pag. 2 de 4". Foi esse o primeiro bug que o validador apanhou.
RUIDO = (
    "www.bankinter.pt",
    "Bankinter, S.A.",
    "Membro do Sistema de Garantia",
    "Data Descritivo",
    "Valor Cred.",
    "CONTA BK ONLINE",
    "Caso se verifique ultrapassagem",
    "autorizado da sua conta",
    "taxa de juro anual nominal",
    "juros e à taxa de",
    "Extracto Nº",
    "Pag. 1 de",
    "Pag. 2 de",
    "Pag. 3 de",
    "Pag. 4 de",
    "Pag. 5 de",
    "O sinal (-) significa",
)


class ErroDeParsing(Exception):
    """O extracto não bateu certo. Nunca engolir em silêncio."""


@dataclass
class Movimento:
    data: date                # data do movimento (coluna 1)
    data_valor: date          # data-valor (coluna 2)
    descritivo: str
    valor: Decimal            # negativo = saída
    saldo: Decimal
    ficheiro: str
    id_mov: str = ""          # hash para deduplicação

    def __post_init__(self):
        if not self.id_mov:
            crua = f"{self.data}|{self.descritivo}|{self.valor}|{self.saldo}"
            self.id_mov = hashlib.sha256(crua.encode("utf-8")).hexdigest()[:16]

    def como_dict(self) -> dict:
        d = asdict(self)
        d["data"] = self.data.isoformat()
        d["data_valor"] = self.data_valor.isoformat()
        d["valor"] = str(self.valor)
        d["saldo"] = str(self.saldo)
        return d


@dataclass
class Extracto:
    inicio: date
    fim: date
    saldo_abertura: Decimal
    saldo_fecho: Decimal
    movimentos: list[Movimento]
    ficheiro: str

    @property
    def total_saidas(self) -> Decimal:
        return sum((m.valor for m in self.movimentos if m.valor < 0), Decimal("0"))

    @property
    def total_entradas(self) -> Decimal:
        return sum((m.valor for m in self.movimentos if m.valor > 0), Decimal("0"))


# ---------------------------------------------------------------- helpers

def _para_decimal(txt: str) -> Decimal:
    """'-1.454,00' -> Decimal('-1454.00')"""
    return Decimal(txt.replace(".", "").replace(",", "."))


def _para_data(dia_mes: str, ano: int, mes_extracto: int) -> date:
    """
    'DD/MM' -> date. Trata a viragem de ano: um movimento de 31/12
    num extracto de janeiro pertence ao ano anterior.
    """
    dia, mes = (int(x) for x in dia_mes.split("/"))
    if mes_extracto == 1 and mes == 12:
        ano -= 1
    elif mes_extracto == 12 and mes == 1:
        ano += 1
    return date(ano, mes, dia)


def _texto_do_pdf(caminho: Path) -> str:
    with pdfplumber.open(caminho) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _bloco_conta_ordem(texto: str) -> list[str]:
    """Isola as linhas da conta à ordem (ignora empréstimo e descobertos)."""
    linhas = texto.split("\n")
    try:
        inicio = next(i for i, l in enumerate(linhas) if "CONTAS À ORDEM" in l)
    except StopIteration:
        raise ErroDeParsing("Não encontrei a secção 'CONTAS À ORDEM'.")

    fim = len(linhas)
    for i in range(inicio + 1, len(linhas)):
        if any(marca in linhas[i] for marca in FIM_SECCAO):
            fim = i
            break
    return linhas[inicio:fim]


def _e_ruido(linha: str) -> bool:
    return any(linha.startswith(r) for r in RUIDO)


# ---------------------------------------------------------------- parser

def ler_extracto(caminho: str | Path) -> Extracto:
    caminho = Path(caminho)
    texto = _texto_do_pdf(caminho)

    m = LINHA_PERIODO.search(texto)
    if not m:
        raise ErroDeParsing(f"{caminho.name}: não encontrei o período do extracto.")
    inicio = date.fromisoformat(m.group(1).replace("/", "-"))
    fim = date.fromisoformat(m.group(2).replace("/", "-"))

    linhas = _bloco_conta_ordem(texto)

    saldos = [(_para_decimal(s.group("saldo")), s.group("data"))
              for s in (LINHA_SALDO.match(l.strip()) for l in linhas) if s]
    if len(saldos) < 2:
        raise ErroDeParsing(f"{caminho.name}: faltam os saldos de abertura/fecho.")
    saldo_abertura, saldo_fecho = saldos[0][0], saldos[-1][0]

    movimentos: list[Movimento] = []
    for linha in linhas:
        linha = linha.strip()
        if not linha or _e_ruido(linha):
            continue

        mt = LINHA_MOV.match(linha)
        if mt:
            movimentos.append(
                Movimento(
                    data=_para_data(mt.group("dia"), inicio.year, inicio.month),
                    data_valor=_para_data(mt.group("dia_valor"), inicio.year, inicio.month),
                    descritivo=re.sub(r"\s+", " ", mt.group("desc")).strip(),
                    valor=_para_decimal(mt.group("valor")),
                    saldo=_para_decimal(mt.group("saldo")),
                    ficheiro=caminho.name,
                )
            )
        elif movimentos and not LINHA_SALDO.match(linha):
            # continuação do descritivo (ref. de transferência, taxa de câmbio, etc.)
            anterior = movimentos[-1]
            anterior.descritivo = f"{anterior.descritivo} {linha}".strip()
            anterior.id_mov = ""
            anterior.__post_init__()

    ext = Extracto(inicio, fim, saldo_abertura, saldo_fecho, movimentos, caminho.name)
    validar(ext)
    return ext


def validar(ext: Extracto) -> None:
    """A rede de segurança: os saldos têm de fechar ao cêntimo."""
    calculado = ext.saldo_abertura + sum((m.valor for m in ext.movimentos), Decimal("0"))
    if calculado != ext.saldo_fecho:
        raise ErroDeParsing(
            f"{ext.ficheiro}: saldos não fecham. "
            f"Abertura {ext.saldo_abertura} + movimentos = {calculado}, "
            f"mas o extracto diz {ext.saldo_fecho} "
            f"(diferença {ext.saldo_fecho - calculado})."
        )

    # segunda rede: a coluna Saldo linha a linha
    corrente = ext.saldo_abertura
    for mov in ext.movimentos:
        corrente += mov.valor
        if corrente != mov.saldo:
            raise ErroDeParsing(
                f"{ext.ficheiro}: saldo inconsistente em {mov.data} '{mov.descritivo[:40]}'. "
                f"Esperado {corrente}, extracto diz {mov.saldo}."
            )


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        e = ler_extracto(arg)
        print(f"{e.ficheiro}: {e.inicio} a {e.fim} | {len(e.movimentos)} movimentos | "
              f"saidas {e.total_saidas} | entradas {e.total_entradas} | "
              f"{e.saldo_abertura} -> {e.saldo_fecho} OK")
