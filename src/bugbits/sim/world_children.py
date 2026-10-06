"""Original live name container semantics in an explicit bounded byte domain.

R371 raw unsigned strcmp/insertion/left-shift removal. This container does
not claim the caller has registered every original world object or its order.
"""
from bisect import bisect_left
from dataclasses import dataclass


def _name_bytes(name):
    if not isinstance(name,str) or not name or '\0' in name:
        raise ValueError('nonempty raw-byte name required')
    try:
        value=name.encode('latin-1')
    except UnicodeEncodeError as error:
        raise ValueError('name outside explicit Latin-1 byte domain') from error
    if len(value)>240:
        raise ValueError('name outside bounded original sprintf domain')
    return value


def _increment(name):
    at=len(name)
    while at and '0'<=name[at-1]<='9':at-=1
    suffix=name[at:]
    value=int(suffix) if suffix else 0
    if value>=2147483647:
        raise ValueError('original signed suffix overflow is not supported')
    result=name[:at]+str(value+1).zfill(len(suffix))
    _name_bytes(result)
    return result


@dataclass(frozen=True)
class Child:
    name:str
    kind:str
    key:object


class NamedChildren:
    def __init__(self):
        self._children=[]

    def entries(self):
        return tuple(self._children)

    def add(self,kind,key,name):
        encoded=_name_bytes(name)
        if any(child.kind==kind and child.key==key for child in self._children):
            raise ValueError('duplicate child identity')
        while True:
            names=[_name_bytes(child.name) for child in self._children]
            index=bisect_left(names,encoded)
            if index==len(names) or names[index]!=encoded:
                self._children.insert(index,Child(name,kind,key))
                return name
            name=_increment(name);encoded=_name_bytes(name)

    def remove(self,kind,key):
        for i,child in enumerate(self._children):
            if child.kind==kind and child.key==key:
                return self._children.pop(i)
        raise KeyError((kind,key))

    def walk(self,update):
        index=0
        while index<len(self._children):
            update(self._children[index])
            index+=1

    def sweep(self,ready,destroy):
        index=0
        while index<len(self._children):
            child=self._children[index]
            if ready(child):
                self._children.pop(index)
                destroy(child)
            # Original48709A increments even after403690 shifted entries left.
            index+=1

    def snapshot(self):
        return {'scope':'bounded-original-name-live-container-v1',
                'nameScope':'latin1-bytes-length240-signed-suffix-safe-v1',
                'children':[{'name':c.name,'kind':c.kind,'key':c.key} for c in self._children]}
