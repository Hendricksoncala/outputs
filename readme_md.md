# Herramientas de Inteligencia y Mapeo - SUSTAINCrop

Este repositorio contiene las herramientas automatizadas para buscar, extraer y clasificar investigaciones científicas y redes de actores relevantes para el proyecto **SUSTAINCrop**. 

El flujo de trabajo consta de dos fases principales:
1. **Extracción de datos** usando la base de datos científica abierta OpenAlex.
2. **Análisis automatizado con Inteligencia Artificial** usando los modelos ultrarrápidos de Groq para clasificar la relevancia de los artículos.

---

## ⚙️ Configuración Inicial (Solo la primera vez)

Antes de ejecutar los scripts, asegúrate de tener instaladas las librerías necesarias en tu entorno de Python. Abre la terminal en esta carpeta y ejecuta:

```bash
pip install requests groq
```

---

## 🚀 FASE 1: Extracción de Trabajos Científicos (OpenAlex)

El archivo encargado de esta fase es el script de extracción (ej. `extractor_openalex.py`). Este programa busca artículos de una institución y descarga sus resúmenes y redes de colaboración.

### 1. Configurar tu API Key personal de OpenAlex
Para hacer consultas a la base de datos sin límites, necesitas una clave gratuita:
1. Ingresa a: [Configuración de API de OpenAlex](https://openalex.org/settings/api-key)
2. Genera y copia tu clave.
3. Abre el script de extracción y reemplaza el texto en la variable correspondiente:
   ```python
   API_KEY = "Aquí va tu api key de OpenAlex"
   ```

### 2. Ejecutar la búsqueda
Corre el script en tu terminal. El programa te pedirá ingresar el nombre del Actor y los Temas. Puedes usar estas combinaciones validadas:

* **Actor:** `AGROSAVIA` | **Temas:** `agriculture, agronomy, crop, biofertilizer, soil`
* **Actor:** `Cenicafé` | **Temas:** `coffee, coffea, agroforestry, coffee pulp, coffee waste`
* **Actor:** `Cenicaña` | **Temas:** `sugarcane, saccharum, bagasse, ethanol, biomass`
* **Actor:** `Cenipalma` | **Temas:** `oil palm, elaeis guineensis, palm oil, biomass`
* **Actor:** `Instituto Humboldt` | **Temas:** `biodiversity, biomass, conservation`

**Resultado Fase 1:** El script generará un archivo CSV en tu carpeta (ej. `resultados_AGROSAVIA.csv`).

---

## 🧠 FASE 2: Análisis y Clasificación con IA (Groq)

El archivo `analizador_gratis.py` toma el CSV generado en la Fase 1, lee los resúmenes y utiliza Inteligencia Artificial para evaluar la relevancia del artículo para SUSTAINCrop, asignando además una categoría del ecosistema de bioeconomía.

### 1. Configurar tu API Key de Groq
1. Crea una cuenta gratuita y entra a: [Groq Console - API Keys](https://console.groq.com/keys)
2. Haz clic en "Create API Key" y copia el código generado (empieza por `gsk_...`).
3. Abre `analizador_gratis.py`. En la línea donde se define la variable `api_key` (aprox. línea 43), pega tu clave entre comillas:
   ```python
   api_key = "gsk_TU_CLAVE_AQUI"
   ```

### 2. Ejecutar el análisis
Corre el script del analizador en tu terminal:
```bash
python analizador_gratis.py
```
La terminal te pedirá la ruta del archivo CSV que quieres analizar. **Puedes simplemente arrastrar el archivo CSV generado en la Fase 1 desde tu explorador de archivos hacia la terminal** y presionar Enter.

**Resultado Fase 2:** El script creará un nuevo documento llamado `resultados_ACTOR_analizado.csv`. Este nuevo archivo incluirá columnas clave para la matriz estratégica:
* **RELEVANCIA:** Alta, Media o Baja.
* **CATEGORÍA:** Clasificación automática basada en la taxonomía de actores (Investigación, Industria, Sector Primario, etc.).
* **JUSTIFICACIÓN:** Una breve explicación de por qué la IA tomó esa decisión.

---
*Documento mantenido para el equipo de mapeo bioeconómico de SUSTAINCrop.*