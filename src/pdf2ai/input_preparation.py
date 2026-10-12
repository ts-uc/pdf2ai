"""Prepare authenticated or explicitly flattened input without changing the original."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import tempfile

import pikepdf

from .path_conflicts import paths_conflict
from .vector import ConversionError


@contextmanager
def prepared_source(source, *, password=None, flatten_annotations=False):
    source = Path(source)
    if password is None and not flatten_annotations:
        yield source
        return
    with pikepdf.open(source, password=password or '') as pdf:
        encrypted = pdf.is_encrypted
    if not encrypted and not flatten_annotations:
        yield source
        return
    with tempfile.TemporaryDirectory(prefix='pdf2ai-input-') as directory:
        prepared = Path(directory)/source.name
        if flatten_annotations:
            import pymupdf
            with pymupdf.open(source) as document:
                if document.needs_pass and not document.authenticate(password or ''):
                    raise ConversionError('PDF password authentication failed')
                if not hasattr(document,'bake'):
                    raise ConversionError('Annotation flattening requires a newer PyMuPDF installation')
                document.bake(annots=True, widgets=True)
                document.save(prepared, encryption=pymupdf.PDF_ENCRYPT_NONE)
        else:
            with pikepdf.open(source, password=password or '') as pdf:
                pdf.save(prepared, encryption=False)
        yield prepared


def prepare_input(function):
    has_output = function.__code__.co_varnames[1] == 'output'
    @wraps(function)
    def wrapped(source, *args, password=None, flatten_annotations=False, **kwargs):
        original = Path(source)
        output = (args[0] if args else kwargs.get('output')) if has_output else None
        if output is not None and paths_conflict(original, Path(output)):
            raise ConversionError('Input and output must differ')
        with prepared_source(original, password=password,
                             flatten_annotations=flatten_annotations) as prepared:
            result = function(prepared, *args, **kwargs)
        for row in result if isinstance(result,list) else [result]:
            row['input'] = str(original)
            if flatten_annotations:
                row.setdefault('warnings',[]).append(
                    'Annotation and form appearances flattened; comments and interactive behavior are not retained')
        return result
    return wrapped
