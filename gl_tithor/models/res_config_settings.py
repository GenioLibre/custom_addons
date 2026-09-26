from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    """Inherits the model res.config.settings to add the field"""
    _inherit = 'res.config.settings'

    is_show_product_image_in_sale_report = fields.Boolean(
        string="Mostrar imagen del producto",
        config_parameter='sale_product_image.is_show_product_image_in_sale_report',
        help='Mostrar producto en el reporte de cotización')

    confection_users = fields.Many2many('res.users', string='Usuarios de confección', domain=[('share', '=', False)], relation='gl_tithor_confection_user_rel')
    confection_admin_users = fields.Many2many('res.users', string='Administradores de confección', domain=[('share', '=', False)], relation='gl_tithor_confection_admin_rel')

    @api.model
    def get_values(self):
        values = super().get_values()
        values.update(confection_users=[(6, 0, self.env.ref('gl_tithor.group_confection_user').users.ids)], confection_admin_users=[(6, 0, self.env.ref('gl_tithor.group_confection_admin').users.ids)])
        return values

    def set_values(self):
        super().set_values()
        self.env.ref('gl_tithor.group_confection_user').users = [(6, 0, self.confection_users.ids)]
        self.env.ref('gl_tithor.group_confection_admin').users = [(6, 0, self.confection_admin_users.ids)]
