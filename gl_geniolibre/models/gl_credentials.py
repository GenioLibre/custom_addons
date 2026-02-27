# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import AccessError

class gl_credentials(models.Model):
    _name = "gl.credentials"
    _description = "Permite guardar credenciales de a los contactos"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char("Nombre del Servicio", tracking=True)
    usuario = fields.Char("Usuario", tracking=True)
    password = fields.Char("Contraseña", copy=False)
    show_password = fields.Boolean("Mostrar contraseña", default=False)
    link = fields.Char("Link de Acceso", tracking=True)
    asignado = fields.Boolean("Asignado", tracking=True)
    credenciales_id = fields.Many2one('res.partner', tracking=True)

    def action_reveal_password(self):
        self.ensure_one()
        self.show_password = True
        return True

    def action_hide_password(self):
        self.ensure_one()
        self.show_password = False
        return True

    @api.model
    def _mask_secret(self, value):
        if not value:
            return value
        return "*" * min(max(len(value), 8), 12)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        rows = super().search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        for row in rows:
            if 'password' in row and row['password']:
                row['password'] = self._mask_secret(row['password'])
        return rows

    def export_data(self, fields_to_export):
        if ('password' in fields_to_export) and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("No tiene permisos para exportar el campo contraseña."))
        return super().export_data(fields_to_export)

    def copy(self, default=None):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("No tiene permisos para duplicar credenciales."))
        return super().copy(default)
