from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    church_logo = fields.Binary(
        string="Logo de la iglesia",
    )
    dni_api_token = fields.Char(
        string="Token API DNI",
        config_parameter="iem.dni_api_token",
    )
    public_member_form_password = fields.Char(
        string="Clave formulario publico",
        config_parameter="iem.public_member_form_password",
    )
    public_member_form_rate_limit = fields.Integer(
        string="Limite de envios (segundos)",
        default=60,
        config_parameter="iem.public_member_form_rate_limit",
    )

    @property
    def _church_logo_attachment_name(self):
        return "iem_church_logo"

    @property
    def _church_logo_param_key(self):
        return "iem.church_logo_attachment_id"

    @property
    def _church_logo_filename_param_key(self):
        return "iem.church_logo_filename"

    @property
    def _church_logo_mimetype_param_key(self):
        return "iem.church_logo_mimetype"

    @property
    def _church_logo_default_filename(self):
        return "church_logo.png"

    @property
    def _church_logo_default_mimetype(self):
        return "image/png"

    @property
    def _church_logo_res_model(self):
        return "res.config.settings"

    def _get_church_logo_attachment(self):
        attachment_id = int(
            self.env["ir.config_parameter"].sudo().get_param(self._church_logo_param_key, 0) or 0
        )
        if not attachment_id:
            return self.env["ir.attachment"]
        return self.env["ir.attachment"].sudo().browse(attachment_id).exists()

    @api.model
    def get_values(self):
        res = super().get_values()
        attachment = self._get_church_logo_attachment()
        res.update(
            church_logo=attachment.datas if attachment else False,
        )
        return res

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        attachment_model = self.env["ir.attachment"].sudo()
        attachment = self._get_church_logo_attachment()

        if self.church_logo:
            vals = {
                "name": params.get_param(self._church_logo_filename_param_key, self._church_logo_default_filename),
                "type": "binary",
                "datas": self.church_logo,
                "mimetype": params.get_param(
                    self._church_logo_mimetype_param_key,
                    self._church_logo_default_mimetype,
                ),
                "res_model": self._church_logo_res_model,
                "public": False,
            }
            if attachment:
                attachment.write(vals)
            else:
                attachment = attachment_model.create(vals)
                params.set_param(self._church_logo_param_key, attachment.id)
                params.set_param(self._church_logo_filename_param_key, vals["name"])
                params.set_param(self._church_logo_mimetype_param_key, vals["mimetype"])
        elif attachment:
            attachment.unlink()
            params.set_param(self._church_logo_param_key, "")
