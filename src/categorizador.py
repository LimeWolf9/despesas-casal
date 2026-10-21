"""
Categorização por regras. Sem ML, de propósito.

O valor do sistema não está em acertar 95% sozinho — está em que o que falha
seja visível e corrigível num clique, e que a correção fique a valer para
sempre. É isso que `aprender_regra` faz.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml

SEM_CATEGORIA = "Por categorizar"

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "categorias.yaml"
# As regras de cada um ficam fora do git: na primeira vez, partem do exemplo.
EXEMPLO = RAIZ / "config" / "categorias.exemplo.yaml"
if not CONFIG.exists() and EXEMPLO.exists():
    shutil.copyfile(EXEMPLO, CONFIG)

# Antes de a app reescrever as regras, guarda uma cópia datada (fora do git) e fica com as 30 mais recentes.
COPIAS = RAIZ / "config" / "copias"
MAX_COPIAS = 30
# Outra pasta para onde copiar também (ex.: uma do OneDrive): a variável DESPESAS_COPIAS_DIR,
# ou "copias_dir:" no config/local.yaml (fora do git).
LOCAL = RAIZ / "config" / "local.yaml"


def pasta_extra_copias() -> Path | None:
    pasta = os.environ.get("DESPESAS_COPIAS_DIR")
    if not pasta and LOCAL.exists():
        try:
            pasta = (yaml.safe_load(LOCAL.read_text(encoding="utf-8")) or {}).get("copias_dir")
        except (OSError, yaml.YAMLError, AttributeError):
            pasta = None
    return Path(os.path.expandvars(os.path.expanduser(str(pasta)))) if pasta else None


def copia_de_seguranca(caminho: Path) -> Path | None:
    """Copia o ficheiro para config/copias/<nome>-AAAAMMDD-HHMMSS.yaml (e para a pasta extra, se houver).

    Apaga as cópias mais antigas a partir da 31.ª. Devolve a cópia feita, ou None se não havia ficheiro.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return None
    nome = f"{caminho.stem}-{datetime.now():%Y%m%d-%H%M%S}{caminho.suffix}"
    COPIAS.mkdir(parents=True, exist_ok=True)
    extra = pasta_extra_copias()
    copia, n = COPIAS / nome, 2
    while copia.exists() or (extra and (extra / copia.name).exists()):   # duas gravações no mesmo segundo
        copia = COPIAS / f"{Path(nome).stem}-{n}{caminho.suffix}"
        n += 1
    shutil.copy2(caminho, copia)
    # Da mais antiga para a mais recente: pela data no nome e, no mesmo segundo, pelo contador (-2, -3...)
    def ordem(p: Path):
        partes = p.stem[len(caminho.stem) + 1:].split("-")
        return partes[:2], int(partes[2]) if len(partes) > 2 and partes[2].isdigit() else 1
    antigas = sorted(COPIAS.glob(f"{caminho.stem}-*{caminho.suffix}"), key=ordem)
    for velha in antigas[:-MAX_COPIAS]:
        velha.unlink(missing_ok=True)
    if extra:
        try:   # uma pasta de rede/OneDrive em falta não pode impedir de gravar a regra
            extra.mkdir(parents=True, exist_ok=True)
            shutil.copy2(caminho, extra / copia.name)
        except OSError as e:
            print(f"Aviso: não consegui copiar as regras para {extra} ({e}).")
    return copia


class Categorizador:
    def __init__(self, caminho_config: str | Path = CONFIG):
        self.caminho = Path(caminho_config)
        self.recarregar()

    def recarregar(self) -> None:
        with open(self.caminho, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        self.regras: dict[str, list[str]] = cfg.get("categorias", {}) or {}
        self.sub_regras: dict[str, dict[str, list[str]]] = cfg.get("subcategorias", {}) or {}
        tipos = cfg.get("tipos", {}) or {}
        self.tipo_por_categoria: dict[str, str] = {}
        for tipo, cats in tipos.items():
            for c in cats or []:
                self.tipo_por_categoria[c] = tipo

    def categoria(self, descritivo: str) -> str:
        texto = descritivo.lower()
        for cat, padroes in self.regras.items():
            for p in padroes or []:
                if str(p).lower() in texto:
                    return cat
        return SEM_CATEGORIA

    def tipo(self, categoria: str) -> str:
        return self.tipo_por_categoria.get(categoria, "recorrente")

    def subcategoria(self, categoria: str, descritivo: str) -> str | None:
        """Afina dentro da categoria. Sem regra que bata, fica None —
        e o movimento continua a contar na categoria, como deve ser."""
        texto = descritivo.lower()
        for sub, padroes in (self.sub_regras.get(categoria) or {}).items():
            for p in padroes or []:
                if str(p).lower() in texto:
                    return sub
        return None

    def subcategorias_de(self, categoria: str) -> list[str]:
        return list((self.sub_regras.get(categoria) or {}).keys())

    def classificar(self, descritivo: str) -> tuple[str, str, str | None]:
        cat = self.categoria(descritivo)
        return cat, self.tipo(cat), self.subcategoria(cat, descritivo)

    # ------------------------------------------------------------ aprender

    def _gravar(self, cfg: dict, texto_original: str) -> None:
        """Reescreve o YAML preservando o cabeçalho de comentários."""
        cabecalho = []
        for linha in texto_original.split("\n"):
            if linha.startswith("#") or not linha.strip():
                cabecalho.append(linha)
            else:
                break
        corpo = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False,
                               default_flow_style=False)
        copia_de_seguranca(self.caminho)
        with open(self.caminho, "w", encoding="utf-8") as f:
            f.write("\n".join(cabecalho).rstrip() + "\n\n" + corpo)
        self.recarregar()

    def aprender_regra(self, padrao: str, categoria: str) -> None:
        """
        Acrescenta um padrão à categoria e grava o YAML. Se a categoria ainda
        não existir, é criada.

        É isto que faz o trabalho mensal tender para zero: cada vez que
        categorizas algo novo no dashboard, o sistema nunca mais te volta a
        perguntar o mesmo.
        """
        padrao = padrao.strip().lower()
        if not padrao:
            raise ValueError("Padrão vazio.")

        with open(self.caminho, encoding="utf-8") as f:
            texto_original = f.read()
        cfg = yaml.safe_load(texto_original) or {}
        lista = cfg.setdefault("categorias", {}).setdefault(categoria, [])
        if padrao in [str(x).lower() for x in lista]:
            return
        lista.append(padrao)
        self._gravar(cfg, texto_original)

    def aprender_subregra(self, categoria: str, subcategoria: str, padrao: str) -> None:
        """O mesmo, um nível abaixo. Cria a subcategoria se não existir."""
        padrao = padrao.strip().lower()
        if not padrao:
            raise ValueError("Padrão vazio.")

        with open(self.caminho, encoding="utf-8") as f:
            texto_original = f.read()
        cfg = yaml.safe_load(texto_original) or {}
        lista = (cfg.setdefault("subcategorias", {})
                    .setdefault(categoria, {})
                    .setdefault(subcategoria, []))
        if padrao in [str(x).lower() for x in lista]:
            return
        lista.append(padrao)
        self._gravar(cfg, texto_original)

    @property
    def nomes_categorias(self) -> list[str]:
        return sorted(self.regras.keys())


def sugerir_padrao(descritivo: str) -> str:
    """
    Sugere um padrão a partir de um descritivo, tirando o lixo do cartão.
    'Compra 1234567 mercadona' -> 'mercadona'
    """
    texto = descritivo.lower()
    for prefixo in ("dev. compra", "compra", "dd ", "pag servicos a"):
        if texto.startswith(prefixo):
            texto = texto[len(prefixo):].strip()
            break
    # tira número de cartão residual (ex.: '.30 nome da pessoa')
    partes = texto.split()
    while partes and all(c.isdigit() or c in ".-" for c in partes[0]):
        partes.pop(0)
    # corta sufixos de taxa de câmbio
    texto = " ".join(partes)
    for corte in ("tx. câmbio", "tx. cambio"):
        if corte in texto:
            texto = texto.split(corte)[0].strip()
    return texto[:40].strip()
