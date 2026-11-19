import base64
import io

from PIL import Image, ImageOps


def optimize_image_for_api(image_path, max_edge=1024):
    with Image.open(image_path) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="JPEG", quality=85, optimize=True)
    return base64.b64encode(image_buffer.getvalue()).decode("ascii")
