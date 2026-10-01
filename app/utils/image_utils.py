"""Validate and orient image bytes without writing them to disk."""

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.models.image_models import DownloadedImage, ImageInputError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Bound decoded memory too: a small compressed PNG can contain huge pixel data.
MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png"}


def validate_image(data: bytes, mime_type: str) -> DownloadedImage:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageInputError("image_invalid")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ImageInputError("image_invalid")
                if SUPPORTED_IMAGE_TYPES.get(image_format) != mime_type:
                    raise ImageInputError("image_invalid")
                image.verify()
            with Image.open(BytesIO(data)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ImageInputError("image_invalid")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Re-encode to remove EXIF/GPS and other metadata before vision.
                clean = Image.new(oriented.mode, oriented.size)
                clean.paste(oriented)
                if clean.mode not in ("RGB", "RGBA", "L"):
                    clean = oriented.convert("RGB")
                    clean.info.clear()
                output = BytesIO()
                clean.save(output, format=image_format)
                normalized = output.getvalue()
                if len(normalized) > MAX_IMAGE_BYTES:
                    raise ImageInputError("image_invalid")
                return DownloadedImage(normalized, mime_type)
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ImageInputError("image_invalid") from None
