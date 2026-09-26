from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    gl_confection_user = fields.Boolean(string="Usuario", compute="_compute_gl_confection_access", inverse="_inverse_gl_confection_user")
    gl_confection_admin = fields.Boolean(string="Administrador", compute="_compute_gl_confection_access", inverse="_inverse_gl_confection_admin")

    def _compute_gl_confection_access(self):
        user_group = self.env.ref("gl_tithor.group_confection_user")
        admin_group = self.env.ref("gl_tithor.group_confection_admin")
        for record in self:
            record.gl_confection_user = user_group in record.groups_id
            record.gl_confection_admin = admin_group in record.groups_id

    def _inverse_gl_confection_user(self):
        group = self.env.ref("gl_tithor.group_confection_user")
        for record in self:
            record.groups_id = [(4, group.id)] if record.gl_confection_user else [(3, group.id)]

    def _inverse_gl_confection_admin(self):
        group = self.env.ref("gl_tithor.group_confection_admin")
        for record in self:
            record.groups_id = [(4, group.id)] if record.gl_confection_admin else [(3, group.id)]
