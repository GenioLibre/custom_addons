from odoo import fields, models

class ResUsers(models.Model):
    _inherit = "res.users"

    gl_task_user = fields.Boolean(string="Usuario", compute="_compute_gl_task_access", inverse="_inverse_gl_task_user")
    gl_task_admin = fields.Boolean(string="Administrador", compute="_compute_gl_task_access", inverse="_inverse_gl_task_admin")

    def _compute_gl_task_access(self):
        user_group = self.env.ref("gl_geniolibre.group_project_task_user")
        admin_group = self.env.ref("gl_geniolibre.group_project_task_admin")
        for record in self:
            record.gl_task_user = user_group in record.groups_id
            record.gl_task_admin = admin_group in record.groups_id

    def _inverse_gl_task_user(self):
        group = self.env.ref("gl_geniolibre.group_project_task_user")
        for record in self:
            record.groups_id = [(4, group.id)] if record.gl_task_user else [(3, group.id)]

    def _inverse_gl_task_admin(self):
        group = self.env.ref("gl_geniolibre.group_project_task_admin")
        for record in self:
            record.groups_id = [(4, group.id)] if record.gl_task_admin else [(3, group.id)]
