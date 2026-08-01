import uuid

from apps.common.services.supabase_storage import upload_file


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png"
}

MAX_IMAGE_SIZE = 50 * 1024 * 1024


class ProductImageValidationError(Exception):
    """Error de validación de imagen de producto."""


def validate_product_image(image) -> None:
    if image.size > MAX_IMAGE_SIZE:
        raise ProductImageValidationError(
            "La imagen no puede superar los 5 MB."
        )

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise ProductImageValidationError(
            "Solo se permiten imágenes JPG, PNG o WEBP."
        )


def upload_product_image(*, product_uuid, image) -> str:
    validate_product_image(image)

    extension = ALLOWED_IMAGE_TYPES[image.content_type]
    filename = f"{uuid.uuid4().hex}{extension}"

    path = f"products/{product_uuid}/{filename}"

    image.seek(0)

    return upload_file(
        path=path,
        content=image.read(),
        content_type=image.content_type,
    )