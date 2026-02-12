import base64, os, openpyxl, tempfile

from odoo import fields, models
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class Camiseta_Registro(models.Model):
    _name = 'camiseta.registro'
    _description = 'Registro de camisetas para jugadores'

    nombre_en_camiseta = fields.Char(string='Nombre en Camiseta')
    numero = fields.Char(string='Número')

    tipo = fields.Selection([
        ('camiseta_short', 'Camiseta + Short'),
        ('camiseta', 'Camiseta'),
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
    ], string='Talla Camiseta', required=True, default='m')

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
    ], string='Corte', required=True, default='varon')

    manga = fields.Selection([
        ('normal', 'Normal'),
        ('larga', 'Larga'),
        ('manga_cero', 'Manga Cero'),
        ('bividi', 'Bividi')
    ], string='Manga', required=True, default='normal')

    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta', ondelete='cascade', readonly=True)


class SaleOrder(models.Model):
    """Inherits the model sale.order"""
    _inherit = 'sale.order'

    is_image_true = fields.Boolean(string="Is Show Image True", help="Mostrar imagen en la línea de pedido de venta", compute="_compute_is_image_true")
    camiseta_registro_ids = fields.One2many('camiseta.registro', 'sale_order_id', string='Detalles de las camisetas')
    camiseta_foto = fields.Image(string="Foto Camiseta", max_width=1280, max_height=1280)
    archivo_excel = fields.Binary("Archivo Excel", attachment=True)
    archivo_nombre = fields.Char("Nombre del archivo")

    def _compute_is_image_true(self):
        """Method _compute_is_image_true returns True if the Show Image option
        in the sale configuration is true"""
        for rec in self:
            rec.is_image_true = True if rec.env[
                'ir.config_parameter'].sudo().get_param('sale_product_image.is_show_product_image_in_sale_report') else False


    def importar_excel(self):
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
