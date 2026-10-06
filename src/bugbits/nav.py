"""寻路与移动层（T4.3→T5.6 校准）: 路点图 Dijkstra 最短路 + 弧长插值 + 飞行/地面/水域三层。

纯模块（D4: 无 IO）——消费 WorldData 数据结构。
三层语义（T5.6 校准后）:
  ground  沿 waypoint 折线; 水域段无通用减速（H10 证伪）——单位特例
          giantwaterbeetle ×1.5 见 sim.consts.WATER_AFFINE
  air     飞行常态直线直飞, 返程采集蜂近图落地转图行（H13 部分证实/部分
          证伪: 仅返程蜂沿图）; 切片维持沿图插值 + FlyHeight
DirectionFactor 参与朝向混合及后续物理推进（REVIEW F4）。本切片仍为折线匀速，
未还原转向/加速动力学，不能宣称到达时间与 DirectionFactor 无关。
假设登记: docs/hypotheses-runtime.md; 引擎证据: docs/exe-econ.md
"""
import heapq
import math


class Route:
    """沿路点折线的路线: 节点序列 + 分段长度。

    段长 = 地面投影 (xz) 欧氏距离——y 是高度（地形起伏）不参与里程与寻路,
    仅在 position_at 中线性插值。
    """

    __slots__ = ("nodes", "points", "seg_len", "water_seg", "length")

    def __init__(self, nodes, points, water_seg):
        self.nodes = nodes                  # [实体名], 含起终点
        self.points = points                # [(x,y,z)] 各节点 grid_pos
        self.water_seg = water_seg          # [bool] 段 i 终点是否水路点
        self.seg_len = [math.hypot(b[0] - a[0], b[2] - a[2])
                        for a, b in zip(points, points[1:])]
        self.length = sum(self.seg_len)

    def seg_multiplier(self, i, layer):
        """段倍率。H10 证伪(T5.4): 引擎无通用水域减速——恒 1.0;
        单位特例(giantwaterbeetle ×1.5)在 sim._lane_mult 按单位查表。"""
        return 1.0

    def travel_time(self, speed, layer="ground"):
        """全程耗时 (秒) = Σ 段长 / (speed × 段倍率)。"""
        return sum(l / (speed * self.seg_multiplier(i, layer))
                   for i, l in enumerate(self.seg_len))

    def position_at(self, s, fly_height=None):
        """弧长 s 处的位置 (钳位到 [0, length]; 线性插值)。

        fly_height 给定时 (飞行层) y 恒为其值; 否则沿折线插值节点 y。
        """
        s = max(0.0, min(s, self.length))
        for i, l in enumerate(self.seg_len):
            if s <= l or i == len(self.seg_len) - 1:
                f = s / l if l > 0 else 0.0
                a, b = self.points[i], self.points[i + 1]
                p = (a[0] + (b[0] - a[0]) * f,
                     a[1] + (b[1] - a[1]) * f,
                     a[2] + (b[2] - a[2]) * f)
                if fly_height is not None:
                    return (p[0], fly_height, p[2])
                return p
            s -= l
        return self.points[-1]


def route_between(world, src, dst):
    """Dijkstra 最短路 → Route; 不可达或未知节点 → None。

    边权 = 节点地面投影欧氏距离 (x/z 平面; y 为高度不参与寻路)。
    """
    pos = {x.name: x.grid_pos for x in list(world.waypoints) + list(world.starts)}
    if src not in pos or dst not in pos:
        return None
    water = {x.name: x.water for x in world.waypoints}

    def ground_dist(a, b):
        return math.hypot(pos[a][0] - pos[b][0], pos[a][2] - pos[b][2])

    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    done = set()
    while pq:
        d, n = heapq.heappop(pq)
        if n in done:
            continue
        done.add(n)
        if n == dst:
            break
        for m in world.adjacency.get(n, ()):
            if m not in pos or m in done:
                continue
            nd = d + ground_dist(n, m)
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                prev[m] = n
                heapq.heappush(pq, (nd, m))
    if dst not in dist or (dst != src and dst not in prev):
        return None
    path, cur = [dst], dst
    while cur != src:
        cur = prev[cur]
        path.append(cur)
    path.reverse()
    pts = [pos[n] for n in path]
    wseg = [bool(water.get(n, False)) for n in path[1:]]
    return Route(path, pts, wseg)


def lane_route(world, lane_index):
    """路线 lane_index 的敌→我路线: start(1,lane) → start(0,lane)。"""
    src = world.start(1, lane_index)
    dst = world.start(0, lane_index)
    if src is None or dst is None:
        return None
    return route_between(world, src.name, dst.name)
