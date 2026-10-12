"""TOYO COLOR FINDERとTOYO 94の特色名を独立したLabデータへ照合する。"""
from functools import lru_cache
from importlib.resources import files
import json
import re


@lru_cache(maxsize=1)
def _colors():
    return json.loads(files('pdf2ai').joinpath('data/toyo_lab.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _aliases():
    candidates = {}
    for name in _colors():
        base = name.rstrip('*')
        aliases = {base}
        if re.fullmatch(r'CF \d{5}', base):
            number = base[3:]
            aliases.update({'CF'+number, 'TOYO CF '+number, 'TOYO CF'+number,
                            'TOYO '+number})
        elif re.fullmatch(r'TOYO \d{4}', base):
            aliases.add('TOYO '+str(int(base[5:])))
        for alias in aliases:
            candidates.setdefault(alias, set()).add(name)
    return {alias: next(iter(names)) for alias, names in candidates.items() if len(names) == 1}


def toyo_name(name):
    """正式名を優先し、星印の省略と番号の明確な別名だけを解決する。"""
    if name in _colors():
        return name
    return _aliases().get(name.rstrip('*'))


def toyo_color(name):
    return _colors().get(toyo_name(name))


def normalize_pdf_spots(page):
    """Align registered CMYK TOYO alternates with the editable Lab book color.

    Existing valid Lab values are retained. DIC is deliberately not handled here.
    """
    import pikepdf
    from .vector import ConversionError, read_spot
    seen, changed = set(), set()
    pending = [page.obj.get('/Resources')]
    while pending:
        resources = pending.pop()
        if not isinstance(resources,pikepdf.Dictionary): continue
        if resources.objgen != (0,0):
            if resources.objgen in seen: continue
            seen.add(resources.objgen)
        spaces = resources.get('/ColorSpace',{})
        if not isinstance(spaces,(dict,pikepdf.Dictionary)): spaces = {}
        for space in spaces.values():
            if not isinstance(space,pikepdf.Array) or len(space)!=4 or str(space[0])!='/Separation': continue
            if toyo_color(str(space[1])[1:]) is None: continue
            try:
                spot = read_spot(space)
            except (ConversionError,pikepdf.PdfError,NotImplementedError,ValueError,TypeError,IndexError,AttributeError):
                continue
            if str(space[2]) != '/DeviceCMYK': continue
            space[1] = pikepdf.Name('/'+spot.name)
            space[2] = pikepdf.Array([pikepdf.Name.Lab,pikepdf.Dictionary(
                WhitePoint=[.964203,1,.824905],Range=[-128,127,-128,127])])
            space[3] = pikepdf.Dictionary(FunctionType=2,Domain=[0,1],
                C0=[100,0,0],C1=list(spot.lab),N=1)
            changed.add(spot.name)
        objects = resources.get('/XObject',{})
        if not isinstance(objects,(dict,pikepdf.Dictionary)): continue
        for obj in objects.values():
            if isinstance(obj,pikepdf.Stream) and str(obj.get('/Subtype'))=='/Form':
                if obj.objgen in seen: continue
                seen.add(obj.objgen)
                pending.append(obj.get('/Resources'))
    return sorted(changed)
