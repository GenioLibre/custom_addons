import json
import re
import requests
import pytz
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
from datetime import timedelta


class GeneradorContenidoPropuesta(models.Model):
    _name = "gl.contenido.propuesta"
    _description = "Publicación generada desde IA"
    _rec_name = "titulo"
    _order = "fecha_publicacion asc, id asc"

    flujo_id = fields.Many2one("gl.contenido.flujo", string="Flujo Relacionado", ondelete="cascade")

    titulo = fields.Char("Título", required=True)
    fecha_publicacion = fields.Datetime("Fecha y Hora de Publicación")
    tipo = fields.Selection([
        ("post", "Post"),
        ("reel", "Reel"),
        ("story", "Story"),
        ("carrusel", "Carrusel"),
    ], string="Tipo de Contenido", default="post")
    descripcion = fields.Text("Descripción")
    texto_en_diseno = fields.Text("Texto en Diseño")
    copy = fields.Text("Copy del Post")
    hashtags = fields.Text("Hashtags")
    recomendaciones = fields.Text("Recomendaciones de Diseño")
    cambios = fields.Text("Modificaciones")
    aprobado = fields.Boolean("Aprobado", default=False)
    es_historia = fields.Boolean("Es Historia", default=False)


class GeneradorContenidoFlujo(models.Model):
    _name = "gl.contenido.flujo"
    name = fields.Char(string="Nombre del Flujo", required=True, tracking=True, help="Nombre o título principal del flujo de contenido (ej. Campaña de Julio, Newport - Cursos de Manejo)")

    _description = "Flujo del Generador de Contenido"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin"
    ]
    fecha_presentacion = fields.Datetime(string="Fecha de Presentación", tracking=True, help="Fecha en la que se presenta o entrega el flujo de contenido")

    date_start = fields.Date(string="Fecha de Inicio", tracking=True, help="Fecha de inicio del rango de planificación o análisis.")
    date = fields.Date(string="Fecha de Fin", tracking=True, help="Fecha de fin del rango de planificación o análisis.")
    plan_cliente = fields.Char(string="Plan del Cliente", related="partner_id.plan_descripcion", readonly=True)
    plan_post = fields.Integer(string="Posts", related="partner_id.plan_post", readonly=True)
    plan_historia = fields.Integer(string="Historias", related="partner_id.plan_historia", readonly=True)
    plan_reel = fields.Integer(string="Reels", related="partner_id.plan_reel", readonly=True)
    redes_ids = fields.Many2many("red.social", string="Redes Sociales Activas")
    partner_id = fields.Many2one("res.partner", string="Cliente", required=True, tracking=True)
    industria = fields.Char("Industria del Cliente")
    etapa = fields.Selection([
        ("ideas", "Creación de Ideas"),
        ("reunion", "Reunión con Cliente"),
        ("refinar", "Perfeccionamiento"),
        ("publicaciones", "Publicaciones Listas"),
    ], string="Etapa", default="ideas", group_expand="_expand_etapas")

    # Etapa: Ideas
    notas = fields.Text("Notas")
    nivel_contenido = fields.Selection(selection=[
        ("minimalista", "Minimalista"),
        ("balanceado", "Balanceado"),
        ("detallado", "Detallado"),
    ], string="Cantidad de contenido", default="balanceado", required=True, )
    usar = fields.Text("Usar")
    evitar = fields.Text("Evitar")
    promtp_ideas = fields.Text("Promtp para Chatpgt")
    promtp_respuesta = fields.Text("Respuesta de Chatpgt")
    ideas_generadas = fields.Html("Ideas Generadas")
    orientacion_comunicacion = fields.Selection([
        ("formativa", "Formativa / Educativa"),
        ("informativa", "Informativa / Profesional"),
        ("emocional", "Emocional / Inspiracional"),
        ("comercial", "Comercial / Persuasiva"),
        ("aspiracional", "Aspiracional / Motivacional"),
        ("relacional", "Relacional / Cercana con la comunidad"),
    ], string="Orientación de la Comunicación", help="Define el enfoque principal del tono con la comunidad o clientes durante esta campaña o mes.")
    tono_comunicacion = fields.Selection([
        ("alegre", "Alegre"),
        ("juvenil", "Juvenil"),
        ("corporativo", "Corporativo"),
        ("empatico", "Empático"),
        ("profesional", "Profesional"),
        ("aspiracional", "Aspiracional"),
    ], string="Tono de Comunicación", help="Define el estilo expresivo o personalidad con la que se comunica la marca en esta campaña.")
    competencia_urls = fields.Text(string="Competencia (URLs)", help="Lista de URLs o referencias de la competencia que pueden servir como inspiración o benchmark.")
    tendencias_urls = fields.Text(string="Tendencias (URLs)", help="Enlaces a videos, imágenes o publicaciones en tendencia relacionadas con la industria.")
    publico_objetivo = fields.Text(string="Público Objetivo", help="Describe el público meta de la campaña: edad, ubicación, intereses, nivel socioeconómico, etc.")
    dias_festivos_referencia = fields.Text(string="Días Festivos / Eventos Relevantes", help="Días festivos o eventos clave sugeridos por IA en función de la industria o temporada.")
    publicacion_ids = fields.One2many("gl.contenido.propuesta", "flujo_id", string="Ideas / Publicaciones")

    # Etapa: Reunión
    feedback_cliente = fields.Text("Feedback del Cliente")
    anotaciones_cliente = fields.Text("Anotaciones de la Reunión")
    promtp_refinamiento = fields.Text("Promtp de Refinamiento")
    promtp_respuesta_refinamiento = fields.Text("Respuesta de Refinamiento")

    # Etapa: Refinamiento
    plan_base = fields.Html("Plan Base")
    plan_refinado = fields.Html("Plan Refinado")

    # Etapa: Publicaciones
    project_id = fields.Many2one("project.project", string="Proyecto Relacionado", domain="[('partner_id', '=', partner_id), ('project_type','=','marketing')]", tracking=True, )
    user_ids = fields.Many2many("res.users", string="Responsables")

    metricas = fields.Text("Métricas (JSON)")

    _CONTENT_TYPE_ALIASES = {
        "post": "post",
        "feed": "post",
        "reel": "reel",
        "video_reels": "reel",
        "story": "story",
        "historia": "story",
        "video_stories": "story",
        "carrusel": "carrusel",
        "carousel": "carrusel",
    }

    def ver_calendario(self):
        """Abre las propuestas del flujo actual en vista calendario"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Calendario de Propuestas",
            "res_model": "gl.contenido.propuesta",
            "view_mode": "calendar,form",
            "domain": [
                ("flujo_id", "=", self.id)
            ],
            "context": {
                "default_flujo_id": self.id,
            },
            "target": "current",
        }

    def _expand_etapas(self, values, domain):
        return [
            "ideas",
            "reunion",
            "refinar",
            "publicaciones"
        ]

    @api.constrains("date_start", "date")
    def _check_date_range(self):
        for record in self:
            if record.date_start and record.date and record.date_start > record.date:
                raise ValidationError("La fecha de inicio no puede ser mayor que la fecha final.")

    @api.constrains("project_id", "partner_id")
    def _check_project_partner_consistency(self):
        for record in self:
            if not record.project_id:
                continue
            if record.project_id.partner_id and record.partner_id and record.project_id.partner_id != record.partner_id:
                raise ValidationError("El proyecto seleccionado no pertenece al mismo cliente del flujo.")
            if getattr(record.project_id, "project_type", False) and record.project_id.project_type != "marketing":
                raise ValidationError("El proyecto relacionado del flujo debe ser de tipo marketing.")

    def _get_openai_client_config(self):
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param("chatgpt.api_key")
        base_url = icp.get_param("chatgpt.base_url", "https://api.openai.com/v1")
        model = icp.get_param("chatgpt.model", "gpt-4.1-mini")

        if not api_key:
            raise ValidationError("No se ha configurado la API Key de ChatGPT en Ajustes del sistema.")

        return api_key, base_url.rstrip("/"), model

    def _call_openai_chat_completion(self, *, prompt, system_prompt, temperature=0.2, timeout=60):
        api_key, base_url, model = self._get_openai_client_config()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }

        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        except (requests.exceptions.RequestException, ValueError, TypeError, KeyError) as e:
            raise ValidationError(f"Error al consultar ChatGPT: {e}")

        if not raw:
            raise ValidationError("ChatGPT no devolvió contenido.")

        return raw

    def _normalize_content_type(self, tipo, *, field_name="tipo"):
        tipo_raw = (tipo or "").strip().lower()
        normalized = self._CONTENT_TYPE_ALIASES.get(tipo_raw)
        if not normalized:
            raise ValidationError(
                f"Tipo de contenido inválido en '{field_name}': {tipo!r}. "
                "Usa uno de: post, reel, story, carrusel."
            )
        return normalized

    def _parse_json_list_field(self, raw_value, *, field_name):
        if not raw_value:
            raise ValidationError(f"El campo '{field_name}' está vacío. Debes pegar un JSON válido.")

        try:
            data = json.loads(raw_value)
        except json.JSONDecodeError as e:
            raise ValidationError(f"El campo '{field_name}' no contiene un JSON válido:\n{e}")

        if not isinstance(data, list):
            raise ValidationError(f"El campo '{field_name}' debe contener una lista JSON de objetos.")

        return data

    def _normalize_hashtags(self, hashtags):
        if not hashtags:
            return ""
        if isinstance(hashtags, list):
            cleaned = []
            seen = set()
            for hashtag in hashtags:
                tag = str(hashtag or "").strip()
                if not tag:
                    continue
                if not tag.startswith("#"):
                    tag = f"#{tag}"
                tag = tag.lower()
                if tag not in seen:
                    seen.add(tag)
                    cleaned.append(tag)
            return " ".join(cleaned)

        if isinstance(hashtags, str):
            parts = hashtags.replace(",", " ").split()
            return self._normalize_hashtags(parts)

        raise ValidationError("El campo 'hashtags' debe ser una lista o un texto.")

    def _validate_publication_date_in_range(self, record, fecha_publicacion, *, item_index):
        if not fecha_publicacion or not record.date_start or not record.date:
            return

        fecha_local = fields.Datetime.context_timestamp(record, fecha_publicacion)
        fecha_local_date = fecha_local.date()
        if fecha_local_date < record.date_start or fecha_local_date > record.date:
            raise ValidationError(
                f"La publicación #{item_index} tiene fecha {fecha_local.strftime('%Y-%m-%d %H:%M:%S')} "
                f"fuera del rango del flujo ({record.date_start} a {record.date})."
            )

    def _parse_publicacion_payload(self, record, item, *, item_index, tz):
        if not isinstance(item, dict):
            raise ValidationError(f"El elemento #{item_index} del JSON debe ser un objeto.")

        titulo_base = (item.get("titulo") or "").strip()
        if not titulo_base:
            raise ValidationError(f"La publicación #{item_index} no tiene 'titulo'.")

        tipo = self._normalize_content_type(item.get("tipo") or "post", field_name=f"tipo[{item_index}]")

        fecha_publicacion_str = (item.get("fecha_publicacion") or "").strip()
        if not fecha_publicacion_str:
            raise ValidationError(f"La publicación '{titulo_base}' no tiene 'fecha_publicacion'.")

        if len(fecha_publicacion_str) == 10:
            fecha_publicacion_str = f"{fecha_publicacion_str} 08:00:00"

        try:
            fecha_local = datetime.strptime(fecha_publicacion_str, "%Y-%m-%d %H:%M:%S")
            fecha_local = tz.localize(fecha_local)
            fecha_utc = fecha_local.astimezone(pytz.UTC)
            fecha_publicacion = fecha_utc.replace(tzinfo=None)
        except (ValueError, TypeError, pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            raise ValidationError(
                f"Formato de fecha inválido en la publicación #{item_index}: {fecha_publicacion_str}. "
                "Usa 'YYYY-MM-DD HH:MM:SS'."
            )

        self._validate_publication_date_in_range(record, fecha_publicacion, item_index=item_index)

        for text_field in ("descripcion", "texto_en_diseno", "copy", "recomendaciones"):
            value = item.get(text_field)
            if value is not None and not isinstance(value, str):
                raise ValidationError(
                    f"El campo '{text_field}' de la publicación #{item_index} debe ser texto."
                )

        return {
            "titulo_base": titulo_base,
            "tipo": tipo,
            "fecha_publicacion": fecha_publicacion,
            "descripcion": item.get("descripcion"),
            "texto_en_diseno": item.get("texto_en_diseno"),
            "copy": item.get("copy"),
            "hashtags": self._normalize_hashtags(item.get("hashtags")),
            "recomendaciones": item.get("recomendaciones"),
        }

    def _validate_plan_counts(self, record, publicaciones):
        counts = {
            "post": sum(1 for item in publicaciones if item["tipo"] in ("post", "carrusel")),
            "reel": sum(1 for item in publicaciones if item["tipo"] == "reel"),
        }
        expected = {
            "post": int(record.plan_post or 0),
            "reel": int(record.plan_reel or 0),
        }

        mismatches = []
        for tipo, expected_count in expected.items():
            if counts[tipo] != expected_count:
                mismatches.append(f"{tipo}: esperado {expected_count}, recibido {counts[tipo]}")

        if mismatches:
            raise ValidationError(
                "La respuesta JSON no coincide con el plan del cliente. "
                + " | ".join(mismatches)
            )

    def _validate_story_selection(self, record):
        expected = int(record.plan_historia or 0)
        selected = len(record.publicacion_ids.filtered(lambda p: p.es_historia))
        if selected != expected:
            raise ValidationError(
                f"Debes seleccionar exactamente {expected} publicaciones como historias en perfeccionamiento. "
                f"Actualmente hay {selected} seleccionadas."
            )

    def convertir_a_instrucciones(self):
        for record in self:
            feedback = (record.feedback_cliente or "").strip()
            if not feedback:
                raise ValidationError("No hay feedback del cliente para analizar.")

            partner = record.partner_id
            idioma = (partner.lang or "es_ES").split("_")[0]
            pais = partner.country_id.name or "Perú"
            ciudad = partner.city or "Lima"

            prompt = (
                "Analiza la transcripción de la reunión del cliente y conviértela en instrucciones claras, "
                "exhaustivas y accionables para el equipo de contenido. No omitas ningún pedido, cambio, "
                "restricción, preferencia, tono, formato, fechas o entregables.\n\n"
                f"Idioma objetivo: {idioma}\n"
                f"Ubicación: {ciudad}, {pais}\n\n"
                "Devuelve SOLO texto plano con el siguiente formato exacto:\n"
                "INSTRUCCIONES\n"
                "- [tipo] instrucción...\n"
                "\n"
                "PENDIENTES\n"
                "- pendiente...\n"
                "\n"
                "DUDAS\n"
                "- duda...\n\n"
                "Reglas:\n"
                "- Cada instrucción debe ser una sola acción clara.\n"
                "- Usa [tipo] como: cambio, nuevo, mantener, restriccion.\n"
                "- Si algo no está claro, va en DUDAS.\n"
                "- Si falta información o se requiere confirmación, va en PENDIENTES.\n"
                "- No inventes datos.\n\n"
                f"Transcripción:\n{feedback}"
            )

            record.anotaciones_cliente = self._call_openai_chat_completion(
                prompt=prompt,
                system_prompt=(
                    "Eres un analista de reuniones experto en extraer requisitos y convertirlos en "
                    "instrucciones precisas para producción de contenido. Respondes solo texto plano "
                    "con el formato solicitado."
                ),
                temperature=0.2,
                timeout=60,
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Instrucciones generadas",
                "message": "Se generaron instrucciones desde la transcripción del cliente.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def crear_ideas(self):

        for record in self:
            user_tz_name = self.env.user.tz or "UTC"
            try:
                tz = pytz.timezone(user_tz_name)
            except pytz.UnknownTimeZoneError:
                tz = pytz.UTC

            data = self._parse_json_list_field(record.promtp_respuesta, field_name="promtp_respuesta")

            publicaciones_preparadas = []
            for item_index, item in enumerate(data, start=1):
                publicaciones_preparadas.append(
                    self._parse_publicacion_payload(record, item, item_index=item_index, tz=tz)
                )

            self._validate_plan_counts(record, publicaciones_preparadas)

            record.publicacion_ids.unlink()

            contadores = {
                "post": 0,
                "reel": 0,
            }

            for item in publicaciones_preparadas:
                tipo = item["tipo"]
                contador_key = "post" if tipo == "carrusel" else tipo
                contadores[contador_key] += 1
                numero = f"{contadores[contador_key]:02d}"

                titulo_base = item["titulo_base"]

                if tipo == "carrusel":
                    titulo_final = f"Post {numero} (Carrusel) - {titulo_base}"
                else:
                    titulo_final = f"{tipo.capitalize()} {numero} - {titulo_base}"

                vals = {
                    "flujo_id": record.id,
                    "titulo": titulo_final,
                    "fecha_publicacion": item["fecha_publicacion"],
                    "tipo": tipo,
                    "descripcion": item["descripcion"],
                    "texto_en_diseno": item["texto_en_diseno"],
                    "copy": item["copy"],
                    "hashtags": item["hashtags"],
                    "recomendaciones": item["recomendaciones"],
                    "aprobado": False,
                    "es_historia": False,
                }

                self.env["gl.contenido.propuesta"].create(vals)

            record.etapa = "reunion"

        return {
            "effect": {
                "fadeout": "slow",
                "message": "✅ Propuestas creadas correctamente y numeradas por tipo.",
                "type": "rainbow_man",
            }
        }

    def etapa_perfeccionamiento(self):
        # --- Cambiar la etapa del flujo ---
        for record in self:
            record.etapa = "refinar"
        return {
            "effect": {
                "fadeout": "slow",
                "message": "✅ Flujo movido a refinamiento.",
                "type": "rainbow_man",
            }
        }

    def aceptar_refinamiento(self):

        for record in self:
            data = self._parse_json_list_field(
                record.promtp_respuesta_refinamiento,
                field_name="promtp_respuesta_refinamiento",
            )

            if not record.publicacion_ids:
                raise ValidationError("No hay publicaciones asociadas a este flujo.")

            publicaciones_actuales = {pub.id: pub for pub in record.publicacion_ids}
            publicaciones_reemplazo = []

            for item_index, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise ValidationError(f"El elemento #{item_index} del refinamiento debe ser un objeto.")

                pub_id = item.get("id")
                if not pub_id:
                    raise ValidationError(f"La entrada #{item_index} del refinamiento no contiene el campo 'id'.")

                publicacion = publicaciones_actuales.get(pub_id)
                if not publicacion:
                    raise ValidationError(f"No se encontró la publicación con ID {pub_id} dentro de este flujo.")

                titulo = item.get("titulo", publicacion.titulo)
                if titulo is not None and not isinstance(titulo, str):
                    raise ValidationError(f"El campo 'titulo' en el refinamiento #{item_index} debe ser texto.")
                titulo = (titulo or "").strip()
                if not titulo:
                    raise ValidationError(f"La publicación refinada #{item_index} no tiene 'titulo'.")

                tipo = self._normalize_content_type(
                    item.get("tipo", publicacion.tipo),
                    field_name=f"tipo[{item_index}]",
                )

                valores_reemplazo = {
                    "flujo_id": record.id,
                    "titulo": titulo,
                    "fecha_publicacion": publicacion.fecha_publicacion,
                    "tipo": tipo,
                    "descripcion": item.get("descripcion", publicacion.descripcion),
                    "texto_en_diseno": item.get("texto_en_diseno", publicacion.texto_en_diseno),
                    "copy": item.get("copy", publicacion.copy),
                    "hashtags": self._normalize_hashtags(item.get("hashtags", publicacion.hashtags)),
                    "recomendaciones": item.get("recomendaciones", publicacion.recomendaciones),
                    "cambios": publicacion.cambios,
                    "aprobado": publicacion.aprobado,
                    "es_historia": publicacion.es_historia,
                }

                for text_field in ("descripcion", "texto_en_diseno", "copy", "recomendaciones"):
                    value = valores_reemplazo[text_field]
                    if value is not None and not isinstance(value, str):
                        raise ValidationError(
                            f"El campo '{text_field}' en el refinamiento #{item_index} debe ser texto."
                        )

                publicaciones_reemplazo.append(valores_reemplazo)

            if len(publicaciones_reemplazo) != len(record.publicacion_ids):
                raise ValidationError(
                    "La respuesta IA de refinamiento debe incluir exactamente todas las publicaciones actuales del flujo."
                )

            record.publicacion_ids.unlink()
            for vals in publicaciones_reemplazo:
                self.env["gl.contenido.propuesta"].create(vals)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Cambios aplicados",
                "message": "Las publicaciones del flujo fueron reemplazadas con el contenido refinado de IA.",
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def generate_prompt_reunion(self):
        for record in self:
            # --- Filtrar publicaciones no aprobadas ---
            publicaciones = record.publicacion_ids.filtered(lambda p: not p.aprobado)

            if not publicaciones:
                raise ValidationError("No hay publicaciones pendientes de refinamiento.")

            # --- Armar JSON de publicaciones a refinar ---
            publicaciones_data = []
            for pub in publicaciones:
                publicaciones_data.append({
                    "id": pub.id,
                    "titulo": pub.titulo or "",
                    "tipo": pub.tipo or "",
                    "descripcion": (pub.descripcion or "").strip(),
                    "texto_en_diseno": (pub.texto_en_diseno or "").strip(),
                    "copy": (pub.copy or "").strip(),
                    "hashtags": (pub.hashtags or "").split() if pub.hashtags else [],
                    "recomendaciones": (pub.recomendaciones or "").strip(),
                    "cambios": (pub.cambios or "").strip(),
                })

            # --- Construcción del JSON base (respetando tu contexto creativo completo) ---
            partner = record.partner_id
            idioma = (partner.lang or "es_ES").split("_")[0]
            pais = partner.country_id.name or "Perú"
            ciudad = partner.city or "Lima"

            data = {
                "cliente": {
                    "nombre": record.partner_id.name if record.partner_id else "",
                    "industria": record.industria or "",
                },
                "contexto_creativo": {
                    "usar": (record.usar or "").strip(),
                    "evitar": (record.evitar or "").strip(),  # Reglas: quedan solo aquí (no se repiten en Condiciones)
                    "orientacion": record.orientacion_comunicacion or "",
                    "tono": record.tono_comunicacion or "",
                    "publico_objetivo": (record.publico_objetivo or "").strip(),
                    "idioma": idioma,
                    "ubicacion": {
                        "ciudad": ciudad,
                        "pais": pais
                    },
                },
                "feedback_cliente": (record.feedback_cliente or "").strip(),
                "anotaciones_cliente": (record.anotaciones_cliente or "").strip(),
                "publicaciones_a_refinar": publicaciones_data,
            }

            # --- Compactar JSON ---
            json_base = json.dumps(data, ensure_ascii=False, indent=2)

            prompt = ("Eres un agente de marketing especializado en el sector indicado.\n"
                      "Lee el siguiente JSON y úsalo como única fuente de verdad.\n"
                      "No reescribas ni resumas el JSON. No inventes información.\n\n"
                      f"{json_base}\n\n"
                      "Tarea:\n"
                      "Refina únicamente las publicaciones listadas en `publicaciones_a_refinar`, "
                      "mejorando redacción, claridad y coherencia, sin cambiar la estrategia base.\n\n"
                      "Devuelve ÚNICAMENTE un JSON con la MISMA estructura de `publicaciones_a_refinar`:\n"
                      "[\n"
                      "  {\n"
                      "    \"id\": int,\n"
                      "    \"titulo\": \"string\",\n"
                      "    \"tipo\": \"post | reel | story | carrusel\",\n"
                      "    \"descripcion\": \"Texto mejorado y más claro\",\n"
                      "    \"texto_en_diseno\": \"Frase optimizada para diseño\",\n"
                      "    \"copy\": \"Copy refinado en formato AIDA (sin marcadores)\",\n"
                      "    \"hashtags\": [\"#hashtag1\", \"#hashtag2\"],\n"
                      "    \"recomendaciones\": \"Sugerencias visuales o de tono actualizadas\"\n"
                      "  }\n"
                      "]\n\n"
                      "Reglas obligatorias (orden de prioridad):\n"
                      "1) Aplica primero el campo `cambios` de cada publicación. Son instrucciones específicas y prioritarias.\n"
                      "2) Luego aplica `anotaciones_cliente` si afectan a esas publicaciones.\n"
                      "3) Luego considera `feedback_cliente` como guía general.\n"
                      "4) Mantén coherencia total con `contexto_creativo` (usar, evitar, tono, orientación, idioma, público).\n\n"
                      "Restricciones:\n"
                      "- No modifiques el `id`.\n"
                      "- No cambies el `tipo` de publicación salvo que el campo `cambios` lo indique explícitamente.\n"
                      "- No rehagas la idea desde cero: esto es un REFINAMIENTO.\n"
                      "- Usa formato AIDA en el `copy` sin escribir los nombres de las etapas.\n"
                      "- Hashtags en minúsculas y sin duplicados.\n"
                      "- El campo `texto_en_diseno` es TEXTO VISUAL, no copy.\n"
                      "- Devuelve solo el JSON final, sin explicaciones.")

            record.promtp_refinamiento = prompt
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Refinamiento generado",
                "message": "Prompt optimizado usando feedback y cambios específicos. Actualizando vista...",
                "sticky": True,
                "type": "success",
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }

    def generar_tareas(self):

        def _format_hashtags(hashtags):
            if not hashtags:
                return ""
            if isinstance(hashtags, list):
                return " ".join(h.strip() for h in hashtags if h)
            return str(hashtags).strip()

        def _extract_base_title(title):
            title = (title or "").strip()
            if not title:
                return "Sin título"
            return re.sub(r"^(Post|Reel|Story|Historia)\s+\d+(?:\s+\(Carrusel\))?\s*-\s*", "", title, flags=re.IGNORECASE)

        def _build_task_name(prop, index_by_type):
            base_title = _extract_base_title(prop.titulo)
            tipo = (prop.tipo or "").strip().lower()

            if tipo == "reel":
                return f"Reel {index_by_type:02d} - {base_title}"
            if tipo == "carrusel":
                return f"Post {index_by_type:02d} (Carrusel) - {base_title}"
            if tipo == "story":
                return f"Historia {index_by_type:02d} - {base_title}"
            return f"Post {index_by_type:02d} - {base_title}"

        TIPO_MAP = {
            "post": "feed",
            "feed": "feed",
            "carrusel": "feed",
            "reel": "video_reels",
            "video_reels": "video_reels",
            "historia": "video_stories",
            "story": "video_stories",
            "video_stories": "video_stories",
        }

        for record in self:
            if not record.project_id:
                raise ValidationError("Debes seleccionar un Proyecto antes de generar tareas.")

            propuestas = record.publicacion_ids.sorted(
                key=lambda p: (
                    p.fecha_publicacion or fields.Datetime.now(),
                    p.id,
                )
            )
            if not propuestas:
                raise ValidationError("No hay propuestas/publicaciones para generar tareas.")

            self._validate_story_selection(record)

            no_aprobadas = propuestas.filtered(lambda p: not getattr(p, "aprobado", False))
            if no_aprobadas:
                raise ValidationError(
                    f"Hay {len(no_aprobadas)} publicaciones sin aprobar en el flujo '{record.name}'."
                )

            partner_id = record.partner_id.id if record.partner_id else False
            redes_ids = record.redes_ids.ids if getattr(record, "redes_ids", False) else []
            asignados_ids = record.user_ids.ids if getattr(record, "user_ids", False) else []

            Task = self.env["project.task"]
            primary_name_map = {}
            story_name_map = {}
            counters = {
                "post": 0,
                "reel": 0,
                "story": 0,
            }

            for prop in propuestas:
                tipo = (prop.tipo or "").strip().lower()
                counter_key = "reel" if tipo == "reel" else "story" if tipo == "story" else "post"
                counters[counter_key] += 1
                primary_name_map[prop.id] = _build_task_name(prop, counters[counter_key])

            story_props = propuestas.filtered(lambda p: p.es_historia)
            for index, story_prop in enumerate(story_props, start=1):
                story_name_map[story_prop.id] = f"Historia {index:02d} - {_extract_base_title(story_prop.titulo)}"

            for prop in propuestas:
                if not prop.fecha_publicacion:
                    raise ValidationError("Todas las publicaciones deben tener Fecha de Publicación.")

                tipo_src = (prop.tipo or "").strip().lower()
                tipo_task = TIPO_MAP.get(tipo_src, "otro")

                fecha_deadline = fields.Datetime.from_string(prop.fecha_publicacion)
                fecha_deadline = fecha_deadline - timedelta(days=1)
                fecha_deadline = fecha_deadline.replace(hour=12, minute=0, second=0, microsecond=0)

                hashtags_txt = _format_hashtags(prop.hashtags)

                description = (prop.copy or "").strip().replace("\n", "<br/>")
                objetivo = (prop.descripcion or "")
                vals = {
                    "name": primary_name_map[prop.id],
                    "project_id": record.project_id.id,
                    "user_ids": [
                        (6, 0, asignados_ids)
                    ],
                    "fecha_publicacion": prop.fecha_publicacion,
                    "date_deadline": fecha_deadline,
                    "tipo": tipo_task,
                    "red_social_ids": [
                        (6, 0, redes_ids)
                    ],
                    "partner_id": partner_id,
                    "post_estado": "Pendiente",
                    "texto_en_diseno": (prop.texto_en_diseno or "").strip(),
                    "hashtags": hashtags_txt,
                    "description": description,
                    "objetivo": objetivo,
                }

                Task.create(vals)

                if prop.es_historia:
                    historia_vals = dict(vals)
                    historia_vals.update({
                        "name": story_name_map[prop.id],
                        "tipo": "video_stories",
                    })
                    Task.create(historia_vals)

            record.etapa = "publicaciones"

        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "kanban,list,form",
            "domain": [
                ("project_id", "in", self.mapped("project_id").ids)
            ],
            "name": "Tareas del Proyecto",
            "context": {
                "search_default_project_id": self[:1].project_id.id if self[:1].project_id else False,
            },
        }

    def previous_stage(self):
        etapa_order = [
            "ideas",
            "reunion",
            "refinar",
            "publicaciones"
        ]
        for record in self:
            if record.etapa in etapa_order:
                idx = etapa_order.index(record.etapa)
                if idx > 0:
                    record.etapa = etapa_order[idx - 1]

    def sugerir_dias_festivos(self):
        for record in self:
            if not record.industria:
                raise ValidationError("Por favor, define la industria del cliente antes de generar las sugerencias.")

            if not record.date_start or not record.date:
                raise ValidationError("Por favor, define un rango de fechas antes de generar las sugerencias.")

            partner = record.partner_id
            idioma = (partner.lang or "es_ES").split("_")[0]
            pais = partner.country_id.name or "Perú"
            ciudad = partner.city or "Lima"

            rango_texto = f"entre {record.date_start.strftime('%d/%m/%Y')} y {record.date.strftime('%d/%m/%Y')}"
            prompt = (f"Industria: {record.industria}\n"
                      f"Ubicación: {ciudad}, {pais}\n"
                      f"Idioma: {idioma}\n\n"
                      f"Sugiere entre 1 y 3 fechas relevantes para marketing en {pais}, {rango_texto}, "
                      f"incluyendo:\n"
                      f"- Días festivos o conmemorativos culturales y patrios.\n"
                      f"- Días COMERCIALES o de marketing (como Black Friday, CyberDay, Día del Padre, etc.).\n\n"
                      f"Devuelve una lista corta en texto, con cada día en una línea separada, incluyendo el nombre y la fecha aproximada.")

            record.dias_festivos_referencia = self._call_openai_chat_completion(
                prompt=prompt,
                system_prompt=(
                    "Eres un asistente de marketing experto en planificación de contenidos y efemérides. "
                    "Responde de forma breve y estructurada."
                ),
                temperature=0.5,
                timeout=40,
            )

        # 🟩 Notificación + recargar vista
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "🎯 Días Festivos y Comerciales Sugeridos",
                "message": "Se generaron de 1 a 3 sugerencias según el rango de fechas, industria y ubicación del cliente.",
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }

    def generate_prompt(self):

        def _safe_date_str(d):
            try:
                return d.isoformat() if d else ""
            except (AttributeError, ValueError, TypeError):
                return ""

        def _try_json_loads(s):
            try:
                return json.loads(s or "{}")
            except (json.JSONDecodeError, TypeError):
                return {}

        def _dedup_lines(s: str) -> str:
            """Multiline -> quita vacías, deduplica y conserva orden."""
            if not s:
                return ""
            seen, out = set(), []
            for line in (s.replace("\r", "").split("\n")):
                line = line.strip()
                if not line:
                    continue
                if line not in seen:
                    seen.add(line)
                    out.append(line)
            return "\n".join(out)

        def _guia_por_nivel(nivel: str) -> str:
            nivel = (nivel or "balanceado").strip().lower()
            return {
                "minimalista": "Redacción compacta y directa. Explica lo esencial. AIDA conciso y CTA claro.",
                "balanceado": "Redacción equilibrada: informa y persuade sin redundancias. AIDA claro y natural.",
                "detallado": "Redacción más explicativa. Aporta contexto y resuelve dudas comunes. AIDA más desarrollado.",
            }.get(nivel, "Redacción equilibrada: informa y persuade sin redundancias. AIDA claro y natural.")

        for record in self:
            if not record.partner_id:
                raise ValidationError("Debes seleccionar un Cliente/Partner antes de generar el prompt.")
            if not record.industria:
                raise ValidationError("Debes definir la industria del cliente antes de generar el prompt.")
            if not record.date_start or not record.date:
                raise ValidationError("Debes definir el rango de fechas antes de generar el prompt.")
            if record.date_start > record.date:
                raise ValidationError("La fecha de inicio no puede ser mayor que la fecha final.")

            partner = record.partner_id
            redes = [r.name for r in record.redes_ids] if record.redes_ids else []

            idioma = (partner.lang or "es_ES").split("_")[0]
            pais = partner.country_id.name or "Perú"
            ciudad = partner.city or "Lima"

            fecha_ini_iso = _safe_date_str(record.date_start)
            fecha_fin_iso = _safe_date_str(record.date)

            competencia_clean = _dedup_lines((record.competencia_urls or "").strip())
            tendencias_clean = _dedup_lines((record.tendencias_urls or "").strip())
            dias_clean = (record.dias_festivos_referencia or "").strip()

            metricas = _try_json_loads(record.metricas)

            nivel_contenido = getattr(record, "nivel_contenido", None) or "balanceado"

            data = {
                "cliente": {
                    "nombre": partner.name or "",
                    "industria": record.industria or "",
                    "redes_activas": redes,
                },
                "contexto_creativo": {
                    "etapa": record.etapa,
                    "notas": (record.notas or "").strip(),
                    "usar": (record.usar or "").strip(),
                    "evitar": (record.evitar or "").strip(),
                    "orientacion": record.orientacion_comunicacion or "",
                    "tono": record.tono_comunicacion or "",
                    "publico_objetivo": (record.publico_objetivo or "").strip(),
                    "competencia_urls": competencia_clean,
                    "tendencias_urls": tendencias_clean,
                    "dias_festivos_referencia": dias_clean,
                    "rango_fechas": {
                        "inicio": fecha_ini_iso,
                        "fin": fecha_fin_iso
                    },
                    "idioma": idioma,
                    "ubicacion": {
                        "ciudad": ciudad,
                        "pais": pais
                    },
                    "cantidad_contenido": nivel_contenido,
                    "guia_cantidad_contenido": _guia_por_nivel(nivel_contenido),
                },
                "referencias_metricas": metricas,
                "objetivo_generacion": {
                    "tipo": (
                        "ideas_iniciales" if record.etapa == "ideas" else "refinamiento" if record.etapa == "refinar" else "publicaciones"),
                    "descripcion": (
                        f"Generar contenido alineado al contexto creativo (tono, orientación, idioma, público, fechas), "
                        f"apoyado en métricas previas y con foco en la industria del cliente ({record.industria})."),
                },
            }

            json_base = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

            prompt = ("Eres un agente de marketing especializado en el sector indicado.\n"
                      "Lee el siguiente JSON y úsalo como única fuente de verdad.\n"
                      "No reescribas ni resumas el JSON. No inventes datos no presentes.\n\n"
                      f"{json_base}\n\n"
                      "Tarea:\n"
                      "Genera un JSON con el plan de publicaciones del periodo.\n\n"
                      "Devuelve ÚNICAMENTE el JSON con esta estructura:\n"
                      "[\n"
                      "  {\n"
                      "    \"titulo\": \"string\",\n"
                      "    \"fecha_publicacion\": \"YYYY-MM-DD HH:MM:SS\",\n"
                      "    \"tipo\": \"post | reel | story | carrusel\",\n"
                      "    \"descripcion\": \"Breve resumen del contenido y su objetivo comunicacional.\",\n"
                      "    \"texto_en_diseno\": \"Frase principal que aparecerá en la pieza gráfica o portada del video.\",\n"
                      "    \"copy\": \"Copy AIDA (sin etiquetas ni marcadores).\",\n"
                      "    \"hashtags\": [\"#hashtag1\", \"#hashtag2\"],\n"
                      "    \"recomendaciones\": \"Sugerencias visuales y de tono.\"\n"
                      "  }\n"
                      "]\n\n"
                      "Condiciones obligatorias (NO opcionales):\n"
                      f"- Genera exactamente {int(record.plan_post or 0)} posts y {int(record.plan_reel or 0)} reels.\n"
                      "- Cada elemento debe incluir obligatoriamente: titulo, fecha_publicacion, tipo, descripcion, texto_en_diseno, copy, hashtags y recomendaciones.\n"
                      "- La `fecha_publicacion` debe caer dentro del rango indicado en `contexto_creativo.rango_fechas`.\n"
                      "- Respeta estrictamente TODO lo definido en `contexto_creativo` (usar/evitar, tono, orientación, idioma, público, fechas, ubicación).\n"
                      "- AIDA obligatorio en `copy` SIN escribir las palabras Atención, Interés, Deseo o Acción.\n"
                      "- El campo `copy` está PROHIBIDO entregarlo en una sola linea.\n"
                      "- El CTA debe ir en una línea final separada.\n"
                      "- Usa `cantidad_contenido` y `guia_cantidad_contenido` para definir profundidad del texto.\n"
                      "- Aplica `usar` y `evitar` como INSTRUCCIONES DIRECTAS.\n"
                      "- Hashtags en minúsculas, sin duplicados.\n"
                      "- El campo `titulo` NO debe incluir el tipo de contenido (reel, post, carrusel, story).\n"
                      "- Todo contenido con `tipo = reel` DEBE estructurarse así: 1. Hook 2. Problema 3. Valor 4. Autoridad 5. CTA, que el contenido esté etiquetado.\n"
                      "- Usa solo saltos de línea simples dentro de `copy`; no uses líneas en blanco dobles.\n"
                      "- Devuelve SOLO el JSON final. No agregues explicaciones ni texto fuera del JSON.")

            # --- Guardar el prompt completo ---
            record.promtp_ideas = prompt

        # --- Notificación visual ---
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "✅ Prompt IA generado",
                "message": "Prompt generado sin redundancias (DRY). Actualizando la vista...",
                "sticky": False,
                "type": "success",
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload"
                },
            },
        }
