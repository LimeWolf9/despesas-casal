"""
Password da app (opcional). Guarda só o hash em config/local.yaml (fora do git).

Uso:  python src/senha.py          (pede a password duas vezes e grava)
      python src/senha.py --tirar  (volta a abrir sem password)

Sem "senha_sha256" no config/local.yaml a app abre sem pedir nada, como antes.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import sys
from pathlib import Path

import yaml

LOCAL = Path(__file__).resolve().parent.parent / "config" / "local.yaml"
CHAVE = "senha_sha256"


def _ler() -> dict:
    try:
        return yaml.safe_load(LOCAL.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


def hash_configurado() -> str | None:
    return _ler().get(CHAVE) or None


def confere(tentativa: str, esperado: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(tentativa.encode("utf-8")).hexdigest(), esperado)


def _gravar(dados: dict) -> None:
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> None:
    dados = _ler()
    if "--tirar" in sys.argv:
        dados.pop(CHAVE, None)
        _gravar(dados)
        print("Password tirada: a app abre sem pedir nada.")
        return
    p1 = getpass.getpass("Nova password: ")
    p2 = getpass.getpass("Outra vez: ")
    if not p1 or p1 != p2:
        sys.exit("As passwords não batem certo (ou estão vazias). Nada mudou.")
    dados[CHAVE] = hashlib.sha256(p1.encode("utf-8")).hexdigest()
    _gravar(dados)
    print(f"Feito. Fica em {LOCAL} (só o hash). Reinicia a app para pedir a password.")


if __name__ == "__main__":
    main()
