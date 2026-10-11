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
