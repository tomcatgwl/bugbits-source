"""Web 线 harness 用例注册表（loop-web.md §3）。

每个用例 = 一个可独立重跑的检查；suite 覆盖：
  assets  H1 资源/schema（W1 起登记）
  bridge  H2 native↔Pyodide 对照 A↔B + H4 时钟（W2 起登记）
  browser H2 C 层 + H3 真实浏览器 + H4 生命周期（W2–W5 起登记）

W0 状态：注册表为空——runner 对必需 suite 报 BLOCKED（exit 2），
这是设计行为（"骨架缺失 suite 必须非零；禁止空测试返回成功"）。
用例实现时在本文件登记并填充 CASES；禁止注册"永远通过"的空用例。
"""
from dataclasses import dataclass, field


class BlockedError(Exception):
    """环境/依赖阻塞（exit 2 语义）。用例内部捕获可判定为环境问题的异常时抛出。"""


@dataclass
class CaseResult:
    status: str                    # PASS | FAIL | BLOCKED | SKIP
    detail: str = ""
    expected: object = None
    actual: object = None
    artifacts: list = field(default_factory=list)


@dataclass
class Case:
    id: str                        # 稳定 ID（--case 精确重跑）
    suite: str                     # assets | bridge | browser
    description: str
    required: bool = True          # False = 允许 SKIP 的补充用例
    profiles: tuple = ("slice", "full")   # 适用的构建 profile
    run: object = None             # callable(ctx) -> CaseResult

    def check(self, ctx):
        if self.run is None:
            return CaseResult("BLOCKED", "用例未实现（注册表占位）")
        return self.run(ctx)


# 必需 suite：无已实现用例（run 可调用）时整个 suite BLOCKED → exit 2
REQUIRED_SUITES = ("assets", "bridge", "browser")

CASES: list = []   # 桥接/浏览器用例 W2+ 登记（合同 §7.1）


def _register_assets():
    """H1 assets 用例（W1；实现 harness/web/cases_assets.py）。"""
    import cases_assets as impl
    spec = [
        ("A01", "manifest schema + files 哈希", impl.a01),
        ("A02", "引用闭包（单位/世界/文本/音频）", impl.a02),
        ("A03", "采样帧数独立重算 + 精灵存在（首/中/末×8yaw）", impl.a03),
        ("A04", "alpha 统计 + 静态降级 fallback 登记", impl.a04),
        ("A05", "对象 JSON 往返逐字段（tuple/set/序/Unicode/None≠0）", impl.a05),
        ("A06", "同输入两次构建逐字节一致", impl.a06),
        ("A07", "源字节变化 → buildId 变化（--data-root 覆盖）", impl.a07),
        ("A08", "非方形投影：等比/居中/逆映射", impl.a08),
        ("A09", "负例：缺文件 + 未登记文件", impl.a09),
        ("A10", "负例：篡改数据 + 篡改 manifest schema", impl.a10),
        ("A11", "负例：截断 PNG（哈希自洽）解码失败", impl.a11),
        ("A12", "负例：断引用精灵（哈希自洽）", impl.a12),
        ("RF-B01", "profile manifest 关联：报告读本 profile 产物，不借用另一 profile",
         impl.rf_b01),
        ("RF-B02", "artifactDigest 覆盖页面源码+交付核心包，对内容敏感",
         impl.rf_b02),
        ("RF-B03", "缺失/陈旧/篡改 artifactDigest 失败回归（不污染真实产物）",
         impl.rf_b03),
    ]
    for cid, desc, fn in spec:
        CASES.append(Case(cid, "assets", desc, run=fn))


def _register_bridge():
    """H2 bridge 用例（W2；实现 harness/web/cases_bridge.py）。"""
    import cases_bridge as impl
    spec = [
        ("B01", "相位合同：step→vm→控制输入（同 tick 事件序+id 序）", impl.b01),
        ("B02", "经济夹具：P−1 拒绝无痕 / P 恰一次余 0 / 重复幂等", impl.b02),
        ("B03", "对话计时：N=0/0.25/2 → tick 21/26/61 + null 负例", impl.b03),
        ("B04", "错误码：E_TYPE/E_UNIT/E_LANE/E_SESSION/E_BATCH/E_ENDED", impl.b04),
        ("B05", "A↔B：原解析对象 vs 恢复 JSON 同命令日志逐 tick 全等", impl.b05),
        ("B06", "批次不变性：1×60 / 5×12 / 混合 → 同状态同 RNG", impl.b06),
        ("B07", "reset 隔离：全新同种子局 / 旧 sid 拒绝 / 事件重置", impl.b07),
        ("B08", "事件游标：保留窗溢出 gap + 连续无重复", impl.b08),
        ("U01", "multi 对抗：演示配置双方生产进攻单位+交战/伤害+拆巢取胜",
         impl.u01),
    ]
    for cid, desc, fn in spec:
        CASES.append(Case(cid, "bridge", desc, run=fn))


def _register_browser():
    """H2-C/H3/H4 浏览器用例（W2 起步，W3/W4 扩充）。"""
    import cases_browser as impl
    from cases_font import font_ui
    from cases_gui import gui02
    from cases_hud import hud01
    spec = [
        ("C01", "Chromium 实启：UI 买兵+脚本出兵+B↔C audit 全等", impl.c01),
        ("C02", "坏包（缺 vendor）→ 显式错误非永久 loading", impl.c02),
        ("C03", "地图/实体绘制：draw 日志+精灵位置像素+缺图报告", impl.c03),
        ("C04", "手动时钟 30/60/144Hz+抖动 → 同 tick 同状态", impl.c04),
        ("C05", "暂停无推进/E_PAUSED/恢复不补算；隐藏自动暂停", impl.c05),
        ("C06", "重开 10 次：tick/游标清零、监听不翻倍", impl.c06),
        ("C07", "点击选道：DPR 1/2+窄窗 CSS 缩放全中、边角无误选", impl.c07),
        ("C08", "真实 rAF 时钟 UI 命令日志 → native 复放 audit 全等", impl.c08),
        ("C09", "level_02 完整一局：选关→买兵→胜利文案→重开→返回", impl.c09),
        ("C10", "坏 manifest/缺音频 → 显式错误/逻辑不阻断", impl.c10),
        ("P01", "性能：冷/热启动 ≤15s ×3", impl.p01),
        ("P02", "性能：100 虫逻辑 tick p95≤50ms", impl.p02),
        ("P03", "性能：60s 负载帧 p95≤33.4ms+tick 漂移+游标", impl.p03),
        ("P04", "性能：10 次重开 heap 无持续增长", impl.p04),
        ("F01", "full：全部关卡装载+500t 覆盖矩阵（复用 runtime）", impl.f01,
         ("full",)),
        ("F02", "full：各类型完整终局（battle/gather/defense/rescue/multi/"
                "multirandom/challenge）", impl.f02, ("full",)),
        ("F03", "交付：外网封锁下离线可玩（vendor 全本地）", impl.f03,
         ("slice", "full")),
        ("L01", "A2：暂停/后台暂停后重开不继承 paused/backlog/错误框", impl.l01),
        ("L02", "stopLoop：返回选关后 tick 冻结（生产 rAF 链）", impl.l02),
        ("L03", "rAF 循环唯一所有权：连续重开 10 次活动循环 ≤1", impl.l03),
        ("L04", "A23：受控网络延迟下 booted() 与 overlay/列表完成对齐", impl.l04),
        ("L05", "A17：受控回包延迟下切局旧回包不串局", impl.l05),
        ("L06", "A6：快进路径保留 winner → 终局屏+按钮锁定", impl.l06),
        ("U04", "A4/A3：买兵栏中文名+价格+稳定 unit ID；buy_reject 可见反馈",
         impl.u04),
        ("U05", "A8：泳道下拉来自世界 START + 地图标记 + 非法点击提示", impl.u05),
        ("U06", "A21/A22：depleted/trapped draw 标记与快照一致", impl.u06),
        ("M01", "FIX-04：按关卡依赖加载图集页（loaded==deps.atlasPages）",
         impl.m01),
        ("M02", "RF-02：延迟切世界竞态——旧局图集回包不污染新局（loaded==新关 deps）",
         impl.m02, ("full",)),
        ("M03", "RF-02：10 次跨世界切换——图集页/地形无累积（terrain 释放计数）",
         impl.m03, ("full",)),
        ("E01", "A7/A20：seed=0 有效 + 非法种子拒绝（不静默回退）", impl.e01),
        ("E02", "A19：无效关卡明确提示并可返回选择", impl.e02),
        ("L07", "BUG-02/03：装载相位锁定买兵/暂停/重开 + E_NOT_RUNNING", impl.l07),
        ("D01", "BUG-05：对话换行（wrapText 显式\\n/空行/自动折行）", impl.d01),
        ("N01", "NC-01.A：终局原因与胜者——winner/endKind 与标题/正文/样式/状态栏一致",
         impl.n01, ("full",)),
        ("N02", "NC-01.B：submitBuy 代次守卫——旧局延迟购买回包不污染新局",
         impl.n02, ("full",)),
        ("N03", "NC-01.C：图集部分失败与重试——成功页接管、失败页重试只补失败页",
         impl.n03, ("full",)),
        ("N04", "NC-01.D：native↔Worker 冷却与回执——同序列买兵事件迹+laneCd 全等",
         impl.n04, ("full",)),
        ("N05", "NC-03：世界尺寸/锚点/飞行高度样板——复刻一致+旋转AABB宽+透视常数",
         impl.n05, ("full",)),
        ("N06", "NC-04：DPR 清晰度——backing 随 DPR 缩放，边缘过渡宽度 dpr2 优于 dpr1 上采样",
         impl.n06, ("slice", "full")),
        ("CAM01", "NC 相机交付：world_02 预设消费链——正映射==权威/点击逆映射/"
                  "letterbox/截断/锚点/λ·camZ/复位（DPR1/2+窄窗）", impl.cam01),
        ("CAM02", "NC 相机交付：world_03 预设消费链（低机位 22.9° pitch 差异断言）",
         impl.cam02, ("full",)),
        ("CAM03", "CAM-01：预设请求生命周期——受控延迟/逆序/复位/重入/跨局/失败"
                  "（latest-intent-wins + close 计数）", impl.cam03),
        ("CAM04", "CAM-02：内容区绘制裁剪+输入边界——黑带/画布外/平行/反向射线"
                  "显式无命中、合法命中不回退、PIL 像素探针（DPR1/2+窄窗）",
         impl.cam04),
        ("CAM05", "CAM-03：操作视口矩阵——双世界×双预设×宽/窄×DPR1/2，地面/飞行"
                  "单位样本+巢穴/泳道可见或工程边缘指示+overview 恢复",
         impl.cam05),
        ("UI01", "UI-01：CSS 逻辑尺寸/backing 分离+首屏操作布局——4 视口组"
                 "（1000×760/420×700×DPR1/2）+resize 往返，逐组合同断言",
         impl.ui01),
        ("FN01", "UI-02：canvasClickAt/mapClient 函数级输入边界（全坐标，"
                 "独立状态准备/断言；不等于 DOM 验证）", impl.fn01),
        ("UI02", "UI-02：真实 DOM 操作闭环——选关→选道→买兵（回执/资源/新"
                 "实体）→暂停/恢复+负例+生产模式冒烟（无 __bb_test）",
         impl.ui02),
        ("UI03", "FONT-UI：控件中文实际使用随包字体——开始/买兵/泳道/暂停等"
                 "10控件×宽窄窗×DPR1/2，Chromium实际字形字体核验", font_ui),
        ("GUI01", "原作GUI资产/价格父链/战场左侧兵卡结构；不等于DYNAMIC", impl.gui01),
        ("GUI02", "真实14卡长列表：完整价条/滚动/首屏控件/底HUD/购买，宽窄DPR",
         gui02, ("full",)),
        ("HUD01", "STATIC HP/10正常数值、双层材质实际像素、新局清空；不等于DYNAMIC", hud01),
        ("STAGE01", "生产默认近景/stage几何/DPR/输入裁剪/四色fixture/真实相机控件；非DYNAMIC", impl.stage01),
        ("FR01", "FRAME-01：帧完成标记（绘制后发布）+条件等待替换固定延时"
                 "+延迟渲染反例+rAF 杀链有限超时诊断", impl.fr01),
    ]
    for entry in spec:
        cid, desc, fn = entry[0], entry[1], entry[2]
        profiles = entry[3] if len(entry) > 3 else ("slice", "full")
        CASES.append(Case(cid, "browser", desc, run=fn, profiles=profiles))


_register_assets()
_register_bridge()
_register_browser()


def validate_registry(cases=None):
    """校验注册表：用例 ID 全局唯一（PBA-07）。返回错误列表（空 = 无冲突）。"""
    cases = CASES if cases is None else cases
    seen = {}
    errors = []
    for c in cases:
        if not isinstance(c.id, str) or not c.id:
            errors.append(f"用例 ID 非法: {c.id!r}")
            continue
        if c.id in seen:
            errors.append(f"用例 ID 重复: {c.id!r}"
                          f"（{seen[c.id].suite} vs {c.suite}）")
        else:
            seen[c.id] = c
    return errors


def _assert_registry_unique():
    errors = validate_registry()
    if errors:
        # 注册时冲突即非零失败（导入即抛，不静默放过重复 ID）
        raise RuntimeError("用例注册表 ID 冲突: " + "; ".join(errors))


_assert_registry_unique()


def cases_for(suite, profile=None, case_id=None):
    """选择用例：suite 过滤 → profile 过滤 → --case 精确过滤。"""
    suites = REQUIRED_SUITES if suite == "all" else (suite,)
    out = [c for c in CASES if c.suite in suites]
    if profile:
        out = [c for c in out if profile in c.profiles]
    if case_id:
        out = [c for c in out if c.id == case_id]
    return out
