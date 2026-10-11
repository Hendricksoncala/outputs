# Extractor de Trabajos Científicos - OpenAlex

Este script automatiza la búsqueda y extracción de investigaciones científicas, resúmenes y redes de colaboradores de instituciones específicas utilizando la API de OpenAlex.

## Paso 1: Configurar tu API Key personal

Para poder hacer consultas a la base de datos, necesitas una clave de acceso gratuita.
1. Ingresa a: [Configuración de API de OpenAlex](https://openalex.org/settings/api-key)
2. Genera y copia tu clave.
3. Abre el archivo del script y reemplaza el texto en la siguiente variable:

```python
API_KEY = "Aquí va tu api key de OpenAlex"
```

## Paso 2 -- Ejecuta el codigo

Al ejecutar el script en la terminal, el programa te pedirá ingresar el nombre de la institución y los temas a buscar. Puedes usar las siguientes combinaciones de prueba validadas para obtener los mejores resultados:

- **Actor:** `AGROSAVIA`
    - **Temas:** `agriculture, agronomy, crop, biofertilizer, soil`

- **Actor:** `Cenicafé`
    - **Temas:** `coffee, coffea, agroforestry, coffee pulp, coffee waste`

- **Actor:** `Cenicaña`
    - **Temas:** `sugarcane, saccharum, bagasse, ethanol, biomass`

- **Actor:** `Cenipalma`
    - **Temas:** `oil palm, elaeis guineensis, palm oil, biomass`

- **Actor:** `INVEMAR`
    - **Temas:** `marine biomass, algae, seaweed`

- **Actor:** `Instituto SINCHI`
    - **Temas:** `agroforestry, amazon, biodiversity`

- **Actor:** `Instituto Humboldt`
    - **Temas:** `biodiversity, biomass, conservation`

- **Actor:** `IDEAM`
    - **Temas:** `climate, agriculture, meteorology`

- **Actor:** `IGAC`
    - **Temas:** `geography, land use, soil`

# Paso 3 --  Revisión de Resultados

Una vez finalizada la búsqueda, el script generará automáticamente un archivo CSV (ej. resultados_AGROSAVIA.csv) en la misma carpeta. Este archivo contiene el DOI, Título, Resumen reconstruido y los Actores Asociados (red de colaboración) listos para su análisis y tabulación.