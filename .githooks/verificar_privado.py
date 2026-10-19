"""Verificação antes de cada commit: trava o commit se um ficheiro tiver algo da lista privada.

A lista fica em .privado.txt na raiz do repositório (fora do git): uma palavra ou frase por linha,
sem distinguir maiúsculas; linhas começadas por # são comentários. Exemplo: nomes, nº de conta, PIN.
Também trava ficheiros que nunca devem ir para o GitHub (bases de dados, extractos, configuração local).

Ligar uma vez, na pasta do repositório:   git config core.hooksPath .githooks
Saltar numa emergência (não recomendado): git commit --no-verify
"""

import fnmatch
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PROIBIDOS = ["*.db", "*.sqlite", "*.pdf", "*.PDF", "*apps.local.json", "*config.local.json",
             "*.privado.txt", "*/data/live.json", "*/data/monitor.json"]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, check=True).stdout


def main() -> int:
    lista = RAIZ / ".privado.txt"
    termos = []
    if lista.exists():
        termos = [l.strip().lower() for l in lista.read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
    else:
        print("Aviso: não há .privado.txt, por isso só verifiquei os ficheiros proibidos.")

    ficheiros = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    problemas = []
    for nome in filter(None, ficheiros):
        if any(fnmatch.fnmatch("/" + nome, p) or fnmatch.fnmatch(nome, p) for p in PROIBIDOS):
            problemas.append(f"{nome}: este ficheiro não deve ir para o GitHub")
            continue
        texto = git("show", f":{nome}").decode("utf-8", errors="ignore").lower()
        for termo in termos:
            if termo in texto:
                linha = texto[:texto.index(termo)].count("\n") + 1
                problemas.append(f"{nome}:{linha}: tem um termo da lista privada")
    if problemas:
        print("Commit travado: há informação privada.")
        print("\n".join("  " + p for p in problemas))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
