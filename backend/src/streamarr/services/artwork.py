"""Image transform/encode helpers extracted from the media router.

Pure PIL-backed transform utilities with no request/router state, kept out of
the large ``api/v1/media.py`` so that module carries endpoints rather than
image-processing plumbing. ``image_format`` is a plain format string (e.g.
``"jpg"``, ``"webp"``) to avoid a circular import back into the router.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import HTTPException


def pil_format_for_image_format(image_format: str | None, storage_path: Path) -> str:
    if image_format is None:
        image_format = (
            "jpg"
            if storage_path.suffix.lower() in {".jpg", ".jpeg"}
            else storage_path.suffix.lower().lstrip(".")
        )
    if image_format == "jpg":
        image_format = "jpeg"
    return image_format.upper()


def pil_format_for_content_type(image_format: str | None, content_type: str) -> str:
    if image_format is None:
        image_format = {
            "image/jpeg": "jpeg",
            "image/png": "png",
            "image/webp": "webp",
            "image/avif": "avif",
        }.get(content_type, "png")
    if image_format == "jpg":
        image_format = "jpeg"
    return image_format.upper()


def image_media_type_for_pil_format(output_format: str) -> str:
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "AVIF": "image/avif",
    }.get(output_format, "application/octet-stream")


def apply_image_transform(
    image,
    *,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    fill_width: int | None,
    fill_height: int | None,
):
    from PIL import Image, ImageOps

    if fill_width or fill_height:
        if not fill_width or not fill_height:
            raise HTTPException(
                status_code=400,
                detail="Both fill_width and fill_height are required for fill transforms",
            )
        return ImageOps.fit(image, (fill_width, fill_height), method=Image.Resampling.LANCZOS)
    if width or height:
        target_width = width or round(image.width * (height / image.height))
        target_height = height or round(image.height * (width / image.width))
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    if max_width or max_height:
        image.thumbnail(
            (
                max_width or image.width,
                max_height or image.height,
            ),
            Image.Resampling.LANCZOS,
        )
    return image


def serialize_transformed_image(image, output_format: str, quality: int | None) -> bytes:
    if output_format == "JPEG" and image.mode in {"RGBA", "LA"}:
        from PIL import Image

        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background

    output = BytesIO()
    save_kwargs = {}
    if output_format in {"JPEG", "WEBP", "AVIF"}:
        save_kwargs["quality"] = quality or 85
    image.save(output, format=output_format, **save_kwargs)
    return output.getvalue()


def transform_image_bytes(
    image_bytes: bytes,
    *,
    content_type: str,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    quality: int | None,
    image_format: str | None,
    fill_width: int | None,
    fill_height: int | None,
) -> tuple[bytes, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Image transform backend is not installed",
        )

    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    except UnidentifiedImageError:
        raise HTTPException(status_code=415, detail="Image is not transformable")

    image = apply_image_transform(
        image,
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        fill_width=fill_width,
        fill_height=fill_height,
    )
    output_format = pil_format_for_content_type(image_format, content_type)
    return (
        serialize_transformed_image(image, output_format, quality),
        image_media_type_for_pil_format(output_format),
    )
