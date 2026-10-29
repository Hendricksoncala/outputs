"""Valida IDs OpenAlex y campos obligatorios en nodos.csv."""

import csv
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

API = "https://api.openalex.org"
ENTRADA = Path.cwd() / "nodos.csv"
MAX_REINTENTOS = 5
CAMPOS_REQUERIDOS = ("openalex_id", "ror", "url_oficial")


def obtener_institucion(openalex_id, api_key):
    ident = openalex_id.strip().rstrip("/").split("/")[-1]
    url = f"{API}/institutions/{quote(ident, safe='')}"
    headers = {
        "User-Agent": "sustaincrop-node-validator/1.0",
        "Authorization": f"Bearer {api_key}",
    }
    for intento in range(MAX_REINTENTOS):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as respuesta:
                return json.load(respuesta)
        except HTTPError as error:
            if error.code in {400, 404}:
                return None
            if error.code not in {408, 429, 500, 502, 503, 504}:
                raise
            espera = int(error.headers.get("Retry-After", 0) or 0)
        except (URLError, TimeoutError, json.JSONDecodeError):
            espera = 0
        if intento == MAX_REINTENTOS - 1:
            raise RuntimeError(f"Consulta fallida tras {MAX_REINTENTOS} intentos.")
        time.sleep(espera or 2**intento)
    return None


def main():
    api_key = "R1O9GVmiIE99uEncU928ck"#-----
    if not api_key:
        print("Configura la variable de entorno OPENALEX_API_KEY antes de validar IDs.")
        return
    if not ENTRADA.is_file():
        print(f"No encontré el archivo: {ENTRADA}")
        return

    try:
        with ENTRADA.open("r", newline="", encoding="utf-8-sig") as archivo:
            lector = csv.DictReader(archivo)
            faltan_columnas = set(CAMPOS_REQUERIDOS).difference(lector.fieldnames or [])
            if faltan_columnas:
                print("Faltan columnas en nodos.csv: " + ", ".join(sorted(faltan_columnas)))
                return
            nodos = list(lector)
    except (OSError, csv.Error) as error:
        print(f"No pude leer nodos.csv: {error}")
        return

    problemas = []
    for numero, nodo in enumerate(nodos, start=2):
        nombre = (nodo.get("nombre_buscado") or nodo.get("display_name") or f"fila {numero}").strip()
        faltantes = [campo for campo in CAMPOS_REQUERIDOS if not (nodo.get(campo) or "").strip()]
        if faltantes:
            problemas.append(f"{nombre}: faltan {', '.join(faltantes)}")

        url_oficial = (nodo.get("url_oficial") or "").strip()
        if url_oficial:
            parsed = urlparse(url_oficial)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                problemas.append(f"{nombre}: url_oficial no parece una URL absoluta válida")

        openalex_id = (nodo.get("openalex_id") or "").strip()
        if openalex_id:
            try:
                institucion = obtener_institucion(openalex_id, api_key)
                if institucion is None:
                    problemas.append(f"{nombre}: openalex_id no existe en OpenAlex ({openalex_id})")
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
                problemas.append(f"{nombre}: no se pudo verificar el ID en OpenAlex ({error})")

    if problemas:
        print(f"Validación: {len(problemas)} problema(s) encontrado(s).")
        for problema in problemas:
            print(f"- {problema}")
    else:
        print(f"Validación correcta: {len(nodos)} nodo(s) tienen los campos requeridos y un ID existente.")


if __name__ == "__main__":
    main()
