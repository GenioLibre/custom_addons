import base64
import time

import requests

from odoo import http, fields, _
from odoo.exceptions import ValidationError, UserError
from odoo.http import request
from odoo.tools import image_process


class IemChurchWebsite(http.Controller):
    def _access_verified_key(self):
        return "iem_public_member_form_access_verified"

    def _access_verified_at_key(self):
        return "iem_public_member_form_access_verified_at"

    def _access_verify_ttl_seconds(self):
        # Keep this short to reduce risk on shared/public devices.
        return 600

    def _get_partner_location_suggestions(self, country_id):
        partner_model = request.env["res.partner"].sudo()
        domain = [("country_id", "=", country_id)] if country_id else []

        provinces_data = partner_model.read_group(
            domain + [("city", "!=", False)],
            ["city"],
            ["city"],
            lazy=False,
        )
        districts_data = partner_model.read_group(
            domain + [("district", "!=", False)],
            ["district"],
            ["district"],
            lazy=False,
        )

        provinces = sorted({(row.get("city") or "").strip() for row in provinces_data if row.get("city")})
        districts = sorted({(row.get("district") or "").strip() for row in districts_data if row.get("district")})
        return provinces, districts

    def _get_public_form_settings(self):
        params = request.env["ir.config_parameter"].sudo()
        return {
            "access_password": (params.get_param("iem.public_member_form_password") or "").strip(),
            "rate_limit_seconds": int(params.get_param("iem.public_member_form_rate_limit") or 60),
        }

    def _get_public_form_reference_data(self):
        env = request.env
        member_model = env["church.member"].sudo()
        current_position_options = member_model._fields["current_position"].selection
        marital_status_options = member_model._fields["marital_status"].selection
        peru = env["res.country"].sudo().search([("code", "=", "PE")], limit=1)
        province_suggestions, district_suggestions = self._get_partner_location_suggestions(peru.id)
        return {
            "identification_types": env["l10n_latam.identification.type"].sudo().search([], order="name asc"),
            "states": env["res.country.state"].sudo().search([("country_id.code", "=", "PE")], order="name asc"),
            "countries": env["res.country"].sudo().search([], order="name asc"),
            "peru_country_id": peru.id or False,
            "province_suggestions": province_suggestions,
            "district_suggestions": district_suggestions,
            "predios": env["iem.church.predio"].sudo().search([], order="name asc"),
            "redes": env["iem.church.red"].sudo().search([], order="name asc"),
            "discipulados": env["iem.church.discipulado"].sudo().search([], order="name asc"),
            "celulas": env["iem.church.celula"].sudo().search([], order="name asc"),
            "current_position_options": current_position_options,
            "marital_status_options": marital_status_options,
        }

    def _render_public_form(self, form=None, error=False, success=False):
        values = {
            "error": error,
            "success": success,
            "form": form or {},
        }
        values.update(self._get_public_form_reference_data())
        return request.render("iem_church_management.church_member_public_form", values)

    def _to_int_or_false(self, value):
        try:
            return int(value) if value else False
        except (TypeError, ValueError):
            return False

    def _rate_limit_key(self):
        return "iem_public_member_form_last_submit"

    def _list_access_verified_key(self):
        return "iem_public_member_list_form_access_verified"

    def _list_access_verified_at_key(self):
        return "iem_public_member_list_form_access_verified_at"

    def _list_rate_limit_key(self):
        return "iem_public_member_list_form_last_submit"

    def _is_dni_type(self, identification_type):
        if not identification_type:
            return False
        code = (getattr(identification_type, "code", "") or "").strip().upper()
        l10n_pe_vat_code = (getattr(identification_type, "l10n_pe_vat_code", "") or "").strip().upper()
        name = (identification_type.name or "").strip().upper()
        return code == "DNI" or l10n_pe_vat_code == "1" or "DNI" in name

    def _find_existing_document(self, identification_type_id, vat):
        return request.env["res.partner"].sudo().search(
            [
                ("l10n_latam_identification_type_id", "=", identification_type_id),
                ("vat", "=", vat),
            ],
            limit=1,
        )

    def _get_online_member_lists(self):
        return request.env["iem.church.member.list"].sudo().search(
            [("active", "=", True), ("website_registration_enabled", "=", True)],
            order="name asc",
        )

    def _selection_label(self, record, field_name, value):
        selection = dict(record._fields[field_name].selection)
        return selection.get(value, value or "")

    def _serialize_online_list(self, member_list):
        info_items = []
        if member_list.predio_id:
            info_items.append({"label": "Predio", "value": member_list.predio_id.display_name})
        if member_list.red_id:
            info_items.append({"label": "Red", "value": member_list.red_id.display_name})
        if member_list.discipulado_id:
            info_items.append({"label": "Discipulado", "value": member_list.discipulado_id.display_name})
        if member_list.celula_id:
            info_items.append({"label": "Célula", "value": member_list.celula_id.display_name})
        if member_list.details:
            info_items.append({"label": "Detalles", "value": member_list.details})
        return {
            "id": member_list.id,
            "name": member_list.name,
            "info_items": info_items,
            "has_extra_step": member_list._website_has_extra_step(),
            "show_boolean_extra": member_list.show_boolean_extra,
            "show_amount_extra": member_list.show_amount_extra,
            "show_text_extra": member_list.show_text_extra,
            "show_image_extra": member_list.show_image_extra,
            "boolean_extra_label": member_list.boolean_extra_label or "Si/No",
            "amount_extra_label": member_list.amount_extra_label or "Monto",
            "text_extra_label": member_list.text_extra_label or "Notas",
            "image_extra_label": member_list.image_extra_label or "Imagen",
            "currency_symbol": member_list.currency_id.symbol or "",
        }

    def _get_online_member_list_by_id(self, list_id):
        list_id = self._to_int_or_false(list_id)
        if not list_id:
            return request.env["iem.church.member.list"]
        return self._get_online_member_lists().filtered(lambda rec: rec.id == list_id)[:1]

    def _search_eligible_members_for_list(self, member_list, query=None, limit=20):
        member_model = request.env["church.member"].sudo()
        domain = list(member_list._website_member_domain())
        cleaned_query = (query or "").strip()
        if cleaned_query:
            domain.extend([
                "|", "|", "|",
                ("first_name", "ilike", cleaned_query),
                ("last_name", "ilike", cleaned_query),
                ("name", "ilike", cleaned_query),
                ("vat", "ilike", cleaned_query),
            ])
        members = member_model.search(domain, limit=limit, order="last_name asc, first_name asc, id asc")
        existing_member_ids = set(member_list.member_line_ids.mapped("member_id").ids)
        return [
            {
                "id": member.id,
                "name": member.display_name,
                "already_added": member.id in existing_member_ids,
            }
            for member in members
        ]

    def _render_public_member_list_form(self, form=None, error=False, success=False):
        online_lists = self._get_online_member_lists()
        selected_list = self._get_online_member_list_by_id((form or {}).get("list_id"))
        selected_member = request.env["church.member"].sudo().browse(
            self._to_int_or_false((form or {}).get("member_id"))
        ).exists()
        online_lists_data = [self._serialize_online_list(member_list) for member_list in online_lists]
        values = {
            "error": error,
            "success": success,
            "form": form or {},
            "online_lists": online_lists,
            "online_lists_data": online_lists_data,
            "selected_member": selected_member,
            "selected_list": selected_list,
            "access_validated": bool(request.session.get(self._list_access_verified_key())),
        }
        return request.render("iem_church_management.church_member_list_public_form", values)

    @http.route(
        ["/church/registro"],
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        csrf=True,
    )
    def church_member_form(self, **kwargs):
        request.session[self._access_verified_key()] = False
        request.session[self._access_verified_at_key()] = 0
        return self._render_public_form(form=kwargs, success=kwargs.get("submitted") == "1")

    @http.route(
        ["/church/registro/validate_access"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_form_validate_access(self, **kwargs):
        settings = self._get_public_form_settings()
        access_password = (kwargs.get("access_password") or "").strip()
        if settings["access_password"] and access_password != settings["access_password"]:
            request.session[self._access_verified_key()] = False
            request.session[self._access_verified_at_key()] = 0
            return request.make_json_response(
                {
                    "ok": False,
                    "message": "La clave no es correcta. El formulario no sera guardado.",
                }
            )
        request.session[self._access_verified_key()] = True
        request.session[self._access_verified_at_key()] = int(time.time())
        return request.make_json_response({"ok": True})

    @http.route(
        ["/church/registro/check_dni"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_form_check_dni(self, **kwargs):
        identification_type_id = self._to_int_or_false(kwargs.get("l10n_latam_identification_type_id"))
        vat = (kwargs.get("vat") or "").strip()
        if not identification_type_id or not vat:
            return request.make_json_response(
                {"ok": False, "message": "Ingresa tipo y numero de identificacion."}
            )
        existing = self._find_existing_document(identification_type_id, vat)
        if existing:
            return request.make_json_response(
                {
                    "ok": False,
                    "message": "Ya existe el documento de identidad registrado. El formulario no sera guardado.",
                }
            )
        return request.make_json_response({"ok": True})

    @http.route(
        ["/church/registro/fetch_dni"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_form_fetch_dni(self, **kwargs):
        identification_type_id = self._to_int_or_false(kwargs.get("l10n_latam_identification_type_id"))
        vat = (kwargs.get("vat") or "").strip()
        if not identification_type_id or not vat:
            return request.make_json_response(
                {"ok": False, "message": "Ingresa tipo y numero de identificacion."}
            )

        identification_type = request.env["l10n_latam.identification.type"].sudo().browse(identification_type_id)
        if not self._is_dni_type(identification_type):
            return request.make_json_response(
                {"ok": False, "message": "Selecciona un tipo de documento DNI."}
            )
        if not vat.isdigit() or len(vat) != 8:
            return request.make_json_response(
                {"ok": False, "message": "Ingresa un DNI valido de 8 digitos."}
            )

        token = request.env["ir.config_parameter"].sudo().get_param("iem.dni_api_token")
        if not token:
            return request.make_json_response(
                {"ok": False, "message": "Falta configurar el token de la API DNI."}
            )

        try:
            response = requests.get(
                "https://api.decolecta.com/v1/reniec/dni",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                params={"numero": vat},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return request.make_json_response(
                {"ok": False, "message": f"Error consultando API DNI: {exc}"}
            )

        names = (payload.get("first_name") or "").strip()
        ap_pat = (payload.get("first_last_name") or "").strip()
        ap_mat = (payload.get("second_last_name") or "").strip()
        if not (names or ap_pat or ap_mat):
            return request.make_json_response(
                {"ok": False, "message": "No se encontraron datos para el DNI ingresado."}
            )
        last_name = " ".join(part for part in [ap_pat, ap_mat] if part).strip()
        return request.make_json_response(
            {
                "ok": True,
                "first_name": names.title() if names else "",
                "last_name": last_name.title() if last_name else "",
            }
        )

    @http.route(
        ["/church/registro/submit"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_form_submit(self, **kwargs):
        form_values = dict(kwargs)
        settings = self._get_public_form_settings()

        # Honeypot: silently ignore spam submissions.
        if (kwargs.get("website") or "").strip():
            return request.redirect("/church/registro?submitted=1")

        # Simple rate limit per session.
        now = int(time.time())
        last_submit = request.session.get(self._rate_limit_key())
        if last_submit and (now - last_submit) < settings["rate_limit_seconds"]:
            return self._render_public_form(
                form=form_values,
                error=_("Por favor espera un momento antes de volver a enviar el formulario."),
            )

        access_password = (kwargs.get("access_password") or "").strip()
        if settings["access_password"] and access_password != settings["access_password"]:
            return self._render_public_form(
                form=form_values,
                error=_("La clave de acceso es incorrecta."),
            )
        verified_at = int(request.session.get(self._access_verified_at_key()) or 0)
        access_valid = bool(request.session.get(self._access_verified_key()))
        access_not_expired = verified_at and (int(time.time()) - verified_at) <= self._access_verify_ttl_seconds()
        if not access_valid or not access_not_expired:
            request.session[self._access_verified_key()] = False
            request.session[self._access_verified_at_key()] = 0
            return self._render_public_form(
                form=form_values,
                error=_("Primero valida la clave de acceso para continuar."),
            )

        first_name = (kwargs.get("first_name") or "").strip()
        last_name = (kwargs.get("last_name") or "").strip()
        if not first_name or not last_name:
            return self._render_public_form(
                form=form_values,
                error=_("Nombre y Apellido son obligatorios."),
            )

        identification_type_id = self._to_int_or_false(kwargs.get("l10n_latam_identification_type_id"))
        vat = (kwargs.get("vat") or "").strip()
        if not identification_type_id or not vat:
            return self._render_public_form(
                form=form_values,
                error=_("Tipo de identificacion y numero de documento son obligatorios."),
            )
        required_map = {
            "gender": _("Sexo"),
            "birth_date": _("Fecha de nacimiento"),
            "predio_id": _("Predio"),
            "discipulado_id": _("Discipulado"),
            "celula_id": _("Celula"),
            "current_position": _("Cargo actual"),
        }
        missing_labels = []
        for key, label in required_map.items():
            raw_val = kwargs.get(key)
            if key.endswith("_id"):
                if not self._to_int_or_false(raw_val):
                    missing_labels.append(label)
            elif not (raw_val or "").strip():
                missing_labels.append(label)
        if missing_labels:
            return self._render_public_form(
                form=form_values,
                error=_("Faltan campos obligatorios: %s") % ", ".join(missing_labels),
            )
        existing = self._find_existing_document(identification_type_id, vat)
        if existing:
            return self._render_public_form(
                form=form_values,
                error=_("Ya existe el documento de identidad registrado. El formulario no sera guardado."),
            )
        peru_country = request.env["res.country"].sudo().search([("code", "=", "PE")], limit=1)
        country_id = self._to_int_or_false(kwargs.get("country_id")) or (peru_country.id or False)

        image_file = False
        for uploaded in request.httprequest.files.getlist("image_1920"):
            if uploaded and uploaded.filename:
                image_file = uploaded
                break
        image_1920 = False
        if image_file and image_file.filename:
            if not (image_file.mimetype or "").startswith("image/"):
                return self._render_public_form(
                    form=form_values,
                    error=_("El archivo de imagen no es valido."),
                )
            try:
                image_bytes = image_file.read()
                processed = image_process(
                    image_bytes,
                    size=(1024, 1024),
                    verify_resolution=True,
                    quality=75,
                )
                image_1920 = base64.b64encode(processed) if processed else False
            except Exception:
                return self._render_public_form(
                    form=form_values,
                    error=_("No se pudo procesar la imagen. Usa una imagen valida."),
                )

        member_vals = {
            "first_name": first_name,
            "last_name": last_name,
            "l10n_latam_identification_type_id": identification_type_id,
            "vat": vat,
            "email": (kwargs.get("email") or "").strip().lower() or False,
            "mobile": (kwargs.get("mobile") or "").strip() or False,
            "gender": (kwargs.get("gender") or "").strip() or False,
            "birth_date": (kwargs.get("birth_date") or "").strip() or False,
            "street": (kwargs.get("street") or "").strip() or False,
            "city": (kwargs.get("city") or "").strip() or False,
            "district": (kwargs.get("district") or "").strip() or False,
            "state_id": self._to_int_or_false(kwargs.get("state_id")),
            "zip": (kwargs.get("zip") or "").strip() or False,
            "country_id": country_id,
            "predio_id": self._to_int_or_false(kwargs.get("predio_id")),
            "red_id": self._to_int_or_false(kwargs.get("red_id")),
            "discipulado_id": self._to_int_or_false(kwargs.get("discipulado_id")),
            "celula_id": self._to_int_or_false(kwargs.get("celula_id")),
            "current_position": (kwargs.get("current_position") or "").strip() or "miembro",
            "baptism_date": (kwargs.get("baptism_date") or "").strip() or False,
            "spiritual_encounter_date": (kwargs.get("spiritual_encounter_date") or "").strip() or False,
            "marital_status": (kwargs.get("marital_status") or "").strip() or False,
            "is_member": True,
            "member_status": "active",
            "membership_date": fields.Date.today(),
            "image_1920": image_1920,
        }

        try:
            request.env["church.member"].sudo().with_context(skip_scope_check=True).create(member_vals)
        except (ValidationError, UserError) as exc:
            return self._render_public_form(form=form_values, error=str(exc))

        request.session[self._rate_limit_key()] = now
        request.session[self._access_verified_key()] = False
        request.session[self._access_verified_at_key()] = 0
        return request.redirect("/church/registro?submitted=1")

    @http.route(
        ["/church/lista/registro"],
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        csrf=True,
    )
    def church_member_list_form(self, **kwargs):
        request.session[self._list_access_verified_key()] = False
        request.session[self._list_access_verified_at_key()] = 0
        return self._render_public_member_list_form(form=kwargs, success=kwargs.get("submitted") == "1")

    @http.route(
        ["/church/lista/registro/validate_access"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_list_form_validate_access(self, **kwargs):
        settings = self._get_public_form_settings()
        access_password = (kwargs.get("access_password") or "").strip()
        if settings["access_password"] and access_password != settings["access_password"]:
            request.session[self._list_access_verified_key()] = False
            request.session[self._list_access_verified_at_key()] = 0
            return request.make_json_response(
                {
                    "ok": False,
                    "message": "La clave no es correcta. El formulario no sera guardado.",
                }
            )
        request.session[self._list_access_verified_key()] = True
        request.session[self._list_access_verified_at_key()] = int(time.time())
        return request.make_json_response({"ok": True})

    @http.route(
        ["/church/lista/registro/search_members"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_list_search_members(self, **kwargs):
        member_list = self._get_online_member_list_by_id(kwargs.get("list_id"))
        if not member_list:
            return request.make_json_response(
                {"ok": False, "message": "Selecciona una lista válida."}
            )
        return request.make_json_response(
            {
                "ok": True,
                "members": self._search_eligible_members_for_list(member_list, kwargs.get("query")),
            }
        )

    @http.route(
        ["/church/lista/registro/submit"],
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def church_member_list_form_submit(self, **kwargs):
        form_values = dict(kwargs)
        settings = self._get_public_form_settings()

        if (kwargs.get("website") or "").strip():
            return request.redirect("/church/lista/registro?submitted=1")

        now = int(time.time())
        last_submit = request.session.get(self._list_rate_limit_key())
        if last_submit and (now - last_submit) < settings["rate_limit_seconds"]:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("Por favor espera un momento antes de volver a enviar el formulario."),
            )

        access_password = (kwargs.get("access_password") or "").strip()
        if settings["access_password"] and access_password != settings["access_password"]:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("La clave de acceso es incorrecta."),
            )
        verified_at = int(request.session.get(self._list_access_verified_at_key()) or 0)
        access_valid = bool(request.session.get(self._list_access_verified_key()))
        access_not_expired = verified_at and (int(time.time()) - verified_at) <= self._access_verify_ttl_seconds()
        if not access_valid or not access_not_expired:
            request.session[self._list_access_verified_key()] = False
            request.session[self._list_access_verified_at_key()] = 0
            return self._render_public_member_list_form(
                form=form_values,
                error=_("Primero valida la clave de acceso para continuar."),
            )

        list_id = self._to_int_or_false(kwargs.get("list_id"))
        member_id = self._to_int_or_false(kwargs.get("member_id"))
        if not list_id or not member_id:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("Lista y Miembro son obligatorios."),
            )

        member_list = self._get_online_member_list_by_id(list_id)
        if not member_list:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("La lista seleccionada no está habilitada para registro online."),
            )

        member = request.env["church.member"].sudo().browse(member_id).exists()
        if not member:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("El miembro seleccionado no existe."),
            )

        eligibility_domain = list(member_list._website_member_domain()) + [("id", "=", member.id)]
        if not request.env["church.member"].sudo().search_count(eligibility_domain):
            return self._render_public_member_list_form(
                form=form_values,
                error=_("El miembro no cumple las condiciones de la lista seleccionada."),
            )

        existing_line = request.env["iem.church.member.list.line"].sudo().search(
            [("list_id", "=", member_list.id), ("member_id", "=", member.id)],
            limit=1,
        )
        if existing_line:
            return self._render_public_member_list_form(
                form=form_values,
                error=_("El miembro ya fue agregado a esta lista."),
            )

        extra_vals = {}
        if member_list.show_boolean_extra:
            raw_boolean = (kwargs.get("extra_boolean") or "").strip().lower()
            if raw_boolean not in {"true", "false"}:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El campo %s es obligatorio.") % (member_list.boolean_extra_label or _("Si/No")),
                )
            extra_vals["extra_boolean"] = raw_boolean == "true"
        if member_list.show_amount_extra:
            raw_amount = (kwargs.get("extra_amount") or "").strip()
            if not raw_amount:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El campo %s es obligatorio.") % (member_list.amount_extra_label or _("Monto")),
                )
            try:
                extra_vals["extra_amount"] = float(raw_amount)
            except ValueError:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El campo %s debe ser numérico.") % (member_list.amount_extra_label or _("Monto")),
                )
        if member_list.show_text_extra:
            raw_text = (kwargs.get("extra_text") or "").strip()
            if not raw_text:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El campo %s es obligatorio.") % (member_list.text_extra_label or _("Notas")),
                )
            extra_vals["extra_text"] = raw_text
        if member_list.show_image_extra:
            image_file = False
            for uploaded in request.httprequest.files.getlist("extra_image"):
                if uploaded and uploaded.filename:
                    image_file = uploaded
                    break
            if not image_file:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El campo Imagen es obligatorio."),
                )
            if not (image_file.mimetype or "").startswith("image/"):
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("El archivo de imagen no es válido."),
                )
            try:
                image_bytes = image_file.read()
                processed = image_process(
                    image_bytes,
                    size=(1024, 1024),
                    verify_resolution=True,
                    quality=75,
                )
                extra_vals["extra_image"] = base64.b64encode(processed) if processed else False
            except Exception:
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("No se pudo procesar la imagen. Usa una imagen válida."),
                )
            if not extra_vals.get("extra_image"):
                return self._render_public_member_list_form(
                    form=form_values,
                    error=_("No se pudo procesar la imagen. Usa una imagen válida."),
                )

        vals = {
            "list_id": member_list.id,
            "member_id": member.id,
            "source": "manual",
            **extra_vals,
        }
        try:
            request.env["iem.church.member.list.line"].sudo().create(vals)
        except (ValidationError, UserError) as exc:
            return self._render_public_member_list_form(form=form_values, error=str(exc))

        request.session[self._list_rate_limit_key()] = now
        request.session[self._list_access_verified_key()] = False
        request.session[self._list_access_verified_at_key()] = 0
        return request.redirect("/church/lista/registro?submitted=1")
