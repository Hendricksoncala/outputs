"""Combina y filtra los CSV analizados de SUSTAINCrop en un Excel maestro."""

from pathlib import Path

import pandas as pd


CARPETA_DATOS = Path.cwd() / "CSV_PARA_DATASET"
ARCHIVOS_CSV = sorted(CARPETA_DATOS.glob("*_analizado.csv"))
ARCHIVO_SALIDA = Path.cwd() / "Dataset_Maestro_SustainCrop.xlsx"

def main():
    if not ARCHIVOS_CSV:
        print("No encontré archivos que terminen en '_analizado.csv' en la carpeta actual.")
        return

    try:
        dataframes = [
            pd.read_csv(archivo, encoding="utf-8-sig") for archivo in ARCHIVOS_CSV
        ]
        dataset = pd.concat(dataframes, ignore_index=True)

        columnas_requeridas = {"RELEVANCIA", "ENFOQUE SOSTENIBILIDAD UE", "DOI"}
        faltantes = columnas_requeridas.difference(dataset.columns)
        if faltantes:
            print("Faltan columnas requeridas: " + ", ".join(sorted(faltantes)))
            return

        relevancia = dataset["RELEVANCIA"].fillna("").astype(str).str.strip().str.casefold()
        enfoque = (
            dataset["ENFOQUE SOSTENIBILIDAD UE"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        dataset = dataset.loc[
            ~relevancia.isin({"baja", "no evaluable", "error"})
            & ~enfoque.str.contains("No aplica", case=False, na=False)
        ]
        dataset = dataset.drop_duplicates(subset=["DOI"], keep="first")
        dataset.to_excel(ARCHIVO_SALIDA, index=False)

        print(
            f"Dataset creado: {ARCHIVO_SALIDA}\n"
            f"CSV combinados: {len(ARCHIVOS_CSV)} | Filas finales: {len(dataset)}"
        )
    except Exception as error:
        print(f"No se pudo generar el dataset: {error}")


if __name__ == "__main__":
    main()
