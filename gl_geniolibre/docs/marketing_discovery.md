# Inteligencia de Marketing: recopilación automática (fase inicial)

## Alcance

- **YouTube Data API v3**: búsqueda de videos cortos (menos de 4 minutos) según tema, país, fechas y, opcionalmente, un ID de canal conocido. Se guardan datos públicos como título, canal, fecha, duración y métricas disponibles. La búsqueda no demuestra que sean Shorts ni videos virales.
- **Google Trends**: lectura del RSS público exportado por la función "Trending now"; filtra títulos usando palabras clave del nicho. Un RSS sin coincidencias puede devolver cero resultados.
- **Odoo**: las evidencias se insertan en `gl.marketing.reference`, mantienen enlaces y origen, se deduplican, y se incorporan al flujo de análisis ya existente. El informe debe aprobarse antes de alimentar `gl.contenido.flujo`.
- **No incluido**: acceso directo a Instagram, TikTok, reels protegidos, transcripciones, análisis visual de videos, búsquedas automáticas de cuentas de competidores o métricas privadas. Esas integraciones quedan para futuras fases según permisos oficiales.

## Configuración en Odoo 18

1. Instalar/actualizar `gl_geniolibre` sobre una base de pruebas; reiniciar el servidor para cargar los modelos Python.
2. En **Ajustes → GenioLibre → Inteligencia de Marketing**, configurar la clave de **YouTube Data API v3** desde Google Cloud; habilitar allí la API y configurar restricciones apropiadas de la clave. La clave no debe guardarse en Git.
3. En **Proyectos → Inteligencia de Marketing**, abrir una investigación en estado **Recopilando** y establecer fuentes, país (PE, US, CR...), tema del sector y máximo por fuente (1–20). Para un competidor de YouTube, ingresar su **ID del canal**, con formato UC..., si se conoce.
4. Para RSS de Google Trends, configurar **Palabras clave de tendencias** separadas por comas. El filtro se aplica a títulos de tendencias actuales: no a todas las consultas que aparecen en Google Trends.
5. Pulsar **Investigar automáticamente**. Comprobar los nuevos registros y sus fuentes, después pulsar **Analizar con IA**, o utilizar el prompt manual, y **Aprobar investigación**.
6. Elegir la investigación aprobada en el **Creador de Contenido**, para incluir el informe en el prompt de publicaciones.

## Ejecución semanal optativa

- El cron **GL Inteligencia de Marketing: recopilar referencias semanalmente** se instala **desactivado**.
- Para habilitarlo: activar manualmente el cron en Ajustes → Técnico → Automatización → Acciones planificadas.
- Marcar **Investigación semanal automática** solo en los informes que deban consultarse regularmente.
- Solo se ejecuta para investigaciones en estado **Recopilando**, nunca sobre un informe aprobado o en análisis.
- El cron procesa como máximo 10 investigaciones por ejecución y omite las actualizadas en los últimos seis días.
- Las solicitudes externas consumen la cuota correspondiente a cada API; ajustar el número de investigaciones y las credenciales según las cuotas del proyecto.
- No ejecuta generación ni aprobación de informes automáticamente.

## Reglas de evidencia

- Las estadísticas son una captura de la API en el momento de la consulta; no demuestran crecimiento, retención o conversiones.
- Las observaciones manuales no se sobrescriben.
- Los registros automáticos se actualizan por ID de fuente; los informes aprobados no se modifican automáticamente.
- La URL de una referencia no implica acceso al video, sus imágenes ni su transcripción.
- Ante error de API o RSS, se muestra error sin exponer el valor de la clave API.
