import logging
from functools import lru_cache

from django.conf import settings
from supabase import Client, create_client


logger = logging.getLogger(__name__)


class SupabaseStorageError(Exception):
    """Error controlado al operar con Supabase Storage."""


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    if not settings.SUPABASE_URL:
        raise SupabaseStorageError(
            "SUPABASE_URL no está configurado."
        )

    if not settings.SUPABASE_SECRET_KEY:
        raise SupabaseStorageError(
            "SUPABASE_SECRET_KEY no está configurado."
        )

    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SECRET_KEY,
    )


def upload_file(
    *,
    path: str,
    content: bytes,
    content_type: str,
) -> str:
    client = get_supabase_client()

    try:
        client.storage.from_(
            settings.SUPABASE_STORAGE_BUCKET
        ).upload(
            path=path,
            file=content,
            file_options={
                "content-type": content_type,
                "cache-control": "3600",
                "upsert": "false",
            },
        )
    except Exception as exc:
        logger.exception(
            "Error subiendo archivo a Supabase. "
            "Bucket=%s path=%s",
            settings.SUPABASE_STORAGE_BUCKET,
            path,
        )

        raise SupabaseStorageError(
            "No fue posible guardar la imagen en Supabase."
        ) from exc

    return path


def delete_file(path: str) -> None:
    if not path:
        return

    client = get_supabase_client()

    try:
        client.storage.from_(
            settings.SUPABASE_STORAGE_BUCKET
        ).remove([path])
    except Exception:
        logger.exception(
            "No se pudo eliminar el archivo de Supabase. "
            "Path=%s",
            path,
        )


def get_public_url(path: str) -> str | None:
    if not path:
        return None

    client = get_supabase_client()

    response = client.storage.from_(
        settings.SUPABASE_STORAGE_BUCKET
    ).get_public_url(path)

    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        return (
            response.get("publicUrl")
            or response.get("public_url")
        )

    return str(response)