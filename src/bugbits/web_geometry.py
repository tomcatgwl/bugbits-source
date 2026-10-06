"""Traceable engine mesh assets; current pose and explicit engineering root policy.

Unit frames stay in raw model coordinates. Root, Q, anchor and ScaleFactor are
applied exactly once by the consumer. Terrain is already in its declared basis.
This does not implement original runtime animation/root/material semantics.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct

from bugbits import unitdb
from bugbits.assets import data_dir, flower_pose, pose, van, v3d, vtx
from bugbits.render import bake

SCHEMA = 'engine-mesh-v1'
POSE_POLICY = 'engine-pose-v1'
CLIP_KEYS = ('walk','idle','normal_attack','hurt','special_attack','special_move')
ROOT_ANGLE = struct.unpack('<f', bytes.fromhex('db0fc9bf'))[0]
# Raw row-vector Rx, separate from pose.py's historical Euler conventions.
ROOT_MATRIX = (1,0,0,0, 0,math.cos(ROOT_ANGLE),math.sin(ROOT_ANGLE),0,
               0,-math.sin(ROOT_ANGLE),math.cos(ROOT_ANGLE),0, 0,0,0,1)
FRAME_FORMAT = 'f32le-pose-v1'
PROP_VARIANT_CONTRACT = 'level-flower-variants-v1'
PROP_IDENTITY = (1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1)

def flower_asset_spec(flower_type, *, rescue=False):
    """Supported flower source bindings; unresolved original branches reject."""
    if type(flower_type) is not int or flower_type not in (1,2,3) or type(rescue) is not bool:
        raise ValueError('unsupported FlowerType/rescue')
    # R155: type2 rescue skips the ordinary model load and changes material
    # on an existing model. Its identity is unresolved; a b_swap is invented.
    if flower_type == 2 and rescue:
        raise ValueError('unverified original type2 rescue model binding')
    asset, scale = {1:('flower_a',2.5),2:('flower_b',2.5),3:('cactus_a',1.0)}[flower_type]
    # SetFlowerType49E81B passes float32(4) to the same model loader for
    # type1 rescue; normal49E858 passes float32(2.5). Other types unchanged.
    if flower_type == 1 and rescue:scale = 4.0
    return {'assetId':asset + ('_swap' if rescue else ''), 'scaleFactor':scale}

def flower_owner_matrix(direction_yup):
    """Engineering orthonormal owner frame: local raw +X follows Direction.

    This is explicit bind presentation, not a recovered ceFlower owner routine.
    Q conjugates the raw frame into Yup; translation remains separate.
    """
    if len(direction_yup)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in direction_yup):
        raise ValueError('finite flower Direction required')
    x=[direction_yup[2],-direction_yup[0],-direction_yup[1]]
    length=math.sqrt(sum(v*v for v in x))
    if not length:raise ValueError('zero flower Direction')
    x=[v/length for v in x]
    reference=(0,0,1) if abs(x[2])<.999 else (0,1,0)
    y=[reference[1]*x[2]-reference[2]*x[1], reference[2]*x[0]-reference[0]*x[2], reference[0]*x[1]-reference[1]*x[0]]
    length=math.sqrt(sum(v*v for v in y));y=[v/length for v in y]
    z=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    raw=[x,y,z];q=[[0,0,1],[-1,0,0],[0,-1,0]]
    matrix=[sum(q[k][i]*raw[k][l]*q[l][j] for k in range(3) for l in range(3))
            if i<3 and j<3 else int(i==j) for i in range(4) for j in range(4)]
    return matrix

def _frame_range(ref, count, byte_length):
    if (not isinstance(ref,dict) or set(ref)!= {'offset','count'} or
            type(ref['offset']) is not int or type(ref['count']) is not int or
            ref['offset']<0 or ref['offset']%4 or ref['count']!=count or
            ref['offset']+4*count>byte_length):
        raise ValueError('invalid binary pose range')

def validate_frame_buffer(unit, raw):
    """Validate the exact bytes consumed as GPU Float32, never decimal refitting."""
    record=unit['frameBuffer']
    if (record.get('format')!=FRAME_FORMAT or type(record.get('byteLength')) is not int or
            record['byteLength']!=len(raw) or len(raw)%4 or
            hashlib.sha256(raw).hexdigest()!=record.get('sha256')):
        raise ValueError('binary pose buffer identity differs')
    if any(not math.isfinite(v[0]) for v in struct.iter_unpack('<f',raw)):
        raise ValueError('non-finite binary pose')
    count=len(unit['positions']);end=0
    for clip in unit['clips'].values():
        for frame in clip['frames']:
            for field in ('positions','normals'):
                ref=frame[field];_frame_range(ref,count,len(raw))
                if ref['offset']!=end:raise ValueError('binary pose ranges must cover buffer in frame order')
                end+=4*count
    if end!=len(raw):raise ValueError('unreferenced binary pose bytes')
    return raw

def decode_frame(unit, frame, raw):
    """Read one public frame after validating its full unit buffer and hash."""
    validate_frame_buffer(unit,raw)
    if not isinstance(frame,dict) or set(frame)!= {'positions','normals'}:
        raise ValueError('selected binary frame fields required')
    for field in ('positions','normals'):
        _frame_range(frame[field],len(unit['positions']),len(raw))
    if not any(frame==declared for clip in unit['clips'].values() for declared in clip['frames']):
        raise ValueError('selected frame is not declared by this unit')
    return {field:list(struct.unpack_from('<'+str(frame[field]['count'])+'f',raw,frame[field]['offset']))
            for field in ('positions','normals')}

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _texture_path(name):
    return data_dir('textures', name + '.vtx')

def bind_attachment(records, name='nektar'):
    """Named bind-model point under validated full ancestry, not runtime +E8."""
    matches=[i for i,record in enumerate(records) if record[0]==name]
    if not matches:return None
    if len(matches)!=1:raise ValueError('duplicate named attachment')
    index=matches[0];chain=[];current=index
    while current not in (-1,0xFFFFFFFF):
        if type(current) is not int or not 0<=current<len(records) or current in chain:
            raise ValueError('invalid attachment parent chain')
        chain.append(current)
        matrix=records[current][3]
        if (len(matrix)!=16 or any(type(v) not in (int,float) or not math.isfinite(v) for v in matrix)
                or any(abs(matrix[i])>1e-8 for i in (3,7,11)) or abs(matrix[15]-1)>1e-8):
            raise ValueError('invalid attachment affine matrix')
        current=records[current][1]
    world=tuple(PROP_IDENTITY)
    for node in reversed(chain):world=pose.mat_mul(records[node][3],world)
    if any(not math.isfinite(v) for v in world):raise ValueError('non-finite composed attachment')
    return {'name':name,'node':index,'parentChain':chain,'positionRaw':list(world[12:15]),
            'poseScope':'bind-model-attachment-v1'}

def _mesh(vertices, groups, texture):
    return {'positions':[float(x) for v in vertices for x in v[0]],
            'normals':[float(x) for v in vertices for x in v[1]],
            'uvs':[float(x) for v in vertices for x in v[2]],
            'groups':[{'indices':list(indices),'texture':texture(name)}
                      for indices,name in groups],
            'textureVFlip':True,'textureUvScope':'engineering-explicit-v1'}

def asset_ledger(unit_ids=None):
    """Real unit/group/clip source ledger without pose sampling or rendering."""
    specs = unitdb.load_all() if unit_ids is None else {u:unitdb.load_unit(u) for u in unit_ids}
    result = {}
    for uid,spec in sorted(specs.items()):
        model = bake._resolve_model(spec.model,'.v3d')
        if model is None: raise FileNotFoundError(f'{uid}: named model {spec.model}')
        vertices,groups,skin,records = v3d.parse_v3d_groups(model)
        clips = {}
        for key in CLIP_KEYS:
            ref = spec.anims.get(key)
            path = bake._resolve_model(ref,'.van') if ref else None
            if ref and path is None: raise FileNotFoundError(f'{uid}/{key}: named animation {ref}')
            clips[key] = {'ref':ref,'file':path,'kind':'declared' if ref else 'missing'}
        result[uid] = {'model':model,'vertices':len(vertices),'skinVertices':len(skin),
                       'nodeCount':len(records),'textures':[n for _,n in groups if n],
                       'groupCount':len(groups),'clips':clips}
    return result

def validate_geometry_sources(scene, input_hashes, *, require_all_units=True):
    """Bind data captured early to creator's final raw source versions and IDs."""
    if any(input_hashes.get(p)!=h for p,h in scene['inputHashes'].items()):
        raise ValueError('geometry and final creator input hashes differ')
    bugs={Path(p).stem for p in scene['inputHashes'] if p.startswith('scripts/bugs/') and p.endswith('.vsc')}
    infos={Path(p).stem for p in scene['inputHashes'] if p.startswith('scripts/buginfos/') and p.endswith('.vsc')}
    actual=bugs & infos
    if set(scene['units'])!=actual or require_all_units and len(actual)!=24:
        raise ValueError('geometry IDs differ from actual unit source closure')
    if scene.get('unitMaterialContract')=='script-diffuse-unit-v1':
        for uid,u in scene['units'].items():
            if scene['inputHashes'].get(u['modelSource'])!=u['modelSHA']:
                raise ValueError('unit model outside source closure')
            for g in u['groups']:
                b=g['unitMaterial']
                if scene['inputHashes'].get(b['source'])!=b['sourceSHA256']:
                    raise ValueError('unit material outside source closure')
    if scene.get('nectarCarryContract')=='same-bug-radius-trajectory-v1':
        for u in scene['units'].values():
            if scene['inputHashes'].get(u['radiusSource'])!=u['radiusSourceSHA256']:
                raise ValueError('unit radius outside source closure')
    for prop in scene.get('props',{}).values():
        if scene['inputHashes'].get(prop['modelSource'])!=prop['modelSHA']:
            raise ValueError('prop model outside source closure')
        _validate_flower_animation(prop)
        if 'animationRig' in prop:
            rig=prop['animationRig']
            for kind in ('model','animation'):
                if scene['inputHashes'].get(rig[kind+'Source'])!=rig[kind+'SHA']:
                    raise ValueError('flower animation outside source closure')
    for texture in scene['textures'].values():
        if scene['inputHashes'].get(texture['source'])!=texture['sourceSHA']:
            raise ValueError('texture outside source closure')
    for name in scene['worlds']:
        if scene.get('props') and 'worlds/'+name+'.vsc' not in scene['inputHashes']:
            raise ValueError('prop world outside source closure')
    return scene

def _validate_flower_animation(prop):
    """Validate rig/skin identity and the preserved bind vertex/attachment pools.

    Skin uses the original binary reference-table mapping. Node -1 is a NULL
    reference, contributing the weighted source pool. Exporting this finite
    mapping does not establish full original runtime skinning fidelity.
    """
    normal=prop['assetId'] in ('flower_a','flower_b','cactus_a')
    if not normal:
        if (prop.get('animationScope')!='raw-bind-only-unverified' or
                'animationRig' in prop or 'animationSkin' in prop):
            raise ValueError('unsupported rescue animation scope')
        return
    try:
        rig=flower_pose.validate_rig(prop['animationRig'])
        canonical=json.dumps({k:v for k,v in rig.items() if k!='rigSHA256'},
                             sort_keys=True,separators=(',',':'),allow_nan=False)
        if prop.get('animationRigJson')!=canonical:
            raise ValueError('flower rig canonical bytes differ')
        if (prop.get('animationScope')!='normal-flower-node-keys-v1' or
                rig['assetId']!=prop['assetId'] or rig['modelSource']!=prop['modelSource'] or
                rig['modelSHA']!=prop['modelSHA'] or len(rig['nodes'])!=prop['nodeCount'] or
                rig['modelSource']!='models/props/'+prop['assetId']+'.v3d' or
                rig['animationSource']!='models/props/'+prop['assetId']+'.van'):
            raise ValueError('flower rig identity differs')
        records=[(n['name'],n['parent'],None,n['bind']) for n in rig['nodes']]
        if prop.get('attachments')!={'nektar':bind_attachment(records)}:
            raise ValueError('flower rig bind attachment differs')
        skin=prop['animationSkin'];count=len(prop['positions'])//3
        if not isinstance(skin,list) or len(skin)!=count or prop['skinVertices']!=count:
            raise ValueError('flower skin vertex count differs')
        for i,vertex in enumerate(skin):
            if not isinstance(vertex,list) or len(vertex)!=3:
                raise ValueError('invalid flower skin vertex')
            for field,raw in zip(vertex[:2],('positions','normals')):
                if (not isinstance(field,list) or len(field)!=3 or
                        any(type(x) not in (int,float) or not math.isfinite(x) for x in field) or
                        field!=prop[raw][3*i:3*i+3]):
                    raise ValueError('flower skin same-index bind pool differs')
            influences=vertex[2]
            if not isinstance(influences,list) or not influences:
                raise ValueError('flower skin influences required')
            for influence in influences:
                if (not isinstance(influence,list) or len(influence)!=2 or
                        type(influence[0]) is not int or not -1<=influence[0]<len(rig['nodes']) or
                        type(influence[1]) not in (int,float) or not math.isfinite(influence[1]) or
                        not 0<influence[1]<=1):
                    raise ValueError('invalid flower skin influence')
    except (KeyError,TypeError,IndexError) as exc:
        raise ValueError('invalid flower animation packet') from exc


def validate_geometry(scene):
    """Validate the actual packet consumed by the browser, including all pools."""
    if scene.get('schema') != SCHEMA or scene.get('posePolicy') != POSE_POLICY:
        raise ValueError('unsupported geometry contract')
    if 'unitMaterialContract' in scene and scene['unitMaterialContract']!='script-diffuse-unit-v1':
        raise ValueError('unsupported unit material contract')
    if 'nectarCarryContract' in scene and scene['nectarCarryContract']!='same-bug-radius-trajectory-v1':
        raise ValueError('unsupported nectar carry contract')
    def numbers(values, stride):
        if not isinstance(values,list) or len(values)%stride or any(
                isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
            raise ValueError('finite geometry arrays required')
    def mesh(m, prop_id=None):
        if 'textureVFlip' in m or 'textureUvScope' in m:
            if ('textureVFlip' not in m or 'textureUvScope' not in m or
                    type(m['textureVFlip']) is not bool or
                    m['textureUvScope'] not in ('engineering-explicit-v1','observed-normal-flower-a-v1') or
                    m['textureUvScope']=='observed-normal-flower-a-v1' and
                    (prop_id!='flower_a' or m.get('assetId')!='flower_a' or m['textureVFlip'] is not False)):
                raise ValueError('unsupported texture UV policy/scope')
        numbers(m['positions'],3);numbers(m['normals'],3);numbers(m['uvs'],2)
        n = len(m['positions'])//3
        if not n or len(m['normals'])!=3*n or len(m['uvs'])!=2*n: raise ValueError('vertex pool mapping differs')
        if not m['groups']: raise ValueError('material groups required')
        for g in m['groups']:
            ix=g['indices']
            if not isinstance(ix,list) or len(ix)%3 or any(type(i) is not int or not 0<=i<n for i in ix): raise ValueError('triangle indices out of pool')
            if g['texture'] is not None and g['texture'] not in scene['textures']: raise ValueError('missing named material texture')
        return n
    for t in scene['textures'].values():
        if (not isinstance(t['file'],str) or not t['file'].startswith('assets/geometry/') or
                '..' in t['file'].split('/') or '\\' in t['file'] or
                type(t['width']) is not int or type(t['height']) is not int or min(t['width'],t['height'])<=0 or
                type(t['size']) is not int or t['size']<=0 or
                not isinstance(t['sha256'],str) or len(t['sha256'])!=64 or any(c not in '0123456789abcdef' for c in t['sha256'])):
            raise ValueError('invalid texture record')
    for uid,u in scene['units'].items():
        n=mesh(u)
        if 'nectarCarryContract' in scene:
            if (type(u.get('radius')) not in (int,float) or not math.isfinite(u['radius']) or u['radius']<=0
                    or u.get('radiusSource')!='scripts/bugs/'+uid+'.vsc'
                    or not isinstance(u.get('radiusSourceSHA256'),str) or len(u['radiusSourceSHA256'])!=64
                    or any(c not in '0123456789abcdef' for c in u['radiusSourceSHA256'])):
                raise ValueError('unit radius source')
        if 'unitMaterialContract' in scene:
            colors=u.get('diffuseARGB')
            if (u.get('unitId')!=uid or u.get('diffuseScope')!='raw-bind-diffuse-v1'
                    or not isinstance(u.get('modelSource'),str) or not u['modelSource'] or u['modelSource'].startswith('/')
                    or '..' in u['modelSource'].split('/') or '\\' in u['modelSource']
                    or not isinstance(u.get('modelSHA'),str) or len(u['modelSHA'])!=64
                    or any(c not in '0123456789abcdef' for c in u['modelSHA'])
                    or not isinstance(colors,list) or len(colors)!=n
                    or any(type(c) is not int or not 0<=c<=0xffffffff for c in colors)):
                raise ValueError('unit raw diffuse pool')
            for index,g in enumerate(u['groups']):
                b=g.get('unitMaterial')
                if (not isinstance(b,dict) or b.get('bindingScope')!='script-unit-material-v1'
                        or 'name' not in b
                        or type(b.get('groupIndex')) is not int or b['groupIndex']!=index
                        or b.get('name') is not None and (not isinstance(b['name'],str) or not b['name'] or len(b['name'].split())!=1)
                        or b.get('source')!='scripts/bugs/'+uid+'.vsc'
                        or not isinstance(b.get('sourceSHA256'),str) or len(b['sourceSHA256'])!=64
                        or any(c not in '0123456789abcdef' for c in b['sourceSHA256'])):
                    raise ValueError('unit script material binding')
        elif 'diffuseARGB' in u or 'diffuseScope' in u or any('unitMaterial' in g for g in u['groups']):
            raise ValueError('missing unit material contract')
        buffer=u.get('frameBuffer')
        if (not isinstance(buffer,dict) or buffer.get('format')!=FRAME_FORMAT or
                type(buffer.get('byteLength')) is not int or buffer['byteLength']<0 or buffer['byteLength']%4 or
                not isinstance(buffer.get('sha256'),str) or len(buffer['sha256'])!=64 or
                any(c not in '0123456789abcdef' for c in buffer['sha256']) or
                not isinstance(buffer.get('file'),str) or not buffer['file'].startswith('assets/geometry/') or
                '..' in buffer['file'].split('/') or '\\' in buffer['file']):
            raise ValueError('binary unit frame buffer required')
        if set(u['clips'])!=set(CLIP_KEYS): raise ValueError('six clip ledger required')
        if u['frameBasis']!='raw-model-v1' or u['rootApplied'] is not False or u['scaleApplied'] is not False: raise ValueError('mixed unit frame basis')
        if u.get('rootPolicy')!='engineering-fixed-S-v1' or u.get('coordinatePolicy')!='raw-to-engine-yup-Q-v1' or u.get('anchorPolicy')!='raw-bind-ground-pivot-v1' or u['rootMatrix']!=list(ROOT_MATRIX): raise ValueError('unsupported unit transform policy')
        numbers(u['anchor'],3);numbers(u['rootMatrix'],16)
        if len(u['anchor'])!=3 or len(u['rootMatrix'])!=16: raise ValueError('root/anchor dimensions')
        if type(u['scaleFactor']) not in (int,float) or not math.isfinite(u['scaleFactor']) or u['scaleFactor']<=0: raise ValueError('positive scaleFactor')
        for c in u['clips'].values():
            if c['kind']=='missing':
                fb=c.get('fallbackClip')
                if c['frames'] or fb is not None and (fb not in u['clips'] or u['clips'][fb]['kind']=='missing'): raise ValueError('invalid clip fallback')
                continue
            if c['kind'] not in ('sampled','static') or len(c['frames'])!=len(c['sampleTimes']) or not c['frames']: raise ValueError('invalid sampled clip')
            numbers(c['sampleTimes'],1)
            if (type(c['duration']) not in (int,float) or not math.isfinite(c['duration']) or c['duration']<=0
                    or type(c['loop']) is not bool or any(not 0<=t<c['duration'] for t in c['sampleTimes'])
                    or any(a>=b for a,b in zip(c['sampleTimes'],c['sampleTimes'][1:]))): raise ValueError('invalid clip timing')
            for f in c['frames']:
                if set(f)!= {'positions','normals'}:raise ValueError('binary frame fields required')
                _frame_range(f['positions'],3*n,buffer['byteLength'])
                _frame_range(f['normals'],3*n,buffer['byteLength'])
    for asset,p in scene.get('props',{}).items():
        mesh(p, asset)
        root_policy = p.get('rootPolicy')
        expected_root = {'engineering-prop-bind-v1': PROP_IDENTITY,
                         'original-load-bind-S-v1': ROOT_MATRIX}.get(root_policy)
        if (p.get('assetId')!=asset or p.get('frameBasis')!='raw-model-v1' or
                p.get('rootApplied') is not False or p.get('scaleApplied') is not False or
                expected_root is None or p.get('rootMatrix')!=list(expected_root) or
                p.get('coordinatePolicy')!='raw-to-engine-yup-Q-v1' or p.get('anchorPolicy')!='raw-model-origin-v1'):
            raise ValueError('unsupported prop bind policy')
        for name,a in p.get('attachments',{}).items():
            if (name!='nektar' or a.get('name')!=name or a.get('poseScope')!='bind-model-attachment-v1'
                    or type(a.get('node')) is not int or not 0<=a['node']<p['nodeCount']
                    or not isinstance(a.get('parentChain'),list) or not a['parentChain']
                    or a['parentChain'][0]!=a['node'] or len(set(a['parentChain']))!=len(a['parentChain'])
                    or any(type(i) is not int or not 0<=i<p['nodeCount'] for i in a['parentChain'])):
                raise ValueError('invalid named bind attachment')
            numbers(a['positionRaw'],3)
            if len(a['positionRaw'])!=3:raise ValueError('attachment point dimensions')
        _validate_flower_animation(p)
    if 'nectarSprites' in scene:
        n=scene['nectarSprites']
        if (n.get('contract')!='bind-flower-nectar-v1' or
                any(n.get(k) not in scene['textures'] for k in ('texture','glowTexture'))):
            raise ValueError('invalid nectar sprite texture contract')
    variants_mode = 'propVariantContract' in scene
    if variants_mode and scene['propVariantContract'] != PROP_VARIANT_CONTRACT:
        raise ValueError('unsupported prop variant contract')
    for w in scene['worlds'].values():
        if variants_mode:
            variants = w.get('propVariants')
            if ('propInstances' in w or not isinstance(variants,dict) or not variants
                    or set(variants)-{'normal','rescue'}):
                raise ValueError('explicit prop variants required')
        else:
            if 'propVariants' in w:raise ValueError('prop variants require contract')
            variants = {'legacy':w.get('propInstances',[])}
        if w['basisVersion'] not in ('loaded-yup-v1','legacy-grid-v1') or not (w['meshes'] or any(variants.values())): raise ValueError('unsupported world basis or empty geometry')
        for m in w['meshes']:mesh(m)
        for variant, instances in variants.items():
          if not isinstance(instances,list):raise ValueError('prop instance list required')
          names=set()
          for instance in instances:
            if instance['name'] in names:raise ValueError('duplicate prop instance')
            names.add(instance['name'])
            if variants_mode and instance['rescue'] is not (variant=='rescue'):
                raise ValueError('prop variant rescue binding differs')
            expected=flower_asset_spec(instance['flowerType'],rescue=instance['rescue'])
            if (instance['assetId'] not in scene.get('props',{}) or instance['assetId']!=expected['assetId'] or
                    instance['scaleFactor']!=expected['scaleFactor'] or
                    instance.get('transformPolicy')!='engine-prop-v1' or instance.get('transformScope')!='engineering-bind-owner-v1' or
                    instance.get('parentMatrix')!=list(PROP_IDENTITY)):
                raise ValueError('unsupported prop instance policy')
            for field,n in (('positionYup',3),('directionYup',3),('directionRaw',3),('ownerMatrix',16),('parentMatrix',16)):
                numbers(instance[field],n)
                if len(instance[field])!=n:raise ValueError('prop transform dimensions')
            if (instance['ownerMatrix']!=flower_owner_matrix(instance['directionYup']) or
                    instance['directionRaw']!=[instance['directionYup'][2],-instance['directionYup'][0],-instance['directionYup'][1]]):
                raise ValueError('flower owner Direction binding differs')
    return scene

def export_geometry_assets(unit_ids, worlds, *, pose_policy, out_dir,
                           sample_hz=8,min_frames=4,max_frames=16,
                           props_only=False,rescue_worlds=None,prop_variants_by_world=None):
    """Write new geometry subtree and return package paths + complete source closure.

    out_dir is a package root. Its assets/geometry subtree must not exist. Named
    missing/invalid inputs fail; absent clip properties alone mean missing clips.
    """
    if pose_policy != POSE_POLICY: raise ValueError('unsupported pose policy')
    worlds=tuple(worlds);unit_ids=tuple(unit_ids)
    if prop_variants_by_world is not None and rescue_worlds is not None:
        raise ValueError('prop variants and rescue_worlds cannot be combined')
    rescue_worlds=set(rescue_worlds or ())
    if prop_variants_by_world is not None:
        if not isinstance(prop_variants_by_world,dict) or set(prop_variants_by_world)!=set(worlds):
            raise ValueError('prop variants must cover selected worlds exactly')
        for values in prop_variants_by_world.values():
            if (not isinstance(values,(list,tuple)) or not values or
                    any(v not in ('normal','rescue') for v in values) or len(set(values))!=len(values)):
                raise ValueError('unsupported prop variant selection')
    selections = {w:tuple(prop_variants_by_world[w]) if prop_variants_by_world is not None
                  else ('rescue' if w in rescue_worlds else 'normal',) for w in worlds}
    if type(props_only) is not bool or rescue_worlds-set(worlds) or props_only and unit_ids:
        raise ValueError('unsupported props-only/rescue world selection')
    if (type(min_frames) is not int or type(max_frames) is not int or
            not 1<=min_frames<=max_frames<=16 or not math.isfinite(sample_hz) or sample_hz<=0): raise ValueError('invalid bounded sampling')
    package=Path(out_dir).absolute();project=Path(__file__).resolve().parents[2]
    if '..' in package.parts or any(p.is_symlink() for p in (package,*package.parents)) or not any(package.is_relative_to(project/f) for f in ('out','tmp')):
        raise ValueError('geometry output must be in project out/tmp without symlinks')
    # Named flower inputs are cheap to check before any expensive unit pose.
    from bugbits import worlddb
    world_data={};preflight_hashes={};flower_rigs={}
    for name in sorted(set(worlds)):
        path=data_dir('worlds',name+'.vsc');preflight_hashes[os.path.abspath(path)]=_sha(path)
        wd=worlddb.parse_world(path)
        if wd.basis_version!='loaded-yup-v1':raise ValueError('engine mesh world requires explicit loaded-yup-v1 terrain')
        world_data[name]=wd
        for variant in selections[name]:
            for flower in wd.flowers:
                asset=flower_asset_spec(flower.flower_type,rescue=variant=='rescue')['assetId']
                model=bake._resolve_model('props/'+asset,'.v3d')
                if model is None:raise FileNotFoundError('named flower model props/'+asset+'.v3d')
                preflight_hashes[os.path.abspath(model)]=_sha(model)
                if variant=='normal':
                    animation=bake._resolve_model('props/'+asset,'.van')
                    if animation is None:raise FileNotFoundError('named flower animation props/'+asset+'.van')
                    preflight_hashes[os.path.abspath(animation)]=_sha(animation)
                    rig=flower_pose.load_normal_rig(asset)
                    if rig['modelSHA']!=_sha(model) or rig['animationSHA']!=_sha(animation):
                        raise ValueError('flower rig source identity differs')
                    flower_rigs[asset]=rig
                _,groups,_,_=v3d.parse_v3d_groups(model)
                for _,texture_name in groups:
                    if texture_name:
                        texture_path=_texture_path(texture_name)
                        if not os.path.isfile(texture_path):raise FileNotFoundError(texture_path)
                        preflight_hashes[os.path.abspath(texture_path)]=_sha(texture_path)
    output=package/'assets/geometry';output.mkdir(parents=True,exist_ok=False)
    sources=set(preflight_hashes);source_hashes=dict(preflight_hashes);textures={};frame_files=[]
    def consume(path):
        if not os.path.isfile(path):raise FileNotFoundError(path)
        path=os.path.abspath(path);h=_sha(path)
        if path in source_hashes and source_hashes[path]!=h:raise ValueError('source changed during export')
        sources.add(path);source_hashes[path]=h
    def texture(name):
        if name is None or name=='':return None
        path=_texture_path(name);consume(path);key=hashlib.sha256(name.encode()).hexdigest()[:24]
        if key not in textures:
            image=vtx.parse_vtx(path)[4];rel=f'assets/geometry/{key}.png';image.save(Path(out_dir)/rel)
            textures[key]={'file':rel,'width':image.width,'height':image.height,'source':os.path.relpath(path,data_dir()),'sourceSHA':_sha(path),
                           'sha256':_sha(Path(out_dir)/rel),'size':(Path(out_dir)/rel).stat().st_size}
        return key
    scene={'schema':SCHEMA,'posePolicy':POSE_POLICY,'sourceScope':'engineering-current-pose',
           'rootPolicy':'engineering-fixed-S-v1','coordinatePolicy':'raw-to-engine-yup-Q-v1',
           'texturePolicy':{'vFlip':True,'perMeshOverride':True,'alphaCutout':64,'shade':'neutral-quarter-plus-40'},
           'units':{},'worlds':{},'textures':textures,'props':{},
           'unitMaterialContract':'script-diffuse-unit-v1',
           'nectarCarryContract':'same-bug-radius-trajectory-v1'}
    scene['nectarSprites']={'contract':'bind-flower-nectar-v1',
                            'texture':texture('particles/nectar_01'),
                            'glowTexture':texture('gui/gizmos/glow_star_01')}
    if prop_variants_by_world is not None:scene['propVariantContract']=PROP_VARIANT_CONTRACT
    for uid in sorted(set(unit_ids)):
        for folder in ('bugs','buginfos'):consume(data_dir('scripts',folder,uid+'.vsc'))
        spec=unitdb.load_unit(uid)
        model=bake._resolve_model(spec.model,'.v3d')
        if model is None:raise FileNotFoundError(f'{uid}: named model {spec.model}')
        consume(model);verts,groups,skin,recs=v3d.parse_v3d_groups(model)
        if skin and len(skin)!=len(verts):raise ValueError('skin/source pool size differs')
        u=_mesh(verts,groups,texture)
        u.update(diffuseARGB=list(v3d.vertex_diffuse(model)),diffuseScope='raw-bind-diffuse-v1')
        material_source=data_dir('scripts','bugs',uid+'.vsc')
        u.update(radius=spec.radius,radiusSource='scripts/bugs/'+uid+'.vsc',
                 radiusSourceSHA256=_sha(material_source))
        for index,g in enumerate(u['groups']):
            values=spec.props.get('Material'+str(index))
            if values is not None and (len(values)!=1 or not isinstance(values[0],str) or not values[0] or len(values[0].split())!=1):
                raise ValueError('unsupported unit material declaration')
            g['unitMaterial']={'name':values[0] if values else None,'groupIndex':index,
                'source':'scripts/bugs/'+uid+'.vsc','sourceSHA256':_sha(material_source),
                'bindingScope':'script-unit-material-v1'}
        lows=[min(v[0][i] for v in verts) for i in range(3)];highs=[max(v[0][i] for v in verts) for i in range(3)]
        u.update(unitId=uid,modelSource=os.path.relpath(model,data_dir()),modelSHA=_sha(model),frameBasis='raw-model-v1',rootApplied=False,
                 scaleApplied=False,rootPolicy='engineering-fixed-S-v1',rootMatrix=list(ROOT_MATRIX),
                 coordinatePolicy='raw-to-engine-yup-Q-v1',anchorPolicy='raw-bind-ground-pivot-v1',
                 anchor=[(lows[0]+highs[0])/2,lows[1],(lows[2]+highs[2])/2],
                 scaleFactor=bake.unit_world_scale(uid),clips={})
        skinnable=bool(skin) and len(skin)==len(verts) and sum(bool(inf) and all(bi<len(recs) for bi,_ in inf) for _,_,inf in skin)>.9*len(skin)
        bind=pose.worlds_from_records(recs) if skinnable else None
        if skinnable:pose._source_uvs(skin,verts)
        binary=bytearray()
        for key in CLIP_KEYS:
            ref=spec.anims.get(key);path=bake._resolve_model(ref,'.van') if ref else None
            if not ref:
                u['clips'][key]={'kind':'missing','ref':None,'frames':[],'sampleTimes':[],'fallbackClip':None,'loop':key in ('walk','idle')};continue
            if path is None:raise FileNotFoundError(f'{uid}/{key}: named animation {ref}')
            consume(path);blocks=van.parse_van(path);keys=next((b for b in blocks if b),None)
            if keys is None or not math.isfinite(keys[-1][0]) or keys[-1][0]<=0:raise ValueError(f'{uid}/{key}: invalid animation duration')
            duration=keys[-1][0];n=min(max_frames,max(min_frames,math.ceil(duration*sample_hz))) if skinnable else 1
            times=[duration*f/n for f in range(n)];frames=[]
            for t in times:
                posed=pose.skin_at(skin,bind,pose.worlds_at(recs,blocks,t),source_vertices=verts) if skinnable else verts
                frame={}
                for field,index in (('positions',0),('normals',1)):
                    values=[x for v in posed for x in v[index]]
                    frame[field]={'offset':len(binary),'count':len(values)}
                    binary.extend(struct.pack('<'+str(len(values))+'f',*values))
                frames.append(frame)
            u['clips'][key]={'kind':'sampled' if skinnable else 'static','ref':ref,'sourceSHA':_sha(path),'duration':duration,'loop':key in ('walk','idle'),'sampleTimes':times,'frames':frames}
        fallback=next((k for k in ('walk','idle') if u['clips'][k]['kind']!='missing'),None)
        for c in u['clips'].values():
            if c['kind']=='missing':c['fallbackClip']=fallback
        frame_file='assets/geometry/'+hashlib.sha256(uid.encode()).hexdigest()[:24]+'-frames.bin'
        u['frameBuffer']={'format':FRAME_FORMAT,'file':frame_file,'byteLength':len(binary),
                          'sha256':hashlib.sha256(binary).hexdigest()}
        validate_frame_buffer(u,binary)
        (package/frame_file).write_bytes(binary);frame_files.append(frame_file)
        scene['units'][uid]=u
    for name in sorted(set(worlds)):
        wd=world_data[name]
        if wd.basis_version!='loaded-yup-v1':raise ValueError('engine mesh world requires explicit loaded-yup-v1 terrain')
        consume(data_dir('worlds',name+'.vsc'))
        variant_instances={}
        for variant in selections[name]:
          instances=[]
          for flower in wd.flowers:
            selected=flower_asset_spec(flower.flower_type,rescue=variant=='rescue')
            asset=selected['assetId']
            if asset not in scene['props']:
                model=bake._resolve_model('props/'+asset,'.v3d')
                if model is None:raise FileNotFoundError('named flower model props/'+asset+'.v3d')
                consume(model);verts,groups,skin,recs=v3d.parse_v3d_groups(model)
                p=_mesh(verts,groups,texture)
                p.update(assetId=asset,modelSource=os.path.relpath(model,data_dir()),modelSHA=_sha(model),
                         frameBasis='raw-model-v1',rootApplied=False,scaleApplied=False,
                         # R140/R141 same flower loader applies this raw-row S.
                         # Owner and animation remain separate, unverified contracts.
                         rootMatrix=list(ROOT_MATRIX),rootPolicy='original-load-bind-S-v1',
                         coordinatePolicy='raw-to-engine-yup-Q-v1',anchorPolicy='raw-model-origin-v1',
                         animationScope='raw-bind-only-unverified',nodeCount=len(recs),skinVertices=len(skin))
                attachment=bind_attachment(recs)
                p['attachments']={'nektar':attachment} if attachment else {}
                if asset in flower_rigs:
                    p.update(animationScope='normal-flower-node-keys-v1',
                             animationRig=flower_rigs[asset],
                             animationRigJson=json.dumps({k:v for k,v in flower_rigs[asset].items()
                                                          if k!='rigSHA256'},sort_keys=True,
                                                         separators=(',',':'),allow_nan=False),
                             animationSkin=[[list(pos),list(normal),[list(i) for i in influences]]
                                            for pos,normal,influences in skin])
                if asset=='flower_a':
                    # R220 same-state UV differential and original normal flower
                    # screenshots support this asset; other materials are unverified.
                    p.update(textureVFlip=False,textureUvScope='observed-normal-flower-a-v1')
                scene['props'][asset]=p
            direction=list(flower.direction)
            instances.append(dict(selected,name=flower.name,flowerType=flower.flower_type,rescue=variant=='rescue',
                positionYup=list(flower.grid_pos),directionYup=direction,directionRaw=[direction[2],-direction[0],-direction[1]],
                ownerMatrix=flower_owner_matrix(direction),parentMatrix=list(PROP_IDENTITY),
                ownerPolicy='engineering-orthonormal-raw-x-forward-v1',
                transformPolicy='engine-prop-v1',transformScope='engineering-bind-owner-v1'))
          variant_instances[variant]=instances
        meshes=[]
        if not props_only:
            for path in bake.terrain_source_paths(name):consume(path)
            meshes=bake.terrain_meshes(name)
        scene['worlds'][name]={'basisVersion':wd.basis_version,'meshes':[
            dict(_mesh(m.verts,bake.terrain_material_groups(m),texture),name=m.name) for m in meshes],
            **({'propVariants':variant_instances} if prop_variants_by_world is not None
               else {'propInstances':instances})}
    validate_geometry(scene)
    if any(_sha(p)!=h for p,h in source_hashes.items()):raise ValueError('geometry source changed during export')
    scene['inputHashes']={os.path.relpath(p,data_dir()):h for p,h in sorted(source_hashes.items())}
    blob=json.dumps(scene,separators=(',',':'),allow_nan=False).encode();rel='assets/geometry/scene.json';(Path(out_dir)/rel).write_bytes(blob)
    result={'file':rel,'sha256':hashlib.sha256(blob).hexdigest(),'source_paths':sorted(sources),'inputHashes':scene['inputHashes'],'unitIds':sorted(scene['units']),'worlds':sorted(scene['worlds']),'files':[rel]+frame_files+[t['file'] for t in textures.values()]}
    if prop_variants_by_world is not None:result['propVariants']={w:sorted(v) for w,v in selections.items()}
    return result

def export_flower_geometry_assets(worlds, *, out_dir, rescue_worlds=None,prop_variants_by_world=None):
    """Real props-only packet; no unit animation sampling or terrain export."""
    return export_geometry_assets((),worlds,pose_policy=POSE_POLICY,out_dir=out_dir,
                                  props_only=True,rescue_worlds=rescue_worlds,
                                  prop_variants_by_world=prop_variants_by_world)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--world',action='append',default=[]);a=p.parse_args()
    out=Path(a.out).absolute();root=Path(__file__).resolve().parents[2]
    if not out.is_relative_to(root/'out') or any(q.is_symlink() for q in (out,*out.parents)) or out.exists():raise ValueError('new project out directory required')
    result=export_geometry_assets(unitdb.load_all(),a.world,out_dir=out,pose_policy=POSE_POLICY)
    print(json.dumps(result));return 0

if __name__=='__main__':raise SystemExit(main())
