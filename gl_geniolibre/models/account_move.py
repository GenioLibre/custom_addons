# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountMove(models.Model):
    """ Inheriting account move model to add id of subscription """
    _inherit = 'account.move'

    contract_origin = fields.Integer(string='Subscription Contract',
                                     help='Reference of Subscription Contract')
