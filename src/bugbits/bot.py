"""bot — 确定性 build order 状态机（T4.7; T6.2 参数面扩展）。

定位（master-plan）: **切片驱动器，非验证对象**——参数全部暴露，用于驱动
各类型关全流程对局。策略: 免费蚁补足采集编队攒蜜; 按节奏买攻击/守军单位
（attack_lanes 多 lane 轮换; garrison=在场维持数, None=蜜够就出）。
只走 sim 公共接口（D4: 不 import sim 内部）。
"""


class Bot:
    def __init__(self, gather_ants=4, attack_unit="littlebeetle",
                 attack_lane=0, attack_every=1, attack_lanes=None,
                 garrison=None, side=0, defend=False):
        self.side = side                            # 阵营（T6.4: 敌我同构对局）
        self.gather_ants = gather_ants        # 采集编队规模（ant 免费）
        self.attack_unit = attack_unit        # 攻击/守军单位名
        self.attack_lanes = list(attack_lanes) if attack_lanes else [attack_lane]
        self.attack_every = attack_every      # 出兵最小间隔（tick）
        self.garrison = garrison              # 守军维持数; None=蜜够就出（T6.2）
        self.defend = defend                  # True=守军驻守本巢不行军攻敌（T6.7 语义）
        self._last_attack = 0
        self._attacks = 0
        self._li = 0                          # attack_lanes 轮换游标

    def on_tick(self, sim):
        """确定性策略（无随机; 读 sim 公共状态）。"""
        # 1) 免费采集蚁补足编队（ant Price 0）。
        #    OFR-02B：泳道冷却下不能再单泳道瞬间铺满——跨可用泳道分散买（每泳道每 10s
        #    一只），与引擎 setflow 按泳道相位出兵同向。旧「全买 lane 0」在冷却门禁下
        #    退化为一泳道一蚁/10s，属旧策略被正确门禁暴露，非机制错误。
        ants = sum(1 for b in sim.bugs
                   if b.side == self.side and b.unit_name == "ant" and not b.dead)
        need = self.gather_ants - ants
        if need > 0:
            lanes = [i for i in range(4)
                     if sim.world.start(self.side, i) is not None]
            for lane in lanes:
                if need <= 0:
                    break
                if sim.buy(self.side, "ant", lane) is not None:
                    need -= 1
        # 2) 攻击/守军单位按节奏出兵（多 lane 轮换; garrison 维持在场数）
        spec = sim.units.get(self.attack_unit)
        if spec is None:
            return
        price = int(spec.price or 0)
        if self.garrison is not None:
            army = sum(1 for b in sim.bugs
                       if b.side == self.side and b.unit_name == self.attack_unit
                       and not b.dead)
            if army >= self.garrison:
                return
        if (sim.nectar[self.side] >= price and price >= 0
                and sim.tick - self._last_attack >= self.attack_every):
            lane = self.attack_lanes[self._li % len(self.attack_lanes)]
            bug = sim.buy(self.side, self.attack_unit, lane)
            if bug is not None:
                self._li += 1
                self._last_attack = sim.tick
                self._attacks += 1
                if self.defend:
                    # 守军驻守本巢 spawn_pos（idle），不行军攻敌——攻巢=自杀(H15/W3)
                    # 后，防守单位不应白白送死；仍会就近接战入侵之敌（combat_tick）。
                    bug.mode = "idle"

    def state_repr(self):
        """确定性相关状态（REVIEW-02）: 影响后续买兵决策的字段。"""
        return (f"s{self.side}|la{self._last_attack}|at{self._attacks}|"
                f"li{self._li}")
