import json
import requests
import pytz
from odoo import models, fields
from odoo.exceptions import ValidationError
from datetime import datetime
from datetime import timedelta


class GeneradorContenidoPropuesta(models.Model):
    _name = "gl.contenido.propuesta"
    _description = "Publicación generada desde IA"
    _rec_name = "titulo"

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

    metricas = fields.Text("Métricas (JSON)")

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

    def convertir_a_instrucciones(self):
        for record in self:
            feedback = (record.feedback_cliente or "").strip()
            if not feedback:
                raise ValidationError("No hay feedback del cliente para analizar.")

            partner = record.partner_id
            idioma = (partner.lang or "es_ES").split("_")[0]
            pais = partner.country_id.name or "Perú"
            ciudad = partner.city or "Lima"

            icp = self.env["ir.config_parameter"].sudo()
            api_key = icp.get_param("chatgpt.api_key")
            base_url = icp.get_param("chatgpt.base_url", "https://api.openai.com/v1")
            model = icp.get_param("chatgpt.model", "gpt-4.1-mini")

            if not api_key:
                raise ValidationError("No se ha configurado la API Key de ChatGPT en Ajustes del sistema.")

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

            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Eres un analista de reuniones experto en extraer requisitos y convertirlos en "
                                "instrucciones precisas para producción de contenido. Respondes solo texto plano "
                                "con el formato solicitado."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "temperature": 0.2,
                }

                response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()

                raw = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if not raw:
                    raise ValidationError("ChatGPT no devolvió contenido.")

                record.anotaciones_cliente = raw

            except Exception as e:
                raise ValidationError(f"Error al convertir a instrucciones: {e}")

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

            if not record.promtp_respuesta:
                raise ValidationError("⚠️ El campo 'promtp_respuesta' está vacío. Debes pegar un JSON válido.")

            try:
                data = json.loads(record.promtp_respuesta)
            except json.JSONDecodeError as e:
                raise ValidationError(f"❌ El contenido no es un JSON válido:\n{e}")

            if not isinstance(data, list):
                raise ValidationError("❌ El JSON debe ser una lista de objetos.")

            record.publicacion_ids.unlink()

            contadores = {
                "post": 0,
                "reel": 0,
            }

            for item in data:
                if not isinstance(item, dict):
                    raise ValidationError("Cada elemento del JSON debe ser un objeto.")

                tipo = (item.get("tipo") or "post").lower()
                if tipo not in ("post", "reel", "carrusel"):
                    tipo = "post"  # fallback seguro

                contador_key = "post" if tipo == "carrusel" else tipo
                contadores[contador_key] += 1
                numero = f"{contadores[contador_key]:02d}"

                titulo_base = (item.get("titulo") or "Sin título").strip()

                if tipo == "carrusel":
                    titulo_final = f"Post {numero} (Carrusel) - {titulo_base}"
                else:
                    titulo_final = f"{tipo.capitalize()} {numero} - {titulo_base}"

                fecha_publicacion_str = item.get("fecha_publicacion")
                fecha_publicacion = False

                if fecha_publicacion_str:
                    if len(fecha_publicacion_str) == 10:
                        fecha_publicacion_str = f"{fecha_publicacion_str} 08:00:00"

                    try:
                        fecha_local = datetime.strptime(fecha_publicacion_str, "%Y-%m-%d %H:%M:%S")
                        fecha_local = tz.localize(fecha_local)
                        fecha_utc = fecha_local.astimezone(pytz.UTC)
                        fecha_publicacion = fecha_utc.replace(tzinfo=None)
                    except Exception:
                        raise ValidationError(f"Formato de fecha inválido: {fecha_publicacion_str}. Usa 'YYYY-MM-DD HH:MM:SS'")

                vals = {
                    "flujo_id": record.id,
                    "titulo": titulo_final,
                    "fecha_publicacion": fecha_publicacion,
                    "tipo": tipo,
                    "descripcion": item.get("descripcion"),
                    "texto_en_diseno": item.get("texto_en_diseno"),
                    "copy": item.get("copy"),
                    "hashtags": (
                        ", ".join(item.get("hashtags", [])) if isinstance(item.get("hashtags"), list) else item.get("hashtags")),
                    "recomendaciones": item.get("recomendaciones"),
                    "aprobado": False,
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
                    "message": "✅ Propuestas creadas correctamente desde JSON.",
                    "type": "rainbow_man",
                }
            }

    def aceptar_refinamiento(self):

        for record in self:
            # --- Validar existencia de resultado ---
            if not record.promtp_respuesta_refinamiento:
                raise ValidationError("No se encontró ningún resultado de refinamiento para aplicar.")

            # --- Intentar parsear el JSON ---
            try:
                data = json.loads(record.promtp_respuesta_refinamiento)
                if not isinstance(data, list):
                    raise ValidationError("El resultado del refinamiento debe ser una lista JSON.")
            except Exception as e:
                raise ValidationError(f"Error al interpretar el JSON del refinamiento: {e}")

            # --- Validar que existan publicaciones ---
            if not record.publicacion_ids:
                raise ValidationError("No hay publicaciones asociadas a este flujo.")

            # --- Aplicar actualizaciones ---
            for item in data:
                pub_id = item.get("id")
                if not pub_id:
                    raise ValidationError("Una de las entradas del JSON no contiene el campo 'id'.")

                publicacion = record.publicacion_ids.filtered(lambda p: p.id == pub_id)
                if not publicacion:
                    raise ValidationError(f"No se encontró la publicación con ID {pub_id} dentro de este flujo.")

                # Campos actualizables
                campos_validos = [
                    "titulo",
                    "tipo",
                    "descripcion",
                    "texto_en_diseno",
                    "copy",
                    "recomendaciones",
                ]

                valores_actualizados = {campo: item[campo] for campo in campos_validos if
                                        campo in item and isinstance(item[campo], str)}

                # Procesar hashtags
                if "hashtags" in item:
                    hashtags = item["hashtags"]
                    if isinstance(hashtags, list):
                        valores_actualizados["hashtags"] = " ".join(hashtags)
                    elif isinstance(hashtags, str):
                        valores_actualizados["hashtags"] = hashtags

                # Aplicar actualización
                if valores_actualizados:
                    publicacion.write(valores_actualizados)
                else:
                    raise ValidationError(f"No se encontró ningún campo válido para actualizar en la publicación ID {pub_id}.")

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
                      "    \"tipo\": \"post | reel | historia | carrusel\",\n"
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

            propuestas = getattr(record, "propuestas_ids", False) or record.publicacion_ids
            if not propuestas:
                raise ValidationError("No hay propuestas/publicaciones para generar tareas.")

            no_aprobadas = propuestas.filtered(lambda p: not getattr(p, "aprobado", False))
            if no_aprobadas:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "⚠️ Publicaciones sin aprobar",
                        "message": f"Hay {len(no_aprobadas)} publicaciones sin aprobar.",
                        "type": "warning",
                        "sticky": True,
                    },
                }

            partner_id = record.partner_id.id if record.partner_id else False
            redes_ids = record.redes_ids.ids if getattr(record, "redes_ids", False) else []
            asignados_ids = record.user_ids.ids if getattr(record, "user_ids", False) else []

            Task = self.env["project.task"]
            created_count = 0

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
                    "name": (prop.titulo or f"Publicación #{prop.id}").strip(),
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
                created_count += 1

            record.etapa = "publicaciones"

            return {
                "type": "ir.actions.act_window",
                "res_model": "project.task",
                "view_mode": "kanban,list,form",
                "domain": [
                    ("project_id", "=", record.project_id.id)
                ],
                "name": "Tareas del Proyecto",
                "context": {
                    "default_project_id": record.project_id.id,
                    "search_default_project_id": record.project_id.id,
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

            # 🧭 Configuración ChatGPT
            icp = self.env["ir.config_parameter"].sudo()
            api_key = icp.get_param("chatgpt.api_key")
            base_url = icp.get_param("chatgpt.base_url", "https://api.openai.com/v1")
            model = icp.get_param("chatgpt.model", "gpt-4.1-mini")

            if not api_key:
                raise ValidationError("No se ha configurado la API Key de ChatGPT en Ajustes del sistema.")

            rango_texto = f"entre {record.date_start.strftime('%d/%m/%Y')} y {record.date.strftime('%d/%m/%Y')}"
            prompt = (f"Industria: {record.industria}\n"
                      f"Ubicación: {ciudad}, {pais}\n"
                      f"Idioma: {idioma}\n\n"
                      f"Sugiere entre 1 y 3 fechas relevantes para marketing en {pais}, {rango_texto}, "
                      f"incluyendo:\n"
                      f"- Días festivos o conmemorativos culturales y patrios.\n"
                      f"- Días COMERCIALES o de marketing (como Black Friday, CyberDay, Día del Padre, etc.).\n\n"
                      f"Devuelve una lista corta en texto, con cada día en una línea separada, incluyendo el nombre y la fecha aproximada.")

            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Eres un asistente de marketing experto en planificación de contenidos y efemérides. "
                                "Responde de forma breve y estructurada."),
                        },
                        {
                            "role": "user",
                            "content": prompt
                        },
                    ],
                    "temperature": 0.5,
                }

                response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=40)
                response.raise_for_status()
                data = response.json()

                suggestion = data["choices"][0]["message"]["content"].strip()
                record.dias_festivos_referencia = suggestion

            except Exception as e:
                raise ValidationError(f"Error al obtener sugerencias: {e}")

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
            except Exception:
                return ""

        def _try_json_loads(s):
            try:
                return json.loads(s or "{}")
            except Exception:
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
                        "Generar contenido alineado al contexto creativo (tono, orientación, idioma, público, fechas), "
                        "apoyado en métricas previas y con foco en la industria del cliente ({record.industria})."),
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
                      "    \"tipo\": \"post | reel | historia | carrusel\",\n"
                      "    \"descripcion\": \"Breve resumen del contenido y su objetivo comunicacional.\",\n"
                      "    \"texto_en_diseno\": \"Frase principal que aparecerá en la pieza gráfica o portada del video.\",\n"
                      "    \"copy\": \"Copy AIDA (sin etiquetas ni marcadores).\",\n"
                      "    \"hashtags\": [\"#hashtag1\", \"#hashtag2\"],\n"
                      "    \"recomendaciones\": \"Sugerencias visuales y de tono.\"\n"
                      "  }\n"
                      "]\n\n"
                      "Condiciones obligatorias (NO opcionales):\n"
                      f"- Genera exactamente {int(record.plan_post or 0)} posts y {int(record.plan_reel or 0)} reels.\n"
                      "- Respeta estrictamente TODO lo definido en `contexto_creativo` (usar/evitar, tono, orientación, idioma, público, fechas, ubicación).\n"
                      "- AIDA obligatorio en `copy` SIN escribir las palabras Atención, Interés, Deseo o Acción.\n"
                      "- El campo `copy` está PROHIBIDO entregarlo en una sola linea.\n"
                      "- El CTA debe ir en una línea final separada.\n"
                      "- Usa `cantidad_contenido` y `guia_cantidad_contenido` para definir profundidad del texto.\n"
                      "- Aplica `usar` y `evitar` como INSTRUCCIONES DIRECTAS.\n"
                      "- Hashtags en minúsculas, sin duplicados.\n"
                      "- El campo `titulo` NO debe incluir el tipo de contenido (reel, post, carrusel, historia).\n"
                      "- Todo contenido con `tipo = reel` DEBE estructurarse así: 1. Hook 2. Problema 3. Valor 4. Autoridad 5. CTA, que el contenido esté etiquetado.\n"
                      "- Usa siempre un solo salto de linea no doble n n \n"
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
