"""Extrae obras OpenAlex por institución, con cursor y punto de control.

Modos: --conteo, --prueba NODO y --completo.
OPENALEX_API_KEY se envía solo en Authorization: Bearer y nunca se imprime.
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.openalex.org"
DESDE = "2019-01-01"
PER_PAGE_COMPLETO = 200  # OpenAlex lo acepta como compatibilidad heredada; fallback a 100.
PER_PAGE_PRUEBA = 50
MAX_REINTENTOS = 6
SELECT_OBRAS = (
    "id,doi,title,display_name,publication_year,type,primary_location,locations,"
    "primary_topic,topics,cited_by_count,abstract_inverted_index,authorships,awards,funders"
)
DIRECTORIO = Path(__file__).resolve().parent
ARCHIVO_NODOS = DIRECTORIO / "nodos.csv"
DB_COMPLETA = DIRECTORIO / "sustaincrop.db"
DB_PRUEBA = DIRECTORIO / "sustaincrop_prueba.db"
VERSION = "extraer_obras.py v0.1"
BPIN_RE = re.compile(r"\b20\d{11}\b")


def canon_id(value):
    """Normaliza un OpenAlex ID a su URL canónica; conserva valores vacíos."""
    if not value:
        return ""
    value = str(value).strip()
    if not value:
        return ""
    short_id = value.rstrip("/").split("/")[-1]
    if re.fullmatch(r"[A-Z]\d+", short_id):
        return f"https://openalex.org/{short_id}"
    return ""


def short_id(value):
    return canon_id(value).rsplit("/", 1)[-1] if canon_id(value) else ""


def no_encontrado(value):
    return (value or "").strip().casefold() in {"no_encontrado", "no encontrado"}


def cargar_nodos(ruta=ARCHIVO_NODOS):
    if not ruta.is_file():
        raise FileNotFoundError(f"No se encontró {ruta}")
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        if "openalex_id" not in (lector.fieldnames or []):
            raise ValueError("nodos.csv debe tener la columna openalex_id")
        filas = list(lector)

    validos, omitidos = [], []
    for indice, fila in enumerate(filas, start=1):
        raw_id = (fila.get("openalex_id") or "").strip()
        nombre = (
            (fila.get("nombre") or "").strip()
            or (fila.get("nombre_buscado") or "").strip()
            or (fila.get("display_name") or "").strip()
            or raw_id
            or f"fila {indice}"
        )
        if no_encontrado(raw_id):
            omitidos.append((nombre, "openalex_id=no_encontrado"))
            continue
        openalex_id = canon_id(raw_id)
        if not openalex_id:
            omitidos.append((nombre, "openalex_id vacío o inválido"))
            continue

        nodo_id = (
            (fila.get("nodo_id") or "").strip()
            or (fila.get("nombre_buscado") or "").strip()
            or openalex_id
        )
        validos.append(
            {
                "nodo_id": nodo_id,
                "openalex_id": openalex_id,
                "nombre": nombre,
                "siglas": (fila.get("siglas") or "").strip(),
                "pais": (fila.get("pais_esperado") or fila.get("pais") or "").strip(),
                "grupo": (fila.get("grupo") or "").strip(),
                "ror": (fila.get("ror") or "").strip(),
                "url_oficial": (fila.get("url_oficial") or "").strip(),
                "fila_origen": fila,
            }
        )
    return validos, omitidos


def filtro_nodo(openalex_id):
    return f"authorships.institutions.lineage:{short_id(openalex_id)},from_publication_date:{DESDE}"


def api_json(endpoint, params, api_key, per_page_fallback=False):
    """GET con reintentos exponenciales en 429/5xx y errores de transporte."""
    params = dict(params)
    fallback = False
    while True:
        query = urlencode(params)
        headers = {"User-Agent": "SUSTAINCrop-extraer-obras/0.1"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = Request(f"{API}/{endpoint}?{query}", headers=headers)
        for intento in range(MAX_REINTENTOS):
            ultimo_error = None
            espera = 0
            try:
                with urlopen(request, timeout=60) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 400 and per_page_fallback and params.get("per_page") == 200 and not fallback:
                    params["per_page"] = 100
                    fallback = True
                    break
                if error.code not in {429, 500, 502, 503, 504}:
                    cuerpo = error.read().decode("utf-8", errors="replace")[:500]
                    raise RuntimeError(f"OpenAlex HTTP {error.code}: {cuerpo}") from None
                ultimo_error = error
                try:
                    espera = float(error.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    espera = 0
            except (URLError, TimeoutError, json.JSONDecodeError) as error:
                ultimo_error = error
            if intento == MAX_REINTENTOS - 1:
                detalle = f"HTTP {ultimo_error.code}" if isinstance(ultimo_error, HTTPError) else str(ultimo_error)
                raise RuntimeError(f"Consulta OpenAlex falló tras {MAX_REINTENTOS} intentos: {detalle}") from None
            time.sleep(espera or min(2**intento, 60))
        else:
            continue
        if fallback:
            continue


def abrir_db(ruta):
    conn = sqlite3.connect(ruta)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodos (
            nodo_id TEXT PRIMARY KEY,
            openalex_id TEXT NOT NULL,
            nombre TEXT NOT NULL DEFAULT '',
            siglas TEXT NOT NULL DEFAULT '',
            pais TEXT NOT NULL DEFAULT '',
            grupo TEXT NOT NULL DEFAULT '',
            ror TEXT NOT NULL DEFAULT '',
            url_oficial TEXT NOT NULL DEFAULT '',
            estado_id TEXT NOT NULL DEFAULT 'valido'
        );
        CREATE TABLE IF NOT EXISTS obras (
            openalex_id TEXT PRIMARY KEY,
            doi TEXT NOT NULL DEFAULT '',
            titulo TEXT NOT NULL DEFAULT '',
            anio INTEGER,
            tipo_obra TEXT NOT NULL DEFAULT '',
            revista TEXT NOT NULL DEFAULT '',
            tipo_fuente TEXT NOT NULL DEFAULT '',
            es_dataset INTEGER NOT NULL DEFAULT 0,
            en_repositorio INTEGER NOT NULL DEFAULT 0,
            campo TEXT NOT NULL DEFAULT '',
            subcampo TEXT NOT NULL DEFAULT '',
            temas TEXT NOT NULL DEFAULT '',
            citas INTEGER,
            resumen TEXT NOT NULL DEFAULT '',
            fuente_url TEXT NOT NULL DEFAULT '',
            fuente_tipo TEXT NOT NULL DEFAULT 'OpenAlex API',
            fecha_verificacion TEXT NOT NULL DEFAULT '',
            verificado_por TEXT NOT NULL DEFAULT 'extraer_obras.py v0.1',
            nivel_confianza TEXT NOT NULL DEFAULT 'B',
            notas_verificacion TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS obra_institucion (
            openalex_id_obra TEXT NOT NULL,
            institucion_openalex_id TEXT NOT NULL,
            ror TEXT NOT NULL DEFAULT '',
            nombre TEXT NOT NULL DEFAULT '',
            tipo TEXT NOT NULL DEFAULT '',
            pais TEXT NOT NULL DEFAULT '',
            n_autores INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (openalex_id_obra, institucion_openalex_id)
        );
        CREATE TABLE IF NOT EXISTS obra_autor (
            openalex_id_obra TEXT NOT NULL,
            autor_openalex_id TEXT NOT NULL DEFAULT '',
            orcid TEXT NOT NULL DEFAULT '',
            nombre TEXT NOT NULL DEFAULT '',
            posicion TEXT NOT NULL DEFAULT '',
            orden INTEGER NOT NULL,
            PRIMARY KEY (openalex_id_obra, autor_openalex_id, orden)
        );
        CREATE TABLE IF NOT EXISTS obra_financiador (
            openalex_id_obra TEXT NOT NULL,
            financiador_id TEXT NOT NULL DEFAULT '',
            nombre TEXT NOT NULL DEFAULT '',
            award_id TEXT NOT NULL DEFAULT '',
            es_bpin INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (openalex_id_obra, financiador_id, award_id)
        );
        CREATE TABLE IF NOT EXISTS obra_nodo (
            openalex_id_obra TEXT NOT NULL,
            nodo_id TEXT NOT NULL,
            PRIMARY KEY (openalex_id_obra, nodo_id)
        );
        CREATE TABLE IF NOT EXISTS posibles_duplicados (
            openalex_id TEXT PRIMARY KEY,
            clave_titulo_anio TEXT NOT NULL,
            titulo_normalizado TEXT NOT NULL,
            anio INTEGER NOT NULL,
            titulo TEXT NOT NULL DEFAULT '',
            cantidad_coincidente INTEGER NOT NULL DEFAULT 2
        );
        CREATE TABLE IF NOT EXISTS puntos_control (
            nodo_id TEXT NOT NULL,
            modo TEXT NOT NULL,
            cursor TEXT NOT NULL DEFAULT '*',
            completado INTEGER NOT NULL DEFAULT 0,
            obras_procesadas INTEGER NOT NULL DEFAULT 0,
            actualizado TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (nodo_id, modo)
        );
        """
    )
    return conn


def guardar_nodos(conn, nodos, omitidos):
    with conn:
        for nodo in nodos:
            conn.execute(
                """INSERT INTO nodos
                (nodo_id,openalex_id,nombre,siglas,pais,grupo,ror,url_oficial,estado_id)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(nodo_id) DO UPDATE SET
                openalex_id=excluded.openalex_id,nombre=excluded.nombre,
                siglas=excluded.siglas,pais=excluded.pais,grupo=excluded.grupo,
                ror=excluded.ror,url_oficial=excluded.url_oficial,estado_id=excluded.estado_id""",
                (nodo["nodo_id"], nodo["openalex_id"], nodo["nombre"], nodo["siglas"],
                 nodo["pais"], nodo["grupo"], nodo["ror"], nodo["url_oficial"], "valido"),
            )
        for nombre, motivo in omitidos:
            conn.execute(
                """INSERT INTO nodos (nodo_id,openalex_id,nombre,estado_id)
                VALUES (?,?,?,?) ON CONFLICT(nodo_id) DO UPDATE SET
                openalex_id=excluded.openalex_id,nombre=excluded.nombre,estado_id=excluded.estado_id""",
                (f"omitido:{nombre}", "", nombre, motivo),
            )


def buscar_nodo(nodos, identificador):
    needle = identificador.strip().casefold()
    for nodo in nodos:
        if needle in {
            nodo["nodo_id"].casefold(),
            nodo["openalex_id"].casefold(),
            short_id(nodo["openalex_id"]).casefold(),
            nodo["nombre"].casefold(),
        }:
            return nodo
    return None


def reconstruir_resumen(inverted_index):
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    tokens = []
    for token, posiciones in inverted_index.items():
        for posicion in posiciones or []:
            tokens.append((posicion, token))
    return " ".join(token for _, token in sorted(tokens))


def normalizar_titulo(titulo):
    texto = unicodedata.normalize("NFKD", titulo or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def nombres_de_temas(work):
    temas = []
    for tema in work.get("topics", []) or []:
        nombre = tema.get("display_name")
        if nombre and nombre not in temas:
            temas.append(nombre)
    return " | ".join(temas)


def fuente_principal(work):
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name") or "", source.get("type") or ""


def existe_repositorio(work):
    locations = list(work.get("locations", []) or [])
    primary = work.get("primary_location")
    if primary:
        locations.append(primary)
    return any(
        ((location or {}).get("source") or {}).get("type", "").casefold() == "repository"
        for location in locations
    )


def obtener_afiliaciones(work):
    """Agrupa afiliaciones por ID institucional y cuenta autores distintos."""
    institutions = {}
    authorships = work.get("authorships", []) or []
    for indice, authorship in enumerate(authorships):
        author = authorship.get("author") or {}
        author_id = canon_id(author.get("id"))
        author_key = author_id or f"__authorship_{indice}"
        for inst in authorship.get("institutions", []) or []:
            inst_id = canon_id(inst.get("id"))
            if not inst_id:
                continue
            record = institutions.setdefault(
                inst_id,
                {
                    "id": inst_id,
                    "ror": inst.get("ror") or "",
                    "nombre": inst.get("display_name") or "",
                    "tipo": inst.get("type") or "",
                    "pais": inst.get("country_code") or "",
                    "autores": set(),
                    "lineage": set(),
                },
            )
            record["autores"].add(author_key)
            lineage = inst.get("lineage") or []
            # Conserva el ID de la institución afiliada además de sus ancestros.
            if inst_id:
                record["lineage"].add(inst_id)
            for ancestor in lineage:
                ancestor_id = canon_id(ancestor)
                if ancestor_id:
                    record["lineage"].add(ancestor_id)
    return institutions


def financiadores_de_obra(work):
    """Combina funders con awards; usa los campos vigentes del esquema OpenAlex."""
    funders = {}
    for funder in work.get("funders", []) or []:
        funder_id = canon_id(funder.get("id"))
        if funder_id:
            funders[funder_id] = funder.get("display_name") or ""

    rows = {}
    funders_con_award = set()
    for award in work.get("awards", []) or []:
        nested_funder = award.get("funder") or {}
        funder_id = canon_id(award.get("funder_id") or nested_funder.get("id"))
        nombre = (
            award.get("funder_display_name")
            or nested_funder.get("display_name")
            or funders.get(funder_id, "")
            or ""
        )
        # El identificador de convocatoria del financiador es funder_award_id;
        # si falta, se conserva el ID OpenAlex G del award.
        award_id = (award.get("funder_award_id") or award.get("id") or "").strip()
        key = (funder_id or "", award_id)
        rows[key] = {
            "financiador_id": funder_id or "",
            "nombre": nombre,
            "award_id": award_id,
            "es_bpin": int(bool(BPIN_RE.search(award_id))),
        }
        if funder_id:
            funders_con_award.add(funder_id)

    for funder_id, nombre in funders.items():
        if funder_id not in funders_con_award:
            key = (funder_id, "")
            rows.setdefault(
                key,
                {"financiador_id": funder_id, "nombre": nombre, "award_id": "", "es_bpin": 0},
            )
    return list(rows.values())


def upsert_obra(conn, work, nodos_por_institucion, fecha_extraccion):
    work_id = canon_id(work.get("id"))
    if not work_id:
        return False
    doi = (work.get("doi") or "").strip()
    title = work.get("title") or work.get("display_name") or ""
    year = work.get("publication_year")
    primary = work.get("primary_topic") or {}
    field = primary.get("field") or {}
    subfield = primary.get("subfield") or {}
    journal, source_type = fuente_principal(work)
    work_type = work.get("type") or ""
    abstract = reconstruir_resumen(work.get("abstract_inverted_index"))
    confidence = "A" if doi else "B"
    fields = (
        work_id, doi, title, year, work_type, journal, source_type,
        int(work_type == "dataset"), int(existe_repositorio(work)),
        field.get("display_name") or "", subfield.get("display_name") or "",
        nombres_de_temas(work), work.get("cited_by_count"), abstract, work_id,
        "OpenAlex API", fecha_extraccion, VERSION, confidence, "",
    )
    conn.execute(
        """INSERT INTO obras (
        openalex_id,doi,titulo,anio,tipo_obra,revista,tipo_fuente,es_dataset,
        en_repositorio,campo,subcampo,temas,citas,resumen,fuente_url,fuente_tipo,
        fecha_verificacion,verificado_por,nivel_confianza,notas_verificacion
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(openalex_id) DO UPDATE SET
        doi=excluded.doi,titulo=excluded.titulo,anio=excluded.anio,
        tipo_obra=excluded.tipo_obra,revista=excluded.revista,tipo_fuente=excluded.tipo_fuente,
        es_dataset=excluded.es_dataset,en_repositorio=excluded.en_repositorio,
        campo=excluded.campo,subcampo=excluded.subcampo,temas=excluded.temas,
        citas=excluded.citas,resumen=excluded.resumen,fuente_url=excluded.fuente_url,
        fuente_tipo=excluded.fuente_tipo,fecha_verificacion=excluded.fecha_verificacion,
        verificado_por=excluded.verificado_por,nivel_confianza=excluded.nivel_confianza,
        notas_verificacion=excluded.notas_verificacion""",
        fields,
    )

    authorships = work.get("authorships", []) or []
    affiliations = obtener_afiliaciones(work)
    for inst_id, inst in affiliations.items():
        conn.execute(
            """INSERT INTO obra_institucion
            (openalex_id_obra,institucion_openalex_id,ror,nombre,tipo,pais,n_autores)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(openalex_id_obra,institucion_openalex_id) DO UPDATE SET
            ror=excluded.ror,nombre=excluded.nombre,tipo=excluded.tipo,
            pais=excluded.pais,n_autores=excluded.n_autores""",
            (work_id, inst_id, inst["ror"], inst["nombre"], inst["tipo"],
             inst["pais"], len(inst["autores"])),
        )

    for orden, authorship in enumerate(authorships, start=1):
        author = authorship.get("author") or {}
        author_id = canon_id(author.get("id"))
        conn.execute(
            """INSERT INTO obra_autor
            (openalex_id_obra,autor_openalex_id,orcid,nombre,posicion,orden)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(openalex_id_obra,autor_openalex_id,orden) DO UPDATE SET
            orcid=excluded.orcid,nombre=excluded.nombre,posicion=excluded.posicion""",
            (work_id, author_id, author.get("orcid") or "",
             author.get("display_name") or "", authorship.get("author_position") or "", orden),
        )

    for funder in financiadores_de_obra(work):
        conn.execute(
            """INSERT INTO obra_financiador
            (openalex_id_obra,financiador_id,nombre,award_id,es_bpin)
            VALUES (?,?,?,?,?)
            ON CONFLICT(openalex_id_obra,financiador_id,award_id) DO UPDATE SET
            nombre=excluded.nombre,es_bpin=excluded.es_bpin""",
            (work_id, funder["financiador_id"], funder["nombre"],
             funder["award_id"], funder["es_bpin"]),
        )

    matched_nodes = set()
    for inst in affiliations.values():
        for lineage_id in inst["lineage"]:
            matched_nodes.update(nodos_por_institucion.get(lineage_id, []))
    for nodo_id in matched_nodes:
        conn.execute(
            """INSERT INTO obra_nodo (openalex_id_obra,nodo_id) VALUES (?,?)
            ON CONFLICT(openalex_id_obra,nodo_id) DO NOTHING""",
            (work_id, nodo_id),
        )

    return True


def actualizar_posibles_duplicados(conn):
    works = conn.execute(
        "SELECT openalex_id,titulo,anio FROM obras WHERE doi='' OR doi IS NULL"
    ).fetchall()
    groups = {}
    for work_id, title, year in works:
        normalized = normalizar_titulo(title)
        if not normalized or year is None:
            continue
        key = f"{year}:{normalized}"
        groups.setdefault(key, []).append((work_id, title, year, normalized))
    for key, members in groups.items():
        if len(members) < 2:
            continue
        for work_id, title, year, normalized in members:
            conn.execute(
                """INSERT INTO posibles_duplicados
                (openalex_id,clave_titulo_anio,titulo_normalizado,anio,titulo,cantidad_coincidente)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(openalex_id) DO UPDATE SET
                clave_titulo_anio=excluded.clave_titulo_anio,
                titulo_normalizado=excluded.titulo_normalizado,anio=excluded.anio,
                titulo=excluded.titulo,cantidad_coincidente=excluded.cantidad_coincidente""",
                (work_id, key, normalized, year, title, len(members)),
            )


def importar_nodos(conn, nodos, omitidos):
    guardar_nodos(conn, nodos, omitidos)
    by_institution = {}
    for nodo in nodos:
        by_institution.setdefault(nodo["openalex_id"], []).append(nodo["nodo_id"])
    return by_institution


def inicializar_checkpoint(conn, nodo_id, modo):
    with conn:
        conn.execute(
            "INSERT INTO puntos_control (nodo_id,modo,cursor,completado,obras_procesadas,actualizado) "
            "VALUES (?,?, '*',0,0,?) ON CONFLICT(nodo_id,modo) DO NOTHING",
            (nodo_id, modo, datetime.now(timezone.utc).isoformat()),
        )
    return conn.execute(
        "SELECT cursor,completado,obras_procesadas FROM puntos_control WHERE nodo_id=? AND modo=?",
        (nodo_id, modo),
    ).fetchone()


def contar_obras(nodo, api_key):
    params = {
        "filter": filtro_nodo(nodo["openalex_id"]),
        "per_page": 1,
        "select": "id",
    }
    result = api_json("works", params, api_key)
    return result.get("meta", {}).get("count", 0)


def extraer_nodo(conn, nodo, nodos_por_institucion, api_key, modo, limite=None):
    checkpoint = inicializar_checkpoint(conn, nodo["nodo_id"], modo)
    cursor, completado, ya_procesadas = checkpoint
    if completado:
        print(f"{nodo['nombre']}: punto de control completo; no repito la extracción.")
        return
    if limite is not None and ya_procesadas >= limite:
        with conn:
            conn.execute(
                "UPDATE puntos_control SET completado=1,actualizado=? WHERE nodo_id=? AND modo=?",
                (datetime.now(timezone.utc).isoformat(), nodo["nodo_id"], modo),
            )
        print(f"{nodo['nombre']}: ya alcanzó el límite de {limite} obras de prueba.")
        return

    per_page = PER_PAGE_PRUEBA if limite else PER_PAGE_COMPLETO
    fecha_extraccion = date.today().isoformat()
    procesadas_sesion = 0
    cursor = cursor or "*"
    while True:
        params = {
            "filter": filtro_nodo(nodo["openalex_id"]),
            "cursor": cursor,
            "per_page": per_page,
            "select": SELECT_OBRAS,
        }
        data = api_json("works", params, api_key, per_page_fallback=(per_page == 200))
        effective_per_page = data.get("meta", {}).get("per_page", per_page)
        rows = data.get("results", []) or []
        next_cursor = data.get("meta", {}).get("next_cursor")
        if limite is not None:
            remaining = limite - ya_procesadas
            rows = rows[:remaining]

        with conn:
            for work in rows:
                upsert_obra(conn, work, nodos_por_institucion, fecha_extraccion)
                procesadas_sesion += 1
            ya_procesadas += len(rows)
            actualizar_posibles_duplicados(conn)
            finished_test = limite is not None and ya_procesadas >= limite
            finished_api = not next_cursor or not rows
            finished = finished_test or finished_api
            save_cursor = next_cursor or cursor
            conn.execute(
                """INSERT INTO puntos_control
                (nodo_id,modo,cursor,completado,obras_procesadas,actualizado)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(nodo_id,modo) DO UPDATE SET cursor=excluded.cursor,
                completado=excluded.completado,obras_procesadas=excluded.obras_procesadas,
                actualizado=excluded.actualizado""",
                (nodo["nodo_id"], modo, save_cursor, int(finished), ya_procesadas,
                 datetime.now(timezone.utc).isoformat()),
            )

        print(
            f"{nodo['nombre']}: {procesadas_sesion} obras en esta ejecución "
            f"({effective_per_page} por página)."
        )
        if finished:
            break
        cursor = next_cursor


def informe_validacion(conn, nodos):
    print("\nInforme de validación por nodo")
    print("Nodo | Obras | DOI % | Resumen % | Afiliaciones con ROR % | Duplicados posibles")
    for nodo in nodos:
        nodo_id = nodo["nodo_id"]
        row = conn.execute(
            """SELECT COUNT(*),
            SUM(CASE WHEN o.doi<>'' THEN 1 ELSE 0 END),
            SUM(CASE WHEN o.resumen<>'' THEN 1 ELSE 0 END)
            FROM obra_nodo onodo JOIN obras o ON o.openalex_id=onodo.openalex_id_obra
            WHERE onodo.nodo_id=?""",
            (nodo_id,),
        ).fetchone()
        total = row[0] or 0
        doi_count = row[1] or 0
        summary_count = row[2] or 0
        affiliations = conn.execute(
            """SELECT COUNT(*),SUM(CASE WHEN oi.ror<>'' THEN 1 ELSE 0 END)
            FROM obra_nodo onodo JOIN obra_institucion oi
            ON oi.openalex_id_obra=onodo.openalex_id_obra WHERE onodo.nodo_id=?""",
            (nodo_id,),
        ).fetchone()
        affiliation_total = affiliations[0] or 0
        ror_count = affiliations[1] or 0
        duplicate_count = conn.execute(
            """SELECT COUNT(DISTINCT pd.openalex_id)
            FROM obra_nodo onodo JOIN posibles_duplicados pd
            ON pd.openalex_id=onodo.openalex_id_obra WHERE onodo.nodo_id=?""",
            (nodo_id,),
        ).fetchone()[0]
        doi_pct = 100 * doi_count / total if total else 0
        summary_pct = 100 * summary_count / total if total else 0
        ror_pct = 100 * ror_count / affiliation_total if affiliation_total else 0
        print(
            f"{nodo['nombre']} | {total} | {doi_pct:.1f}% | {summary_pct:.1f}% | "
            f"{ror_pct:.1f}% | {duplicate_count}"
        )


def imprimir_omitidos(omitidos):
    if not omitidos:
        return
    print("Nodos omitidos:")
    for nombre, motivo in omitidos:
        print(f"- {nombre}: {motivo}")


def ejecutar_conteo(nodos, omitidos, api_key):
    print("\nNodo | Obras desde 2019-01-01")
    print("-" * 72)
    total = 0
    for nodo in nodos:
        try:
            count = contar_obras(nodo, api_key)
            total += count
            print(f"{nodo['nombre']} | {count}")
        except Exception as error:
            print(f"{nodo['nombre']} | ERROR: {error}")
    print("-" * 72)
    print(f"TOTAL POR NODO (puede contar obras compartidas más de una vez) | {total}")
    imprimir_omitidos(omitidos)


def main():
    parser = argparse.ArgumentParser(description="Extracción de obras de OpenAlex para SUSTAINCrop")
    modos = parser.add_mutually_exclusive_group(required=True)
    modos.add_argument("--conteo", action="store_true", help="Consulta solo meta.count por nodo")
    modos.add_argument("--prueba", metavar="NODO", help="Extrae hasta 50 obras de un nodo (nodo_id, OpenAlex ID o nombre)")
    modos.add_argument("--completo", action="store_true", help="Extrae todas las obras desde 2019; no ejecutar sin autorización explícita")
    parser.add_argument("--nodos", type=Path, default=ARCHIVO_NODOS, help="CSV de nodos; por defecto nodos.csv junto al script")
    args = parser.parse_args()

    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    try:
        nodos, omitidos = cargar_nodos(args.nodos)
    except (OSError, csv.Error, ValueError) as error:
        print(f"No se pudo cargar el CSV de nodos: {error}")
        return 2

    imprimir_omitidos(omitidos)
    if args.conteo:
        ejecutar_conteo(nodos, omitidos, api_key)
        return 0

    if not api_key:
        print("Define OPENALEX_API_KEY para usar la paginación cursorada de extracción.")
        return 2

    if args.prueba:
        nodo = buscar_nodo(nodos, args.prueba)
        if nodo is None:
            print(f"No se encontró un nodo válido para: {args.prueba}")
            imprimir_omitidos(omitidos)
            return 2
        nodos_objetivo = [nodo]
        modo = "prueba"
        ruta_db = DB_PRUEBA
        limite = 50
    else:
        # --completo solo corre cuando el usuario lo ejecuta expresamente.
        nodos_objetivo = nodos
        modo = "completo"
        ruta_db = DB_COMPLETA
        limite = None

    if not nodos_objetivo:
        print("No hay nodos con OpenAlex ID válido para extraer.")
        return 2

    conn = abrir_db(ruta_db)
    try:
        nodos_por_institucion = importar_nodos(conn, nodos, omitidos)
        for nodo in nodos_objetivo:
            try:
                extraer_nodo(
                    conn, nodo, nodos_por_institucion, api_key, modo, limite=limite
                )
            except Exception as error:
                print(f"Error en nodo {nodo['nombre']}: {error}")
        informe_validacion(conn, nodos_objetivo)
        print(f"Base actualizada: {ruta_db}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

