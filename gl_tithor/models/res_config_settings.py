from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    """Inherits the model res.config.settings to add the field"""
    _inherit = 'res.config.settings'

    is_show_product_image_in_sale_report = fields.Boolean(
        string="Mostrar imagen del producto",
        config_parameter='sale_product_image.is_show_product_image_in_sale_report',
        help='Mostrar producto en el reporte de cotización')

    @api.model
    def _cleanup_legacy_confection_security(self):
        legacy_xmlids = (
            'gl_tithor.view_users_tithor_access',
            'gl_tithor.access_gl_confection_order_user',
            'gl_tithor.access_gl_confection_order_admin',
            'gl_tithor.access_ir_attachment_confection_user',
            'gl_tithor.access_ir_attachment_confection_admin',
            'gl_tithor.access_ir_attachment_tithor_user',
            'gl_tithor.group_confection_admin',
            'gl_tithor.group_confection_user',
            'gl_tithor.module_category_tithor',
        )
        for xmlid in legacy_xmlids:
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if record:
                record.sudo().unlink()
        return True
