"""BugBits CLI 入口。

用法:
  python3 tools/bugbits.py info                 # 安装根/数据目录/关键资产计数
  python3 tools/bugbits.py smoke-ant [--size N] [--out DIR]
                                               # t22 parity 渲染冒烟 (ant 四帧 PNG)
  python3 tools/bugbits.py scene [--size N] [--out DIR] [--hud]
                                               # level_02 静态场景 (地形+花+巢+单位+HUD)
  python3 tools/bugbits.py play [--seed N] [--render]
                                               # E2E 对局 (bot 驱动 level_02 全流程)
"""
import os
import sys

from PIL import Image

from bugbits.assets import data_dir, game_root
from bugbits.assets import pose, v3d, van, vtx
from bugbits.render import software


def _cmd_info(_args):
    root = game_root()
    print(f"游戏根: {root}")
    print(f"data/: {os.path.join(root, 'data')} (存在: {os.path.isdir(os.path.join(root, 'data'))})")

    def count(sub, ext):
        n = 0
        for _, _, fs in os.walk(data_dir(sub)):
            n += sum(1 for f in fs if f.endswith(ext))
        return n

    print(f"资产: .v3d={count('models', '.v3d')} .van={count('models', '.van')} "
          f".vtx={count('textures', '.vtx')} .vfm={count('fontmetrics', '.vfm')}")
    return 0


def _cmd_smoke_ant(args):
    size = int(args[args.index("--size") + 1]) if "--size" in args else 640
    out = args[args.index("--out") + 1] if "--out" in args else "out"
    os.makedirs(out, exist_ok=True)
    (verts, idx, k), skin, recs, tex_name = v3d.parse_v3d(
        data_dir("models", "bugs", "ant.v3d"))
    print(f"ant.v3d: {len(verts)} 顶点/{len(idx)} 索引(k={k})/蒙皮 {len(skin)}/"
          f"节点 {len(recs)}/蒙皮段纹理 {tex_name!r}")
    _, _, _, _, tex = vtx.parse_vtx(data_dir("textures", tex_name + ".vtx"))
    blocks = van.parse_van(data_dir("models", "bugs", "ant_walk.van"))
    dur = blocks[0][-1][0]
    bind = pose.worlds_from_records(recs)
    for tag, use in (("shape", False), ("tex", True)):
        img, tris = software.render(verts, idx, tex, size=size, use_tex=use)
        path = os.path.join(out, f"ant_render_{tag}.png")
        img.save(path)
        print(f"渲染[{tag}]: {tris} 三角形 → {path}")
    for tag, t in (("bind", 0.0), ("walk50", dur * 0.5)):
        posed = pose.skin_at(skin, bind, pose.worlds_at(recs, blocks, t),
                             source_vertices=verts)
        img, tris = software.render(posed, idx, tex, size=size, use_tex=False)
        path = os.path.join(out, f"ant_anim_{tag}.png")
        img.save(path)
        xs = [v[0][0] for v in posed]
        ys = [v[0][1] for v in posed]
        print(f"动画[{tag}] t={t:.2f}s: {tris} 三角形, "
              f"bounds x[{min(xs):.1f},{max(xs):.1f}] y[{min(ys):.1f},{max(ys):.1f}]")
    return 0


def _cmd_scene(args):
    """静态场景: level_02 地形 + 花 + 双巢 + 三只蚁 → PNG + ASCII（人工抽验用）。"""
    size = int(args[args.index("--size") + 1]) if "--size" in args else 512
    out = args[args.index("--out") + 1] if "--out" in args else "out"
    os.makedirs(out, exist_ok=True)
    from bugbits import level as levelmod, worlddb
    from bugbits.render import bake, scene as scenemod, software

    w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
    lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
    terrain = bake.bake_terrain("world_02", size=size)
    sprites = bake.bake_unit_sprites(["ant", "littlebeetle", "bee"], frames=1,
                                     yaws=8, size=128)
    flower = bake.bake_flower_sprite(128)
    sc = scenemod.Scene(terrain, sprites, flower=flower, bounds=(
        w.terrain[0], w.terrain[1], w.terrain[4], w.terrain[5]))
    s0, s1 = w.start(0, 0), w.start(1, 0)
    ents = [("ant", s0.grid_pos[0], s0.grid_pos[2], 0.0),
            ("littlebeetle", w.start(0, 1).grid_pos[0], w.start(0, 1).grid_pos[2], 45.0),
            ("bee", w.start(0, 2).grid_pos[0], w.start(0, 2).grid_pos[2], 90.0)]
    flowers = [(f.grid_pos[0], f.grid_pos[2]) for f in w.flowers]
    hives = [(0, *s0.grid_pos), (1, *w.start(1, 0).grid_pos)]
    img = sc.compose_frame(ents, flowers=flowers, hives=hives)
    if "--hud" in args:
        from bugbits import unitdb
        from bugbits.assets import vln
        from bugbits.render.ui import font as uifont, shell as uishell
        texts = vln.parse_vln(data_dir("scripts", "lang4.vln"))
        f = uifont.FontAtlas.load_cn()
        hud = uishell.Hud(f)
        units = unitdb.load_all()
        snap = {"nectar": lv.initial_nectar, "title": texts.get(lv.name_text, ""),
                "buy": [(texts.get(f"BUGNAME_{u.upper()}", u),
                         int(units[u].price or 0), True)
                        for u in ("ant", "littlebeetle", "bee")],
                "hint": texts.get("HINT_DAMAGEDBASE", "")}
        img = Image.alpha_composite(img.convert("RGBA"),
                                    hud.render(snap, img.size)).convert("RGB")
    p = os.path.join(out, "scene_level_02.png")
    img.save(p)
    print(f"场景 {img.size} → {p}")
    print(software.ascii_preview(img))
    print(f"# 花 {len(flowers)} 巢 2 单位 3; 占位巢已标注 placeholder"
          + ("; HUD 叠层" if "--hud" in args else ""))
    return 0


def _cmd_play(args):
    """E2E 对局: bot 驱动 level_02 全流程 headless（买兵→采集→战斗→敌波→胜负）。"""
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 2026
    out = args[args.index("--out") + 1] if "--out" in args else "out"
    from bugbits import bot as botmod, level as levelmod, scriptvm, sim as simmod
    from bugbits import unitdb, worlddb

    w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
    lv = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
    sim = simmod.Sim(lv, w, unitdb.load_all(), seed=seed)
    vm = scriptvm.ScriptVM(sim, lv)
    b = botmod.Bot()
    import time
    t0 = time.time()
    while sim.tick < 20000 and sim.winner is None:
        sim.step()
        vm.on_tick()
        b.on_tick(sim)
    dt = time.time() - t0
    print(f"对局结果: winner={'玩家' if sim.winner == 0 else '敌方' if sim.winner == 1 else '无'}"
          f" tick={sim.tick} ({sim.tick / 20:.1f}s 游戏时间) 墙钟={dt:.1f}s")
    print(f"我方买兵 {sum(1 for e in sim.events if e[1] == 'buy' and e[2][0] == 0)} 次 | "
          f"存款 {sum(1 for e in sim.events if e[1] == 'deposit')} 次 | "
          f"敌巢受击 {sum(1 for e in sim.events if e[1] == 'hive_damage')} 次 | "
          f"我巢 HP {sim.hives[0].hp}/{lv.player_base_size}")
    if "--render" in args:
        from bugbits.assets import vln
        from bugbits.render import bake, scene as scenemod, software
        from bugbits.render.ui import font as uifont, shell as uishell
        os.makedirs(out, exist_ok=True)
        terrain = bake.bake_terrain("world_02", size=512)
        sprites = bake.bake_unit_sprites(["ant", "littlebeetle", "bee"], frames=1,
                                         yaws=8, size=128)
        sc = scenemod.Scene(terrain, sprites, flower=bake.bake_flower_sprite(128),
                            bounds=(w.terrain[0], w.terrain[1], w.terrain[4], w.terrain[5]))
        ents = [(x.unit_name, x.pos(sim)[0], x.pos(sim)[2], 0.0)
                for x in sim.bugs if not x.dead]
        flowers = [(f.grid_pos[0], f.grid_pos[2]) for f in w.flowers]
        hives = [(0, *w.start(0, 0).grid_pos), (1, *w.start(1, 0).grid_pos)]
        frame = sc.compose_frame(ents, flowers=flowers, hives=hives)
        texts = vln.parse_vln(data_dir("scripts", "lang4.vln"))
        f = uifont.FontAtlas.load_cn()
        hud = uishell.Hud(f)
        units = unitdb.load_all()
        snap = {"nectar": sim.nectar[0], "title": texts.get(lv.name_text, ""),
                "buy": [(texts.get(f"BUGNAME_{u.upper()}", u), int(units[u].price or 0),
                         sim.nectar[0] >= int(units[u].price or 0))
                        for u in ("ant", "littlebeetle", "bee")],
                "hint": "对局终局帧"}
        frame = Image.alpha_composite(frame.convert("RGBA"),
                                      hud.render(snap, frame.size)).convert("RGB")
        p = os.path.join(out, "play_final.png")
        frame.save(p)
        print(f"终局帧 → {p}")
        print(software.ascii_preview(frame))
    return 0


COMMANDS = {"info": _cmd_info, "smoke-ant": _cmd_smoke_ant, "scene": _cmd_scene,
            "play": _cmd_play}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    cmd = COMMANDS.get(argv[0])
    if cmd is None:
        print(f"未知命令: {argv[0]}\n{__doc__}", file=sys.stderr)
        return 2
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
