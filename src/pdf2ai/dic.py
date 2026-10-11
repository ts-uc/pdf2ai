"""DIC名が一致する特色に、旧版カラーブックのCMYK代替値を設定する。"""
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def _colors():
    return json.loads(files('pdf2ai').joinpath('data/dic_cmyk.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _aliases():
    candidates = {}
    for name in _colors():
        base = name.rstrip('*').removesuffix('s')
        candidates.setdefault(base, []).append(name)
    # Use only unambiguous entries; exact book names always take precedence.
    return {base: names[0] for base,names in candidates.items() if len(names)==1}


def dic_name(name):
    """末尾のs・*を省略したDIC名を、登録済みの正式名に解決する。"""
    if name in _colors():
        return name
    return _aliases().get(name.rstrip('*').removesuffix('s'))


def dic_color(name):
    return _colors().get(dic_name(name))


def normalize_pdf_spots(page):
    """Keep the PDF view and editable DIC spots on the same CMYK book values.

    Validate tint definitions before replacing them. Malformed or unsupported
    definitions remain for the ordinary parser to reject rather than hiding them.
    """
    import pikepdf
    from .vector import ConversionError, read_spot
    seen = set()
    changed = set()

    def resources(value):
        if not isinstance(value, pikepdf.Dictionary):
            return
        if value.objgen != (0, 0):
            if value.objgen in seen:
                return
            seen.add(value.objgen)
        spaces = value.get('/ColorSpace', pikepdf.Dictionary())
        if not isinstance(spaces, pikepdf.Dictionary):
            spaces = pikepdf.Dictionary()
        for space in spaces.values():
            if not isinstance(space, pikepdf.Array) or len(space) != 4 or str(space[0]) != '/Separation':
                continue
            name = str(space[1])[1:]
            reference = dic_color(name)
            if reference is None:
                continue
            try:
                read_spot(space)
            except (ConversionError, pikepdf.PdfError, NotImplementedError, ValueError, TypeError, IndexError, AttributeError):
                continue
            canonical = dic_name(name)
            space[1] = pikepdf.Name('/'+canonical)
            space[2] = pikepdf.Name.DeviceCMYK
            space[3] = pikepdf.Dictionary(FunctionType=2, Domain=[0, 1],
                                          C0=[0, 0, 0, 0], C1=reference['cmyk'], N=1,
                                          Range=[0, 1]*4)
            changed.add(canonical)
        objects = value.get('/XObject', pikepdf.Dictionary())
        if not isinstance(objects, pikepdf.Dictionary):
            return
        for obj in objects.values():
            if not isinstance(obj, pikepdf.Stream):
                continue
            if str(obj.get('/Subtype')) == '/Form':
                if obj.objgen in seen:
                    continue
                seen.add(obj.objgen)
                resources(obj.get('/Resources'))

    resources(page.obj.get('/Resources'))
    return sorted(changed)
