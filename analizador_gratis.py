"""Clasifica la relevancia de cada resumen de un CSV usando Groq."""

import csv
import json
import os
import sys
from pathlib import Path


MODELO = "mixtral-8x7b-32768"


def clasificar_resumen(cliente, resumen, tipo_cultivo):
    if not resumen.strip():
        return "No evaluable", "La fila no contiene resumen."

    prompt = f"""
Evalúa la relevancia del artículo para investigación en agricultura sostenible,
cultivos industriales y valorización de biomasa (proyecto SUSTAINCrop).
Considera el cultivo indicado, si existe. Usa solo la información del resumen.
Devuelve JSON válido con exactamente dos claves: "relevancia" ("Alta", "Media"
o "Baja") y "justificacion" (una frase breve en español).

Tipo de cultivo: {tipo_cultivo or "No especificado"}
Resumen: {resumen}
""".strip()

    respuesta = cliente.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    resultado = json.loads(respuesta.choices[0].message.content)
    relevancia = resultado.get("relevancia", "No evaluable")
    if relevancia not in {"Alta", "Media", "Baja"}:
        relevancia = "No evaluable"
    justificacion = resultado.get("justificacion", "")
    return relevancia, justificacion


def main():
    if len(sys.argv) > 1:
        archivo_entrada = Path(sys.argv[1])
    else:
        archivo_entrada = Path(input("Ruta del CSV generado por OpenAlex: ").strip())

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Configura la variable GROQ_API_KEY con tu clave de Groq.")
        return
    if not archivo_entrada.is_file():
        print(f"No encuentro el archivo: {archivo_entrada}")
        return

    try:
        from groq import Groq
    except ImportError:
        print("Falta la librería. Instálala con: pip install groq")
        return

    cliente = Groq(api_key=api_key)
    archivo_salida = archivo_entrada.with_name(
        f"{archivo_entrada.stem}_analizado{archivo_entrada.suffix}"
    )

    with archivo_entrada.open("r", newline="", encoding="utf-8-sig") as entrada:
        lector = csv.DictReader(entrada)
        if not lector.fieldnames or "RESUMEN DE ARTÍCULO" not in lector.fieldnames:
            print("El CSV no contiene la columna 'RESUMEN DE ARTÍCULO'.")
            return

        columnas = list(lector.fieldnames) + ["RELEVANCIA", "JUSTIFICACION"]
        with archivo_salida.open("w", newline="", encoding="utf-8-sig") as salida:
            escritor = csv.DictWriter(salida, fieldnames=columnas)
            escritor.writeheader()

            for numero, fila in enumerate(lector, start=1):
                try:
                    relevancia, justificacion = clasificar_resumen(
                        cliente,
                        fila.get("RESUMEN DE ARTÍCULO", ""),
                        fila.get("TIPO DE CULTIVO", ""),
                    )
                except Exception as error:
                    relevancia = "Error"
                    justificacion = str(error)

                fila["RELEVANCIA"] = relevancia
                fila["JUSTIFICACION"] = justificacion
                escritor.writerow(fila)
                print(f"Fila {numero}: {relevancia}")

    print(f"Análisis guardado en: {archivo_salida}")


if __name__ == "__main__":
    main()
