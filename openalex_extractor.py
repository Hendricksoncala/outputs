"""Extrae trabajos de una institución y temas dados desde OpenAlex."""

import csv
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://api.openalex.org"
API_KEY = "Aqui va tu api key de OpenAlex"  # Configura la variable OPENALEX_API_KEY con tu clave gratuita de OpenAlex. 
MAX_RESULTADOS = 5


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


def extraer_colaboradores(trabajo):
    """Agrupa los autores y las instituciones asociadas por firma/autorship."""
    colaboradores = []
    for firma in trabajo.get("authorships", []):
        autor = firma.get("author", {}).get("display_name", "Autor sin nombre")
        instituciones = [
            institucion.get("display_name")
            for institucion in firma.get("institutions", [])
            if institucion.get("display_name")
        ]
        colaboradores.append({"autor": autor, "instituciones": instituciones})
    return colaboradores


def reconstruir_resumen(indice):
    """Reconstruye el abstract de OpenAlex a partir de su índice invertido."""
    if not indice:
        return ""
    palabras = []
    for palabra, posiciones in indice.items():
        for posicion in posiciones:
            palabras.append((posicion, palabra))
    return " ".join(palabra for _, palabra in sorted(palabras))


def extraer_trabajos(nombre_institucion, temas):
    """Busca trabajos y los guarda en un CSV; devuelve la ruta del archivo."""
    if not API_KEY:
        print("Configura la variable OPENALEX_API_KEY con tu clave gratuita de OpenAlex.")
        return None

    nombre_institucion = nombre_institucion.strip()
    temas = [tema.strip() for tema in temas if tema.strip()]
    if not nombre_institucion or not temas:
        print("Debes indicar una institución y al menos un tema de búsqueda.")
        return None

    try:
        ident = buscar_institucion(nombre_institucion)
        if not ident:
            print(f"No encontré la institución '{nombre_institucion}' en OpenAlex.")
            return None

        filtro = f"authorships.institutions.id:{ident}"
        trabajos = {}
        for tema in temas:
            datos = consultar(
                "works",
                {
                    "search": tema,
                    "filter": filtro,
                    "per_page": 5,
                    "select": "id,doi,title,authorships,abstract_inverted_index",
                },
            )
            for trabajo in datos.get("results", []):
                trabajos[trabajo["id"]] = trabajo

        resultados = list(trabajos.values())[:MAX_RESULTADOS]
        if not resultados:
            print("No encontré trabajos con esos términos. Prueba otros temas agrícolas.")
            return None

        nombre_archivo = re.sub(r"[^\w.-]+", "_", nombre_institucion, flags=re.UNICODE)
        nombre_archivo = nombre_archivo.strip("._") or "institucion"
        archivo_csv = Path(__file__).with_name(f"resultados_{nombre_archivo}.csv")
        with archivo_csv.open("w", newline="", encoding="utf-8-sig") as archivo:
            columnas = ["DOI", "Titulo", "Resumen", "Actores_Asociados"]
            escritor = csv.DictWriter(archivo, fieldnames=columnas)
            escritor.writeheader()
            for trabajo in resultados:
                escritor.writerow(
                    {
                        "DOI": trabajo.get("doi") or "",
                        "Titulo": trabajo.get("title") or "",
                        "Resumen": reconstruir_resumen(
                            trabajo.get("abstract_inverted_index")
                        ),
                        "Actores_Asociados": json.dumps(
                            extraer_colaboradores(trabajo), ensure_ascii=False
                        ),
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
    temas = input("¿Qué temas (separados por coma)? ").split(",")
    extraer_trabajos(institucion, temas)


if __name__ == "__main__":
    main()
