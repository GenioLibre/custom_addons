# -*- coding: utf-8 -*-

from xml.etree import ElementTree as ET

from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


class GlWebRoadmapGenerateWizard(models.TransientModel):
    _name = 'gl.web.roadmap.generate.wizard'
    _description = 'Confirmar generación de Hoja de Ruta Web'

    project_id = fields.Many2one('project.project', string='Proyecto', required=True, readonly=True)
    warning_message = fields.Text(
        string='Advertencia',
        readonly=True,
        default='Se eliminarán todas las tareas y la hoja de ruta anterior antes de generar una nueva.'
    )

    def action_confirm_generate(self):
        self.ensure_one()
        self.project_id.action_regenerate_web_roadmap()
        return {'type': 'ir.actions.act_window_close'}


class GlProjectWebType(models.Model):
    _name = 'gl.project.web.type'
    _description = 'Tipo de Web'

    name = fields.Char(string='Nombre', required=True)
    active = fields.Boolean(default=True)
    xml_template = fields.Text(string='Plantilla XML', required=True)

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'El nombre del tipo de web debe ser único.'),
    ]

    @api.constrains('xml_template')
    def _check_xml_template(self):
        for record in self:
            record._parse_xml_template()

    def _parse_xml_template(self):
        self.ensure_one()

        xml_content = (self.xml_template or '').strip()
        if not xml_content:
            raise ValidationError('La plantilla XML es obligatoria.')

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as error:
            raise ValidationError(f'El XML no es válido: {error}')

        if root.tag != 'checklist_web':
            raise ValidationError('La etiqueta raíz debe ser <checklist_web>.')

        stages = []
        for stage_node in root.findall('etapa'):
            stage_name = (stage_node.attrib.get('nombre') or '').strip()
            if not stage_name:
                raise ValidationError('Cada <etapa> debe tener el atributo nombre.')

            tasks = []
            for task_node in stage_node.findall('tarea'):
                task_name = (task_node.attrib.get('nombre') or '').strip()
                if not task_name:
                    raise ValidationError('Cada <tarea> debe tener el atributo nombre.')

                items = []
                for item_node in task_node.findall('item'):
                    item_text = (item_node.text or '').strip()
                    if item_text:
                        items.append(item_text)

                tasks.append({
                    'name': task_name,
                    'items': items,
                })

            if not tasks:
                raise ValidationError(f'La etapa "{stage_name}" debe tener al menos una <tarea>.')

            stages.append({
                'name': stage_name,
                'tasks': tasks,
            })

        if not stages:
            raise ValidationError('La plantilla XML debe incluir al menos una <etapa>.')

        return stages


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    gl_is_web_roadmap_generated = fields.Boolean(string='Generada por Hoja de Ruta Web', default=False, copy=False)
    gl_roadmap_project_id = fields.Many2one('project.project', string='Proyecto Hoja de Ruta Web', copy=False)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    gl_is_web_roadmap_generated = fields.Boolean(string='Generada por Hoja de Ruta Web', default=False, copy=False)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    web_type_id = fields.Many2one('gl.project.web.type', string='Tipo de Web')
    web_roadmap_generated = fields.Boolean(string='Hoja de Ruta Generada', default=False, copy=False, readonly=True)

    def action_generate_web_roadmap(self):
        self.ensure_one()
        if self.project_type != 'web':
            raise ValidationError('Solo se puede generar la hoja de ruta en proyectos de tipo Web.')
        if not self.web_type_id:
            raise ValidationError('Selecciona un Tipo de Web para generar la hoja de ruta.')

        wizard = self.env['gl.web.roadmap.generate.wizard'].create({
            'project_id': self.id,
        })
        return {
            'name': 'Confirmar generación',
            'type': 'ir.actions.act_window',
            'res_model': 'gl.web.roadmap.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def action_regenerate_web_roadmap(self):
        for project in self:
            project._action_delete_web_roadmap_single()
            project._action_generate_web_roadmap_single()
        return True

    def _action_generate_web_roadmap_single(self):
        self.ensure_one()

        if self.project_type != 'web':
            raise ValidationError('Solo se puede generar la hoja de ruta en proyectos de tipo Web.')

        if not self.web_type_id:
            raise ValidationError('Selecciona un Tipo de Web para generar la hoja de ruta.')

        Stage = self.env['project.task.type'].sudo()
        Task = self.env['project.task'].with_context(
            default_user_ids=False,
            default_personal_stage_type_ids=False,
            default_personal_stage_type_id=False,
        ).sudo()

        stage_data_list = self.web_type_id._parse_xml_template()
        for sequence, stage_data in enumerate(stage_data_list, start=1):
            stage = Stage.create({
                'name': stage_data['name'],
                'sequence': sequence * 10,
                'project_ids': [Command.link(self.id)],
                'gl_is_web_roadmap_generated': True,
                'gl_roadmap_project_id': self.id,
            })

            for task_data in stage_data['tasks']:
                parent_task = Task.create({
                    'name': task_data['name'],
                    'project_id': self.id,
                    'stage_id': stage.id,
                    'partner_id': self.partner_id.id or False,
                    'user_ids': [Command.clear()],
                    'gl_is_web_roadmap_generated': True,
                })

                for item_name in task_data['items']:
                    Task.create({
                        'name': item_name,
                        'project_id': self.id,
                        'parent_id': parent_task.id,
                        'stage_id': stage.id,
                        'partner_id': self.partner_id.id or False,
                        'user_ids': [Command.clear()],
                        'gl_is_web_roadmap_generated': True,
                    })

        self.web_roadmap_generated = True

    def action_delete_web_roadmap(self):
        for project in self:
            project._action_delete_web_roadmap_single()
        return True

    def _action_delete_web_roadmap_single(self):
        self.ensure_one()
        if self.project_type != 'web':
            raise ValidationError('Solo se puede eliminar la hoja de ruta en proyectos de tipo Web.')

        all_project_tasks = self.env['project.task'].sudo().search([
            ('project_id', '=', self.id),
        ])
        stages = self.env['project.task.type'].sudo().search([
            ('gl_roadmap_project_id', '=', self.id),
            ('gl_is_web_roadmap_generated', '=', True),
        ])

        all_project_tasks.unlink()
        stages.unlink()
        self.type_ids = [Command.clear()]
        self.web_roadmap_generated = False
