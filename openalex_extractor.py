"""Extrae trabajos de una institución y temas dados desde OpenAlex."""

import csv
import os
import re
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://api.openalex.org"
API_KEY = "R1O9GVmiIE99uEncU928ck"  # Configura la variable OPENALEX_API_KEY con tu clave gratuita de OpenAlex. 
MAX_RESULTADOS = 300
RESULTADOS_POR_PAGINA = 120
BUSQUEDA_TEMATICA_BASE = "(agriculture OR sustainability OR bioeconomy OR crops OR agroecology OR biomass)"
SELECT_TRABAJOS = (
    "id,doi,title,authorships,abstract_inverted_index,publication_year,"
    "concepts,keywords,primary_location,locations,awards,funders,type"
)


def consultar(endpoint, parametros):
    """Hace una petición GET y devuelve el JSON de OpenAlex."""
    parametros["api_key"] = API_KEY
    url = f"{API}/{endpoint}?{urlencode(parametros)}"
    solicitud = Request(url, headers={"User-Agent": "sustaincrop-extractor/0.1"})
    with urlopen(solicitud, timeout=30) as respuesta:
        return json.load(respuesta)


def buscar_institucion(nombre):
    datos = consultar(
        "institutions",
        {
            "search": nombre,
            "per_page": 10,
            "select": "id,display_name,display_name_alternatives,display_name_acronyms",
        },
    )
    nombre_buscado = nombre.strip().casefold()
    for institucion in datos.get("results", []):
        nombre_oficial = institucion.get("display_name", "").strip()
        alternativas = institucion.get("display_name_alternatives", []) or []
        siglas = institucion.get("display_name_acronyms", []) or []
        nombres = [nombre_oficial, *alternativas, *siglas]
        if any(
            isinstance(candidato, str)
            and candidato.strip().casefold() == nombre_buscado
            for candidato in nombres
        ):
            print(f"Institución encontrada: {nombre_oficial}")
            return institucion["id"].rsplit("/", 1)[-1]
    return None


def reconstruir_resumen(indice):
    """Reconstruye el abstract de OpenAlex a partir de su índice invertido."""
    if not indice:
        return ""
    palabras = []
    for palabra, posiciones in indice.items():
        for posicion in posiciones:
            palabras.append((posicion, palabra))
    return " ".join(palabra for _, palabra in sorted(palabras))


def extraer_financiadores(trabajo):
    """Obtiene financiadores de awards y funders (esquema actual de OpenAlex)."""
    nombres = []
    vistos = set()
    for campo in ("awards", "funders"):
        for elemento in trabajo.get(campo, []) or []:
            nombre = (
                elemento.get("funder_display_name")
                or elemento.get("display_name")
                or ""
            ).strip()
            if nombre and nombre.casefold() not in vistos:
                nombres.append(nombre)
                vistos.add(nombre.casefold())
    return ", ".join(nombres)


def sintetizar_doi(doi):
    """Devuelve el DOI como URL DOI cuando OpenAlex solo entrega el identificador."""
    doi = (doi or "").strip()
    if doi.startswith("10."):
        return f"https://doi.org/{doi}"
    return doi


def extraer_autores(trabajo):
    nombres = [
        firma.get("author", {}).get("display_name", "").strip()
        for firma in trabajo.get("authorships", [])
    ]
    return "; ".join(nombre for nombre in nombres if nombre)


def extraer_instituciones_colaboradoras(trabajo):
    """Recoge instituciones únicas asociadas a todos los autores del trabajo."""
    nombres = []
    vistos = set()
    for firma in trabajo.get("authorships", []) or []:
        for institucion in firma.get("institutions", []) or []:
            nombre = (institucion or {}).get("display_name")
            if isinstance(nombre, str):
                nombre = nombre.strip()
                if nombre and nombre.casefold() not in vistos:
                    nombres.append(nombre)
                    vistos.add(nombre.casefold())
    return ", ".join(nombres)


def tiene_dataset_o_repositorio(trabajo):
    """Marca Sí si hay data_availability, un dataset o una ubicación de repositorio."""
    if trabajo.get("data_availability"):
        return "Sí"
    if trabajo.get("type", "").casefold() == "dataset":
        return "Sí"

    ubicaciones = list(trabajo.get("locations", []) or [])
    ubicacion_principal = trabajo.get("primary_location")
    if ubicacion_principal:
        ubicaciones.append(ubicacion_principal)
    for ubicacion in ubicaciones:
        source = (ubicacion or {}).get("source") or {}
        if source.get("type", "").casefold() == "repository":
            return "Sí"
    return "No"


def extraer_convocatorias(trabajo):
    """Extrae IDs disponibles en awards, el reemplazo actual de grants en OpenAlex."""
    convocatorias = []
    vistos = set()
    for award in trabajo.get("awards", []) or []:
        award_id = (
            award.get("award_id")
            or award.get("funder_award_id")
            or award.get("id")
            or ""
        ).strip()
        if award_id and award_id.casefold() not in vistos:
            convocatorias.append(award_id)
            vistos.add(award_id.casefold())
    return "; ".join(convocatorias)


def extraer_trabajos(nombre_institucion, temas):
    """Busca trabajos y los guarda en un CSV; devuelve la ruta del archivo."""
    if not API_KEY:
        print("Configura la variable OPENALEX_API_KEY con tu clave gratuita de OpenAlex.")
        return None

    nombre_institucion = nombre_institucion.strip()
    temas = [tema.strip() for tema in (temas or []) if tema.strip()]
    tipo_cultivo = temas[0] if temas else ""
    if not nombre_institucion:
        print("Debes indicar una institución.")
        return None

    try:
        ident = buscar_institucion(nombre_institucion)
        if not ident:
            print(f"No encontré la institución '{nombre_institucion}' en OpenAlex.")
            return None

        filtro = f"authorships.institutions.id:{ident}"
        trabajos = {}
        # Exige coincidencia con al menos un término temático base.
        # Si se proporcionan temas, cada uno se combina como filtro adicional.
        consultas = temas or [None]
        for tema in consultas:
            pagina = 1
            while len(trabajos) < MAX_RESULTADOS:
                parametros = {
                    "filter": filtro,
                    "per_page": RESULTADOS_POR_PAGINA,
                    "page": pagina,
                    "sort": "publication_year:desc",
                    "select": SELECT_TRABAJOS,
                }
                if tema:
                    parametros["search"] = f"{BUSQUEDA_TEMATICA_BASE} AND ({tema})"
                else:
                    parametros["search"] = BUSQUEDA_TEMATICA_BASE

                datos = consultar("works", parametros)
                resultados_pagina = datos.get("results", [])
                for trabajo in resultados_pagina:
                    trabajos[trabajo["id"]] = trabajo
                    if len(trabajos) >= MAX_RESULTADOS:
                        break

                total = datos.get("meta", {}).get("count", 0)
                if (
                    not resultados_pagina
                    or len(resultados_pagina) < RESULTADOS_POR_PAGINA
                    or pagina * RESULTADOS_POR_PAGINA >= total
                ):
                    break
                pagina += 1

        resultados = sorted(
            trabajos.values(),
            key=lambda trabajo: trabajo.get("publication_year") or 0,
            reverse=True,
        )[:MAX_RESULTADOS]
        if not resultados:
            print("No encontré trabajos para esa institución y esos filtros.")
            return None

        nombre_archivo = re.sub(r"[^\w.-]+", "_", nombre_institucion, flags=re.UNICODE)
        nombre_archivo = nombre_archivo.strip("._") or "institucion"
        archivo_csv = Path(__file__).with_name(f"resultados_{nombre_archivo}.csv")
        with archivo_csv.open("w", newline="", encoding="utf-8-sig") as archivo:
            columnas = [
                "DOI",
                "HIPERVÍNCULO SINTETIZADO",
                "AÑO",
                "REVISTA",
                "AUTORES",
                "INSTITUCIONES_COLABORADORAS",
                "TIPO DE CULTIVO",
                "DATASET",
                "RESUMEN DE ARTÍCULO",
                "ENTE FINANCIADOR",
                "CONVOCATORIA",
            ]
            escritor = csv.DictWriter(archivo, fieldnames=columnas)
            escritor.writeheader()
            for trabajo in resultados:
                escritor.writerow(
                    {
                        "DOI": trabajo.get("doi") or "",
                        "HIPERVÍNCULO SINTETIZADO": sintetizar_doi(
                            trabajo.get("doi")
                        ),
                        "AÑO": trabajo.get("publication_year") or "",
                        "REVISTA": (
                            (trabajo.get("primary_location") or {}).get("source")
                            or {}
                        ).get("display_name", ""),
                        "AUTORES": extraer_autores(trabajo),
                        "INSTITUCIONES_COLABORADORAS": (
                            extraer_instituciones_colaboradoras(trabajo)
                        ),
                        "TIPO DE CULTIVO": tipo_cultivo,
                        "DATASET": tiene_dataset_o_repositorio(trabajo),
                        "RESUMEN DE ARTÍCULO": reconstruir_resumen(
                            trabajo.get("abstract_inverted_index")
                        ),
                        "ENTE FINANCIADOR": extraer_financiadores(trabajo),
                        "CONVOCATORIA": extraer_convocatorias(trabajo),
                    }
                )
        print(f"Se guardaron {len(resultados)} resultados en: {archivo_csv}")
        return archivo_csv

    except HTTPError as error:
        print(f"Error HTTP de OpenAlex ({error.code}): {error.reason}")
    except URLError as error:
        print(f"No pude conectar con OpenAlex: {error.reason}")
    except (TimeoutError, json.JSONDecodeError, KeyError) as error:
        print(f"Error al leer la respuesta de OpenAlex: {error}")
        return None


def main():
    """Pide parámetros en terminal y ejecuta la extracción."""
    institucion = input("¿Qué institución deseas buscar? ").strip()
    entrada_temas = input(
        "¿Qué temas (separados por coma)? (opcional; Enter para todos) "
    ).strip()
    temas = [tema.strip() for tema in entrada_temas.split(",") if tema.strip()]
    extraer_trabajos(institucion, temas)


if __name__ == "__main__":
    main()


