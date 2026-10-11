"""Read-only page validation using the same parser and writer as conversion."""
from pathlib import Path
import pikepdf

from .native import drawing_report, make_private
from .vector import ConversionError, read_drawing


def inspect_document(source, pages=None, raster_dpi=300):
    source = Path(source)
    results = []
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted:
            raise ConversionError('Encrypted PDFs are unsupported')
        selected = list(pages) if pages is not None else list(range(1, len(pdf.pages)+1))
        if not selected or any(type(p) is not int or not 1 <= p <= len(pdf.pages) for p in selected):
            raise ConversionError('Invalid page selection')
        for number in selected:
            try:
                drawing = read_drawing(pdf.pages[number-1], root=pdf.Root)
                make_private(drawing, source.name)
                result = drawing_report(drawing, source, '', number-1, 'vector', None, raster_dpi, False, 0)
                result['native_supported'] = True
            except (ConversionError, pikepdf.PdfError, NotImplementedError) as error:
                result = {'input':str(source), 'page':number, 'native_supported':False,
                          'first_blocker':str(error), 'planned_mode':'raster-fallback',
                          'lost_features':['editable paths/text', 'spot ink separation', 'layer structure']}
            result['inspection_only'] = True
            result['all_blockers_enumerated'] = False
            results.append(result)
    return results
