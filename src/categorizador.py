"""
Categorização por regras. Sem ML, de propósito.

O valor do sistema não está em acertar 95% sozinho — está em que o que falha
seja visível e corrigível num clique, e que a correção fique a valer para
sempre. É isso que `aprender_regra` faz.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SEM_CATEGORIA = "Por categorizar"

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "categorias.yaml"


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
