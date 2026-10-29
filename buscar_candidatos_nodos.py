"""Busca candidatos de institución en OpenAlex para revisión humana.

Entrada: nodos_semilla.csv en la carpeta actual.
Salida: candidatos_nodos.csv, sin selección automática.
"""

import csv
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.openalex.org"
CAMPOS = "id,display_name,ror,country_code,type,works_count,homepage_url,lineage"
MAX_REINTENTOS = 5
ENTRADA = Path.cwd() / "nodos_semilla.csv"
SALIDA = Path.cwd() / "candidatos_nodos.csv"
COLUMNAS_SALIDA = [
    "nombre_buscado", "siglas", "pais_esperado", "grupo", "openalex_id",
    "display_name", "ror", "country_code", "type", "works_count",
    "homepage_url", "lineage", "openalex_id_elegido",
]


def consultar_instituciones(termino, api_key):
    parametros = urlencode({"search": termino, "per_page": 10, "select": CAMPOS})
    url = f"{API}/institutions?{parametros}"
    headers = {"User-Agent": "sustaincrop-node-review/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for intento in range(MAX_REINTENTOS):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as respuesta:
                return json.load(respuesta).get("results", [])
        except HTTPError as error:
            if error.code not in {408, 429, 500, 502, 503, 504}:
                raise
            espera = int(error.headers.get("Retry-After", 0) or 0)
        except (URLError, TimeoutError, json.JSONDecodeError):
            espera = 0
        if intento == MAX_REINTENTOS - 1:
            raise RuntimeError(f"Consulta fallida tras {MAX_REINTENTOS} intentos.")
        time.sleep(espera or 2**intento)
    return []


def fila_candidato(semilla, candidato):
    lineage = candidato.get("lineage") or []
    return {
        "nombre_buscado": semilla["nombre_buscado"],
        "siglas": semilla.get("siglas", ""),
        "pais_esperado": semilla.get("pais_esperado", ""),
        "grupo": semilla.get("grupo", ""),
        "openalex_id": candidato.get("id", ""),
        "display_name": candidato.get("display_name", ""),
        "ror": candidato.get("ror", ""),
        "country_code": candidato.get("country_code", ""),
        "type": candidato.get("type", ""),
        "works_count": candidato.get("works_count", ""),
        "homepage_url": candidato.get("homepage_url", ""),
        "lineage": " | ".join(lineage) if isinstance(lineage, list) else lineage,
        "openalex_id_elegido": "",
    }


def main():
    api_key = "R1O9GVmiIE99uEncU928ck"
    if not api_key:
        print("OPENALEX_API_KEY no está definida; haré consultas básicas sin clave.")
    if not ENTRADA.is_file():
        print(f"No encontré el archivo de entrada: {ENTRADA}")
        return

    try:
        with ENTRADA.open("r", newline="", encoding="utf-8-sig") as archivo:
            lector = csv.DictReader(archivo)
            requeridas = {"nombre_buscado", "siglas", "pais_esperado", "grupo"}
            faltantes = requeridas.difference(lector.fieldnames or [])
            if faltantes:
                print("Faltan columnas en nodos_semilla.csv: " + ", ".join(sorted(faltantes)))
                return
            semillas = list(lector)

        filas = []
        for numero, semilla in enumerate(semillas, start=1):
            nombre = (semilla.get("nombre_buscado") or "").strip()
            siglas = (semilla.get("siglas") or "").strip()
            semilla["nombre_buscado"] = nombre
            semilla["siglas"] = siglas
            if not nombre:
                print(f"Fila {numero}: nombre_buscado vacío; se omite.")
                continue

            candidatos_por_id = {}
            consultas = [nombre]
            if siglas and siglas.casefold() != nombre.casefold():
                consultas.append(siglas)
            for termino in consultas:
                for candidato in consultar_instituciones(termino, api_key):
                    candidato_id = candidato.get("id")
                    if candidato_id:
                        candidatos_por_id.setdefault(candidato_id, candidato)

            candidatos = list(candidatos_por_id.values())[:5]
            if not candidatos:
                print(f"Fila {numero}: sin candidatos para '{nombre}'.")
            for candidato in candidatos:
                filas.append(fila_candidato(semilla, candidato))
            print(f"Fila {numero}: {len(candidatos)} candidatos; ninguno seleccionado.")

        with SALIDA.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_SALIDA)
            escritor.writeheader()
            escritor.writerows(filas)
        print(f"Candidatos guardados en: {SALIDA}")
    except HTTPError as error:
        print(f"OpenAlex devolvió HTTP {error.code}; agotados o inválidos los reintentos.")
    except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
        print(f"Error durante la consulta a OpenAlex: {error}")
    except OSError as error:
        print(f"Error al leer o guardar archivos: {error}")


if __name__ == "__main__":
    main()

