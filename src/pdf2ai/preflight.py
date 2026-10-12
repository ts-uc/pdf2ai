"""Read-only page validation using the same parser and writer as conversion."""
from pathlib import Path
import math
import pikepdf

from .native import drawing_report, make_private
from .vector import ConversionError, read_drawing
from .input_preparation import prepare_input


@prepare_input
def inspect_document(source, pages=None, raster_dpi=300, *, progress=None):
    if not math.isfinite(raster_dpi) or not 72 <= raster_dpi <= 1200:
        raise ConversionError('Raster DPI must be between 72 and 1200')
    source = Path(source)
    results = []
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted:
            raise ConversionError('Encrypted PDFs are unsupported')
        selected = list(pages) if pages is not None else list(range(1, len(pdf.pages)+1))
        if not selected or any(type(p) is not int or not 1 <= p <= len(pdf.pages) for p in selected) or len(set(selected)) != len(selected):
            raise ConversionError('Invalid page selection')
        for index, number in enumerate(selected):
            try:
                drawing = read_drawing(pdf.pages[number-1], root=pdf.Root)
                make_private(drawing, source.name)
                result = drawing_report(drawing, source, '', number-1, 'vector', None, raster_dpi, False, 0)
                result['native_supported'] = True
                result['planned_mode'] = 'vector'
            except (ConversionError, pikepdf.PdfError, NotImplementedError) as error:
                result = {'input':str(source), 'page':number, 'native_supported':False,
                          'first_blocker':str(error), 'planned_mode':'raster-fallback',
                          'lost_features':['editable paths/text', 'spot ink separation', 'layer structure']}
            result['inspection_only'] = True
            result['all_blockers_enumerated'] = False
            results.append(result)
            if progress is not None: progress(number,index+1,len(selected))
    return results


@prepare_input
def inspect_combination(source, pages=None, raster_dpi=300, *, raster_fallback=True,
                        page_labels=None, progress=None):
    """Validate packing, final color model and serialization without publishing AI."""
    from .multiboard import convert_document
    try:
        return convert_document(source, None, pages=pages, page_labels=page_labels,
            raster_dpi=raster_dpi, raster_fallback=raster_fallback,
            progress=progress, inspection_only=True)
    except ConversionError as error:
        results = inspect_document(source, pages, raster_dpi)
        for index, item in enumerate(results):
            if page_labels is not None: item['page'] = page_labels[index]
            item.update(combined_constraints_checked=True, combined_blocker=str(error))
        return results
