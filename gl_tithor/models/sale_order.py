import base64, os, openpyxl, tempfile, unicodedata
from io import BytesIO
from markupsafe import Markup, escape

from odoo import fields, models, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class Camiseta_Registro(models.Model):
    _name = 'camiseta.registro'
    _description = 'Registro de camisetas para jugadores'

    nombre_en_camiseta = fields.Char(string='Nombre en Camiseta')
    numero = fields.Char(string='Número')
    notas = fields.Text(string='Notas')
    diseno = fields.Char(string='Diseño')

    tipo = fields.Selection([
        ('camiseta_short', 'Camiseta + Short'),
        ('camiseta', 'Camiseta'),
        ('solo_short', 'Solo Short'),
        ('bividi', 'Bividi')
    ], string='Tipo', default='camiseta_short', required=True)

    talla_camiseta = fields.Selection([
        ('2', '2'),
        ('4', '4'),
        ('6', '6'),
        ('8', '8'),
        ('10', '10'),
        ('12', '12'),
        ('14', '14'),
        ('16', '16'),
        ('xs', 'XS'),
        ('s', 'S'),
        ('m', 'M'),
        ('l', 'L'),
        ('xl', 'XL'),
        ('2xl', '2XL'),
        ('3xl', '3XL'),
    ], string='Talla Camiseta')

    modelo = fields.Selection([
        ('ranglan', 'Ranglan'),
        ('clasico', 'Clásico'),
    ], string='Modelo')

    talla_short = fields.Selection([
        ('2', '2'),
        ('4', '4'),
        ('6', '6'),
        ('8', '8'),
        ('10', '10'),
        ('12', '12'),
        ('14', '14'),
        ('16', '16'),
        ('xs', 'XS'),
        ('s', 'S'),
        ('m', 'M'),
        ('l', 'L'),
        ('xl', 'XL'),
        ('2xl', '2XL'),
        ('3xl', '3XL'),
    ], string='Talla Short', default='m')

    corte = fields.Selection([
        ('varon', 'Varón'),
        ('dama', 'Dama')
    ], string='Corte')

    manga = fields.Selection([
        ('normal', 'Normal'),
        ('larga', 'Larga'),
        ('manga_cero', 'Manga Cero'),
        ('bividi', 'Bividi')
    ], string='Manga')

    cuello = fields.Selection([
        ('v', 'V'),
        ('redondo', 'Redondo'),
    ], string='Cuello')

    tipo_short = fields.Selection([
        ('varon', 'Varón'),
        ('mujer', 'Mujer'),
        ('basket', 'Basket'),
        ('falda_short', 'Falda Short'),
    ], string='Tipo Short')

    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta', ondelete='cascade', readonly=True)


class SaleOrder(models.Model):
    """Inherits the model sale.order"""
    _inherit = 'sale.order'

    is_image_true = fields.Boolean(string="Is Show Image True", help="Mostrar imagen en la línea de pedido de venta", compute="_compute_is_image_true")
    camiseta_registro_ids = fields.One2many('camiseta.registro', 'sale_order_id', string='Detalles')
    excel_headers = fields.Json(string='Encabezados del Excel', copy=True)
    excel_rows = fields.Json(string='Contenido del Excel', copy=True)
    excel_sheet_name = fields.Char(string='Hoja importada', copy=True)
    excel_imported_filename = fields.Char(string='Archivo importado', copy=True)
    excel_preview_html = fields.Html(
        string='Contenido importado',
        compute='_compute_excel_preview_html',
        sanitize=False,
    )
    camiseta_foto_ids = fields.Many2many(
        'ir.attachment',
        string="Mockup Camiseta",
        domain="[('mimetype', 'ilike', 'image/')]",
    )
    archivo_excel = fields.Binary("Archivo Excel", attachment=True)
    archivo_nombre = fields.Char("Nombre del archivo")
    confection_order_id = fields.Many2one(
        'gl.confection.order',
        string='Confección',
        compute='_compute_confection_order_id',
    )

    def _compute_confection_order_id(self):
        confection_by_sale = {
            confection.sale_order_id.id: confection
            for confection in self.env['gl.confection.order'].search([('sale_order_id', 'in', self.ids)])
        }
        for order in self:
            order.confection_order_id = confection_by_sale.get(order.id)

    def action_send_to_confection(self):
        self.ensure_one()
        confection = self.confection_order_id or self.env['gl.confection.order'].create({'sale_order_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confección',
            'res_model': 'gl.confection.order',
            'view_mode': 'form',
            'res_id': confection.id,
            'target': 'current',
        }

    @api.constrains('camiseta_foto_ids')
    def _check_camiseta_foto_is_image(self):
        for rec in self:
            for attachment in rec.camiseta_foto_ids:
                mimetype = (attachment.mimetype or '').lower()
                if not mimetype.startswith('image/'):
                    raise ValidationError("Los mockups deben ser imágenes (JPG, PNG, etc.).")

    def _compute_is_image_true(self):
        """Method _compute_is_image_true returns True if the Show Image option
        in the sale configuration is true"""
        for rec in self:
            rec.is_image_true = True if rec.env[
                'ir.config_parameter'].sudo().get_param('sale_product_image.is_show_product_image_in_sale_report') else False

    @api.depends('excel_headers', 'excel_rows')
    def _compute_excel_preview_html(self):
        for order in self:
            headers = order.excel_headers or []
            rows = order.excel_rows or []
            if not headers:
                order.excel_preview_html = False
                continue
            head = ''.join('<th>%s</th>' % escape(header) for header in headers)
            body = ''.join(
                '<tr>%s</tr>' % ''.join('<td>%s</td>' % escape(value or '') for value in row)
                for row in rows
            )
            order.excel_preview_html = Markup(
                '<div class="table-responsive"><table class="table table-sm table-bordered">'
                '<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)
            )

    def importar_excel(self):
        """Importa de forma genérica cualquier tabla de la primera hoja con contenido."""
        self.ensure_one()
        if not self.archivo_excel:
            raise ValidationError("Por favor, cargue un archivo Excel (.xlsx).")

        try:
            workbook = openpyxl.load_workbook(
                BytesIO(base64.b64decode(self.archivo_excel)),
                data_only=True,
                read_only=True,
            )
            sheet = next(
                (candidate for candidate in workbook.worksheets if candidate.max_row and candidate.max_column),
                workbook.active,
            )
            raw_rows = list(sheet.iter_rows(values_only=True))
            nonempty_rows = [row for row in raw_rows if any(value not in (None, '') for value in row)]
            if not nonempty_rows:
                raise ValidationError("El archivo Excel no contiene información.")

            last_column = max(
                index
                for row in nonempty_rows
                for index, value in enumerate(row)
                if value not in (None, '')
            ) + 1

            def display_value(value):
                if value in (None, ''):
                    return ''
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                if hasattr(value, 'strftime'):
                    return value.strftime('%d/%m/%Y %H:%M:%S' if hasattr(value, 'hour') else '%d/%m/%Y')
                return str(value)

            first_row = nonempty_rows[0][:last_column]
            headers = [
                display_value(value).strip() or 'Columna %s' % (index + 1)
                for index, value in enumerate(first_row)
            ]
            rows = [
                [display_value(value) for value in row[:last_column]]
                for row in nonempty_rows[1:]
            ]
            self.write({
                'excel_headers': headers,
                'excel_rows': rows,
                'excel_sheet_name': sheet.title,
                'excel_imported_filename': self.archivo_nombre or sheet.title,
                'archivo_excel': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'gl_tithor_delayed_reload',
                'params': {
                    'title': 'Importación completada',
                    'message': '%s filas y %s columnas importadas desde %s.' % (
                        len(rows), len(headers), sheet.title),
                    'type': 'success',
                    'delay': 3000,
                },
            }
        except ValidationError:
            raise
        except Exception as error:
            _logger.exception("Error al importar el Excel")
            raise ValidationError("Error al procesar el archivo: %s" % error)

    def action_clear_imported_excel(self):
        self.ensure_one()
        self.write({
            'excel_headers': False,
            'excel_rows': False,
            'excel_sheet_name': False,
            'excel_imported_filename': False,
            'archivo_excel': False,
            'archivo_nombre': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'gl_tithor_delayed_reload',
            'params': {
                'title': 'Contenido eliminado',
                'message': 'El archivo importado y su contenido fueron eliminados.',
                'type': 'success',
                'delay': 3000,
            },
        }

    def _importar_excel_v03(self):
        """Importa el formato Tithor V03 usando los nombres de las columnas."""
        self.ensure_one()
        if not self.archivo_excel:
            raise ValidationError("Por favor, cargue un archivo Excel (.xlsx).")

        def normalize(value):
            text = str(value or '').strip().lower()
            return ''.join(
                char for char in unicodedata.normalize('NFD', text)
                if unicodedata.category(char) != 'Mn'
            ).replace(' ', '_')

        def normalize_size(value):
            if value in (None, ''):
                return False
            if isinstance(value, (int, float)):
                value = str(int(value))
            value = normalize(value)
            valid_sizes = {'2', '4', '6', '8', '10', '12', '14', '16', 'xs', 's', 'm', 'l', 'xl', '2xl', '3xl'}
            return value if value in valid_sizes else False

        try:
            workbook = openpyxl.load_workbook(
                BytesIO(base64.b64decode(self.archivo_excel)),
                data_only=True,
                read_only=True,
            )
            sheet = workbook['Detalle de Camisetas'] if 'Detalle de Camisetas' in workbook.sheetnames else workbook.active
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows, None)
            if not headers:
                raise ValidationError("El archivo Excel está vacío.")

            columns = {normalize(header): index for index, header in enumerate(headers) if header}
            required_headers = {'prenda', 'nombre', 'numero', 'talla_camiseta', 'modelo', 'corte', 'manga', 'cuello', 'tipo_short', 'talla_short'}
            missing = sorted(required_headers - set(columns))
            if missing:
                raise ValidationError("Faltan columnas en el Excel: %s" % ', '.join(missing))

            selection_values = {
                'tipo': {'camiseta', 'camiseta_short', 'solo_short', 'bividi'},
                'modelo': {'ranglan', 'clasico'},
                'corte': {'varon', 'dama'},
                'manga': {'normal', 'larga', 'manga_cero', 'bividi'},
                'cuello': {'v', 'redondo'},
                'tipo_short': {'varon', 'mujer', 'basket', 'falda_short'},
            }
            aliases = {
                'camiseta_+_short': 'camiseta_short',
                'camiseta+short': 'camiseta_short',
                'solo_short': 'solo_short',
                'clasico': 'clasico',
                'raglan': 'ranglan',
                'hombre': 'varon',
                'dama': 'dama',
                'mujer': 'mujer',
                'manga_cero': 'manga_cero',
                'falda_short': 'falda_short',
            }
            records = []
            omitted = 0

            for row_number, row in enumerate(rows, start=2):
                def value(column):
                    index = columns.get(column)
                    return row[index] if index is not None and index < len(row) else None

                raw_type = normalize(value('prenda'))
                if not raw_type:
                    omitted += 1
                    continue
                item_type = aliases.get(raw_type, raw_type)
                if item_type not in selection_values['tipo']:
                    raise ValidationError("Fila %s: Prenda '%s' no es válida." % (row_number, value('prenda')))

                vals = {
                    'sale_order_id': self.id,
                    'diseno': str(value('diseno')).strip() if value('diseno') else False,
                    'tipo': item_type,
                    'nombre_en_camiseta': str(value('nombre')).strip() if value('nombre') else False,
                    'numero': str(int(value('numero'))) if isinstance(value('numero'), (int, float)) else str(value('numero') or '').strip(),
                    'talla_camiseta': normalize_size(value('talla_camiseta')),
                    'talla_short': normalize_size(value('talla_short')),
                }
                for field_name, column_name in (
                    ('modelo', 'modelo'), ('corte', 'corte'), ('manga', 'manga'),
                    ('cuello', 'cuello'), ('tipo_short', 'tipo_short'),
                ):
                    normalized = aliases.get(normalize(value(column_name)), normalize(value(column_name)))
                    vals[field_name] = normalized if normalized in selection_values[field_name] else False

                if item_type != 'solo_short' and not vals['talla_camiseta']:
                    raise ValidationError("Fila %s: Talla Camiseta no es válida." % row_number)
                if item_type in ('camiseta_short', 'solo_short') and not vals['talla_short']:
                    raise ValidationError("Fila %s: Talla Short no es válida." % row_number)
                records.append(vals)

            if not records:
                raise ValidationError("El archivo Excel no contiene filas válidas.")

            size_order = {size: index for index, size in enumerate(
                ('2', '4', '6', '8', '10', '12', '14', '16', 'xs', 's', 'm', 'l', 'xl', '2xl', '3xl')
            )}
            records.sort(key=lambda vals: (
                size_order.get(vals['talla_camiseta'] or vals['talla_short'], 999),
                size_order.get(vals['talla_short'], 999),
            ))
            self.env['camiseta.registro'].create(records)
            self.archivo_excel = False
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Importación completada',
                    'message': '%s prendas importadas. %s filas omitidas.' % (len(records), omitted),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except ValidationError:
            raise
        except Exception as error:
            _logger.exception("Error al importar el Excel V03")
            raise ValidationError("Error al procesar el archivo: %s" % error)

    def _importar_excel_legacy(self):
        """Importa un archivo Excel con los registros de camisetas, validando y creando cada línea."""
        if not self.archivo_excel:
            raise ValidationError("Por favor, cargue un archivo Excel (.xlsx).")

        tmp_path = None
        try:
            _logger.info("Iniciando proceso de importación de Excel...")

            # --- 1) Guardar temporalmente el archivo Excel decodificado ---
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(base64.b64decode(self.archivo_excel))
                tmp_path = tmp.name

            _logger.info(f"Archivo Excel guardado temporalmente en: {tmp_path}")

            # --- 2) Cargar workbook de forma segura ---
            libro = openpyxl.load_workbook(tmp_path, data_only=True, read_only=True)
            hoja = libro.active
            _logger.info(f"Hoja activa: {hoja.title} | Filas: {hoja.max_row}")

            registros = []
            registros_omitidos = 0

            # Mapa de orden para tallas
            orden_tallas = {
                '2': 0,
                '4': 1,
                '6': 2,
                '8': 3,
                '10': 4,
                '12': 5,
                '14': 6,
                '16': 7,
                'xs': 8,
                's': 9,
                'm': 10,
                'l': 11,
                'xl': 12,
                '2xl': 13,
                '3xl': 14
            }

            # --- 3) Iterar filas (evitar bloqueo en archivos grandes) ---
            for idx, fila in enumerate(hoja.iter_rows(min_row=2), start=2):
                if idx % 200 == 0:
                    _logger.info(f"Procesando fila {idx}...")

                valores = [celda.value for celda in fila]

                # Validaciones de campos mínimos
                if (len(valores) < 8 or not valores[2] or not valores[4] or not valores[6] or not valores[7]):
                    registros_omitidos += 1
                    continue

                nombre = valores[1] or None
                tipo = valores[2]
                numero = valores[3] if valores[3] is not None else ""
                talla_camiseta = valores[4]
                talla_short = valores[5]
                corte = valores[6]
                manga = valores[7]
                notas = valores[8] if len(valores) > 8 and valores[8] is not None else False

                # Normalizar tallas
                def normalizar_talla(talla):
                    if talla is not None and talla != "":
                        if isinstance(talla, (int, float)):
                            talla = str(int(talla))
                        else:
                            talla = str(talla).strip().lower()
                        if talla.isdigit() or talla in orden_tallas:
                            return talla
                    return None

                talla_camiseta = normalizar_talla(talla_camiseta)
                talla_short = normalizar_talla(talla_short)

                if not talla_camiseta:
                    registros_omitidos += 1
                    continue

                # Normalizar campo manga
                if isinstance(manga, str):
                    manga = manga.strip().lower()
                    if manga == "manga_cero":
                        manga = "manga_cero"
                if not manga:
                    manga = "Sin información"

                registros.append({
                    'nombre_en_camiseta': nombre,
                    'numero': numero,
                    'notas': str(notas).strip() if notas else False,
                    'tipo': tipo,
                    'talla_camiseta': talla_camiseta,
                    'talla_short': talla_short or False,
                    'corte': corte,
                    'manga': manga,
                })

            # --- 4) Ordenar resultados ---
            registros_ordenados = sorted(registros, key=lambda r: (orden_tallas.get(
                r['talla_camiseta'], 999), orden_tallas.get(r['talla_short'], 999)))

            if not registros_ordenados:
                raise ValidationError("El archivo Excel no contiene filas válidas.")

            # --- 5) Crear registros en lote ---
            _logger.info(f"Creando {len(registros_ordenados)} registros de camisetas...")
            camiseta_model = self.env['camiseta.registro']
            for r in registros_ordenados:
                camiseta_model.create({
                                          **r,
                                          'sale_order_id': self.id
                                      })

            _logger.info("Importación completada exitosamente.")
            self.archivo_excel = False

            # --- 6) Mensaje visual al usuario ---
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Importación completada',
                    'message': (f"{len(registros_ordenados)} camisetas importadas correctamente. "
                                f"{registros_omitidos} filas omitidas por estar incompletas."),
                    'type': 'success',
                    'sticky': False,
                },
            }

        except Exception as e:
            _logger.exception("Error inesperado al importar Excel")
            raise ValidationError(f"Error al procesar el archivo: {str(e)}")

        finally:
            # --- 7) Limpieza del archivo temporal ---
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    _logger.info(f"Archivo temporal eliminado: {tmp_path}")
                except Exception as e:
                    _logger.warning(f"No se pudo eliminar el archivo temporal: {tmp_path}. Error: {e}")
