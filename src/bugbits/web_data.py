"""Web 数据导出 schema（W1）：LevelData/WorldData/UnitSpec ⇄ JSON。

to_dict/restore_* 是导出（tools/web_build.py）与运行时恢复（web_bridge/浏览器）
的唯一 schema 事实源——两端共用本模块，避免双实现漂移。
恢复类型必须与原解析对象逐字段相等（harness/web A05 断言）：
tuple/set/数字键/脚本保序/Unicode/None≠0 都不丢（JSON 数组→tuple、邻接→set）。
纯 stdlib + dataclasses——Pyodide 可用；禁止 IO 与原文件装载。
"""
from bugbits.level import LevelData, light_tokens
import copy
import json
from bugbits.assets.flower_pose import CONTRACT as FLOWER_RIG_CONTRACT, validate_rig
from bugbits.unitdb import UnitSpec
from bugbits.worlddb import (Flower, Light, Start, Waypoint, WorldData,
                            LEGACY_BASIS_VERSION, LOADED_BASIS_VERSION,
                            validate_loaded_world_values)

SCHEMA_VERSION = 2


# ── LevelData ────────────────────────────────────────────────────────
def level_to_dict(lv):
    return {
        "props": lv.props,
        "bugSetups": [list(t) for t in lv.bug_setups],
        "setLanes": [list(t) for t in lv.set_lanes],
        "scripts": [[sub, list(args)] for sub, args in lv.scripts],
        "unlock": lv.unlock,
        "lightRequests": [list(light_tokens(args)) for args in lv.light_requests],
    }


def restore_level(d):
    return LevelData(
        props={k: list(v) for k, v in d["props"].items()},
        bug_setups=[(int(a), str(b), int(c)) for a, b, c in d["bugSetups"]],
        set_lanes=[(int(a), int(b)) for a, b in d["setLanes"]],
        scripts=[(str(s), [str(a) for a in args]) for s, args in d["scripts"]],
        unlock=d.get("unlock"),
        light_requests=[light_tokens(args) for args in d.get("lightRequests", [])],
    )


# ── WorldData ────────────────────────────────────────────────────────
def _vec3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def world_to_dict(w):
    rigs = _flower_rigs(w.flower_rigs, w.flowers, required=w.world_id is not None)
    if w.basis_version not in (LEGACY_BASIS_VERSION, LOADED_BASIS_VERSION):
        raise ValueError("unknown world basis")
    if w.basis_version == LEGACY_BASIS_VERSION and w.basis_assumptions:
        raise ValueError("legacy world cannot carry loaded-basis assumptions")
    if w.basis_version == LOADED_BASIS_VERSION:
        validate_loaded_world_values(
            static_position=w.static_position, static_direction=w.static_direction,
            static_scale=w.static_scale, basis_assumptions=w.basis_assumptions,
            terrain=w.terrain,
            entity_vectors=[v for e in w.flowers + w.lights + w.starts + w.waypoints
                            for v in (e.grid_pos, e.direction)])
    return {
        "worldId": w.world_id,
        "flowerRigContract": FLOWER_RIG_CONTRACT if rigs else None,
        "flowerRigs": copy.deepcopy(rigs),
        # Keep the signed source text across JS JSON.stringify; its Number
        # encoding erases Python float/integer spelling and signed zero.
        "flowerRigJsons": {asset: json.dumps({k: v for k, v in rig.items() if k != 'rigSHA256'},
            sort_keys=True, separators=(',', ':'), allow_nan=False) for asset, rig in rigs.items()},
        "worldBasisVersion": w.basis_version,
        "staticPosition": list(w.static_position),
        "staticDirection": list(w.static_direction),
        "staticScale": w.static_scale,
        "loadedBasisAssumptions": list(w.basis_assumptions),
        "props": w.props,
        "flowers": [{"name": f.name, "pos": list(f.grid_pos),
                     "dir": list(f.direction), "type": f.flower_type}
                    for f in w.flowers],
        "lights": [{"name": l.name, "pos": list(l.grid_pos),
                    "dir": list(l.direction)} for l in w.lights],
        "staticModel": w.static_model,
        "starts": [{"name": s.name, "pos": list(s.grid_pos),
                    "dir": list(s.direction), "sideId": s.side_id,
                    "index": s.index, "connectTo": list(s.connect_to),
                    "water": bool(s.water)}
                   for s in w.starts],
        "waypoints": [{"name": x.name, "pos": list(x.grid_pos),
                       "dir": list(x.direction), "water": bool(x.water),
                       "connectTo": list(x.connect_to)} for x in w.waypoints],
        "edges": w.edges,
        # adjacency: set → 排序 list（确定性; 恢复回 set）
        "adjacency": {k: sorted(v) for k, v in w.adjacency.items()},
        "terrain": list(w.terrain) if w.terrain else None,
    }


def _flower_rigs(rigs, flowers, *, required=False):
    if not isinstance(rigs,dict):raise ValueError('flower rig mapping required')
    for asset,rig in rigs.items():
        validate_rig(rig)
        if asset not in ('flower_a','flower_b','cactus_a') or asset!=rig['assetId']:
            raise ValueError('flower rig asset identity differs')
        if (rig['modelSource']!='models/props/'+asset+'.v3d' or
                rig['animationSource']!='models/props/'+asset+'.van'):
            raise ValueError('flower rig source path differs')
    if rigs or required:
        names={1:'flower_a',2:'flower_b',3:'cactus_a'}
        if any(names[f.flower_type] not in rigs for f in flowers if f.flower_type in names):
            raise ValueError('normal flower rig missing')
    return rigs


def validate_world_rig_sources(world, input_hashes):
    """Package-only source closure; never reads original resources."""
    _flower_rigs(world.flower_rigs,world.flowers,required=world.world_id is not None)
    for rig in world.flower_rigs.values():
        for path,sha in (('modelSource','modelSHA'),('animationSource','animationSHA')):
            if input_hashes.get(rig[path])!=rig[sha]:
                raise ValueError('world flower rig outside original input closure')


def _same_wire_rig_value(source, wire):
    if type(source) in (int, float) and type(wire) in (int, float):
        return source == wire  # JSON Number permits 0/0.0 and +/-0, never bool.
    if type(source) is not type(wire):
        return False
    if isinstance(source, dict):
        return source.keys() == wire.keys() and all(_same_wire_rig_value(v, wire[k])
                                                    for k, v in source.items())
    if isinstance(source, list):
        return len(source) == len(wire) and all(_same_wire_rig_value(a, b) for a, b in zip(source, wire))
    return source == wire


def restore_world(d):
    contract=d.get('flowerRigContract')
    rigs=d.get('flowerRigs',{})
    if (contract not in (None,FLOWER_RIG_CONTRACT) or
            bool(rigs)!=(contract==FLOWER_RIG_CONTRACT)):
        raise ValueError('flower rig contract differs')
    if 'flowerRigJsons' in d and rigs:
        texts = d['flowerRigJsons']
        if not isinstance(texts, dict) or set(texts) != set(rigs):
            raise ValueError('flower rig source text mapping differs')
        restored = {}
        for asset, rig in rigs.items():
            text = texts[asset]
            if not isinstance(text, str):
                raise ValueError('flower rig source text required')
            decoded = json.loads(text)
            if text != json.dumps(decoded, sort_keys=True, separators=(',', ':'), allow_nan=False):
                raise ValueError('flower rig canonical source text required')
            if not isinstance(rig, dict) or not _same_wire_rig_value(decoded,
                    {k: v for k, v in rig.items() if k != 'rigSHA256'}):
                raise ValueError('flower rig source text values differ')
            # validate_rig still checks the original strict SHA and shape. The
            # decoded source owns all numeric stores; no re-signing takes place.
            restored[asset] = validate_rig(dict(decoded, rigSHA256=rig.get('rigSHA256')))
        rigs = restored
    world_id=d.get('worldId')
    if world_id is not None and (type(world_id) is not str or not world_id):
        raise ValueError('world ID required')
    new_fields = {"staticPosition", "staticDirection", "staticScale", "loadedBasisAssumptions"}
    if "worldBasisVersion" not in d:
        if new_fields.intersection(d):
            raise ValueError("new world metadata requires worldBasisVersion")
        basis = LEGACY_BASIS_VERSION  # Explicit historical shape migration only.
    else:
        basis = d["worldBasisVersion"]
        if basis not in (LEGACY_BASIS_VERSION, LOADED_BASIS_VERSION):
            raise ValueError("unknown worldBasisVersion")
        if not new_fields.issubset(d):
            raise ValueError("versioned world requires complete owner metadata")
    assumptions_raw = d.get("loadedBasisAssumptions", ())
    if basis == LOADED_BASIS_VERSION:
        validate_loaded_world_values(
            static_position=d["staticPosition"], static_direction=d["staticDirection"],
            static_scale=d["staticScale"], basis_assumptions=assumptions_raw,
            terrain=d.get("terrain"),
            entity_vectors=[e[k] for collection in ("flowers", "lights", "starts", "waypoints")
                            for e in d[collection] for k in ("pos", "dir")])
    assumptions = tuple(assumptions_raw)
    if basis == LEGACY_BASIS_VERSION and assumptions:
        raise ValueError("legacy world cannot carry loaded-basis assumptions")
    result = WorldData(
        props={k: list(v) for k, v in d["props"].items()},
        flowers=[Flower(f["name"], _vec3(f["pos"]), _vec3(f["dir"]),
                        int(f["type"])) for f in d["flowers"]],
        lights=[Light(l["name"], _vec3(l["pos"]), _vec3(l["dir"]))
                for l in d["lights"]],
        static_model=d["staticModel"],
        starts=[Start(s["name"], _vec3(s["pos"]), _vec3(s["dir"]),
                      int(s["sideId"]), int(s["index"]), list(s["connectTo"]),
                      bool(s.get("water", False)))
                for s in d["starts"]],
        waypoints=[Waypoint(x["name"], _vec3(x["pos"]), _vec3(x["dir"]),
                            bool(x["water"]), list(x["connectTo"]))
                   for x in d["waypoints"]],
        edges=int(d["edges"]),
        adjacency={k: set(v) for k, v in d["adjacency"].items()},
        terrain=tuple(d["terrain"]) if d.get("terrain") else None,
        basis_version=basis,
        static_position=_vec3(d.get("staticPosition", (0., 0., 0.))),
        static_direction=_vec3(d.get("staticDirection", (1., 0., 0.))),
        static_scale=float(d.get("staticScale", 1.)),
        basis_assumptions=assumptions,
        world_id=world_id,
        flower_rigs=copy.deepcopy(rigs),
    )
    _flower_rigs(result.flower_rigs,result.flowers,required=world_id is not None)
    return result


# ── UnitSpec ─────────────────────────────────────────────────────────
def unit_to_dict(spec):
    return {
        "name": spec.name,
        "price": spec.price,
        "priority": spec.priority,
        "reloadTime": spec.reload_time,
        "canFly": spec.can_fly,
        "canGather": spec.can_gather,
        "model": spec.model,
        "anims": dict(spec.anims),
        "props": spec.props,
        "infoProps": spec.info_props,
        "attackHitFrames": list(spec.attack_hit_frames),
        "attackDuration": spec.attack_duration,
        "walkDuration": spec.walk_duration,
    }


def restore_unit(d):
    from bugbits import unitdb
    spec = UnitSpec(
        name=d["name"],
        price=d.get("price"),
        priority=d.get("priority"),
        reload_time=d.get("reloadTime"),
        can_fly=bool(d.get("canFly")),
        can_gather=bool(d.get("canGather")),
        model=d.get("model"),
        anims=dict(d.get("anims") or {}),
        props={k: list(v) for k, v in (d.get("props") or {}).items()},
        info_props={k: list(v) for k, v in (d.get("infoProps") or {}).items()},
        attack_hit_frames=tuple(float(x) for x in d.get("attackHitFrames") or []),
        attack_duration=d.get("attackDuration"),
        walk_duration=d.get("walkDuration"),
    )
    # 动态 typed 属性（speed/melee_damage 等）由 props 重推导——与原解析
    # 共用 unitdb.apply_props（W2 B01：dataclass 字段比对抓不出的假绿）
    unitdb.apply_props(spec)
    return spec


def restore_units(d):
    return {name: restore_unit(spec) for name, spec in d.items()}
