"""Clasifica la relevancia de cada resumen de un CSV usando Groq."""

import csv
import json
import os
import sys
import time
from pathlib import Path


MODELO = "openai/gpt-oss-20b"
CATEGORIAS_SUSTAINCROP = [
    "Investigación & Conocimiento",
    "Industria & Mercado",
    "Sector Primario",
    "Política & Regulación",
    "Financiación & Inversión",
    "Sociedad Civil & Territorio",
]


def clasificar_resumen(cliente, resumen, tipo_cultivo):
    if not resumen.strip():
        return "No evaluable", "", "No aplica"

    lista_categorias = "\n".join(
        f"{i}. {categoria}"
        for i, categoria in enumerate(CATEGORIAS_SUSTAINCROP, start=1)
    )

    prompt = f"""
Evalúa la relevancia del artículo para investigación en agricultura sostenible,
cultivos industriales y valorización de biomasa (proyecto SUSTAINCrop).
Considera el cultivo indicado, si existe. Usa solo la información del resumen.
Clasifica el resumen en exactamente UNA de estas categorías de SUSTAINCrop:
{lista_categorias}
Para "enfoque_sostenibilidad_ue", identifica si el resumen aborda prácticas
agrícolas sostenibles (por ejemplo, agrosilvicultura o rotación de cultivos) o
diseño químico/material sostenible (Safe and Sustainable by Design, SSbD).
Escribe el enfoque específico que aparece en el resumen, o "No aplica" si no
hay relación. No infieras prácticas que el resumen no mencione.

Devuelve JSON válido con exactamente estas tres claves:
- "relevancia": "Alta", "Media" o "Baja".
- "categoria_sustaincrop": el nombre exacto de una categoría de la lista.
- "enfoque_sostenibilidad_ue": el enfoque específico o "No aplica".

Tipo de cultivo: {tipo_cultivo or "No especificado"}
Resumen: {resumen}
""".strip()

    respuesta = cliente.chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    texto_respuesta = respuesta.choices[0].message.content
    texto_respuesta = (
        texto_respuesta.replace("```json", "").replace("```", "").strip()
    )
    resultado = json.loads(texto_respuesta)
    relevancia = resultado.get("relevancia", "No evaluable")
    if relevancia not in {"Alta", "Media", "Baja"}:
        relevancia = "No evaluable"
    categoria = resultado.get("categoria_sustaincrop", "")
    categoria_normalizada = categoria.strip().casefold()
    categoria = next(
        (
            opcion
            for opcion in CATEGORIAS_SUSTAINCROP
            if opcion.casefold() == categoria_normalizada
        ),
        "",
    )
    enfoque_ue = resultado.get("enfoque_sostenibilidad_ue", "No aplica")
    if not isinstance(enfoque_ue, str) or not enfoque_ue.strip():
        enfoque_ue = "No aplica"
    return relevancia, categoria, enfoque_ue.strip()


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

        columnas_resultado = [
            "RELEVANCIA",
            "CATEGORÍA SUSTAINCROP",
            "ENFOQUE SOSTENIBILIDAD UE",
        ]
        columnas = [
            nombre for nombre in lector.fieldnames if nombre not in columnas_resultado
        ] + columnas_resultado
        with archivo_salida.open("w", newline="", encoding="utf-8-sig") as salida:
            escritor = csv.DictWriter(salida, fieldnames=columnas)
            escritor.writeheader()

            for index, fila in enumerate(lector, start=1):
                try:
                    relevancia, categoria, enfoque_ue = clasificar_resumen(
                        cliente,
                        fila.get("RESUMEN DE ARTÍCULO", ""),
                        fila.get("TIPO DE CULTIVO", ""),
                    )
                except Exception as error:
                    print(f"Error en fila {index}: {error}")
                    relevancia = "Error"
                    categoria = ""
                    enfoque_ue = "Error"

                fila["RELEVANCIA"] = relevancia
                fila["CATEGORÍA SUSTAINCROP"] = categoria
                fila["ENFOQUE SOSTENIBILIDAD UE"] = enfoque_ue
                escritor.writerow(fila)
                print(f"Fila {index}: {relevancia}")
                time.sleep(2)

    print(f"Análisis guardado en: {archivo_salida}")


if __name__ == "__main__":
    main()
