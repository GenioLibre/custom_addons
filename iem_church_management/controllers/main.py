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
            response = requests.post(
                "https://api.json.pe/api/dni",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"dni": vat},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return request.make_json_response(
                {"ok": False, "message": f"Error consultando API DNI: {exc}"}
            )

        data = payload.get("data") or {}
        names = (data.get("nombres") or "").strip()
        ap_pat = (data.get("apellido_paterno") or "").strip()
        ap_mat = (data.get("apellido_materno") or "").strip()
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
        settings = self._get_public_form_settings()

        # Honeypot: silently ignore spam submissions.
        if (kwargs.get("website") or "").strip():
            return request.redirect("/church/registro?submitted=1")

        # Simple rate limit per session.
        now = int(time.time())
        last_submit = request.session.get(self._rate_limit_key())
        if last_submit and (now - last_submit) < settings["rate_limit_seconds"]:
            return self._render_public_form(
                form=kwargs,
                error=_("Por favor espera un momento antes de volver a enviar el formulario."),
            )

        access_password = (kwargs.get("access_password") or "").strip()
        if settings["access_password"] and access_password != settings["access_password"]:
            return self._render_public_form(
                form=kwargs,
                error=_("La clave de acceso es incorrecta."),
            )
        verified_at = int(request.session.get(self._access_verified_at_key()) or 0)
        access_valid = bool(request.session.get(self._access_verified_key()))
        access_not_expired = verified_at and (int(time.time()) - verified_at) <= self._access_verify_ttl_seconds()
        if not access_valid or not access_not_expired:
            request.session[self._access_verified_key()] = False
            request.session[self._access_verified_at_key()] = 0
            return self._render_public_form(
                form=kwargs,
                error=_("Primero valida la clave de acceso para continuar."),
            )

        first_name = (kwargs.get("first_name") or "").strip()
        last_name = (kwargs.get("last_name") or "").strip()
        if not first_name or not last_name:
            return self._render_public_form(
                form=kwargs,
                error=_("Nombre y Apellido son obligatorios."),
            )

        identification_type_id = self._to_int_or_false(kwargs.get("l10n_latam_identification_type_id"))
        vat = (kwargs.get("vat") or "").strip()
        if not identification_type_id or not vat:
            return self._render_public_form(
                form=kwargs,
                error=_("Tipo de identificacion y numero de documento son obligatorios."),
            )
        existing = self._find_existing_document(identification_type_id, vat)
        if existing:
            return self._render_public_form(
                form=kwargs,
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
                    form=kwargs,
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
                    form=kwargs,
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
            "maps_url": (kwargs.get("maps_url") or "").strip() or False,
            "city": (kwargs.get("city") or "").strip() or False,
            "district": (kwargs.get("district") or "").strip() or False,
            "state_id": self._to_int_or_false(kwargs.get("state_id")),
            "zip": (kwargs.get("zip") or "").strip() or False,
            "country_id": country_id,
            "predio_id": self._to_int_or_false(kwargs.get("predio_id")),
            "red_id": self._to_int_or_false(kwargs.get("red_id")),
            "discipulado_id": self._to_int_or_false(kwargs.get("discipulado_id")),
            "celula_id": self._to_int_or_false(kwargs.get("celula_id")),
            "is_member": True,
            "member_status": "active",
            "current_position": "participante",
            "membership_date": fields.Date.today(),
            "image_1920": image_1920,
        }

        try:
            request.env["church.member"].sudo().with_context(skip_scope_check=True).create(member_vals)
        except (ValidationError, UserError) as exc:
            return self._render_public_form(form=kwargs, error=str(exc))

        request.session[self._rate_limit_key()] = now
        request.session[self._access_verified_key()] = False
        request.session[self._access_verified_at_key()] = 0
        return request.redirect("/church/registro?submitted=1")
