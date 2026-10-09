"""Appearance-preserving page rendering for unsupported native PDF features."""
import math
import pymupdf
from PIL import Image
from .vector import Drawing, Raster, State, ConversionError


def render_drawing(source, page_index, dpi=300):
    if not math.isfinite(dpi) or not 72 <= dpi <= 1200:
        raise ConversionError('Raster DPI must be between 72 and 1200')
    with pymupdf.open(source) as document:
        page = document[page_index]
        rect = page.rect
        width,height = rect.width,rect.height
        if not all(math.isfinite(v) and 0<v<=16000 for v in (width,height)):
            raise ConversionError('Page size exceeds the supported Illustrator canvas')
        estimate = math.ceil(width*dpi/72)*math.ceil(height*dpi/72)
        if estimate>40_000_000:
            raise ConversionError('Raster fallback exceeds 40 million pixels; lower --raster-dpi')
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(dpi/72,dpi/72),colorspace=pymupdf.csRGB,alpha=True,annots=True)
        # MuPDF delivers premultiplied RGBA. Native Illustrator XI requires
        # separate, unassociated color and alpha planes.
        image = Image.frombytes('RGBa',(pixmap.width,pixmap.height),pixmap.samples).convert('RGBA')
        rgb = image.convert('RGB').tobytes()
        alpha = image.getchannel('A').tobytes()
        if image.getchannel('A').getextrema() == (255,255): alpha=None
        raster = Raster(pixmap.width,pixmap.height,'RGB',rgb,alpha,State(matrix=(width,0,0,height,0,0)))
        return Drawing((0,0,width,height),[],[],{},[raster],[raster],'RGB')
