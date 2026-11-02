# Prueba integral: Inteligencia de Marketing (fases 1–3)

## Entrega

La investigación funciona en tres niveles:

1. **Fase 1:** reunir referencias, producir informe en modo manual o por API de OpenAI, validar citas por ID y aprobarlo para el Creador de Contenido.
2. **Fase 2:** descubrir referencias en YouTube Data API v3 o Google Trends RSS por tema y país, sin descargar medios ni consultar cuentas privadas. El cron semanal inicia desactivado.
3. **Fase 3:** analizar individualmente referencias de videos y competidores usando transcripciones **aportadas** o notas visuales **aportadas**, identificar hooks/estructura/CTA y generar comparación documental. Los análisis vigentes alimentan el informe estratégico de la fase 1.

### Limitaciones expresas

- Solo la recopilación de **metadatos públicos** de YouTube/Trends es automática. No hay descarga, subtítulos automáticos, extracción de fotogramas, análisis visual remoto, conexión a Instagram/TikTok, ni cálculo confiable de viralidad.
- Las transcripciones y notas visuales deben aportarse mediante fuentes autorizadas. No se afirma haber visto un video solo porque se recibió su URL.
- `interacciones / visualizaciones` se muestra como cociente descriptivo, **no** como tasa de engagement comparable entre plataformas.
- Los resultados de IA son propuestas para revisión humana. No se publican automáticamente.
- Una investigación aprobada sigue requiriendo revisión si cambian referencias o material usado.

## Instalación en desarrollo

1. Actualizar `main` en el checkout del proyecto y reiniciar Odoo.
2. Actualizar el módulo `gl_geniolibre` en una **base de pruebas** para registrar los nuevos campos, vistas y pruebas.
3. En Ajustes de GenioLibre, agregar la clave de YouTube Data API v3. Para probar Trends no es necesaria.
4. Dejar el cron semanal desactivado hasta verificar las consultas y cuotas.

Ejemplo de prueba por CLI, **ajustar ruta, addons-path, archivo de configuración y base** a tu instalación:

```bash
./odoo-bin -c /ruta/odoo.conf -d BASE_PRUEBAS -u gl_geniolibre --test-enable --test-tags /gl_geniolibre --stop-after-init
```

Las pruebas de `gl_geniolibre/tests` se etiquetan para ejecutarse después de instalar o actualizar el módulo. No se han ejecutado contra el servidor de GenioLibre desde GitHub.

## Recorrido manual completo

### A. Recopilación de referencias (fase 2)

- Crear una investigación con cliente, sector y país.
- Seleccionar `Google Trends`, definir palabras del nicho y pulsar **Investigar automáticamente**. Verificar que cada registro contenga URL, fecha, origen y observación; cero coincidencias también es un resultado válido.
- Configurar YouTube Data API v3 si está disponible. Seleccionar `YouTube`, escribir tema o ID de canal y recopilar. Revisar el origen y las visualizaciones; **ningún video debe clasificarse automáticamente como viral**.
- Repetir la búsqueda para comprobar deduplicación. Las observaciones manuales no deben sobrescribirse.

### B. Análisis de video y competidores (fase 3)

- Abrir una referencia existente. En la pestaña **Material del video**, incluir una transcripción facilitada por el equipo o la fuente autorizada y, si la hay, una descripción de recursos visuales observados.
- Si **Conexión directa con IA está desactivada**, pulsar **Preparar prompt**, copiarlo, pegar en ChatGPT la respuesta JSON y pulsar **Aplicar análisis JSON**.
- Si la conexión está activada y configurada, pulsar **Analizar referencia con IA**. Comprobar que los campos de hook, estructura, CTA, formato, oportunidad y limitaciones **no inventen escenas ni datos**.
- Usar **Comparar referencias** con al menos dos competidores/videos y revisar la comparación. El resultado es descriptivo, no un ranking.
- Cambiar las notas o transcripción de una referencia para verificar que el análisis y la comparación queden marcados como **desactualizados**.

### C. Informe y uso en la parrilla (fase 1)

- Desde la investigación, generar **Analizar con IA** o seguir el modo manual. Comprobar que el informe utilice solo referencias existentes, cite sus IDs y contemple los análisis estructurales vigentes.
- Aprobar la investigación y elegirla desde el **Creador de Contenido**.
- Verificar que el prompt de la parrilla incluya `investigacion_marketing` y que los posts y reels propuestos respeten el plan y el tono del cliente.
- Cambiar una referencia tras la aprobación. El Creador de Contenido debe **bloquear el uso del informe desactualizado** hasta reabrir, volver a analizar y aprobar.
- Confirmar que los botones existentes del modo manual/directo, refinamiento y tareas de publicación siguen funcionando.

## Pruebas automatizadas incluidas

- JSON completo y validación de estructura.
- Propagación del análisis de referencia al prompt general.
- Comparación y detección de desactualización.
- Rechazo de modificaciones de análisis tras aprobación.
- Invalidación de informe aprobado cuando cambia material de referencia.
- Filtrado de tendencias RSS por palabra clave y deduplicación por identificador externo.

## No activar sin probar

No habilitar tareas programadas ni configurar producción hasta completar el recorrido en una base de pruebas y revisar los logs de Odoo.
