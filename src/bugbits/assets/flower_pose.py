"""Normal flower node animation in raw coordinates; not x87 bit parity.

Only the loader performs IO. Pose evaluation does not establish the original
frame at which a cached attachment world matrix was consumed.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from bugbits.assets import data_dir
from bugbits.assets.pose import euler_rot, mat_apply, mat_mul
from bugbits.assets.van import parse_van, sample
from bugbits.assets.v3d import parse_v3d

CONTRACT = 'flower-node-keys-v1'
_CACHE = {}


def _number(x):
    return type(x) in (int, float) and math.isfinite(x)


def _vector(v, n):
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(_number(x) for x in v):
        raise ValueError('finite numeric vector required')
    return v


def _digest(rig):
    return hashlib.sha256(json.dumps({k:v for k,v in rig.items() if k != 'rigSHA256'},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_rig(rig):
    try:
        if not isinstance(rig, dict) or rig['contract'] != CONTRACT:
            raise ValueError('unsupported flower rig contract')
        for key in ('assetId', 'modelSource', 'animationSource'):
            if not isinstance(rig[key], str) or not rig[key]:
                raise ValueError('nonempty source metadata required')
        for key in ('modelSHA', 'animationSHA', 'rigSHA256'):
            if not isinstance(rig[key], str) or not re.fullmatch('[0-9a-f]{64}', rig[key]):
                raise ValueError('invalid source digest')
        duration = rig['duration']
        if not _number(duration) or duration <= 0:
            raise ValueError('positive duration required')
        nodes = rig['nodes']
        if not isinstance(nodes, list) or not nodes:
            raise ValueError('nonempty node list required')
        names = set()
        for node in nodes:
            name = node['name']
            if not isinstance(name, str) or not name or name in names:
                raise ValueError('unique node names required')
            names.add(name)
            parent = node['parent']
            if type(parent) is not int or not -1 <= parent < len(nodes):
                raise ValueError('invalid parent index')
            bind = _vector(node['bind'], 16)
            if any(bind[i] != 0 for i in (3, 7, 11)) or bind[15] != 1:
                raise ValueError('affine bind required')
            keys = node['keys']
            if not isinstance(keys, list) or not keys:
                raise ValueError('nonempty keys required')
            previous = -1
            for key in keys:
                _vector(key, 7)
                if key[0] <= previous:
                    raise ValueError('strictly increasing key times required')
                previous = key[0]
            if keys[0][0] != 0 or keys[-1][0] != duration:
                raise ValueError('key endpoints must span the declared duration')
        for i in range(len(nodes)):
            seen = set()
            while i != -1:
                if i in seen:
                    raise ValueError('cyclic parent graph')
                seen.add(i)
                i = nodes[i]['parent']
        index = rig['nektarNode']
        if type(index) is not int or not 0 <= index < len(nodes) or nodes[index]['name'] != 'nektar':
            raise ValueError('exact nektar node required')
        if _digest(rig) != rig['rigSHA256']:
            raise ValueError('rig digest mismatch')
        return rig
    except (KeyError, TypeError, IndexError, OverflowError, RecursionError) as exc:
        raise ValueError('invalid flower rig') from exc


def load_normal_rig(asset_id):
    if asset_id not in ('flower_a', 'flower_b', 'cactus_a'):
        raise ValueError('unsupported normal flower asset')
    sources = Path(data_dir('models', 'props'))
    model, animation = sources / (asset_id + '.v3d'), sources / (asset_id + '.van')
    model_raw, animation_raw = model.read_bytes(), animation.read_bytes()
    shas = tuple(hashlib.sha256(raw).hexdigest() for raw in (model_raw, animation_raw))
    cache_key = (asset_id, *shas)
    if cache_key not in _CACHE:
        recs = parse_v3d(model)[2]
        blocks = parse_van(animation)
        # Recheck parser reads to avoid signing bytes changed during parsing.
        if model.read_bytes() != model_raw or animation.read_bytes() != animation_raw:
            raise ValueError('flower source changed while loading')
        if 4 + sum(4 + 28*len(keys) for keys in blocks) != len(animation_raw):
            raise ValueError('VAN trailing bytes or incomplete node blocks')
        if len(recs) != len(blocks):
            raise ValueError('V3D/VAN node count mismatch')
        nodes = [dict(name=r[0], parent=-1 if r[1] == 0xffffffff else r[1],
                      bind=list(r[3]), keys=[list(k) for k in keys])
                 for r, keys in zip(recs, blocks)]
        if not blocks or not blocks[0]:
            raise ValueError('empty animation')
        rig = dict(contract=CONTRACT, assetId=asset_id,
                   modelSource='models/props/' + model.name, modelSHA=shas[0],
                   animationSource='models/props/' + animation.name, animationSHA=shas[1],
                   duration=blocks[0][-1][0], nodes=nodes,
                   nektarNode=next((i for i,n in enumerate(nodes) if n['name']=='nektar'), -1))
        rig['rigSHA256'] = _digest(rig)
        _CACHE[cache_key] = validate_rig(rig)
    return copy.deepcopy(_CACHE[cache_key])


def worlds_at(rig, phase):
    validate_rig(rig)
    if not _number(phase) or phase < 0:
        raise ValueError('finite nonnegative phase required')
    nodes = rig['nodes']
    result = [None] * len(nodes)
    def resolve(i):
        if result[i] is None:
            key = sample(nodes[i]['keys'], phase)
            local = list(euler_rot(*key[1:4]))
            local[12:15] = key[4:7]
            p = nodes[i]['parent']
            result[i] = tuple(local) if p == -1 else mat_mul(local, resolve(p))
        return result[i]
    for i in range(len(nodes)):
        resolve(i)
    return result


def attachment_at(rig, phase):
    return tuple(worlds_at(rig, phase)[rig['nektarNode']][12:15])


def owner_matrix(direction_yup, observed=False):
    _vector(direction_yup, 3)
    if type(observed) is not bool:
        raise ValueError('boolean observed policy required')
    x = [direction_yup[2], -direction_yup[0], -direction_yup[1]]
    length = math.sqrt(sum(v*v for v in x))
    if not length or not math.isfinite(length):
        raise ValueError('nonzero finite flower direction required')
    x = [v/length for v in x]
    if observed:
        c = [x[1], -x[0], 0]
        length = math.sqrt(sum(v*v for v in c))
        if not length:
            raise ValueError('unsupported up-parallel observed direction')
        c = [v/length for v in c]
        u = [x[1]*c[2]-x[2]*c[1], x[2]*c[0]-x[0]*c[2], x[0]*c[1]-x[1]*c[0]]
        raw = [c, x, [-v for v in u]]
    else:
        reference = (0,0,1) if abs(x[2]) < .999 else (0,1,0)
        y = [reference[1]*x[2]-reference[2]*x[1], reference[2]*x[0]-reference[0]*x[2], reference[0]*x[1]-reference[1]*x[0]]
        length = math.sqrt(sum(v*v for v in y)); y = [v/length for v in y]
        z = [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
        raw = [x,y,z]
    q = [[0,0,1],[-1,0,0],[0,-1,0]]
    return [sum(q[k][i]*raw[k][l]*q[l][j] for k in range(3) for l in range(3))
            if i<3 and j<3 else int(i==j) for i in range(4) for j in range(4)]


def world_attachment(rig, phase, position_yup, direction_yup, scale, observed=False):
    _vector(position_yup, 3)
    if not _number(scale) or scale <= 0:
        raise ValueError('positive finite scale required')
    raw = attachment_at(rig, phase)
    angle = struct.unpack('<f', struct.pack('<f', -math.pi/2))[0]
    raw = mat_apply(euler_rot(angle,0,0), (*raw,1))
    yup = (-raw[1]*scale, -raw[2]*scale, raw[0]*scale)
    rotated = mat_apply(owner_matrix(direction_yup, observed), (*yup,1))
    return tuple(rotated[i]+position_yup[i] for i in range(3))
