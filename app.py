"""
Dashboard de despesas do casal.

Correr:  streamlit run app.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "src"))

from categorizador import Categorizador, SEM_CATEGORIA, sugerir_padrao  # noqa: E402
import objetivos                                                        # noqa: E402
from db import (ligar, guardar_extracto, recategorizar_tudo,            # noqa: E402
                definir_categoria, definir_etiqueta, aplicar_subcategorias,
                definir_subcategoria)
from parser import ler_extracto, ErroDeParsing                          # noqa: E402

INPUT = RAIZ / "input"

st.set_page_config(page_title="Despesas", page_icon="🏠", layout="wide")

# ---------------------------------------------------------------- estilo

st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1300px; }
  [data-testid="stMetricValue"] { font-size: 1.6rem; }
  [data-testid="stMetricLabel"] { font-size: .8rem; opacity: .75; }
  h1 { font-size: 1.9rem !important; letter-spacing: -.02em; }
</style>
""", unsafe_allow_html=True)

# Paleta estável: a mesma categoria tem sempre a mesma cor, em qualquer gráfico.
PALETA = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#EECA3B",
    "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC", "#7F3C8D", "#11A579",
    "#3969AC", "#F2B701", "#E73F74", "#80BA5A", "#E68310", "#008695",
]


@st.cache_resource
def obter_categorizador() -> Categorizador:
    return Categorizador()


def carregar() -> pd.DataFrame:
    with ligar() as con:
        df = pd.read_sql_query("SELECT * FROM movimentos ORDER BY data, id_mov", con)
    if df.empty:
        return df
    df["data"] = pd.to_datetime(df["data"])
    df["mes"] = df["data"].dt.to_period("M").astype(str)
    df["saida"] = df["valor"].where(df["valor"] < 0, 0).abs()
    df["entrada"] = df["valor"].where(df["valor"] > 0, 0)
    return df


def euro(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", " ").replace(".", ",")
    return f"{'-' if v < 0 else ''}{s} €"


MESES_PT = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
            7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}

def rotulo_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES_PT[int(m)]} {ano[2:]}"


def escala_cor(categorias: list[str]) -> alt.Scale:
    cats = sorted(categorias)
    return alt.Scale(domain=cats, range=[PALETA[i % len(PALETA)] for i in range(len(cats))])


cat_engine = obter_categorizador()
df = carregar()

# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Importar extracto")
    carregados = st.file_uploader(
        "PDF do Bankinter", type=["pdf"], accept_multiple_files=True,
        help="O extracto só entra se os saldos fecharem ao cêntimo.",
    )
    if carregados and st.button("Importar", type="primary", width="stretch"):
        INPUT.mkdir(exist_ok=True)
        resultados = []
        with ligar() as con:
            for f in carregados:
                destino = INPUT / f.name
                destino.write_bytes(f.getbuffer())
                try:
                    ext = ler_extracto(destino)
                except ErroDeParsing as e:
                    resultados.append(("erro", f.name, str(e)))
                    continue
                novos, dupes = guardar_extracto(con, ext, cat_engine)
                resultados.append(("ok", f.name, f"{novos} novos, {dupes} repetidos"))
        for estado, nome, msg in resultados:
            (st.success if estado == "ok" else st.error)(f"**{nome}** — {msg}")
        st.cache_data.clear()
        st.rerun()

    if not df.empty:
        st.divider()
        st.caption("O que contar")
        incluir_internas = st.toggle("Transferências internas", value=False,
                                     help="Dinheiro teu a mudar de bolso. Normalmente não é despesa.")
        # Desligado por defeito de propósito: com uma compra grande (ex.: a escritura
        # da casa) ligada, todos os outros meses viram uma linha rasteira no gráfico.
        incluir_pontuais = st.toggle("Despesas pontuais", value=False,
                                     help="Compra da casa, alojamento, etc. Liga para ver o total bruto.")
        etiquetas = sorted(e for e in df["etiqueta"].dropna().unique() if e)
        excluir_etq = st.multiselect("Excluir etiquetas", etiquetas, default=[])
    else:
        incluir_internas, incluir_pontuais, excluir_etq = False, True, []

if df.empty:
    st.title("Despesas")
    st.info("Ainda não há nada na base de dados. Importa um extracto na barra lateral.")
    st.stop()

# ---------------------------------------------------------------- filtros

st.title("Despesas")

# O período fica aqui, à vista, e não na barra lateral: é o filtro que mais se
# mexe, e no telemóvel a barra lateral está escondida atrás de um botão.
meses = sorted(df["mes"].unique())
st.session_state.setdefault("meses_sel", meses)
# Meses novos (extracto acabado de importar) entram seleccionados.
if set(st.session_state["meses_sel"]) - set(meses):
    st.session_state["meses_sel"] = [m for m in st.session_state["meses_sel"] if m in meses]

cm, cb_lim = st.columns([6, 1], vertical_alignment="bottom")
with cm:
    st.segmented_control(
        "Período", meses, selection_mode="multi", key="meses_sel",
        format_func=rotulo_mes, label_visibility="collapsed",
    )
with cb_lim:
    if st.button("Todos", width="stretch",
                 disabled=set(st.session_state["meses_sel"]) == set(meses)):
        st.session_state["meses_sel"] = meses
        st.rerun()

sel_meses = st.session_state["meses_sel"] or meses

f = df[df["mes"].isin(sel_meses)].copy()
if not incluir_internas:
    f = f[f["tipo"] != "interno"]
if not incluir_pontuais:
    f = f[f["tipo"] != "pontual"]
if excluir_etq:
    f = f[~f["etiqueta"].isin(excluir_etq)]

por_categorizar = f[f["categoria"] == SEM_CATEGORIA]
if len(por_categorizar):
    st.warning(f"**{len(por_categorizar)}** movimento(s) por categorizar. "
               f"Separador **Por categorizar** — cada um que resolveres nunca mais te volta a aparecer.")

# ---------------------------------------------------------------- KPIs

n_meses = max(len(sel_meses), 1)
saidas, entradas = f["saida"].sum(), f["entrada"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Saídas", euro(saidas), f"{euro(saidas / n_meses)}/mês")
c2.metric("Entradas", euro(entradas), f"{euro(entradas / n_meses)}/mês")
c3.metric("Saldo do período", euro(entradas - saidas),
          f"{euro((entradas - saidas) / n_meses)}/mês",
          delta_color="normal" if entradas >= saidas else "inverse")
c4.metric("Saldo em conta", euro(df.sort_values("data").iloc[-1]["saldo"]),
          df.sort_values("data").iloc[-1]["data"].strftime("%d/%m/%Y"))

VISTAS = ["Resumo", "Visão geral", "Categorias", "Movimentos", "Por categorizar"]

# st.tabs não se consegue mudar por código, e precisamos disso para o clique
# no título de uma categoria saltar para os movimentos já filtrados.
#
# O Streamlit proíbe escrever no estado de um widget DEPOIS de ele ser criado.
# Daí este padrão: o botão deixa um pedido pendente e faz rerun; no início da
# execução seguinte, antes de os widgets existirem, o pedido é aplicado.
if "_ir_para" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("_ir_para")
if "_filtrar_cats" in st.session_state:
    st.session_state["filtro_categorias"] = st.session_state.pop("_filtrar_cats")

st.session_state.setdefault("nav", "Resumo")
st.segmented_control("Vista", VISTAS, key="nav", label_visibility="collapsed")
vista = st.session_state.get("nav") or "Resumo"

# ---------------------------------------------------------------- resumo
# Uma despesa por cartão, mês a mês, em linguagem normal.
# É o separador para olhar de relance — e o que funciona no telemóvel.

CSS_CARTOES = """
<style>
.cartao{border:1px solid rgba(0,0,0,.09);border-radius:14px;padding:15px 18px;
        margin-bottom:13px;background:#fff}
.cartao-topo{display:flex;justify-content:space-between;align-items:baseline;
             gap:10px;margin-bottom:11px}
.cartao-nome{font-weight:650;font-size:1.03rem;letter-spacing:-.01em}
.cartao-media{font-size:.78rem;opacity:.55;white-space:nowrap}
.linha{display:grid;grid-template-columns:52px 1fr 94px;align-items:center;
       gap:11px;margin:6px 0}
.linha .mes{font-size:.78rem;opacity:.55}
.linha .val{font-size:.85rem;text-align:right;font-variant-numeric:tabular-nums}
.barra{background:rgba(0,0,0,.055);border-radius:5px;height:9px;overflow:hidden;
       position:relative}
.barra i{display:block;height:100%;border-radius:5px;background:#4C78A8}
.barra i.zero{background:rgba(0,0,0,.12)}
.barra i.dentro{background:#2E7D52}
.barra i.acima{background:#C4393B}
/* risco vertical a marcar o objetivo */
.barra u{position:absolute;top:-2px;bottom:-2px;width:2px;background:rgba(0,0,0,.45);
         border-radius:1px}
.linha .val.dentro{color:#2E7D52}
.linha .val.acima{color:#C4393B;font-weight:600}
.alvo{font-size:.72rem;padding:2px 8px;border-radius:999px;white-space:nowrap}
.alvo.dentro{background:rgba(46,125,82,.11);color:#2E7D52}
.alvo.acima{background:rgba(196,57,59,.11);color:#C4393B}
.alvo.sem_alvo{background:rgba(0,0,0,.05);opacity:.6}
.sub{margin-top:11px;padding-top:9px;border-top:1px solid rgba(0,0,0,.06)}
.sub-l{display:flex;justify-content:space-between;gap:10px;font-size:.8rem;
       opacity:.78;margin:3px 0}
.sub-l .sub-v{font-variant-numeric:tabular-nums;opacity:.8}
.nota{margin-top:10px;padding-top:9px;border-top:1px solid rgba(0,0,0,.06);
      font-size:.82rem;opacity:.72;line-height:1.45}
@media (max-width:640px){.linha{grid-template-columns:44px 1fr 82px;gap:8px}}
</style>
"""


def nota_da_categoria(pares: list[tuple[str, float]]) -> str:
    """A frase em português que explica o mês mais recente."""
    if not pares:
        return ""
    ultimo_mes, ultimo_val = pares[-1]
    anteriores = [v for _, v in pares[:-1]]
    com_valor = [v for v in anteriores if v > 0]

    if ultimo_val == 0:
        if com_valor:
            return f"Não houve nada em {rotulo_mes(ultimo_mes)}."
        return "Sem movimento no período escolhido."

    if not com_valor:
        return f"Só apareceu em {rotulo_mes(ultimo_mes)}: {euro(ultimo_val)}."

    # Mediana, não média: um mês atípico (ex.: uma 1.ª prestação
    # parcial) puxava a média e dizia "X % acima" sobre uma prestação
    # que na verdade é sempre igual. A mediana ignora esses casos.
    ordenados = sorted(com_valor)
    meio = len(ordenados) // 2
    habitual = (ordenados[meio] if len(ordenados) % 2
                else (ordenados[meio - 1] + ordenados[meio]) / 2)

    delta = (ultimo_val - habitual) / habitual * 100
    base = (f"Em {rotulo_mes(ultimo_mes)} foram {euro(ultimo_val)}, "
            f"contra os {euro(habitual)} habituais")
    if abs(delta) < 8:
        return base + " — em linha com o costume."
    direcao = "acima" if delta > 0 else "abaixo"
    return base + f" — {abs(delta):.0f} % {direcao}."


if vista == "Resumo":
    st.markdown(CSS_CARTOES, unsafe_allow_html=True)

    tabela_res = f.pivot_table(index="categoria", columns="mes", values="saida",
                               aggfunc="sum", fill_value=0)
    tabela_res = tabela_res.loc[tabela_res.sum(axis=1) > 0]

    alvos = objetivos.carregar()

    # ------------------------------------------------------- editor de objetivos
    with st.expander(
        f"Objetivos de gasto  ·  {len(alvos)} definido(s)"
        + ("" if alvos else "  — ainda nenhum")
    ):
        st.caption(
            "Deixa em branco o que não quiseres controlar. Usa **anual** para o que "
            "sai de uma vez por ano (os seguros, por exemplo) — num objetivo mensal "
            "esses meses apareciam sempre a vermelho sem razão."
        )

        todas_cats = sorted(set(df["categoria"]) - {SEM_CATEGORIA})
        base = pd.DataFrame({
            "Categoria": todas_cats,
            "Objetivo (€)": [alvos.get(c, {}).get("valor") for c in todas_cats],
            "Período": [alvos.get(c, {}).get("periodo", "mensal") for c in todas_cats],
        })

        editado = st.data_editor(
            base, hide_index=True, width="stretch", key="editor_objetivos",
            column_config={
                "Categoria": st.column_config.TextColumn(disabled=True),
                "Objetivo (€)": st.column_config.NumberColumn(
                    min_value=0.0, step=10.0, format="%.2f",
                    help="Em branco = sem objetivo."),
                "Período": st.column_config.SelectboxColumn(options=["mensal", "anual"]),
            },
        )

        ca, cb = st.columns([1, 4])
        if ca.button("Guardar objetivos", type="primary"):
            novos = {
                linha["Categoria"]: {
                    "valor": float(linha["Objetivo (€)"]),
                    "periodo": linha["Período"] or "mensal",
                }
                for _, linha in editado.iterrows()
                if pd.notna(linha["Objetivo (€)"]) and float(linha["Objetivo (€)"]) > 0
            }
            objetivos.guardar(novos)
            cb.success(f"{len(novos)} objetivo(s) guardado(s).")
            st.rerun()

        if not alvos and len(tabela_res):
            sugestao = (tabela_res.sum(axis=1) / max(len(tabela_res.columns), 1)).round(0)
            st.caption(
                "Sem ideia por onde começar? A tua média actual: "
                + " · ".join(f"**{c}** {v:,.0f} €".replace(",", " ")
                             for c, v in sugestao.head(5).items())
            )

    if tabela_res.empty:
        st.info("Nada a mostrar com os filtros actuais.")
    else:
        tabela_res = tabela_res.reindex(
            sorted(tabela_res.columns), axis=1
        ).loc[tabela_res.sum(axis=1).sort_values(ascending=False).index]

        escolha_cats = st.multiselect(
            "Mostrar", list(tabela_res.index), default=[],
            placeholder="Todas as despesas — ou escolhe as que queres ver",
        )
        if escolha_cats:
            # .loc[lista] reordena pela ordem em que as escolheste — volta a
            # ordenar por valor para a regra não se perder ao filtrar.
            tabela_res = tabela_res.loc[
                [c for c in tabela_res.index if c in escolha_cats]]

        n_cols = 1 if len(tabela_res) <= 3 else 2
        ordenadas = list(tabela_res.iterrows())

        for inicio in range(0, len(ordenadas), n_cols):
            faixa = ordenadas[inicio:inicio + n_cols]
            colunas = st.columns(n_cols, gap="medium")

            for pos, (categoria, serie) in enumerate(faixa):
                pares = [(m, float(serie[m])) for m in tabela_res.columns]
                maximo = max(v for _, v in pares) or 1.0
                total = sum(v for _, v in pares)

                alvo_cfg = alvos.get(categoria)
                alvo = alvo_cfg["valor"] if alvo_cfg else None
                anual = bool(alvo_cfg and alvo_cfg["periodo"] == "anual")

                # Num objetivo anual a comparação é com o acumulado; num mensal,
                # com cada mês de per si.
                if anual:
                    estado_global = objetivos.estado(total, alvo)
                else:
                    estado_global = objetivos.estado(pares[-1][1], alvo) if alvo else "sem_alvo"

                # Escala das barras: o objetivo mensal também conta, senão um mês
                # muito abaixo do alvo enchia a barra toda e parecia mau.
                escala = max(maximo, alvo) if (alvo and not anual) else maximo
                pos_alvo = (alvo / escala * 100) if (alvo and not anual) else None

                linhas = ""
                for m, v in pares:
                    if v == 0:
                        classe = "zero"
                    elif anual or not alvo:
                        classe = ""
                    else:
                        classe = "acima" if v > alvo else "dentro"
                    marca = (f'<u style="left:{pos_alvo:.1f}%"></u>'
                             if pos_alvo is not None else "")
                    linhas += (
                        f'<div class="linha">'
                        f'<span class="mes">{rotulo_mes(m)}</span>'
                        f'<div class="barra">{marca}<i class="{classe}" '
                        f'style="width:{max(v / escala * 100, 1.5):.1f}%"></i></div>'
                        f'<span class="val {classe if classe != "zero" else ""}">'
                        f'{euro(v)}</span>'
                        f"</div>"
                    )

                with colunas[pos].container(border=True):
                    ct, cb_ = st.columns([3, 2], vertical_alignment="center")

                    # O título é um botão: leva aos movimentos desta categoria.
                    if ct.button(categoria, key=f"ir_{categoria}", type="tertiary",
                                 help=f"Ver os movimentos de {categoria}"):
                        st.session_state["_ir_para"] = "Movimentos"
                        st.session_state["_filtrar_cats"] = [categoria]
                        st.rerun()

                    if alvo:
                        periodo_txt = " no ano" if anual else "/mês"
                        cb_.markdown(
                            f'<div style="text-align:right">'
                            f'<span class="alvo {estado_global}">objetivo '
                            f'{euro(alvo)}{periodo_txt}</span></div>',
                            unsafe_allow_html=True)
                    else:
                        cb_.markdown(
                            f'<div style="text-align:right" class="cartao-media">'
                            f'{euro(total / len(pares))}/mês · '
                            f'{euro(total)} no total</div>',
                            unsafe_allow_html=True)

                    st.markdown(linhas, unsafe_allow_html=True)

                    # Repartição por subcategoria, quando a categoria tem.
                    detalhe = f[f["categoria"] == categoria]
                    if cat_engine.subcategorias_de(categoria) and len(detalhe):
                        reparte = (detalhe.groupby(detalhe["subcategoria"].fillna("Sem detalhe"))
                                   ["saida"].sum().sort_values(ascending=False))
                        reparte = reparte[reparte > 0]
                        if len(reparte) > 1 or (len(reparte) == 1 and total > 0):
                            soma = reparte.sum() or 1.0
                            st.markdown(
                                '<div class="sub">' + "".join(
                                    f'<div class="sub-l"><span>{nome}</span>'
                                    f'<span class="sub-v">{euro(v)} · '
                                    f'{v / soma * 100:.0f} %</span></div>'
                                    for nome, v in reparte.items()
                                ) + "</div>", unsafe_allow_html=True)

                    nota = nota_da_categoria(pares)
                    if alvo:
                        if anual:
                            falta = alvo - total
                            nota += (f" Objetivo anual de {euro(alvo)}: "
                                     + (f"ultrapassado em {euro(-falta)}." if falta < 0
                                        else f"ainda há margem de {euro(falta)}."))
                        else:
                            dentro = sum(1 for _, v in pares if 0 < v <= alvo)
                            com_gasto = sum(1 for _, v in pares if v > 0)
                            if com_gasto:
                                nota += (f" {dentro} de {com_gasto} "
                                         f"{'mês' if com_gasto == 1 else 'meses'} "
                                         f"dentro do objetivo.")
                    st.markdown(f'<div class="nota">{nota}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- visão geral

if vista == "Visão geral":
    e, d = st.columns([3, 2])

    mensal = (f.groupby(["mes", "categoria"])["saida"].sum().reset_index())
    mensal = mensal[mensal["saida"] > 0]

    with e:
        st.subheader("Saídas por mês")
        barras = alt.Chart(mensal).mark_bar().encode(
            x=alt.X("mes:N", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("saida:Q", title="€", stack="zero"),
            color=alt.Color("categoria:N", title="Categoria",
                            scale=escala_cor(list(mensal["categoria"].unique()))),
            tooltip=["mes", "categoria", alt.Tooltip("saida:Q", title="€", format=".2f")],
        ).properties(height=380)
        st.altair_chart(barras, width="stretch")

    with d:
        st.subheader("Média mensal por categoria")
        media = (f.groupby("categoria")["saida"].sum() / n_meses).reset_index()
        media = media[media["saida"] > 0].sort_values("saida", ascending=False)
        h = alt.Chart(media).mark_bar().encode(
            y=alt.Y("categoria:N", sort="-x", title=None),
            x=alt.X("saida:Q", title="€/mês"),
            color=alt.Color("categoria:N", scale=escala_cor(list(media["categoria"])), legend=None),
            tooltip=[alt.Tooltip("saida:Q", title="€/mês", format=".2f")],
        ).properties(height=380)
        st.altair_chart(h, width="stretch")

    st.subheader("Saldo ao fim de cada mês")
    st.caption("Fim do mês, não movimento a movimento — senão um cheque grande (ex.: a "
               "escritura, compensada pelo empréstimo no mesmo dia) achata o resto do gráfico.")
    fecho = (df.sort_values("data").groupby("mes").last().reset_index()[["mes", "saldo"]])
    linha = alt.Chart(fecho).mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=2.5).encode(
        x=alt.X("mes:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("saldo:Q", title="€", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("mes:N", title="Mês"),
                 alt.Tooltip("saldo:Q", title="Saldo", format=",.2f")],
    ).properties(height=240)
    st.altair_chart(linha, width="stretch")

# ---------------------------------------------------------------- categorias

if vista == "Categorias":
    tabela = f.pivot_table(index="categoria", columns="mes", values="saida",
                           aggfunc="sum", fill_value=0)
    tabela["Total"] = tabela.sum(axis=1)
    tabela["Média/mês"] = tabela["Total"] / n_meses
    tabela = tabela[tabela["Total"] > 0].sort_values("Total", ascending=False)
    st.dataframe(
        tabela.style.format("{:,.2f} €").background_gradient(cmap="Blues", axis=None),
        width="stretch",
    )

    st.caption("Entradas")
    ent = f[f["entrada"] > 0].pivot_table(index="categoria", columns="mes",
                                          values="entrada", aggfunc="sum", fill_value=0)
    if not ent.empty:
        ent["Total"] = ent.sum(axis=1)
        st.dataframe(ent.style.format("{:,.2f} €"), width="stretch")

# ---------------------------------------------------------------- movimentos

if vista == "Movimentos":
    col1, col2 = st.columns([2, 1])
    procura = col1.text_input("Procurar no descritivo", "")

    # Pré-seleção vinda de um clique no título de uma categoria, no Resumo.
    disponiveis = sorted(f["categoria"].unique())
    # Limpa categorias que deixaram de existir com os filtros actuais —
    # senão o multiselect rebenta com um valor que não está nas opções.
    st.session_state["filtro_categorias"] = [
        c for c in st.session_state.get("filtro_categorias", []) if c in disponiveis
    ]
    cats_sel = col2.multiselect("Categorias", disponiveis, key="filtro_categorias")

    v = f.copy()
    if procura:
        v = v[v["descritivo"].str.contains(procura, case=False, na=False)]
    if cats_sel:
        v = v[v["categoria"].isin(cats_sel)]

    st.caption(f"{len(v)} movimentos · saídas {euro(v['saida'].sum())} · entradas {euro(v['entrada'].sum())}")
    st.dataframe(
        v[["data", "descritivo", "categoria", "subcategoria", "tipo",
           "etiqueta", "valor", "saldo"]]
        .assign(data=lambda x: x["data"].dt.strftime("%d/%m/%Y")),
        width="stretch", hide_index=True, height=460,
    )

    with st.expander("Etiquetar movimentos (viagens, obras, eventos)"):
        st.caption("A etiqueta é independente da categoria: o jantar fora numa viagem continua a ser "
                   "Restaurantes, mas podes tirar a viagem toda das médias de uma vez.")
        ids = st.multiselect(
            "Movimentos",
            options=list(v["id_mov"]),
            format_func=lambda i: (
                f"{v.loc[v['id_mov'] == i, 'data'].iloc[0]:%d/%m} · "
                f"{v.loc[v['id_mov'] == i, 'descritivo'].iloc[0][:45]} · "
                f"{v.loc[v['id_mov'] == i, 'valor'].iloc[0]:.2f} €"
            ),
        )
        nova_etq = st.text_input("Etiqueta", placeholder="Férias verão/26")
        ca, cb = st.columns(2)
        if ca.button("Aplicar etiqueta", disabled=not (ids and nova_etq)):
            with ligar() as con:
                definir_etiqueta(con, ids, nova_etq)
            st.rerun()
        if cb.button("Remover etiqueta", disabled=not ids):
            with ligar() as con:
                definir_etiqueta(con, ids, None)
            st.rerun()

# ---------------------------------------------------------------- fila

if vista == "Por categorizar":
    NOVA = "➕ criar nova…"

    # ---------------------------------------------------- sem categoria
    pendentes = df[df["categoria"] == SEM_CATEGORIA]
    st.subheader("Sem categoria")

    if pendentes.empty:
        st.success("Nada por categorizar.")
    else:
        st.caption("Escolhe a categoria, ou cria uma nova. O sistema grava a regra "
                   "e nunca mais pergunta por este comerciante.")
        opcoes = cat_engine.nomes_categorias + [NOVA]

        for _, linha in pendentes.iterrows():
            chave = linha["id_mov"]
            with st.container(border=True):
                a, b, c, d = st.columns([3, 2, 2, 1], vertical_alignment="center")
                a.markdown(f"**{linha['descritivo'][:60]}**  \n"
                           f"<span style='opacity:.6'>{linha['data']:%d/%m/%Y} · "
                           f"{euro(linha['valor'])}</span>", unsafe_allow_html=True)

                escolha = b.selectbox("Categoria", opcoes, key=f"c_{chave}",
                                      label_visibility="collapsed", index=None,
                                      placeholder="Categoria…")
                if escolha == NOVA:
                    escolha = b.text_input("Nome da nova categoria", key=f"nc_{chave}",
                                           placeholder="Nome da categoria nova…",
                                           label_visibility="collapsed").strip() or None

                padrao = c.text_input("Padrão", value=sugerir_padrao(linha["descritivo"]),
                                      key=f"p_{chave}", label_visibility="collapsed")

                # O botão NÃO é desactivado com base no texto escrito: o
                # Streamlit só regista o campo quando se carrega Enter ou se
                # clica fora, e um botão desactivado engolia o primeiro clique.
                if d.button("Guardar", key=f"b_{chave}"):
                    if not escolha or not padrao.strip():
                        st.warning("Falta a categoria ou o padrão.")
                        st.stop()
                    cat_engine.aprender_regra(padrao, escolha)
                    with ligar() as con:
                        definir_categoria(con, chave, escolha, cat_engine.tipo(escolha))
                        n = recategorizar_tudo(con, cat_engine)
                        aplicar_subcategorias(con, cat_engine)
                    st.toast(f"Regra **{padrao}** → **{escolha}**. "
                             f"{n} movimento(s) recategorizado(s).", icon="✅")
                    st.cache_resource.clear()
                    st.rerun()

    # ---------------------------------------------------- sem subcategoria
    # Só interessa onde há subcategorias definidas: não faz sentido pedir
    # detalhe do Crédito habitação.
    com_sub = [c for c in cat_engine.nomes_categorias if cat_engine.subcategorias_de(c)]
    sem_sub = df[(df["categoria"].isin(com_sub)) & (df["subcategoria"].isna())
                 & (df["valor"] < 0)]

    st.divider()
    st.subheader("Sem subcategoria")

    if not com_sub:
        st.caption("Ainda não há nenhuma categoria com subcategorias definidas.")
    elif sem_sub.empty:
        st.success("Todas as subcategorias atribuídas.")
    else:
        st.caption("Estes movimentos já têm categoria — falta-lhes o detalhe. "
                   "Também podes criar uma subcategoria nova.")

        for _, linha in sem_sub.iterrows():
            chave = linha["id_mov"]
            cat = linha["categoria"]
            opcoes_sub = cat_engine.subcategorias_de(cat) + [NOVA]
            with st.container(border=True):
                a, b, c, d = st.columns([3, 2, 2, 1], vertical_alignment="center")
                a.markdown(f"**{linha['descritivo'][:60]}**  \n"
                           f"<span style='opacity:.6'>{linha['data']:%d/%m/%Y} · "
                           f"{euro(linha['valor'])} · {cat}</span>",
                           unsafe_allow_html=True)

                sub = b.selectbox("Subcategoria", opcoes_sub, key=f"s_{chave}",
                                  label_visibility="collapsed", index=None,
                                  placeholder="Subcategoria…")
                if sub == NOVA:
                    sub = b.text_input("Nome da nova subcategoria", key=f"ns_{chave}",
                                       placeholder="Nome da subcategoria nova…",
                                       label_visibility="collapsed").strip() or None

                so_este = c.checkbox("Só este movimento", key=f"u_{chave}",
                                     help="Para lojas como a Amazon, em que o "
                                          "descritivo não diz o que foi comprado. "
                                          "Marca este movimento sem criar regra.")
                padrao_s = ""
                if not so_este:
                    padrao_s = c.text_input(
                        "Padrão", value=sugerir_padrao(linha["descritivo"]),
                        key=f"ps_{chave}", label_visibility="collapsed")

                if d.button("Guardar", key=f"bs_{chave}"):
                    if not sub:
                        st.warning("Falta escolher ou nomear a subcategoria.")
                        st.stop()
                    with ligar() as con:
                        if so_este:
                            definir_subcategoria(con, chave, sub)
                            st.toast(f"→ **{cat} / {sub}** (só este movimento).",
                                     icon="✅")
                        else:
                            if not padrao_s.strip():
                                st.warning("Falta o padrão.")
                                st.stop()
                            cat_engine.aprender_subregra(cat, sub, padrao_s)
                            n = aplicar_subcategorias(con, cat_engine)
                            st.toast(f"**{padrao_s}** → **{cat} / {sub}**. "
                                     f"{n} movimento(s) actualizado(s).", icon="✅")
                    st.cache_resource.clear()
                    st.rerun()
