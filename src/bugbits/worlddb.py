"""世界装载层: worlds/*.vsc → 强类型 WorldData（T4.2）。

版本显式区分历史包络启发式 legacy-grid-v1 与条件装载 loaded-yup-v1。
loaded 实体 Q=(-B,-C,A)，模型边界消费 Q(W(S(p))+Position)；
原始 VSC/V3D 解析不改，skin/incoming I 与缺省 scale1 保留候选前提。
"""
import os
import math
from dataclasses import dataclass, field, replace

from bugbits.assets import v3d, vsc

LEGACY_BASIS_VERSION = "legacy-grid-v1"
LOADED_BASIS_VERSION = "loaded-yup-v1"
DEFAULT_BASIS_BY_WORLD = {"world_01": LOADED_BASIS_VERSION,
                          "world_02": LOADED_BASIS_VERSION,
                          "world_03": LOADED_BASIS_VERSION}


def _strict_finite_vector(value, size, label):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{label} requires exactly {size} numeric components")
    for component in value:
        if type(component) not in (int, float):
            raise ValueError(f"{label} components must be numeric, not bool/string")
        try:
            finite = math.isfinite(component)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{label} components must be finite")


def validate_loaded_world_values(*, static_position, static_direction, static_scale,
                                 basis_assumptions, terrain, entity_vectors):
    """Shared strict public loaded-data domain before any JSON coercion.

    Does not transform coordinates; R55 owns the supported model basis domain.
    Legacy packets retain their separately identified historical migration.
    """
    _strict_finite_vector(static_position, 3, "static Position")
    _strict_finite_vector(static_direction, 3, "static Direction")
    _strict_finite_vector((static_scale,), 1, "static ScaleFactor")
    if not isinstance(basis_assumptions, (list, tuple)) or any(type(a) is not str for a in basis_assumptions):
        raise ValueError("loaded assumptions must be a string list/tuple")
    required = {"skin-matrix-identity", "upstream-parent-identity"}
    actual = set(basis_assumptions)
    if (len(actual) != len(basis_assumptions) or not required.issubset(actual)
            or actual - required - {"missing-static-scale-assumed-one"}):
        raise ValueError("loaded world requires supported unique assumptions")
    if terrain is not None:
        _strict_finite_vector(terrain, 6, "terrain bounds")
    for value in entity_vectors:
        _strict_finite_vector(value, 3, "entity Position/Direction")
    from bugbits.assets import world_basis
    world_basis.loaded_model_vector(
        (0., 0., 0.), direction=static_direction, scale=static_scale,
        node_matrix=world_basis.IDENTITY, node_parent=-1,
        skin_matrix=world_basis.IDENTITY, parent_matrix=world_basis.IDENTITY)


@dataclass
class Flower:
    name: str
    grid_pos: tuple
    direction: tuple
    flower_type: int


@dataclass
class Light:
    name: str
    grid_pos: tuple
    direction: tuple


@dataclass
class Start:
    name: str
    grid_pos: tuple
    direction: tuple
    side_id: int
    index: int
    connect_to: list
    water: bool = False   # Inherited ceWayPoint +17C, not an entity-type flag.


@dataclass
class Waypoint:
    name: str
    grid_pos: tuple
    direction: tuple
    water: bool
    connect_to: list


@dataclass
class WorldData:
    props: dict
    flowers: list
    lights: list
    static_model: str
    starts: list
    waypoints: list
    edges: int
    adjacency: dict = field(default_factory=dict)
    terrain: tuple = None          # (xmin,xmax,ymin,ymax,zmin,zmax) Y-up
    basis_version: str = LEGACY_BASIS_VERSION
    static_position: tuple = (0., 0., 0.)  # Original owner components, not Q/S.
    static_direction: tuple = (1., 0., 0.)
    static_scale: float = 1.
    basis_assumptions: tuple = ()
    world_id: str = None
    flower_rigs: dict = field(default_factory=dict)

    def normal_level_view(self, is_reversed):
        """START properties applied in normal cLevel load mode (+112=0).

        49AD39 stores the raw SideID, then 49AD5B maps it to (raw==0) when
        IsReversed is nonzero. Keep parsed/exported input untouched so each
        normal session applies this once. Other level-load modes remain open.
        All other world data is shared read-only with the parsed input.
        """
        return replace(self, starts=[replace(start, side_id=(int(start.side_id == 0)
                       if is_reversed else start.side_id)) for start in self.starts])

    def directed_links(self):
        """Original ConnectTo categories: source130 outgoing, target154 incoming.

        Resolve only existing named nodes, as the original command lookup does.
        Valid unique static ASCII instance names have original unsigned order;
        runtime renaming/insertion belongs to the scene container, not this view.
        The legacy undirected adjacency remains an engineering query surface.
        """
        nodes = self.waypoints + self.starts
        by_name = {node.name: node for node in nodes}
        if len(by_name) != len(nodes):
            raise ValueError('directed route names must be unique')
        outgoing = {name:set() for name in by_name}
        incoming = {name:set() for name in by_name}
        for node in nodes:
            for target in node.connect_to:
                if target in by_name:
                    outgoing[node.name].add(target)
                    incoming[target].add(node.name)
        def ordered(links):
            return {name:tuple(sorted(targets, key=lambda value:value.encode('utf-8')))
                    for name, targets in links.items()}
        return ordered(outgoing), ordered(incoming)

    def start(self, side, index):
        """取指定 (SideID, Index) 的 START 锚点，无则 None。"""
        for s in self.starts:
            if s.side_id == side and s.index == index:
                return s
        return None

    def components(self):
        """路点图连通分量（无向），返回 [[实体名], ...]，按大小降序。

        仅统计参与 ≥1 条边的节点（寻路图语义）；无边孤立实体不算分量
        （实测 world_02: wp32/wp51 为设计残留, 度 0）。
        """
        seen, comps = set(), []
        for n in self.adjacency:
            if n in seen or not self.adjacency[n]:
                continue
            stack, comp = [n], []
            seen.add(n)
            while stack:
                x = stack.pop()
                comp.append(x)
                for y in self.adjacency[x]:
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
            comps.append(comp)
        return sorted(comps, key=len, reverse=True)


def _grid(p):
    """vsc Position (p0,p1,p2) → 网格 Y-up (x,y,z) = (p1,p2,p0)。"""
    return (p[1], p[2], p[0])


def parse_world(path, *, basis=None):
    """世界 .vsc → WorldData; default migrates only named world_01/02/03.

    Explicit loaded input outside the supported model domain raises ValueError;
    it never falls back to legacy when parsing/validation fails.
    """
    if basis is None:
        basis = DEFAULT_BASIS_BY_WORLD.get(os.path.splitext(os.path.basename(path))[0],
                                           LEGACY_BASIS_VERSION)
    if basis not in (LEGACY_BASIS_VERSION, LOADED_BASIS_VERSION):
        raise ValueError(f"unknown world basis: {basis!r}")
    if basis == LOADED_BASIS_VERSION:
        from bugbits.assets import world_basis
        convert = world_basis.to_yup
    else:
        convert = _grid
    props, spawns, blocks = {}, [], {}
    cur = None
    for _, cmd, args in vsc.parse_vsc(path):
        if cmd == "sp" and cur is None and args:
            props.setdefault(args[0], args[1:])
        elif cmd == "SpawnEntity":
            spawns.append((args[0], args[1]))
        elif cmd == ">":
            cur = args[0]
            blocks[cur] = {"sp": {}, "connect": []}
        elif cmd == "<":
            cur = None
        elif cmd == "ConnectTo" and cur:
            blocks[cur]["connect"].append(args[0])
        elif cmd == "sp" and cur and args:
            blocks[cur]["sp"].setdefault(args[0], args[1:])

    def fnum(block, key, i):
        return float(block["sp"][key][i])

    def fvec(block, key):
        result = tuple(float(x) for x in block["sp"][key])
        if basis == LOADED_BASIS_VERSION:
            _strict_finite_vector(result, 3, key)
        return result

    flowers, lights, starts, wps = [], [], [], []
    static_model = None
    static_position, static_direction, static_scale = (0., 0., 0.), (1., 0., 0.), 1.
    static_count, basis_assumptions = 0, ()
    for name, etype in spawns:
        b = blocks.get(name)
        if etype == "STATIC" and b and "Model" in b["sp"]:
            static_count += 1
            static_model = b["sp"]["Model"][0]
            if basis == LOADED_BASIS_VERSION and not all(k in b["sp"] for k in ("Position", "Direction")):
                raise ValueError("loaded world requires explicit STATIC Position/Direction")
            static_position = fvec(b, "Position") if "Position" in b["sp"] else (0., 0., 0.)
            static_direction = fvec(b, "Direction") if "Direction" in b["sp"] else (1., 0., 0.)
            static_scale = fnum(b, "ScaleFactor", 0) if "ScaleFactor" in b["sp"] else 1.
            if basis == LOADED_BASIS_VERSION:
                basis_assumptions = ("skin-matrix-identity", "upstream-parent-identity")
                if "ScaleFactor" not in b["sp"]:
                    basis_assumptions += ("missing-static-scale-assumed-one",)
        if b is None or "Position" not in b["sp"]:
            if etype == "STATIC" and b and "Model" in b["sp"]:
                static_model = b["sp"]["Model"][0]
            continue
        gp = convert(fvec(b, "Position"))
        d = world_basis.to_yup(fvec(b, "Direction")) if basis == LOADED_BASIS_VERSION else fvec(b, "Direction")
        if etype == "FLOWER":
            flowers.append(Flower(name, gp, d, int(fnum(b, "FlowerType", 0))))
        elif etype == "LIGHT":
            lights.append(Light(name, gp, d))
        elif etype == "START":
            starts.append(Start(name, gp, d, int(fnum(b, "SideID", 0)),
                                int(fnum(b, "Index", 0)), list(b["connect"]),
                                fnum(b, "Water", 0) != 0.0 if "Water" in b["sp"] else False))
        elif etype == "WAYPOINT":
            wps.append(Waypoint(name, gp, d, fnum(b, "Water", 0) != 0.0, list(b["connect"])))
        elif etype == "STATIC":
            static_model = b["sp"].get("Model", [None])[0]

    edges, adjacency = 0, {}
    for n in [w.name for w in wps] + [s.name for s in starts]:
        adjacency.setdefault(n, set()).update(blocks[n]["connect"])
        edges += len(blocks[n]["connect"])
        for m in blocks[n]["connect"]:
            adjacency.setdefault(m, set()).add(n)

    terrain = None
    if basis == LOADED_BASIS_VERSION and static_count != 1:
        raise ValueError("loaded world requires exactly one STATIC model owner")
    if static_model:
        # path = <data>/worlds/xxx.vsc → <data>/models/<static_model>.v3d
        models_dir = os.path.dirname(os.path.dirname(path))
        mp = os.path.join(models_dir, "models", *static_model.split("/")) + ".v3d"
        meshes = v3d.parse_world_meshes(mp)
        if basis == LOADED_BASIS_VERSION:
            meshes = world_basis.loaded_world_meshes(
                meshes, static_position, direction=static_direction, scale=static_scale,
                skin_matrix=world_basis.IDENTITY, parent_matrix=world_basis.IDENTITY)
        vs = [v[0] for m in meshes for v in m.verts]
        if not vs:
            raise ValueError("world terrain has no vertices")
        terrain = (min(x[0] for x in vs), max(x[0] for x in vs),
                   min(x[1] for x in vs), max(x[1] for x in vs),
                   min(x[2] for x in vs), max(x[2] for x in vs))

    result = WorldData(props, flowers, lights, static_model, starts, wps,
                       edges, adjacency, terrain, basis, static_position,
                       static_direction, static_scale, basis_assumptions)
    from bugbits.assets.flower_pose import load_normal_rig
    result.world_id = os.path.splitext(os.path.basename(path))[0]
    assets = {1:'flower_a',2:'flower_b',3:'cactus_a'}
    result.flower_rigs = {asset:load_normal_rig(asset)
                         for asset in sorted({assets[f.flower_type] for f in flowers
                                              if f.flower_type in assets})}
    if basis == LOADED_BASIS_VERSION:
        validate_loaded_world_values(
            static_position=static_position, static_direction=static_direction,
            static_scale=static_scale, basis_assumptions=basis_assumptions, terrain=terrain,
            entity_vectors=[v for e in flowers + lights + starts + wps for v in (e.grid_pos, e.direction)])
    return result
