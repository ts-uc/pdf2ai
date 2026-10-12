"""Resolve image resource aliases for both native decoding and the PDF view."""
import pikepdf
from .vector import ConversionError


def resolve_image_space(value, resources, seen=()):
    if isinstance(value,pikepdf.Name) and str(value) not in ('/DeviceRGB','/DeviceCMYK','/DeviceGray'):
        name=str(value)
        if name in seen or len(seen)>=32:raise ConversionError('Recursive image color space alias')
        replacement=resources.get('/ColorSpace',{}).get(name)
        if replacement is None:raise ConversionError('Missing image color space alias: '+name)
        return resolve_image_space(replacement,resources,(*seen,name))
    if isinstance(value,pikepdf.Array) and len(value)==4 and str(value[0])=='/Indexed':
        return pikepdf.Array([value[0],resolve_image_space(value[1],resources,seen),value[2],value[3]])
    return value


def normalize_image_spaces(page, pdf):
    """Clone alias-bearing images per resource scope; never reinterpret a shared image globally."""
    pending=[page.obj.get('/Resources')];seen=set();changed=False
    while pending:
        resources=pending.pop()
        if not isinstance(resources,pikepdf.Dictionary):continue
        if resources.objgen!=(0,0):
            if resources.objgen in seen:continue
            seen.add(resources.objgen)
        objects=resources.get('/XObject',{})
        if not isinstance(objects,(dict,pikepdf.Dictionary)):continue
        replacements=None
        for key,obj in list(objects.items()):
            if not isinstance(obj,pikepdf.Stream):continue
            if str(obj.get('/Subtype'))=='/Form':
                if obj.objgen in seen:continue
                seen.add(obj.objgen);pending.append(obj.get('/Resources'))
            elif str(obj.get('/Subtype'))=='/Image' and not obj.get('/ImageMask',False):
                original=obj.get('/ColorSpace')
                try:resolved=resolve_image_space(original,resources)
                except (ConversionError,TypeError,ValueError,pikepdf.PdfError):continue
                if resolved==original:continue
                # Shared /XObject dictionaries and streams can be referenced
                # under different ColorSpace dictionaries. Copy both bindings.
                if replacements is None:replacements=pikepdf.Dictionary(objects)
                clone=pdf.make_stream(obj.read_raw_bytes())
                clone.update({name:value for name,value in obj.items() if str(name)!='/Length'})
                clone.ColorSpace=resolved
                replacements[key]=clone;changed=True
        if replacements is not None:resources.XObject=replacements
    return changed
