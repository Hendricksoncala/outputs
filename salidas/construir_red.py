"""Construye tablas y visualizaciones de coautoría institucional.

Lee sustaincrop.db en modo SQLite de solo lectura. Por defecto analiza las
obras asociadas en obra_nodo a nodos del grupo nucleo.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd


SALIDAS = Path(__file__).resolve().parent
DB_POR_DEFECTO = SALIDAS.parent / "sustaincrop.db"
TIPOS = ("education", "company", "government", "nonprofit", "facility", "other")
COLORES_TIPO = {
    "education": "#3973ac",
    "company": "#e07a32",
    "government": "#4f9b68",
    "nonprofit": "#9b59a4",
    "facility": "#bd5261",
    "other": "#9aa0a6",
}
TABLAS_REQUERIDAS = {
    "nodos": {"nodo_id", "openalex_id", "nombre", "siglas", "grupo", "ror", "pais"},
    "obras": {"openalex_id", "doi", "titulo", "anio", "tipo_obra", "es_dataset"},
    "obra_nodo": {"openalex_id_obra", "nodo_id"},
    "obra_institucion": {
        "openalex_id_obra", "institucion_openalex_id", "ror", "nombre", "tipo", "pais"
    },
    "obra_autor": {"openalex_id_obra", "autor_openalex_id", "orcid", "nombre", "posicion"},
    "obra_financiador": {
        "openalex_id_obra", "financiador_id", "nombre", "award_id", "es_bpin"
    },
    "posibles_duplicados": {
        "openalex_id", "clave_titulo_anio", "titulo_normalizado", "anio", "titulo"
    },
}


def conectar_solo_lectura(ruta: Path) -> sqlite3.Connection:
    uri = ruta.resolve().as_uri() + "?mode=ro"
    conexion = sqlite3.connect(uri, uri=True)
    conexion.row_factory = sqlite3.Row
    return conexion


def validar_esquema(conexion: sqlite3.Connection) -> list[str]:
    disponibles = {
        fila[0]
        for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    faltantes = []
    for tabla, columnas_requeridas in TABLAS_REQUERIDAS.items():
        if tabla not in disponibles:
            faltantes.append(f"tabla {tabla}")
            continue
        columnas = {
            fila[1] for fila in conexion.execute(f'PRAGMA table_info("{tabla}")')
        }
        for columna in sorted(columnas_requeridas - columnas):
            faltantes.append(f"columna {tabla}.{columna}")
    return faltantes


def modo_texto(serie: pd.Series) -> str:
    valores = serie.dropna().astype(str)
    valores = valores[valores.str.strip() != ""]
    if valores.empty:
        return ""
    frecuencias = valores.value_counts()
    return str(sorted(frecuencias[frecuencias == frecuencias.max()].index)[0])


def categoria_tipo(valor: object) -> str:
    texto = str(valor or "").strip().casefold()
    return texto if texto in TIPOS[:-1] else "other"


def escribir_csv(df: pd.DataFrame, nombre: str) -> None:
    df.to_csv(SALIDAS / nombre, index=False, encoding="utf-8-sig")


def cargar_datos(conexion: sqlite3.Connection):
    nodos = pd.read_sql_query(
        """SELECT nodo_id, openalex_id, nombre, siglas, grupo, ror, pais
           FROM nodos WHERE grupo='nucleo' AND openalex_id<>''
             AND openalex_id NOT LIKE 'omitido:%' ORDER BY nodo_id""",
        conexion,
    )
    if nodos.empty:
        raise ValueError("No hay nodos válidos con grupo='nucleo' en nodos.")

    enlaces_nodo = pd.read_sql_query(
        """SELECT DISTINCT onodo.openalex_id_obra, onodo.nodo_id
           FROM obra_nodo AS onodo JOIN nodos AS n ON n.nodo_id=onodo.nodo_id
           WHERE n.grupo='nucleo' AND n.openalex_id<>''
             AND n.openalex_id NOT LIKE 'omitido:%'""",
        conexion,
    )
    obras = pd.read_sql_query(
        """SELECT DISTINCT o.openalex_id, o.doi, o.titulo, o.anio,
                  o.tipo_obra, o.es_dataset
           FROM obras AS o JOIN obra_nodo AS onodo
             ON onodo.openalex_id_obra=o.openalex_id
           JOIN nodos AS n ON n.nodo_id=onodo.nodo_id
           WHERE n.grupo='nucleo' AND n.openalex_id<>''
             AND n.openalex_id NOT LIKE 'omitido:%'""",
        conexion,
    )
    instituciones = pd.read_sql_query(
        """SELECT DISTINCT i.openalex_id_obra, i.institucion_openalex_id,
                  i.ror, i.nombre, i.tipo, i.pais
           FROM obra_institucion AS i JOIN obra_nodo AS onodo
             ON onodo.openalex_id_obra=i.openalex_id_obra
           JOIN nodos AS n ON n.nodo_id=onodo.nodo_id
           WHERE n.grupo='nucleo' AND n.openalex_id<>''
             AND n.openalex_id NOT LIKE 'omitido:%'""",
        conexion,
    )
    financiadores = pd.read_sql_query(
        """SELECT DISTINCT f.openalex_id_obra, f.financiador_id, f.nombre,
                  f.award_id, f.es_bpin
           FROM obra_financiador AS f JOIN obra_nodo AS onodo
             ON onodo.openalex_id_obra=f.openalex_id_obra
           JOIN nodos AS n ON n.nodo_id=onodo.nodo_id
           WHERE n.grupo='nucleo' AND n.openalex_id<>''
             AND n.openalex_id NOT LIKE 'omitido:%'""",
        conexion,
    )
    return nodos, enlaces_nodo, obras, instituciones, financiadores


def construir_enlaces(instituciones: pd.DataFrame, obras: pd.DataFrame):
    instituciones_por_obra = {
        work_id: sorted(set(group["institucion_openalex_id"].dropna().astype(str)))
        for work_id, group in instituciones.groupby("openalex_id_obra", sort=False)
    }
    anios = obras.set_index("openalex_id")["anio"].to_dict()
    acumulados = {}
    for work_id, ids in instituciones_por_obra.items():
        n_instituciones = len(ids)
        if n_instituciones < 2:
            continue
        aporte = 1.0 / (n_instituciones - 1)
        anio = anios.get(work_id)
        try:
            anio = int(anio) if pd.notna(anio) else None
        except (TypeError, ValueError):
            anio = None
        for origen, destino in itertools.combinations(ids, 2):
            dato = acumulados.setdefault(
                (origen, destino), {"n_obras": 0, "anio_primero": None, "anio_ultimo": None, "peso": 0.0}
            )
            dato["n_obras"] += 1
            dato["peso"] += aporte
            if anio is not None:
                dato["anio_primero"] = anio if dato["anio_primero"] is None else min(dato["anio_primero"], anio)
                dato["anio_ultimo"] = anio if dato["anio_ultimo"] is None else max(dato["anio_ultimo"], anio)
    columnas = ["origen", "destino", "n_obras", "anio_primero", "anio_ultimo", "peso"]
    filas = [{"origen": a, "destino": b, **dato} for (a, b), dato in acumulados.items()]
    aristas = pd.DataFrame(filas, columns=columnas)
    return aristas, instituciones_por_obra


def construir_grafo(nodos, aristas, instituciones, instituciones_por_obra):
    grafo = nx.Graph()
    core_ids = set(nodos["openalex_id"].dropna().astype(str))
    metadata = {}
    if not instituciones.empty:
        for inst_id, grupo in instituciones.groupby("institucion_openalex_id", sort=False):
            metadata[str(inst_id)] = {
                "nombre": modo_texto(grupo["nombre"]),
                "ror": modo_texto(grupo["ror"]),
                "tipo": modo_texto(grupo["tipo"]),
                "pais": modo_texto(grupo["pais"]),
                "n_obras": int(grupo["openalex_id_obra"].nunique()),
            }
    for nodo in nodos.to_dict("records"):
        inst_id = str(nodo["openalex_id"])
        metadata.setdefault(
            inst_id,
            {
                "nombre": str(nodo.get("nombre") or ""),
                "ror": str(nodo.get("ror") or ""),
                "tipo": "",
                "pais": str(nodo.get("pais") or ""),
                "n_obras": 0,
            },
        )
        # Los nombres son etiquetas; todos los enlaces se identifican por OpenAlex ID.
        metadata[inst_id]["es_nucleo"] = True
    for inst_id, dato in metadata.items():
        dato.setdefault("es_nucleo", inst_id in core_ids)
        dato["tipo_categoria"] = categoria_tipo(dato.get("tipo"))
        grafo.add_node(inst_id, **dato)
    for edge in aristas.to_dict("records"):
        peso = float(edge["peso"])
        grafo.add_edge(
            edge["origen"],
            edge["destino"],
            n_obras=int(edge["n_obras"]),
            anio_primero=edge["anio_primero"] if pd.notna(edge["anio_primero"]) else "",
            anio_ultimo=edge["anio_ultimo"] if pd.notna(edge["anio_ultimo"]) else "",
            weight=peso,
            distance=1.0 / peso if peso > 0 else 0.0,
        )
    return grafo, metadata, core_ids


def centralidad_intermediacion(grafo: nx.Graph) -> dict[str, float]:
    n = grafo.number_of_nodes()
    if n == 0:
        return {}
    # Muestreo determinista para mantener viable el cálculo en redes grandes.
    k = min(500, n) if n > 1500 else None
    if k is None:
        return nx.betweenness_centrality(grafo, normalized=True, weight="distance")
    return nx.betweenness_centrality(
        grafo, k=k, normalized=True, weight="distance", seed=42
    )


def comunidades_louvain(grafo: nx.Graph) -> dict[str, str]:
    try:
        comunidades = nx.community.louvain_communities(grafo, weight="weight", seed=42)
    except (AttributeError, ImportError, nx.NetworkXError):
        return {node: "" for node in grafo}
    salida = {}
    for numero, comunidad in enumerate(comunidades, start=1):
        for node in comunidad:
            salida[node] = str(numero)
    return salida


def tabla_nodos(grafo, metadata, core_ids, betweenness, comunidades):
    filas = []
    for inst_id in grafo.nodes:
        dato = metadata[inst_id]
        filas.append(
            {
                "institucion_openalex_id": inst_id,
                "nombre": dato.get("nombre", ""),
                "ror": dato.get("ror", ""),
                "tipo": dato.get("tipo", ""),
                "pais": dato.get("pais", ""),
                "n_obras": int(dato.get("n_obras", 0)),
                "grado": int(grafo.degree(inst_id)),
                "grado_ponderado": float(grafo.degree(inst_id, weight="weight")),
                "intermediacion": float(betweenness.get(inst_id, 0.0)),
                "comunidad": comunidades.get(inst_id, ""),
                "es_nucleo": inst_id in core_ids,
            }
        )
    return pd.DataFrame(
        filas,
        columns=[
            "institucion_openalex_id", "nombre", "ror", "tipo", "pais", "n_obras",
            "grado", "grado_ponderado", "intermediacion", "comunidad", "es_nucleo",
        ],
    )


def tablas_por_nodo(nodos, enlaces_nodo, obras, instituciones, financiadores, nodos_red):
    etiquetas = nodos.set_index("nodo_id").to_dict("index")
    obra_info = obras.set_index("openalex_id").to_dict("index")
    inst_por_obra = {
        work_id: group.drop_duplicates("institucion_openalex_id")
        for work_id, group in instituciones.groupby("openalex_id_obra", sort=False)
    }
    nodo_por_id = {str(row["openalex_id"]): row for row in nodos.to_dict("records")}

    # Obras por año y nodo.
    base_anio = enlaces_nodo.copy()
    base_anio = base_anio.merge(
        obras[["openalex_id", "anio"]],
        left_on="openalex_id_obra", right_on="openalex_id", how="left",
    )
    base_anio["anio"] = pd.to_numeric(base_anio["anio"], errors="coerce")
    obras_anio = (
        base_anio.dropna(subset=["anio"])
        .groupby(["nodo_id", "anio"], as_index=False)["openalex_id_obra"].nunique()
        .rename(columns={"openalex_id_obra": "n_obras"})
    )
    obras_anio["nodo"] = obras_anio["nodo_id"].map(lambda x: etiquetas[x].get("siglas") or etiquetas[x]["nombre"])
    obras_anio["anio"] = obras_anio["anio"].astype(int)
    escribir_csv(obras_anio[["nodo_id", "nodo", "anio", "n_obras"]], "obras_por_anio_y_nodo.csv")

    # Pares nodo núcleo-institución colaboradora por obra, con ID estable.
    pares = set()
    for rel in enlaces_nodo.itertuples(index=False):
        core = nodo_por_id.get(str(etiquetas[rel.nodo_id]["openalex_id"]))
        core_id = str(core["openalex_id"]) if core else ""
        for inst_id in inst_por_obra.get(rel.openalex_id_obra, pd.DataFrame())["institucion_openalex_id"].tolist() if rel.openalex_id_obra in inst_por_obra else []:
            inst_id = str(inst_id)
            if inst_id and inst_id != core_id:
                pares.add((rel.nodo_id, rel.openalex_id_obra, inst_id))

    inst_metadata = {}
    if not instituciones.empty:
        for inst_id, group in instituciones.groupby("institucion_openalex_id", sort=False):
            inst_metadata[str(inst_id)] = {
                "nombre": modo_texto(group["nombre"]),
                "tipo": modo_texto(group["tipo"]),
                "pais": modo_texto(group["pais"]),
            }

    # Tipos de institución colaboradora y principales colaboradores.
    tipo_inst = defaultdict(set)
    tipo_obras = defaultdict(set)
    colab_obras = defaultdict(set)
    pais_inst = defaultdict(set)
    pais_obras = defaultdict(set)
    for nodo_id, work_id, inst_id in pares:
        dato = inst_metadata.get(inst_id, {"nombre": "", "tipo": "", "pais": ""})
        categoria = categoria_tipo(dato.get("tipo"))
        tipo_inst[(nodo_id, categoria)].add(inst_id)
        tipo_obras[(nodo_id, categoria)].add(work_id)
        colab_obras[(nodo_id, inst_id)].add(work_id)
        pais = str(dato.get("pais") or "")
        pais_inst[(nodo_id, pais)].add(inst_id)
        pais_obras[(nodo_id, pais)].add(work_id)

    tipo_rows = []
    for nodo_id in etiquetas:
        nodo = etiquetas[nodo_id].get("siglas") or etiquetas[nodo_id]["nombre"]
        for categoria in TIPOS:
            tipo_rows.append(
                {
                    "nodo_id": nodo_id, "nodo": nodo, "tipo": categoria,
                    "n_instituciones": len(tipo_inst[(nodo_id, categoria)]),
                    "n_obras": len(tipo_obras[(nodo_id, categoria)]),
                }
            )
    escribir_csv(pd.DataFrame(tipo_rows), "tipos_de_institucion_colaboradora_por_nodo.csv")

    top_rows = []
    for nodo_id in etiquetas:
        ranked = sorted(
            ((inst_id, len(work_set)) for (n_id, inst_id), work_set in colab_obras.items() if n_id == nodo_id),
            key=lambda x: (-x[1], inst_metadata.get(x[0], {}).get("nombre", "").casefold(), x[0]),
        )[:20]
        for posicion, (inst_id, n_works) in enumerate(ranked, start=1):
            dato = inst_metadata.get(inst_id, {"nombre": "", "tipo": "", "pais": ""})
            top_rows.append(
                {
                    "nodo_id": nodo_id,
                    "nodo": etiquetas[nodo_id].get("siglas") or etiquetas[nodo_id]["nombre"],
                    "posicion": posicion, "institucion_openalex_id": inst_id,
                    "nombre": dato.get("nombre", ""), "tipo": dato.get("tipo", ""),
                    "pais": dato.get("pais", ""), "n_obras": n_works,
                }
            )
    top = pd.DataFrame(
        top_rows,
        columns=["nodo_id", "nodo", "posicion", "institucion_openalex_id", "nombre", "tipo", "pais", "n_obras"],
    )
    escribir_csv(top, "top_20_colaboradores_por_nodo.csv")

    pais_rows = []
    for nodo_id in etiquetas:
        for (n_id, pais), insts in pais_inst.items():
            if n_id == nodo_id:
                pais_rows.append(
                    {
                        "nodo_id": nodo_id,
                        "nodo": etiquetas[nodo_id].get("siglas") or etiquetas[nodo_id]["nombre"],
                        "pais": pais, "n_instituciones": len(insts),
                        "n_obras": len(pais_obras[(nodo_id, pais)]),
                    }
                )
    escribir_csv(pd.DataFrame(pais_rows, columns=["nodo_id", "nodo", "pais", "n_instituciones", "n_obras"]), "colaboracion_por_pais.csv")

    # Financiación por obra, con cero explícito para nodos sin BPIN.
    funder_work = financiadores.dropna(subset=["openalex_id_obra"]).drop_duplicates(
        ["openalex_id_obra", "financiador_id", "award_id"]
    )
    funder_freq = (
        funder_work.groupby(["financiador_id", "nombre"], dropna=False)
        .agg(
            n_obras=("openalex_id_obra", "nunique"),
            n_awards=("award_id", lambda values: values.replace("", pd.NA).nunique()),
            n_bpin=("es_bpin", lambda values: int(pd.to_numeric(values, errors="coerce").fillna(0).astype(bool).sum())),
        )
        .reset_index()
        .sort_values(["n_obras", "nombre"], ascending=[False, True])
    )
    escribir_csv(funder_freq, "financiadores_mas_frecuentes.csv")

    bpin_rows, dataset_rows = [], []
    bpin_set = set(
        funder_work.loc[pd.to_numeric(funder_work["es_bpin"], errors="coerce").fillna(0).astype(bool), "openalex_id_obra"]
    )
    for nodo_id in etiquetas:
        node_works = enlaces_nodo.loc[enlaces_nodo["nodo_id"] == nodo_id, "openalex_id_obra"].drop_duplicates().tolist()
        total = len(node_works)
        with_bpin = len(set(node_works) & bpin_set)
        dataset_count = sum(
            str(obra_info.get(wid, {}).get("tipo_obra") or "").casefold() == "dataset"
            for wid in node_works
        )
        bpin_rows.append(
            {
                "nodo_id": nodo_id,
                "nodo": etiquetas[nodo_id].get("siglas") or etiquetas[nodo_id]["nombre"],
                "obras_totales": total, "obras_con_bpin": with_bpin,
            }
        )
        dataset_rows.append(
            {
                "nodo_id": nodo_id,
                "nodo": etiquetas[nodo_id].get("siglas") or etiquetas[nodo_id]["nombre"],
                "obras_totales": total, "obras_dataset": dataset_count,
                "porcentaje_dataset": (100.0 * dataset_count / total) if total else 0.0,
            }
        )
    escribir_csv(pd.DataFrame(bpin_rows), "obras_con_bpin_por_nodo.csv")
    escribir_csv(pd.DataFrame(dataset_rows), "porcentaje_obras_dataset_por_nodo.csv")

    aislados = nodos_red.loc[nodos_red["es_nucleo"] & (nodos_red["grado"] <= 1)].copy()
    aislados["criterio_grado_bajo"] = "grado <= 1"
    escribir_csv(aislados, "nodos_del_nucleo_aislados.csv")
    top_betweenness = nodos_red.sort_values(
        ["intermediacion", "institucion_openalex_id"], ascending=[False, True]
    ).head(15)
    escribir_csv(top_betweenness, "top_15_por_intermediacion.csv")
    return obras_anio, top, tipo_rows


def crear_graficas(obras_anio, top, tipo_rows, nodos_red, grafo, metadata, core_ids):
    plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 180, "font.size": 9})

    # 1. Obras por año y nodo.
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not obras_anio.empty:
        pivot = obras_anio.pivot_table(index="anio", columns="nodo", values="n_obras", aggfunc="sum", fill_value=0)
        pivot.sort_index().plot(ax=ax, marker="o", linewidth=1.5)
        ax.legend(title="Nodo", bbox_to_anchor=(1.02, 1), loc="upper left")
    else:
        ax.text(0.5, 0.5, "Sin años disponibles", ha="center", va="center", transform=ax.transAxes)
    ax.set(title="Obras por año y nodo del núcleo", xlabel="Año", ylabel="Obras")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(SALIDAS / "obras_por_anio_y_nodo.png", bbox_inches="tight")
    plt.close(fig)

    # 2. Composición por categoría de tipo de colaborador.
    tipos = pd.DataFrame(tipo_rows)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not tipos.empty:
        pivot = tipos.pivot(index="nodo", columns="tipo", values="n_instituciones").fillna(0)
        pivot = pivot.reindex(columns=TIPOS, fill_value=0)
        pivot.plot(kind="bar", stacked=True, ax=ax, color=[COLORES_TIPO[t] for t in pivot.columns])
        ax.legend(title="Tipo", bbox_to_anchor=(1.02, 1), loc="upper left")
    ax.set(title="Composición de instituciones colaboradoras", xlabel="Nodo", ylabel="Instituciones únicas")
    ax.tick_params(axis="x", labelrotation=35)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(SALIDAS / "composicion_por_tipo.png", bbox_inches="tight")
    plt.close(fig)

    # 3. Núcleo por sus 15 colaboradores más frecuentes en conjunto.
    fig, ax = plt.subplots(figsize=(12, 6))
    if not top.empty:
        global_top = top.groupby(["institucion_openalex_id", "nombre"], as_index=False)["n_obras"].sum()
        global_top = global_top.sort_values("n_obras", ascending=False).head(15)
        ids = set(global_top["institucion_openalex_id"])
        heat_rows = []
        for nodo_id in sorted(top["nodo_id"].unique()):
            nodo_label = top.loc[top["nodo_id"] == nodo_id, "nodo"].iloc[0]
            row = {inst_id: 0 for inst_id in ids}
            subset = top[(top["nodo_id"] == nodo_id) & top["institucion_openalex_id"].isin(ids)]
            for rec in subset.to_dict("records"):
                row[rec["institucion_openalex_id"]] = rec["n_obras"]
            heat_rows.append((nodo_label, row))
        matrix = [[row[inst_id] for inst_id in global_top["institucion_openalex_id"]] for _, row in heat_rows]
        im = ax.imshow(matrix, aspect="auto", cmap="YlGnBu")
        ax.set_yticks(range(len(heat_rows)), labels=[label for label, _ in heat_rows])
        ax.set_xticks(range(len(global_top)), labels=[(str(x)[:28] + "…") if len(str(x)) > 29 else str(x) for x in global_top["nombre"]], rotation=45, ha="right")
        fig.colorbar(im, ax=ax, label="Obras compartidas")
    else:
        ax.text(0.5, 0.5, "Sin colaboraciones registradas", ha="center", va="center", transform=ax.transAxes)
    ax.set(title="Núcleo × colaboradores principales")
    fig.tight_layout()
    fig.savefig(SALIDAS / "mapa_calor_nucleo_colaboradores.png", bbox_inches="tight")
    plt.close(fig)

    # 4. Subred legible del núcleo y sus 25 colaboradores principales por nodo.
    keep = set(core_ids)
    if not top.empty:
        for _, grupo in top.groupby("nodo_id", sort=False):
            keep.update(grupo.head(25)["institucion_openalex_id"].astype(str))
    sub = grafo.subgraph(keep).copy()
    fig, ax = plt.subplots(figsize=(11, 8))
    if sub.number_of_nodes():
        pos = nx.spring_layout(sub, seed=42, iterations=35, weight="weight")
        ranks = nodos_red.set_index("institucion_openalex_id")["intermediacion"].to_dict()
        sizes = [100 + 2200 * math.sqrt(max(0.0, float(ranks.get(node, 0.0)))) for node in sub.nodes]
        colors = [COLORES_TIPO.get(categoria_tipo(metadata.get(node, {}).get("tipo")), COLORES_TIPO["other"]) for node in sub.nodes]
        borders = ["#111111" if node in core_ids else "white" for node in sub.nodes]
        nx.draw_networkx_edges(sub, pos, ax=ax, alpha=0.18, width=0.6, edge_color="#657786")
        nx.draw_networkx_nodes(
            sub, pos, ax=ax, node_size=sizes, node_color=colors,
            edgecolors=borders, linewidths=[1.8 if node in core_ids else 0.4 for node in sub.nodes],
        )
        ax.axis("off")
        from matplotlib.lines import Line2D
        leyenda = [
            Line2D([0], [0], marker="o", color="w", label=tipo,
                   markerfacecolor=color, markersize=8)
            for tipo, color in COLORES_TIPO.items()
        ]
        ax.legend(handles=leyenda, title="Tipo", loc="lower left", frameon=False)
    else:
        ax.text(0.5, 0.5, "Red vacía", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Red del núcleo y colaboradores principales\n(tamaño ∝ intermediación; borde negro = núcleo)")
    fig.tight_layout()
    fig.savefig(SALIDAS / "red_colaboracion.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera tablas y gráficas de la red de coautoría del núcleo.")
    parser.add_argument("--db", type=Path, default=DB_POR_DEFECTO, help="Ruta a sustaincrop.db")
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"No se encontró la base: {args.db}")
        return 2

    SALIDAS.mkdir(parents=True, exist_ok=True)
    try:
        conexion = conectar_solo_lectura(args.db)
    except sqlite3.Error as error:
        print(f"No se pudo abrir la base en modo solo lectura: {error}")
        return 2
    try:
        faltantes = validar_esquema(conexion)
        if faltantes:
            print("Faltan tablas o columnas requeridas; no se generaron salidas:")
            for elemento in faltantes:
                print(f"- {elemento}")
            return 2

        nodos, enlaces_nodo, obras, instituciones, financiadores = cargar_datos(conexion)
        aristas, _ = construir_enlaces(instituciones, obras)
        grafo, metadata, core_ids = construir_grafo(nodos, aristas, instituciones, {})
        betweenness = centralidad_intermediacion(grafo)
        comunidades = comunidades_louvain(grafo)
        nodos_red = tabla_nodos(grafo, metadata, core_ids, betweenness, comunidades)

        escribir_csv(aristas, "aristas_coautoria.csv")
        escribir_csv(nodos_red, "nodos_red.csv")
        nx.write_gexf(grafo, SALIDAS / "red.gexf")
        obras_anio, top, tipo_rows = tablas_por_nodo(
            nodos, enlaces_nodo, obras, instituciones, financiadores, nodos_red
        )
        crear_graficas(obras_anio, top, tipo_rows, nodos_red, grafo, metadata, core_ids)

        total_db = int(conexion.execute("SELECT COUNT(*) FROM obras").fetchone()[0])
        obras_red = int(obras["openalex_id"].nunique())
        doi_pct = 100.0 * int((obras["doi"].fillna("").astype(str).str.strip() != "").sum()) / len(obras) if len(obras) else 0.0
        print(f"Obras únicas en la base: {total_db}")
        print(f"Obras vinculadas al núcleo analizadas: {obras_red}")
        print(f"Instituciones en la red: {grafo.number_of_nodes()}")
        print(f"Aristas de coautoría: {grafo.number_of_edges()}")
        print(f"Obras del entorno con DOI: {doi_pct:.1f}%")
        print("La red representa el entorno bibliográfico del núcleo SUSTAINCrop, no todo el sector.")
        if grafo.number_of_nodes() > 1500:
            print("Intermediación aproximada con muestreo determinista de hasta 500 nodos.")
        print(f"Salidas guardadas en: {SALIDAS}")
    except (sqlite3.Error, ValueError, KeyError) as error:
        print(f"No se pudo construir la red: {error}")
        return 2
    finally:
        conexion.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
