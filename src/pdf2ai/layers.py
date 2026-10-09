"""PDF optional-content groups mapped to native Illustrator layer attributes."""
from dataclasses import dataclass
from .vector import ConversionError


@dataclass(frozen=True)
class Layer:
    key: tuple[int,int]
    name: str
    visible: bool = True
    locked: bool = False
    printable: bool = True


def read_layers(root):
    properties = root.get('/OCProperties') if root is not None else None
    if properties is None: return {}
    configuration = properties.get('/D', {})
    base = str(configuration.get('/BaseState','/ON'))
    if base not in ('/ON','/OFF'): raise ConversionError('Unsupported optional-content BaseState')
    on = {o.objgen for o in configuration.get('/ON',[])}
    off = {o.objgen for o in configuration.get('/OFF',[])}
    locked = {o.objgen for o in configuration.get('/Locked',[])}
    if on & off: raise ConversionError('Conflicting layer visibility states')
    if configuration.get('/RBGroups'): raise ConversionError('Radio-button PDF layer groups are unsupported')
    layers = {}
    for obj in properties.get('/OCGs',[]):
        if str(obj.get('/Type')) != '/OCG' or obj.objgen == (0,0):
            raise ConversionError('Invalid optional-content group')
        visible = False if obj.objgen in off else True if obj.objgen in on else base=='/ON'
        printable = str(obj.get('/Usage',{}).get('/Print',{}).get('/PrintState','/ON' if visible else '/OFF'))=='/ON'
        layers[obj.objgen] = Layer(obj.objgen,str(obj.get('/Name','PDF layer')),visible,obj.objgen in locked,printable)
    for entry in configuration.get('/AS',[]):
        if str(entry.get('/Event')) != '/View': continue
        if any(str(c)!='/View' for c in entry.get('/Category',[])):
            raise ConversionError('Automatic PDF layer zoom/language rules are unsupported')
        for obj in entry.get('/OCGs',properties.get('/OCGs',[])):
            if obj.objgen not in layers: raise ConversionError('Unknown automatic layer group')
            visible = str(obj.get('/Usage',{}).get('/View',{}).get('/ViewState','/ON'))=='/ON'
            old = layers[obj.objgen]
            layers[obj.objgen] = Layer(old.key,old.name,visible,old.locked,old.printable)
    return layers


def layer_for(obj, layers):
    if str(obj.get('/Type')) != '/OCG':
        raise ConversionError('PDF layer membership expressions (OCMD) are unsupported')
    if obj.objgen not in layers: raise ConversionError('Layer missing from PDF OCProperties')
    return layers[obj.objgen]
