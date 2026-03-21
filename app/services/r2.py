"""
Cloudflare R2 service — wrapper sobre boto3 para multipart uploads y presigned URLs.

R2 es compatible con la API S3 de AWS, por eso usamos boto3 directamente.
Docs R2: https://developers.cloudflare.com/r2/api/s3/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from app.config import Settings, get_settings
from app.logger import get_logger

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = get_logger(__name__)


def get_r2_client(settings: Settings | None = None) -> Any:
    """Crea y devuelve un cliente boto3 apuntando al endpoint de R2."""
    s = settings or get_settings()
    if not s.r2_endpoint or not s.r2_access_key_id or not s.r2_secret_access_key:
        logger.warning("R2 settings incompletos (endpoint/access_key/secret)")
    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint,
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


# ── Multipart upload ──────────────────────────────────────────────────────────


def create_multipart_upload(key: str, content_type: str) -> str:
    """Inicia un multipart upload en R2 y devuelve el UploadId."""
    client = get_r2_client()
    settings = get_settings()
    response = client.create_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        ContentType=content_type,
    )
    upload_id: str = response["UploadId"]
    logger.debug("Multipart upload creado: key=%s uploadId=%s", key, upload_id)
    return upload_id


def generate_presigned_part_url(key: str, upload_id: str, part_number: int) -> str:
    """
    Genera una presigned URL para hacer PUT de una parte de un multipart upload.
    Válida por 2 horas (suficiente para subir un chunk desde mobile).
    """
    client = get_r2_client()
    settings = get_settings()
    url: str = client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=7200,
    )
    return url


def generate_presigned_put_url(key: str, content_type: str | None = None, expires_in: int = 7200) -> str:
    """
    Genera una presigned URL para PUT directo de un objeto (chunk completo).
    Válida por defecto 2 horas.
    """
    client = get_r2_client()
    settings = get_settings()
    params: dict[str, Any] = {"Bucket": settings.r2_bucket_name, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    url: str = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return url


def complete_multipart_upload(key: str, upload_id: str, parts: list[dict]) -> str:
    """
    Completa el multipart upload ensamblando todas las partes en el objeto final.

    parts: lista de {"PartNumber": int, "ETag": str} ordenada por PartNumber.
    Devuelve la URL pública del objeto resultante.
    """
    client = get_r2_client()
    settings = get_settings()
    client.complete_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    final_url = f"{settings.r2_endpoint}/{settings.r2_bucket_name}/{key}"
    logger.info("Multipart upload completado: %s", final_url)
    return final_url


def abort_multipart_upload(key: str, upload_id: str) -> None:
    """
    Aborta un multipart upload incompleto y libera el storage reservado.
    Siempre llamar esto si la sesión se cancela para no acumular partes huérfanas.
    """
    client = get_r2_client()
    settings = get_settings()
    client.abort_multipart_upload(
        Bucket=settings.r2_bucket_name,
        Key=key,
        UploadId=upload_id,
    )
    logger.info("Multipart upload abortado: key=%s uploadId=%s", key, upload_id)


def generate_presigned_get_url(key: str, expires_in: int = 3600) -> str:
    """Genera una presigned URL para GET (descarga) de un objeto ya subido."""
    client = get_r2_client()
    settings = get_settings()
    url: str = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )
    return url
