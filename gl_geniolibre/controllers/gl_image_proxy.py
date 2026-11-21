# -*- coding: utf-8 -*-

import logging
import subprocess
from urllib.parse import urlparse

import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)
ALLOWED_IMAGE_HOSTS = ("tiktokcdn.com", "tiktokcdn-us.com")
MAX_PROXY_IMAGE_BYTES = 10 * 1024 * 1024
FFMPEG_TIMEOUT_SECONDS = 10


class GLImageProxyController(http.Controller):

    @http.route('/gl_geniolibre/tiktok/image_proxy', type='http', auth='public', website=False, csrf=False)
    def tiktok_image_proxy(self, url=None, **kwargs):
        if not url:
            return request.not_found()

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(
            hostname == allowed_host or hostname.endswith(f".{allowed_host}")
            for allowed_host in ALLOWED_IMAGE_HOSTS
        ):
            _logger.warning("Se rechazó image proxy TikTok para host no permitido: %s", hostname)
            return request.not_found()

        response = None
        try:
            response = requests.get(
                url,
                timeout=20,
                stream=True,
                allow_redirects=False,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://www.tiktok.com/",
                },
            )
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                _logger.warning("Contenido no visual rechazado por proxy TikTok: %s", content_type)
                return request.not_found()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_PROXY_IMAGE_BYTES:
                _logger.warning("Imagen TikTok demasiado grande para proxy: %s bytes", content_length)
                return request.not_found()

            chunks = []
            total_size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                total_size += len(chunk)
                if total_size > MAX_PROXY_IMAGE_BYTES:
                    _logger.warning("Imagen TikTok excede el límite del proxy: %s bytes", total_size)
                    return request.not_found()
                chunks.append(chunk)
            content = b"".join(chunks)
        except requests.exceptions.RequestException as exc:
            _logger.warning("No se pudo descargar imagen TikTok para proxy: %s", exc)
            return request.not_found()
        except (TypeError, ValueError):
            _logger.warning("Content-Length inválido en imagen TikTok para proxy")
            return request.not_found()
        finally:
            if response is not None:
                response.close()

        content_type = response.headers.get("Content-Type", "application/octet-stream")

        if "webp" in content_type.lower() or ".webp" in url.lower():
            try:
                process = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        "pipe:0",
                        "-frames:v",
                        "1",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "mjpeg",
                        "pipe:1",
                    ],
                    input=content,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=FFMPEG_TIMEOUT_SECONDS,
                )
                jpeg_bytes = process.stdout
                headers = [
                    ("Content-Type", "image/jpeg"),
                    ("Cache-Control", "public, max-age=86400"),
                ]
                return request.make_response(jpeg_bytes, headers=headers)
            except (OSError, subprocess.SubprocessError) as exc:
                _logger.info(
                    "No se pudo convertir WEBP de TikTok a JPEG con ffmpeg: %s | content-type=%s | first-bytes=%r",
                    exc,
                    content_type,
                    content[:24],
                )

        headers = [
            ("Content-Type", content_type),
            ("Cache-Control", "public, max-age=86400"),
        ]
        return request.make_response(content, headers=headers)
