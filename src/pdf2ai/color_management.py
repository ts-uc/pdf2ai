"""Explicit color conversion for editable artwork; source PDF stays untouched."""
from io import BytesIO
from functools import lru_cache

from PIL import Image
import pymupdf

from .vector import ConversionError


def cmyk_to_rgb(pixels, width, height):
    """Use the same default CMYK interpretation as our PDF proof renderer."""
    source = pymupdf.Pixmap(pymupdf.csCMYK, width, height, pixels, False)
    return pymupdf.Pixmap(pymupdf.csRGB, source).samples


@lru_cache(maxsize=32)
def icc_transform(model, profile, intent):
    try:
        from PIL import ImageCms
    except ImportError as error:
        raise ConversionError('ICC conversion requires Pillow with LittleCMS support') from error
    try:
        source = ImageCms.ImageCmsProfile(BytesIO(profile))
        actual = source.profile.xcolor_space.strip()
        if actual != {'RGB':'RGB','CMYK':'CMYK','Gray':'GRAY'}[model]:
            raise ConversionError('ICC profile channel model does not match PDF /N')
        transform = ImageCms.buildTransformFromOpenProfiles(source, ImageCms.createProfile('sRGB'),
                                                            {'RGB':'RGB','CMYK':'CMYK','Gray':'L'}[model], 'RGB', renderingIntent=intent,
                                                            flags=0x2000)  # LCMS black point compensation.
        return transform
    except ConversionError:
        raise
    except (OSError, ValueError, ImageCms.PyCMSError) as error:
        raise ConversionError(f'Unable to convert ICC color space: {error}') from error


def icc_to_rgb(pixels, width, height, model, profile, intent=1):
    transform = icc_transform(model,profile,intent)
    from PIL import ImageCms
    image = Image.frombytes({'RGB':'RGB','CMYK':'CMYK','Gray':'L'}[model], (width,height), pixels)
    return ImageCms.applyTransform(image, transform).tobytes()
