"use strict";
const CAPTURED_FIRST_LEVEL_CAMERA = {"projection":{"kind":"matrix-yup-v1","basis9":[-6.342090316132706e-29,2.7722157017458515e-36,1.0,-0.9981470108032227,0.0608484148979187,-6.330338532353298e-29,-0.0608484148979187,-0.9981470108032227,-3.859058428099811e-30],"cameraPosition":[48.612158002294166,297.41118114567564,-9.703709602355957],"size":768.0,"cot":1.7320507764816284,"aspect":1.3333333639224525,"near":1.0,"far":1000.0005954507562},"cameraSource":{"schema":"captured-camera-source-v1","scope":"captured-static-first-level-v1","levelId":"level_01","variant":"normal","worldId":"world_01","coordinateBasis":"loaded-yup-v1","sampleSequence":5,"appElapsedSeconds":121.79145969310775,"atomicFrame":false,"originalDynamicFollowVerified":false,"sampleSHA256":"c668654725c6b861cceb856c7fed6fae8f9def5a730d2eb88df65380755cc953","pngSHA256":"a9366e546d8ec5eb98de248c33905f974dc9887d6cf96a9a10f78444bbe1ab20","mathSHA256":"3943061d1f48710783e2142ea11f56fca493d53fe8c796f5bb8ed3fc8d4bb0b8","inputs":{"analyze/extracted/ccdzz/虫虫大作战 鸾霄汉化版.exe":"00262b6e1694fd4007542a2e121f6d7f09c2ce89f64defa41a531025c5945a29","out/linux-continuation/original-runtime-r114/r135-camera-20261004-1716/memory/00005.json":"c668654725c6b861cceb856c7fed6fae8f9def5a730d2eb88df65380755cc953","out/linux-continuation/original-runtime-r114/r135-camera-20261004-1716/frames/00005.png":"a9366e546d8ec5eb98de248c33905f974dc9887d6cf96a9a10f78444bbe1ab20","out/linux-continuation/r135-camera-projection-final-20261004-1726/report.json":"3943061d1f48710783e2142ea11f56fca493d53fe8c796f5bb8ed3fc8d4bb0b8","analyze/extracted/ccdzz/data/scripts/levels/level_01.vsc":"848b310bb46faeed6afb0fc45c189c9647b4e29223897979c71254ae6b3ffee1","analyze/extracted/ccdzz/data/worlds/world_01.vsc":"8de18b7fee6db34c6b893a99cd3ef21938a4604dd9c90bfc53087aea6e465554"},"viewRawHex":"0000803f3f7ea090c18a9c8e0000000085caa01090867f3f303c793d0000000083d56b84303c79bd90867f3f0000000065421b419166f341b6e895430000803f","projectionRawHex":"e146a63f00000000000000000000000000000000d7b3dd3f00000000000000000000000000000000cd20803f0000803f0000000000000000cd2080bf00000000"}};
function capturedCameraApplicable(preset, levelId, levelType, world) {
  const equal=(a,b)=>{
    if(a===b)return true;
    if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
    const keys=Object.keys(a);
    return keys.length===Object.keys(b).length && keys.every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));
  };
  const expected={levelId:'level_01',variant:'normal',worldId:'world_01'};
  return levelId==='level_01' && levelType==='gather' && world==='world_01'
    && preset.world===world && preset.worldBasisVersion==='loaded-yup-v1'
    && !Object.hasOwn(preset,'meshView') && equal(preset.applicability,expected)
    && equal(preset.projection,CAPTURED_FIRST_LEVEL_CAMERA.projection)
    && equal(preset.camera,preset.projection)
    && equal(preset.cameraSource,CAPTURED_FIRST_LEVEL_CAMERA.cameraSource);
}
// Captured camera contract end

// BugBits Web 宿主（W3：Canvas 地图/实体渲染 + 20Hz 推进 + 受控买兵）。
// 完整输入映射/HUD/音频为 W4–W5。
// 渲染约定（合同 §6.5，OF-03.B/C）：投影参数取自 manifest.projection——
// 静态斜俯视透视（render/camera.py StaticObliqueCamera），非仿射 scale/offset。
// worldToCanvas/canvasToWorld/unitBillboard/flowerBillboard 消费同一组几何常数
// （cx/cz/cot/sinP/cosP/tanP/distance/size），pitch=40°/fov=60°/aspect=1 在
// Python 权威端 camera.DEFAULT_* 单一来源。
// yaw 由相邻快照 pos 差分推导——展示态，不入游戏状态/对照快照。
// 测试模式（?test=1）：禁用墙钟循环，只读 hook + 手动推进 + draw 日志。

const $ = (id) => document.getElementById(id);
const TICK_HZ = 20;
const CANVAS_SIZE = 640;
// Engineering deadline for one camera request, including fetch and decoding.
const CAMERA_LOAD_TIMEOUT_MS = 8000;
// Shared production/test near policy: keep a legal canvas lane target under
// the existing 200-world-unit input contract. Original_cam remains research.
const NEAR_CAMERA_PRESET = "wide_cam";
// A16：关卡类型中文标签（轻量分组；类型原文见 manifest levels[].type）
const TYPE_LABEL = {
  battle: "对战", gather: "采集", defense: "防守", rescue: "营救",
  multibattle: "多人对战", multirandom: "多人随机", challenge: "挑战", menu: "菜单",
};

const state = {
  worker: null, sessionId: null, buyable: [], manifest: null,
  seed: 2026, levelId: "level_02", running: false,
  lastReceipt: null, testMode: false, recordMode: false,
  ready: false, tick: 0,
  lastSnapshot: null, world: null, texts: null, levelProps: null,
  paused: false, manualPause: false, autoPaused: false,
  eventCursor: 0, receipts: [], resetCount: 0, backlog: false,
  started: false, muted: false,
  seedNote: "",           // URL 非法种子提示（init 后状态栏显示）
  endKind: null,          // A24：终局原因（timeup/survived/rescued，来自 sim 事件）
  generation: 0,          // 会话代次：startGame/切局递增；异步回包据此淘汰旧局
  booted: false,          // onWorkerReady 完整完成（manifest+texts+列表+overlay）
  phase: "booting",       // booting→selecting→loading→running→paused→ended
};

// ── 20Hz 逻辑时钟（合同 §2.3） ───────────────────────────────────────
// rAF 驱动累积时钟；每帧补 due tick（≤5/批），单批未结束不叠发；
// backlog >1s 显式暂停+提示（不静默跳 tick/追帧）；恢复重置锚点不补算。
// ── 性能仪表（W6/H5；环缓冲，hook 只读导出） ─────────────────────────
const perf = {
  frameTimes: [],          // rAF 间隔 ms（最近 1200 帧）
  advanceMs: [],           // clock.step 中 advance 批往返 ms（最近 1200 批）
  _lastFrame: 0,
  push(arr, v, cap = 1200) {
    arr.push(v);
    if (arr.length > cap) { arr.shift(); }
  },
};

const clock = {
  anchorMs: 0,              // 上一逻辑 tick 对应的墙钟时刻
  inFlightGen: 0,           // 非 0 = 该代次的 advance 批在途（按代次隔离，防叠发）
  useRealTime: true,        // 测试注入时钟时置 false（合成时间线）
  reset() {
    this.anchorMs = this.useRealTime ? performance.now() : 0;
    state.backlog = false;
  },
  async step(nowMs) {
    if (state.paused || state.winnerLocked()) { this.anchorMs = nowMs; return; }
    if (this.inFlightGen === state.generation) { return; }   // 同代次批在途，不叠发
    const due = Math.floor((nowMs - this.anchorMs) * TICK_HZ / 1000);
    if (due <= 0) { return; }
    const n = Math.min(5, due);
    const gen = state.generation;                            // 本批所属会话
    this.inFlightGen = gen;
    const t0 = performance.now();
    try {
      const r = await call("advance", {ticks: n});
      perf.push(perf.advanceMs, performance.now() - t0);
      if (gen !== state.generation) { return; }              // 旧批：不挂到新局
      if (r.ok) {
        this.anchorMs += n * 1000 / TICK_HZ;
        await refresh(r.result, gen);
        // backlog：落后墙钟超过 1s（20 tick）→ 显式暂停（不无限追帧）
        if (nowMs - this.anchorMs > 1000 && !state.paused) {
          state.paused = true;
          state.backlog = true;
          showError(`性能落后 >1s，已自动暂停（tick ${state.tick}）。`
                    + " 请点击继续。");
        }
      }
    } catch (e) {
      if (gen !== state.generation) { return; }              // 旧批拒绝/超时：静默淘汰
      showError(`推进失败: ${e && e.message || e}`);
      stopLoop();
    } finally {
      if (this.inFlightGen === gen) { this.inFlightGen = 0; }
    }
  },
};

// ── 渲染资源与呈现态（展示层，不影响游戏逻辑/RNG） ──────────────────
const render = {
  atlas: null, pages: [], terrain: null, projection: null,
  // NC 相机交付：世界预设表（manifest.cameraPresets[world]）与激活预设。
  // null is overview/fallback; world_02/03 select a packaged static near view.
  worldPresets: null, activePreset: null, activePresetKey: null,
  presetTerrain: null,      // 预设地形位图（与默认 terrain 并存，切回即释放）
  presetTerrainCloseCount: 0,   // 预设位图 close 总数（CAM-01 所有权诊断：
                            // null 复位/换预设替换/在途淘汰/换关重置四路释放）
  presetReqSeq: 0,        // CAM-01：预设请求版本（单调递增，latest-intent-wins）
  presetController: null, presetPending: null, presetError: "",
  cameraReady: false,     // current session's default selection attempt settled
  cameraControlGeneration: 0,   // legal overview/world base exists for this session
  terrainWorld: null, terrainCloseCount: 0,   // 切世界地形释放计数（RF-02 诊断）
  atlasCloseCount: 0,     // 图集 bitmap close 总数（NC-01.C 所有权诊断：
                          // keep 剪枝 + 失效代次释放两处；N03 观测面）
  yaw: {},            // bugId → 上次位置（差分推导 yaw）
  lastPos: {},        // bugId → [x,y,z]
  draws: [],          // 最近一帧 draw 日志 [{id,unit,clip,frame,yaw,culled}]
  fallbackHits: {},   // "unit.clip" → 次数（缺图回退可见报告）
  meshScene: null, meshAssets: null,
  meshProjection: null, meshFollowId: null, meshZoomFactor: 1, meshTargetYup: null,
  meshCameraPending: false,
  meshHeading: {}, meshLastPos: {}, meshDisposeCount: 0,
};

// ── FRAME-01 帧完成标记 ───────────────────────────────────────────────
// renderFrame **真实绘制结束后**发布（请求开始不标完成）：seq=已完成帧代次
// （单调递增）；tick=本帧实际消费的快照 tick（draws 数据来源）；stateTick=
// 本帧读取的 HUD tick；presetReq/presetKey=本帧实际使用的相机请求版本与激活
// 预设。测试条件等待据此判定「目标快照 tick + 相机版本已绘制」，替换固定
// 延时（advanceTo/refresh 完成 ≠ 目标帧已绘制）。只读查询经
// __bb_test.renderState()（test 层；生产冒烟不依赖它）。
const frameMark = {
  seq: 0, tick: null, stateTick: -1, presetReq: 0, presetKey: null,
  generation: 0, atMs: 0, stageAspect: 1, offY: 0, cameraReady: false,
};

// NC 相机交付：激活投影（预设→预设自带常数；默认→manifest.projection）。
function activeProjection() {
  return render.meshProjection || (render.activePreset ? render.activePreset.projection
                             : render.projection);
}

// One 3D/depth seam for world anchors, billboards and target indicators.
function cameraSpacePoint(point, p = activeProjection()) {
  if (p.kind === "matrix-yup-v1") {
    return BugBitsCameraProjection.cameraSpace(p, point);
  }
  if (p.kind && p.kind !== "legacy-euler-v1") {
    throw new TypeError("Unknown camera projection kind");
  }
  const dx = point[0] - (p.tx ?? p.cx), wy = point[1] - (p.ty ?? 0);
  const dz = point[2] - (p.tz ?? p.cz);
  const sinY = p.sinY ?? 0, cosY = p.cosY ?? 1;
  const forward = dx * sinY + dz * cosY;
  return [dx * cosY - dz * sinY,
          forward * p.sinP + wy * p.cosP,
          forward * p.cosP - wy * p.sinP + p.distance];
}

function projectCanvasPoint(point, p = activeProjection()) {
  let value;
  if (p.kind === "matrix-yup-v1") {
    value = BugBitsCameraProjection.projectWorldPoint(p, point);
    if (!value) { return null; }
  } else {
    const [x, y, depth] = cameraSpacePoint(point, p);
    const z = Math.max(depth, 1e-6), aspect = p.aspect ?? 1;
    value = {px: (p.cot * x / (z * aspect) + 1) * p.size * aspect / 2,
             py: (1 - p.cot * y / z) * p.size / 2, camZ: depth};
  }
  const aspect = p.aspect ?? 1, k = CANVAS_SIZE / (p.size * aspect);
  return {px: value.px * k,
          py: value.py * k + (CANVAS_SIZE - CANVAS_SIZE / aspect) / 2,
          camZ: value.camZ};
}

// NC 相机交付：预设精灵键前缀（默认 "" → 键与旧版逐字节一致）。
function activeSpritePrefix() {
  return render.activePreset ? (render.activePreset.spritePrefix || "") : "";
}

function closePresetBitmap(bitmap) {
  if (!bitmap) { return; }
  bitmap.close();
  render.presetTerrainCloseCount += 1;
}

// Same logical 640 square and world projection, independent of CSS/DPR.
function stageGeometry() {
  const aspect = render.activePreset ? activeProjection().aspect : 1;
  const contentH = CANVAS_SIZE / aspect;
  const offY = (CANVAS_SIZE - contentH) / 2;
  const rect = (element) => {
    const r = element.getBoundingClientRect();
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom,
            width: r.width, height: r.height};
  };
  const stageRect = rect($("worldstage"));
  return {aspect, contentH, offY, stageRect, canvasRect: rect($("scene")),
          worldRect: {left: 0, top: offY, width: CANVAS_SIZE, height: contentH},
          scale: stageRect.width / CANVAS_SIZE};
}

function syncStageGeometry() {
  const aspect = render.activePreset ? activeProjection().aspect : 1;
  const offY = (CANVAS_SIZE - CANVAS_SIZE / aspect) / 2;
  const style = $("battlefield").style;
  style.setProperty("--stage-aspect", String(aspect));
  style.setProperty("--scene-shift", `${-100 * offY / CANVAS_SIZE}%`);
  // 800×500 near stage keeps the original left rail's three cards/price bars
  // clear of the top/base HUD. Narrow windows scale via CSS max-width only.
  style.setProperty("--battlefield-width", render.activePreset ? "802px" : "642px");
}

function cameraControlAvailable() {
  return render.cameraControlGeneration === state.generation
    && (state.phase === "loading" || state.phase === "running");
}

function defaultCameraPresetFor(world, presets, levelId=null, levelType=null, isReversed=false) {
  const supported = world === "world_01" || world === "world_02" || world === "world_03";
  if (!supported || !presets) { return null; }
  if (!isReversed && ['gather','battle','defense'].includes(levelType)
      && nativeCameraPresetValid(presets.native_camera)) {
    return 'native_camera';
  }
  if (presets.original_static_01 && capturedCameraApplicable(presets.original_static_01,levelId,levelType,world)) {
    return 'original_static_01';
  }
  return presets.mesh_cam ? "mesh_cam" : presets[NEAR_CAMERA_PRESET] ? NEAR_CAMERA_PRESET : null;
}
function nativeCameraPresetValid(preset) {
  return !!preset && preset.nativeCameraContract === 'normal-camera-static-branches-outer20hz-v1'
    && preset.nativeCameraQualification === 'static-normal-no-shake-no-overlap-4:3-outer20hz-v1'
    && !Object.hasOwn(preset,'meshView')
    && ['kind','size','cot','aspect','near','far'].every(key =>
      preset.projection?.[key] === CAPTURED_FIRST_LEVEL_CAMERA.projection[key]);
}
// Default camera selection end

function updateCameraControl() {
  const control = $("camera-mode");
  if (control) {
    control.value = render.activePresetKey || "overview";
    control.disabled = !cameraControlAvailable();
    const near = control.querySelector(`option[value="${NEAR_CAMERA_PRESET}"]`);
    if (near) { near.disabled = !(render.worldPresets && render.worldPresets[NEAR_CAMERA_PRESET]); }
    const mesh = control.querySelector('option[value="mesh_cam"]');
    if (mesh) { mesh.disabled = !(render.worldPresets && render.worldPresets.mesh_cam); }
    const native = control.querySelector('option[value="native_camera"]');
    const currentLevel = state.manifest?.levels.find(x=>x.id===state.levelId);
    if (native) { native.disabled = !render.worldPresets?.native_camera
      || !['gather','battle','defense'].includes(currentLevel?.type)
      || Number(state.levelProps?.IsReversed?.[0] || 0) !== 0; }
    const captured = control.querySelector('option[value="original_static_01"]');
    const level = state.manifest?.levels.find(x=>x.id===state.levelId);
    if (captured) { captured.disabled = !render.worldPresets?.original_static_01
      || !capturedCameraApplicable(render.worldPresets.original_static_01,state.levelId,level?.type,state.world); }
    control.setAttribute("aria-busy", render.presetPending === null ? "false" : "true");
  }
  const note = $("camera-note");
  if (note) { note.textContent = render.presetError ? "视角加载失败，已保留当前视角。" : ""; }
}

// Atomic publish: terrain/projection/sprite metadata and stage geometry switch
// together; CSS never reflects an unfulfilled request's aspect.
function commitCameraView(key, preset, bitmap, meshScene = null, meshAssets = null) {
  const previous = render.presetTerrain;
  const previousMesh = render.meshScene;
  render.presetTerrain = bitmap;
  render.meshScene = meshScene;
  render.meshAssets = meshAssets;
  render.meshSceneGeneration = meshScene ? state.generation : null;
  render.meshProjection = null; render.meshFollowId = null; render.meshZoomFactor = 1;
  render.meshTargetYup = null; render.meshCameraPending = false;
  render.nativeCameraGeneration = null;
  render.activePreset = preset;
  render.activePresetKey = key;
  syncStageGeometry();
  if (previous !== bitmap) { closePresetBitmap(previous); }
  if (previousMesh && previousMesh !== meshScene) {
    previousMesh.dispose(); render.meshDisposeCount += 1;
  }
  updateCameraControl();
}

function setMeshProjection(next) {
  if (!render.meshScene) { throw new Error('Mesh camera unavailable'); }
  BugBitsCameraProjection.validateProjection(next);
  const initial = render.activePreset.projection;
  if (next.aspect !== initial.aspect || next.size !== initial.size) {
    throw new TypeError('Mesh view keeps the stage dimensions');
  }
  const candidate = JSON.parse(JSON.stringify(next));
  render.meshScene.setProjection(candidate);
  render.meshProjection = candidate;
}

function updateNativeCamera(snapshot) {
  if (render.activePresetKey !== 'native_camera') { return; }
  const camera = snapshot?.nativeCamera;
  if (!nativeCameraPresetValid(render.activePreset)
      || !camera || camera.scope !== render.activePreset.nativeCameraContract
      || camera.scope !== 'normal-camera-static-branches-outer20hz-v1'
      || !Number.isSafeInteger(camera.generation) || camera.generation < 0
      || !camera.view
      || !Number.isSafeInteger(camera.view.basisGeneration) || camera.view.basisGeneration < 0
      || !Number.isSafeInteger(camera.view.eyeGeneration) || camera.view.eyeGeneration < 0
      || camera.view.basisGeneration > camera.view.eyeGeneration
      || camera.view.eyeGeneration > camera.generation) {
    throw new TypeError('Native camera state unavailable');
  }
  const next = {...render.activePreset.projection,
    basis9:camera.view.basis9,cameraPosition:camera.view.cameraPosition};
  setMeshProjection(next);
  render.nativeCameraGeneration = camera.generation;
}

function updateMeshFollow(snapshot) {
  const view = render.activePreset.meshView;
  if (!view || !snapshot) { return; }
  const units = snapshot.bugs.filter(b => b.side === 0 && !b.dead);
  const bug = render.meshFollowId === 'auto' ? units[0]
    : units.find(b => b.id === render.meshFollowId);
  if (render.meshFollowId !== null && !bug) { render.meshFollowId = 'auto'; }
  if (bug) { render.meshTargetYup = [...bug.pos]; }
  const target = bug ? bug.pos : (render.meshTargetYup || view.targetYup);
  const projection = render.activePreset.projection;
  const distance = view.distance * (render.meshZoomFactor || 1);
  const next = {...projection, cameraPosition: target.map((v,i) =>
    v - projection.basis9[6+i] * distance)};
  setMeshProjection(next);
  render.meshCameraPending = false;
}

function updateMeshControls(snapshot) {
  const controls = $('mesh-controls');
  if (!controls) { return; }
  controls.hidden = !render.meshScene || !render.activePreset?.meshView;
  if (controls.hidden) { return; }
  const select = $('mesh-target');
  const live = (snapshot?.bugs || []).filter(b => b.side === 0 && !b.dead);
  const signature = live.map(b => b.id).join(',');
  if (select.dataset.units !== signature) {
    const chosen = select.value; select.textContent = '';
    for (const [id,label] of [['auto','首个单位'], ...live.map(b =>
      [String(b.id),unitInfo(b.unit).name + ' ' + b.id])]) {
      const option = document.createElement('option');option.value=id;
      option.textContent=label;select.appendChild(option);
    }
    select.value = live.some(b => String(b.id) === chosen) ? chosen : 'auto';
    select.dataset.units = signature;
  }
  $('mesh-follow').textContent = render.meshFollowId === null ? '跟随' : '停止跟随';
  $('mesh-zoom').value = String(render.meshZoomFactor || 1);
}
// Mesh view controls end

function loadCameraBitmap(url, signal) {
  // createImageBitmap has no abort operation. Reject promptly on the deadline,
  // but keep observing its promise so a late bitmap is closed exactly once.
  return new Promise((resolve, reject) => {
    let settled = false;
    const aborted = () => {
      if (!settled) {
        settled = true;
        reject(new DOMException("Camera loading cancelled", "AbortError"));
      }
    };
    signal.addEventListener("abort", aborted, {once: true});
    if (signal.aborted) { aborted(); }
    loadBitmap(url, signal).then((bitmap) => {
      if (settled || signal.aborted) { closePresetBitmap(bitmap); }
      else { settled = true; resolve(bitmap); }
    }, (error) => {
      if (!settled) { settled = true; reject(error); }
    }).finally(() => signal.removeEventListener("abort", aborted));
  });
}

function loadMeshScene(assets, preset, signal) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const aborted = () => {
      if (!settled) {
        settled = true;
        reject(new DOMException('Mesh loading cancelled', 'AbortError'));
      }
    };
    signal.addEventListener('abort', aborted, {once: true});
    if (signal.aborted) { aborted(); }
    Promise.resolve().then(() => {
      if (Object.hasOwn(assets, 'propVariantContract')) {
        meshPropInstancesFor(assets, state.world, state.levelId, state.manifest);
      }
      return BugBitsMeshScene.prepareMeshScene({assets, projection: preset.projection,
        worldId: state.world, requiredUnitIds: Object.keys(state.units || {}), signal,
        materialPolicy: state.world==='world_01' ? BugBitsPresentationMaterial.POLICY : null});
    }).then(prepared => {
        if (settled || signal.aborted) { prepared.dispose(); }
        else { settled = true; resolve(prepared); }
      }, error => {
        if (!settled) { settled = true; reject(error); }
      }).finally(() => signal.removeEventListener('abort', aborted));
  });
}

async function setCameraPreset(key) {
  const gen = state.generation;
  const req = ++render.presetReqSeq;
  if (render.presetController) { render.presetController.abort(); }
  render.presetController = null;
  render.presetPending = null;
  render.presetError = "";
  const superseded = () => req !== render.presetReqSeq || gen !== state.generation;
  if (key === null) { commitCameraView(null, null, null); return true; }
  const preset = render.worldPresets && render.worldPresets[key];
  const aspect = preset && preset.projection && preset.projection.aspect;
  if (!preset || !(Number.isFinite(aspect) && aspect >= 1)) {
    render.presetError = "Preset missing or invalid aspect";
    updateCameraControl();
    return false;
  }
  const level = state.manifest?.levels.find(x=>x.id===state.levelId);
  if ((key==='original_static_01' || preset.cameraSource)
      && !capturedCameraApplicable(preset,state.levelId,level?.type,state.world)) {
    render.presetError = 'Captured camera is not applicable to this level';
    updateCameraControl(); return false;
  }
  if (key === 'native_camera' && (!['gather','battle','defense'].includes(level?.type)
      || Number(state.levelProps?.IsReversed?.[0] || 0) !== 0
      || !nativeCameraPresetValid(preset))) {
    render.presetError = 'Dynamic camera is not applicable to this level';
    updateCameraControl(); return false;
  }
  if (preset.projection.kind && preset.projection.kind !== "legacy-euler-v1") {
    try {
      BugBitsCameraProjection.validateProjection(preset.projection);
      // The native atlas adapter is not implemented. Metadata labels alone
      // cannot make old Euler/yawIndex sprites match a general matrix camera.
      if (preset.presentationScope !== 'engine-mesh-v1'
          || preset.meshContractVersion !== 'engine-mesh-v1'
          || !preset.geometryFile || !preset.geometrySHA256
          || preset.nativeScope === true || typeof BugBitsMeshScene === 'undefined') {
        throw new TypeError("Matrix geometry is research-only until native sprite consumption is verified");
      }
    } catch (error) {
      render.presetError = String(error);
      updateCameraControl();
      return false;
    }
  }
  if (render.activePresetKey === key && render.activePreset === preset) {
    updateCameraControl();
    return true;
  }
  // Camera presets can share one verified geometry closure. Replacing only
  // the projection avoids downloading/decoding it and allocating a second GL
  // scene while the current scene is still rendering.
  const current = render.activePreset;
  if (render.meshScene && render.meshAssets && render.meshSceneGeneration === gen
      && current?.presentationScope === 'engine-mesh-v1'
      && preset.presentationScope === 'engine-mesh-v1'
      && current.world === state.world && preset.world === state.world
      && state.worldBasisVersion === 'loaded-yup-v1'
      && current.worldBasisVersion === state.worldBasisVersion
      && preset.worldBasisVersion === state.worldBasisVersion
      && render.meshAssets.worlds?.[state.world]?.basisVersion === state.worldBasisVersion
      && current.geometryFile === preset.geometryFile
      && /^[0-9a-f]{64}$/.test(preset.geometrySHA256)
      && current.geometrySHA256 === preset.geometrySHA256) {
    try {
      if (Object.hasOwn(render.meshAssets, 'propVariantContract')) {
        meshPropInstancesFor(render.meshAssets, state.world, state.levelId, state.manifest);
      }
      render.meshScene.setProjection(preset.projection);
      commitCameraView(key, preset, null, render.meshScene, render.meshAssets);
      return true;
    } catch (error) {
      render.presetError = String(error && error.message || error);
      updateCameraControl();
      return false;
    }
  }
  const controller = new AbortController();
  render.presetController = controller;
  render.presetPending = req;
  updateCameraControl();
  const timeout = setTimeout(() => controller.abort(), CAMERA_LOAD_TIMEOUT_MS);
  try {
    if (preset.presentationScope === 'engine-mesh-v1') {
      const response = await fetch(preset.geometryFile, {signal: controller.signal});
      if (!response.ok) { throw new Error('Mesh scene unavailable'); }
      const bytes = await response.arrayBuffer();
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
        .map(x => x.toString(16).padStart(2, '0')).join('');
      if (digest !== preset.geometrySHA256) { throw new Error('Mesh scene hash mismatch'); }
      const assets = JSON.parse(new TextDecoder().decode(bytes));
      const prepared = await loadMeshScene(assets, preset, controller.signal);
      if (superseded() || controller.signal.aborted) { prepared.dispose(); return false; }
      commitCameraView(key, preset, null, prepared, assets);
      return true;
    }
    const bitmap = await loadCameraBitmap(preset.terrainFile, controller.signal);
    if (superseded()) { closePresetBitmap(bitmap); return false; }
    commitCameraView(key, preset, bitmap);
    return true;
  } catch (error) {
    if (!superseded()) {
      render.presetError = controller.signal.aborted ? "Camera request timed out"
        : String(error && error.message || error);
    }
    return false;
  } finally {
    clearTimeout(timeout);
    if (!superseded()) {
      render.presetController = null;
      render.presetPending = null;
      updateCameraControl();
    }
  }
}

// ── 音频（W5）：用户手势解锁；静音/缺音频/未获播放许可不阻断逻辑 ──────
const audio = {
  ctx: null, music: null, ambient: null, sfx: {}, unlocked: false,
  note: "",            // 全局单条（未解锁/未获许可/初始化失败）
  failed: new Set(),   // A11：按资源去重的加载失败集合（多件失败不互相覆盖）
  unlock() {                          // 首个用户手势（开始/重开按钮）调用
    if (this.unlocked) { return; }
    this.unlocked = true;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) { this.ctx = new AC(); this.ctx.resume().catch(() => {}); }
    } catch (e) { this.note = `AudioContext 不可用: ${e}`; }
  },
  _el(src, loop, vol) {
    const el = new Audio(src);
    el.loop = loop;
    el.volume = vol;
    el.muted = state.muted;
    el.addEventListener("error", () => {
      this.failed.add(src.split("/").pop());   // A11：去重聚合，不单槽覆盖
    });
    return el;
  },
  startGameAudio(musicUrl, ambientUrl) {
    this.unlock();
    this.stopMusic();              // RF-02：重开/换关停上一局循环音乐/环境音，不叠放
    try {
      if (musicUrl) {
        this.music = this._el(musicUrl, true, 0.5);
        this.music.play().catch(() => {
          this.note = "音乐未获播放许可（需用户手势）";
        });
      }
      if (ambientUrl) {
        this.ambient = this._el(ambientUrl, true, 0.25);
        this.ambient.play().catch(() => {});
      }
      for (const [ev, path] of Object.entries(
          state.manifest.capabilities.audioSfx.eventSfx || {})) {
        this.sfx[ev] = this._el(`audio/${path}.ogg`, false, 0.6);
      }
    } catch (e) { this.note = `音频初始化失败: ${e}`; }
  },
  stopMusic() {
    for (const el of [this.music, this.ambient]) {
      if (el) { el.pause(); }
    }
  },
  playEvent(ev) {
    const el = this.sfx[ev];
    if (!el || state.muted) { return; }
    try {
      el.currentTime = 0;
      el.play().catch(() => {});
    } catch (e) { /* 缺音频/未解锁不阻断 */ }
  },
  setMuted(m) {
    state.muted = m;
    for (const el of [this.music, this.ambient,
                      ...Object.values(this.sfx)]) {
      if (el) { el.muted = m; }
    }
    if (m) { this.stopMusic(); }
    else if (this.music) { this.music.play().catch(() => {}); }
    if (this.ambient && !m) { this.ambient.play().catch(() => {}); }
  },
};

function call(op, payload) {
  if (['advance', 'snapshot', 'audit_state', 'init', 'reset', 'dispose', 'fromObjects'].includes(op)) {
    flushCameraInput();
  }
  return new Promise((resolve, reject) => {
    const id = ++call._seq;
    const timer = setTimeout(() => {
      if (call._pending[id]) {
        delete call._pending[id];
        reject(new Error(`worker 超时: ${op}`));
      }
    }, 30000);
    call._pending[id] = value => { clearTimeout(timer); resolve(value); };
    try { state.worker.postMessage({id, op, payload}); }
    catch (error) { delete call._pending[id]; clearTimeout(timer); reject(error); }
  });
}
call._seq = 0;
call._pending = {};

// The original interface owns a 1024x768 client point independently of the
// world. Adapt the exposed viewport, not the translated square canvas or DPR.
// While a reply is in flight, retain only the latest unsent point. A world
// advance/read/lifecycle request flushes it synchronously before posting itself.
// No input is synthesized by render/resize.
const cameraInputTransport = {sequence: 0, last: null, pending: null, inFlight: 0};
function flushCameraInput() {
  const pending = cameraInputTransport.pending;
  if (!pending) { return; }
  cameraInputTransport.pending = null;
  const {payload, generation} = pending;
  if (generation !== state.generation || payload.sessionId !== state.sessionId) { return; }
  cameraInputTransport.inFlight += 1;
  const failed = (detail) => {
    if (generation !== state.generation || payload.sessionId !== state.sessionId
        || cameraInputTransport.last?.sequence !== payload.sequence) { return; }
    cameraInputTransport.last = null;
    showError(`视角输入失败: ${detail}`);
  };
  call('camera_input', payload)
    .then(reply => { if (!reply.ok) { failed(reply.detail || reply.result?.detail || reply.error); } })
    .catch(error => failed(error.message || error))
    .finally(() => {
      cameraInputTransport.inFlight -= 1;
      if (cameraInputTransport.inFlight === 0) { flushCameraInput(); }
    });
}
function onCameraPointerMove(event) {
  if ((event.pointerType && event.pointerType !== 'mouse')
      || !state.ready || !state.sessionId || !state.worker
      || !['running', 'paused'].includes(state.phase) || state.winnerLocked()) { return; }
  const rect = $('worldstage').getBoundingClientRect();
  if (![rect.left, rect.top, rect.width, rect.height, event.clientX, event.clientY]
      .every(Number.isFinite) || rect.width <= 0 || rect.height <= 0) { return; }
  const x = event.clientX - rect.left, y = event.clientY - rect.top;
  if (x < 0 || y < 0 || x >= rect.width || y >= rect.height) { return; }
  const positionClient = [Math.floor(1024 * x / rect.width), Math.floor(768 * y / rect.height)];
  const sid = state.sessionId, gen = state.generation;
  const previous = cameraInputTransport.last;
  const sampledClient = state.lastSnapshot?.cameraClientInput || state.lastSnapshot?.nativeCamera?.clientInput;
  const authorityChanged = previous && sampledClient && sampledClient.sequence >= previous.sequence
    && (sampledClient.sequence > previous.sequence
      || !sampledClient.positionClient.every((value, index) => value === previous.positionClient[index])
      || sampledClient.sizeClient[0] !== 1024 || sampledClient.sizeClient[1] !== 768);
  if (previous && previous.sessionId === sid
      && !authorityChanged
      && previous.positionClient.every((value, index) => value === positionClient[index])) { return; }
  const sequence = Math.max(cameraInputTransport.sequence, sampledClient?.sequence || 0) + 1;
  if (!Number.isSafeInteger(sequence)) { return; }
  cameraInputTransport.sequence = sequence;
  cameraInputTransport.last = {sessionId: sid, positionClient, sequence};
  cameraInputTransport.pending = {generation: gen, payload: {sessionId: sid, sequence,
    positionClient, sizeClient: [1024, 768], source: 'gameviewport-to-client1024x768-adapter-v1'}};
  if (cameraInputTransport.inFlight === 0) { flushCameraInput(); }
}
// Camera client input adapter end

let replyDelayMs = 0;      // 测试故障注入：延迟 worker 回包分发（L05）

function handleReply(msg) {
  if (replyDelayMs > 0) {
    setTimeout(() => handleReplyNow(msg), replyDelayMs);
    return;
  }
  handleReplyNow(msg);
}

function handleReplyNow(msg) {
  const data = msg.data || {};
  if (data.type === "ready") { state.ready = true; onWorkerReady(); return; }
  if (data.type === "bootError") { showError(`运行时初始化失败: ${data.error}`); return; }
  if (data.type === "reply") {
    const resolve = call._pending[data.id];
    if (resolve) { delete call._pending[data.id]; resolve(data); }
  }
}

// 终局判定（呈现层缓存，不读 sim 内部）
state.winnerLocked = () =>
  state.lastSnapshot !== null && state.lastSnapshot.winner !== null;

function showError(text) {
  const friendly = friendlyError(text);
  $("status").textContent = friendly;
  $("status").className = "error";
  $("error-box").hidden = false;
  // A10：技术详情保留在错误框（玩家看状态栏友好文案，诊断仍可查）
  $("error-detail").textContent = text;
}

// A10：原始异常文本 → 玩家可理解文案（技术详情仍经 showError 存入 error-detail）。
function friendlyError(text) {
  const t = String(text || "");
  if (/JSON|SyntaxError|Expected|property value|Failed to fetch|NetworkError/i.test(t)) {
    return "数据加载失败：资源可能已损坏或版本不符，请重新构建或刷新。";
  }
  if (/init\/reset|Worker|worker|运行时初始化/i.test(t)) {
    return "对局初始化失败：请重试，或刷新页面。";
  }
  return t;   // 其余已是友好文案（如关卡不存在/种子非法/事件流溢出）
}

// A7/A20：种子统一校验为有限安全整数；空=默认 2026；拒绝 NaN/Infinity/非整数/越界
// （Number.isSafeInteger 覆盖 |n|≤2^53-1 且为整数）。0 有效（不再被 || 当作 falsy）。
function validateSeed(str) {
  const s = String(str ?? "").trim();
  if (s === "") { return {ok: true, value: 2026}; }
  const n = Number(s);
  if (!Number.isSafeInteger(n)) {
    return {ok: false, value: null,
            error: `种子须为有限安全整数（收到 "${s}"）`};
  }
  return {ok: true, value: n};
}

// A3: 买兵结果可见反馈（短时；日志保留在开发视图事件流）。非错误框——不足/扣款
// 不打断对局，只在买兵栏下方提示。
let buyFeedbackTimer = 0;
function showBuyFeedback(text, kind) {
  const el = $("buy-feedback");
  if (!el) { return; }
  el.textContent = text;
  el.className = kind === "reject" ? "reject" : (kind === "ok" ? "ok" : "");
  el.hidden = false;
  if (buyFeedbackTimer) { clearTimeout(buyFeedbackTimer); }
  buyFeedbackTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

let loadDelayMs = 0;      // 测试故障注入：延迟位图解码（RF-02 竞态复现）
async function loadBitmap(url, signal) {
  if (loadDelayMs > 0) {
    await new Promise((resolve, reject) => {
      const cancel = () => {
        clearTimeout(timer);
        reject(new DOMException("Bitmap loading cancelled", "AbortError"));
      };
      const timer = setTimeout(() => {
        if (signal) { signal.removeEventListener("abort", cancel); }
        resolve();
      }, loadDelayMs);
      if (signal) {
        signal.addEventListener("abort", cancel, {once: true});
        if (signal.aborted) { cancel(); }
      }
    });
  }
  const response = await fetch(url, signal ? {signal} : undefined);
  if (!response.ok) { throw new Error(`Bitmap HTTP ${response.status}`); }
  const blob = await response.blob();
  return createImageBitmap(blob);
}

// FIX-04: 按关卡依赖加载图集页（不全量解码）；释放本关不再需要的已载页。
// RF-02：局部加载 → 会话校验 → 提交；失效会话的解码位图立即释放，不回写全局
// （旧请求晚到不污染新局，切换世界/重开不串页）。解码字节预算=项目目标
// （默认当前关常驻 ≤256MiB，单页 2048² RGBA≈16MiB），非原作事实。
async function loadAtlasPages(neededPages, gen) {
  const keep = new Set(neededPages);
  for (let i = 0; i < render.pages.length; i++) {
    if (render.pages[i] && !keep.has(i)) {
      render.pages[i].close();
      render.pages[i] = null;
      render.atlasCloseCount += 1;
    }
  }
  const toLoad = [...keep].filter((i) => !render.pages[i]);
  // PBA-03：allSettled 而非 all——任一页失败不能吞掉同批已成功解码的 bitmap。
  // 每个成功 bitmap 的唯一接管者：失效会话→逐个 close；否则发布 render.pages[i]；
  // 失败页抛错（成功页已发布，重试时 !render.pages[i] 只会重载失败页）。
  const results = await Promise.allSettled(toLoad.map(async (i) => {
    const bmp = await loadBitmap(render.atlas.pages[i].file);
    return {i, bmp};
  }));
  const loaded = [];
  const failed = [];
  for (const res of results) {
    if (res.status === "fulfilled") { loaded.push(res.value); }
    else { failed.push(res.reason); }
  }
  if (gen !== undefined && gen !== state.generation) {
    for (const {bmp} of loaded) { bmp.close(); }   // 失效会话：释放，不回写
    render.atlasCloseCount += loaded.length;
    return;
  }
  for (const {i, bmp} of loaded) { render.pages[i] = bmp; }
  if (failed.length) {
    throw new Error(`图集加载失败（${failed.length}/${toLoad.length} 页）: `
      + failed.map((e) => (e && e.message) || String(e)).join("; "));
  }
}

async function onWorkerReady() {
  try {
    const mf = await (await fetch("manifest.json")).json();
    state.manifest = mf;
    state.texts = await fetch("texts.json").then((r) => r.json());
    // 选关屏（生产流程：用户选关+种子 → 开始=音频解锁手势）
    const list = $("level-list");
    list.innerHTML = "";
    // A16：按类型轻量分组 + 中文类型标签
    const groups = new Map();
    for (const lv of mf.levels) {
      if (!groups.has(lv.type)) { groups.set(lv.type, []); }
      groups.get(lv.type).push(lv);
    }
    for (const [type, lvs] of groups) {
      const h = document.createElement("div");
      h.className = "level-group";
      h.textContent = `${TYPE_LABEL[type] || type}（${lvs.length} 关）`;
      list.appendChild(h);
      for (const lv of lvs) {
        const btn = document.createElement("button");
        btn.className = "level-btn";
        btn.dataset.id = lv.id;
        btn.textContent = lv.id;
        btn.onclick = () => {
          for (const b of list.querySelectorAll(".level-btn")) {
            b.classList.remove("sel");
          }
          btn.classList.add("sel");
          state.levelId = lv.id;
        };
        if (lv.id === state.levelId) { btn.classList.add("sel"); }
        list.appendChild(btn);
      }
    }
    $("seed-input").value = String(state.seed);
    $("start-btn").onclick = () => startGame(null, null);
    $("overlay").hidden = false;
    $("status").textContent = state.seedNote
      ? `${state.seedNote}（已用默认 2026）` : "请选择关卡并点击开始";
    $("status").className = state.seedNote ? "error" : "";
    state.phase = "selecting";
    state.booted = true;          // 完整初始化完成（manifest+texts+列表+overlay）
  } catch (e) {
    showError(e.message);
    state.phase = "error";
  }
}

async function startGame(levelId, seed) {
  flushCameraInput();                   // Preserve the last interface point before replacing the world.
  const gen = ++state.generation;      // 新会话代次：淘汰旧局及旧在途回包
  state.lastSnapshot = null;
  render.cameraReady = false;
  render.cameraControlGeneration = 0;
  render.presetReqSeq += 1;
  if (render.presetController) { render.presetController.abort(); }
  render.presetController = null;
  render.presetPending = null;
  stopLoop();                          // 停止上一局逻辑循环（若在跑）
  state.paused = false;                // 新局不继承暂停/后台/backlog/错误框（A2）
  state.manualPause = false;
  state.autoPaused = false;
  state.backlog = false;
  state.started = false;
  state.phase = "loading";
  state.endKind = null;                // A24：新局重置终局原因
  state.lastSnapshot = null;           // 换关加载中不绘制上一局残留（RF-05 F01 drawImage 竞态）
  updateHud(null);                    // also clear DOM progress before async loading
  $("error-box").hidden = true;
  updateUi();                          // BUG-02/03：装载相位立即冻结旧买兵栏/暂停/重开
  if (levelId) { state.levelId = levelId; }
  if (seed === null || seed === undefined) {
    const sv = validateSeed($("seed-input").value);
    if (!sv.ok) { showError(sv.error); return; }   // A7/A20：非法种子拒绝，不静默回退
    seed = sv.value;
  } else if (!Number.isSafeInteger(seed)) {
    showError(`种子须为有限安全整数（收到 ${seed}）`);
    return;
  }
  state.seed = seed;
  const lv = state.manifest.levels.find((x) => x.id === state.levelId);
  if (!lv) {                       // A19：无效关卡明确提示并可返回选择
    state.phase = "selecting";
    $("overlay").hidden = false;
    showError(`关卡 "${state.levelId}" 不存在，请重新选择`);
    return;
  }
  state.levelId = lv.id;
  state.buyable = lv.buyable;
  state.world = lv.world;
  $("overlay").hidden = true;
  $("endscreen").hidden = true;
  $("status").textContent = "装载中…";
  try {
    const [level, world, units] = await Promise.all([
      fetch(`levels/${lv.id}.json`).then((r) => r.json()),
      fetch(`worlds/${lv.world}.json`).then((r) => r.json()),
      fetch("units.json").then((r) => r.json()),
    ]);
    if (gen !== state.generation) { return; }              // 已被更新会话淘汰
    state.worldBasisVersion = world.worldBasisVersion ?? "legacy-grid-v1";
    state.units = units;                 // A4: 买兵栏中文名/价格数据源
    if (!render.atlas) {
      render.atlas = await fetch("atlas.json").then((r) => r.json());
      render.pages = new Array(render.atlas.pages.length).fill(null);
    }
    // FIX-04: 按本关 deps.atlasPages 加载/释放图集页（缺省/空回退全量，防御旧包）
    const atlasNeeded = (lv.deps && lv.deps.atlasPages
                         && lv.deps.atlasPages.length)
      ? lv.deps.atlasPages
      : render.atlas.pages.map((_, i) => i);
    await loadAtlasPages(atlasNeeded, gen);
    if (gen !== state.generation) { return; }              // 已被更新会话淘汰
    // 地形：局部加载 → 会话校验 → 提交；切世界时释放旧世界地形（RF-02）
    if (!render.terrain || render.terrainWorld !== lv.world) {
      const newTerrain = await loadBitmap(
        state.manifest.terrainFiles[lv.world]);
      if (gen !== state.generation) { newTerrain.close(); return; }
      if (render.terrain && render.terrainWorld !== lv.world) {
        render.terrain.close();          // 旧世界地形不再被引用
        render.terrainCloseCount += 1;
      }
      render.terrain = newTerrain;
      render.terrainWorld = lv.world;
    }
    render.projection = state.manifest.projection[lv.world];
    if (render.projection.kind && render.projection.kind !== "legacy-euler-v1") {
      throw new TypeError("Matrix default view is research-only until native sprites are verified");
    }
    // NC 相机交付：换关重置相机预设（预设与世界绑定，不跨关/跨世界泄漏）。
    // CAM-01：同步推进请求版本——旧局在途预设请求落地即被淘汰（generation
    // 已淘汰旧局回包，此处双保险；同局内意图语义见 setCameraPreset）。
    render.presetReqSeq += 1;
    commitCameraView(null, null, null);
    render.worldPresets =
      (state.manifest.cameraPresets || {})[lv.world] || null;
    state.levelProps = level.props;
    render.cameraControlGeneration = gen;
    // Packaged STATIC composite only, not original tracking. Production/test
    // use one policy; unsupported worlds retain the newly loaded overview.
    const defaultCamera = setCameraPreset(defaultCameraPresetFor(lv.world, render.worldPresets, lv.id, lv.type,
      Number(level.props.IsReversed?.[0] || 0) !== 0));
    renderFallbackReport();
    state.worldAmbient = (world.props.AmbientSfx || [null])[0];
    state.starts0 = {};
    // Camera controls can cancel a slow default after the legal overview base
    // exists. Gameplay controls remain disabled until init/default settle.
    renderBuyBar();
    updateUi();
    // multi 关敌方 Bot 配置来自 manifest（版本化显式演示配置, web_build.MULTI_DEMO_*）；
    // 不再用运行时启发式（旧 BugSetup 权重启发式对 multi 空 BugSetup 退化为 ant,
    // 无进攻能力）。非 multi 关 enemyBot=null（无敌方 Bot）。
    const opts = {buyable: state.buyable, enemyBot: lv.enemyBot || null};
    const isReset = state.sessionId !== null;
    let r;
    if (!isReset) {
      r = await call("init", {levelId: lv.id, seed, level, world, units,
                              opts});
    } else {
      r = await call("reset", {levelId: lv.id, seed, level, world, units,
                               opts});
      state.resetCount += 1;
    }
    if (gen !== state.generation) { return; }              // 已被更新会话淘汰
    if (!r.ok) { throw new Error(`init/reset 失败: ${r.error} ${r.detail}`); }
    await defaultCamera;
    if (gen !== state.generation) { return; }
    render.cameraReady = true;
    state.sessionId = r.result.sessionId;
    // HUD 文案（texts.json；中文用系统字体=表现层简化，见合同局限）
    $("hud-title").textContent =
      state.texts[state.levelProps.NameText?.[0]] || lv.id;
    $("hud-objective").textContent =
      state.texts[state.levelProps.Objective?.[0]] || "";
    $("status").textContent = `就绪：${lv.id}（${lv.type}）种子 ${seed}`;
    $("status").className = "ok";
    state.tick = 0;
    state.eventCursor = 0;
    state.receipts = [];
    state.lastSnapshot = null;
    render.yaw = {};
    render.lastPos = {};
    render.meshHeading = {};
    render.meshLastPos = {};
    $("eventlog").innerHTML = "";
    updateHud(null);
    // 音频：开始/重开按钮即用户手势；缺音频/未解锁不阻断
    audio.startGameAudio(
      lv.deps.music || null,
      state.worldAmbient ? `audio/${state.worldAmbient}.ogg` : null);
    // Keep rendering and gameplay locked until the actual first snapshot is
    // available. A synthetic {tick: 0} has no verified material/light state.
    await refresh({tick: 0, winner: null}, gen);
    if (gen !== state.generation) { return; }
    if (!state.lastSnapshot || state.lastSnapshot.tick !== 0
        || state.lastSnapshot.sessionId !== state.sessionId) {
      throw new Error('初始游戏快照不可用');
    }
    state.started = true;
    if (!state.startedOnce) {
      state.startedOnce = true;
      requestAnimationFrame(renderFrame);     // 呈现循环（只读快照）
    }
    state.phase = "running";
    updateUi();
    if (!state.testMode || state.recordMode) { startLoop(); }
  } catch (e) {
    if (gen !== state.generation) { return; }              // 已被更新会话淘汰
    state.phase = "error";
    showError(e.message);
  }
}

function renderFallbackReport() {
  const box = $("fallback-report");
  // A15：生产模式隐藏工程诊断（占位/缺图近似已登记于 manifest.capabilities/fallbacks；
  // 详细回退仅在 test/record 开发视图显示）
  if (!state.testMode && !state.recordMode) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const fbs = state.manifest.fallbacks || [];
  if (!fbs.length) { box.textContent = "无缺图回退。"; return; }
  box.innerHTML = "<b>缺图回退（显式，不冒充）：</b><br>" + fbs.map((f) =>
    `${f.unit}.${(f.clip || "*")}: ${f.kind}` +
    (f.fallbackClip ? ` → ${f.fallbackClip}` : "") +
    `（${f.why}）`).join("<br>");
}

function unitInfo(unit) {
  // A4: 中文名从 infoProps.NameText→texts；价格读单位数值（不从提示文案提取）
  const spec = (state.units || {})[unit];
  const nameKey = spec && spec.infoProps && spec.infoProps.NameText
    ? spec.infoProps.NameText[0] : null;
  const name = (nameKey && state.texts && state.texts[nameKey]) || unit;
  const price = (spec && spec.price !== null && spec.price !== undefined)
    ? spec.price : null;
  return {name, price};
}

function renderBuyBar() {
  const bar = $("buybar");
  bar.innerHTML = "";
  const controls = $("controls");
  controls.innerHTML = "";
  // OF-04：按 Priority 重排可买栏（面板插入排序口径：高优先靠前；exe-props §5、
  // research/of04_layout.py 0x48BCA0/0x48BE10）。Priority 已随 units.json 导出。
  // 20 按钮网格序与 24 槽面板序关系未 byte 证（HYPOTHESIS），此处采面板口径。
  const prio = (u) => {
    const p = (state.units && state.units[u]) ? state.units[u].priority : null;
    return (p === null || p === undefined) ? -1 : p;
  };
  const sorted = [...state.buyable].sort((a, b) => prio(b) - prio(a));
  for (const unit of sorted) {
    const {name, price} = unitInfo(unit);
    const btn = document.createElement("button");
    btn.id = `buy-${unit}`;
    btn.className = "buy";
    btn.dataset.unit = unit;          // 稳定 unit ID（A4: 不靠 textContent 取 ID）
    // OF-04：原作兵种图标（maingui_bug_*.vtx→icons/ PNG）；缺图标回退纯文本
    const iconPath = (state.manifest && state.manifest.icons
                      && state.manifest.icons[unit]) || null;
    if (iconPath) {
      const icon = document.createElement("img");
      icon.src = iconPath;
      icon.alt = name;
      icon.className = "buy-icon";
      icon.draggable = false;
      btn.appendChild(icon);
    }
    const label = document.createElement("span");
    label.className = "buy-label";
    label.textContent = name;
    btn.appendChild(label);
    if (price !== null) {
      const priceEl = document.createElement("span");
      priceEl.className = "price";
      priceEl.textContent = String(price);
      // STATIC: nectar/text belong to maingui_bar, not directly to button.
      // Screen placement below is responsive adaptation, not raw parent offsets.
      const priceBar = document.createElement("span");
      priceBar.className = "buy-price-bar";
      priceBar.appendChild(priceEl);
      btn.appendChild(priceBar);
    }
    btn.title = `${name}（${unit}）`;
    // OF-02：ReloadTime 倒计时展示（原作 ciBugButton 覆盖，纯展示非门禁——按钮仍可点）
    const reload = document.createElement("span");
    reload.className = "reload";
    reload.hidden = true;
    btn.appendChild(reload);
    btn.onclick = () => submitBuy(unit);
    bar.appendChild(btn);
  }
  // 泳道下拉来自当前世界我方 START（A8: 不硬编码 0..3）
  const lanes = Object.keys(state.starts0 || {}).map(Number).sort((a, b) => a - b);
  const laneSel = document.createElement("select");
  laneSel.id = "lane";
  for (const i of (lanes.length ? lanes : [0])) {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = `泳道 ${i}`;
    laneSel.appendChild(o);
  }
  controls.appendChild(laneSel);
  const camera = document.createElement("select");
  camera.id = "camera-mode";
  camera.setAttribute("aria-label", "画面视角");
  for (const [value, label] of [[NEAR_CAMERA_PRESET, "近景"], ["overview", "全景"],
                               ["native_camera", "动态视角"],
                               ["original_static_01", "原作首关视角"], ["mesh_cam", "网格视角"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    camera.appendChild(option);
  }
  camera.onchange = () => {
    if (!cameraControlAvailable()) { updateCameraControl(); return; }
    const key = camera.value === "overview" ? null : camera.value;
    void setCameraPreset(key);
  };
  controls.appendChild(camera);
  const meshControls = document.createElement('span');meshControls.id='mesh-controls';
  meshControls.hidden = true;
  const meshTarget = document.createElement('select');meshTarget.id='mesh-target';
  meshTarget.setAttribute('aria-label','跟随对象');
  meshTarget.onchange = () => { if (render.meshFollowId !== null) {
    render.meshFollowId = meshTarget.value === 'auto' ? 'auto' : Number(meshTarget.value);
  }};
  const follow = document.createElement('button');follow.id='mesh-follow';follow.textContent='跟随';
  follow.onclick = () => {
    if (!render.meshScene || !render.activePreset?.meshView) { return; }
    render.meshFollowId = render.meshFollowId === null
      ? (meshTarget.value === 'auto' ? 'auto' : Number(meshTarget.value)) : null;
    if (render.meshFollowId !== null) {
      render.meshZoomFactor = Math.max(.35, Math.min(1.5,180/render.activePreset.meshView.distance));
    }
  };
  const home = document.createElement('button');home.id='mesh-home';home.textContent='视野复位';
  home.onclick = () => {
    if (!render.meshScene || !render.activePreset?.meshView) { return; }
    setMeshProjection(render.activePreset.projection);
    render.meshFollowId=null;render.meshZoomFactor=1;render.meshTargetYup=null;
    render.meshCameraPending=false;
  };
  const zoom = document.createElement('input');zoom.id='mesh-zoom';zoom.type='range';
  zoom.min='.35';zoom.max='1.5';zoom.step='.01';zoom.value='1';
  zoom.setAttribute('aria-label','视野距离');
  zoom.oninput = () => { if (render.meshScene && render.activePreset?.meshView) {
    render.meshZoomFactor=Number(zoom.value);
    render.meshCameraPending=true;
  } };
  meshControls.append(meshTarget,follow,home,zoom);controls.appendChild(meshControls);
  const pause = document.createElement("button");
  pause.id = "pause-btn";
  pause.textContent = "暂停";
  pause.onclick = () => setPaused(!state.paused);
  controls.appendChild(pause);
  const reset = document.createElement("button");
  reset.id = "reset-btn";
  reset.textContent = "重开";
  reset.onclick = () => startGame(null, state.seed)
    .then(() => {}).catch((e) => showError(e.message));
  controls.appendChild(reset);
  const mute = document.createElement("button");
  mute.id = "mute-btn";
  mute.textContent = "静音";
  mute.onclick = () => {
    audio.setMuted(!state.muted);
    mute.textContent = state.muted ? "放音" : "静音";
  };
  controls.appendChild(mute);
  const back = document.createElement("button");
  back.id = "back-btn";
  back.textContent = "选关";
  back.onclick = () => leaveGame();
  controls.appendChild(back);
  const cameraNote = document.createElement("span");
  cameraNote.id = "camera-note";
  cameraNote.setAttribute("role", "status");
  controls.appendChild(cameraNote);
  updateCameraControl();
}

async function submitBuy(unit) {
  // 合同 §3：loading/selecting/ended/error 期间不接受游戏输入（旧按钮残留点击被拒）
  if (state.phase !== "running") {
    state.lastReceipt = {queued: false, reason: "E_NOT_RUNNING"};
    return {ok: false, error: "E_NOT_RUNNING"};
  }
  // 合同 §2.3：暂停期间不执行买兵，按合同拒绝输入（UI 层禁用+拒绝）
  if (state.paused || state.winnerLocked()) {
    state.lastReceipt = {queued: false, reason: "E_PAUSED"};
    return {ok: false, error: "E_PAUSED"};
  }
  const lane = parseInt(document.getElementById("lane").value, 10);
  const gen = state.generation;               // 本次购买所属会话代次（PBA-02）
  const r = await call("submit", {cmd: {
    sessionId: state.sessionId,
    commandId: `ui-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
    targetTick: null,
    type: "buy", unit, lane,
  }});
  if (gen !== state.generation) { return r; } // 旧局回包：完成 Promise，不改写新局状态
  state.lastReceipt = r.result;
  state.receipts.push(r.result);
  if (r.result && r.result.queued === false) {
    // 提交层拒绝（E_UNIT/E_LANE/E_DUP/E_SESSION/E_ENDED）可见反馈；E_PRICE 走事件
    const reason = r.result.reason || "";
    const {name} = unitInfo(unit);
    const msgs = {E_UNIT: `单位 ${name} 不在本关可买栏`,
                  E_LANE: "泳道无效", E_ENDED: "对局已终局，无法购买",
                  E_DUP: "重复命令", E_SESSION: "会话失效"};
    showBuyFeedback(msgs[reason] || `买兵被拒：${reason}`, "reject");
  }
  if (!r.ok) { showError(`买兵被拒: ${r.error} ${r.detail || ""}`); }
  return r;
}

async function resetGame(seed) {     // 重开按钮：同关同/新种子（startGame 复用 reset 桥）
  return startGame(null, seed);
}

// ── 点击选道（H3 点击映射）：canvas → 世界坐标 → 最近我方 START 泳道 ──
// CAM-02：canvasToWorld 返回**显式无命中 null**——画布内容框外（含 NaN）、
// 预设激活时上下黑带、射线与地面平行、交点在射线后方（s<0）、坐标非有限。
// onCanvasClick 收 null 不改泳道（A8 同口径提示）。旧实现黑带/画布外
// 照常反解（黑带点击改道的反例见 review 探针 letterboxInput）。
function canvasToWorld(ev) {
  const cvs = $("scene");
  const visible = $("worldstage").getBoundingClientRect();
  // Strict client visibility, before the legacy 0.5 logical-pixel tolerance.
  // The translated square extends outside stage; that hidden area is no hit.
  if (!(visible.width > 0 && visible.height > 0
        && Number.isFinite(ev.clientX) && Number.isFinite(ev.clientY)
        && ev.clientX >= visible.left && ev.clientX <= visible.right
        && ev.clientY >= visible.top && ev.clientY <= visible.bottom)) {
    return null;
  }
  const rect = cvs.getBoundingClientRect();
  // NC-03 视口合同：内容框（border-box 减边框）↔ backing 精确换算——
  // rect 含边框，clientLeft/clientTop = 边框宽；旧版按 border-box 线性映射
  // 有 ~边框宽×(640/内容宽) backing px 系统性偏移（与 CSS 缩放/DPR 无关）。
  // NC-04：backing 随 DPR 缩放（640×dpr）——逆映射一律用逻辑 640（CANVAS_SIZE），
  // 不读 cvs.width（DPR≥2 时为 1280，混用会双重缩放）。
  const bw = cvs.clientLeft, bh = cvs.clientTop;
  const cw = rect.width - bw * 2, ch = rect.height - bh * 2;
  // CAM-02：内容框退化（隐藏/零尺寸）→ 无命中（cw/ch 非有限同落此分支）
  if (!(cw > 0 && ch > 0)) { return null; }
  const cx = (ev.clientX - rect.left - bw) * CANVAS_SIZE / cw;
  const cy = (ev.clientY - rect.top - bh) * CANVAS_SIZE / ch;
  // CAM-02：换算后出 0..640 逻辑域（CSS 缩放/边框外/画布外）→ 无命中。
  // NaN 经同一分支排除（与 NaN 的比较恒 false → 断言不成立即出界）。
  if (!(cx >= 0 && cx <= CANVAS_SIZE && cy >= 0 && cy <= CANVAS_SIZE)) {
    return null;
  }
  const matrix = activeProjection();
  if (matrix.kind === "matrix-yup-v1") {
    const contentH = CANVAS_SIZE / matrix.aspect, offY = (CANVAS_SIZE-contentH)/2;
    if (cy < offY-0.5 || cy > offY+contentH+0.5) { return null; }
    const k = CANVAS_SIZE / (matrix.size*matrix.aspect);
    return BugBitsCameraProjection.pixelToGround(matrix,cx/k,(cy-offY)/k);
  }
  if (matrix.kind && matrix.kind !== "legacy-euler-v1") {
    throw new TypeError("Unknown camera projection kind");
  }
  // NC 相机交付：预设激活走通用基向量逆映射（含 yaw/aspect/letterbox）；
  // 默认（无预设）走旧闭式（位级不变，OF-03.B/C pixel_to_ground）。
  if (render.activePreset) {
    const p = activeProjection();
    const contentH = CANVAS_SIZE / p.aspect;
    const offY = (CANVAS_SIZE - contentH) / 2;
    // CAM-02：上下黑带显式无命中。容差 0.5 逻辑像素 = 640 逻辑网格的量化
    // 半步（clientX/Y 经 CSS 内容框亚像素换算而来，±0.5px 内无法区分边界
    // 内外；再收紧会拒掉贴边的合法命中——C07/CAM01 的边界往返在容差内）。
    if (cy < offY - 0.5 || cy > offY + contentH + 0.5) { return null; }
    const ndcX = 2 * cx / CANVAS_SIZE - 1;
    const ndcY = 1 - 2 * (cy - offY) / contentH;
    // 相机空间射线 (ndcX·aspect/cot, ndcY/cot, 1) → 世界方向（基向量）
    const d0 = ndcX * p.aspect / p.cot, d1 = ndcY / p.cot;
    const dxw = p.cosY * d0 + p.sinP * p.sinY * d1 + p.sinY * p.cosP;
    const dyw = p.cosP * d1 - p.sinP;
    const dzw = -p.sinY * d0 + p.sinP * p.cosY * d1 + p.cosY * p.cosP;
    // CAM-02：射线与地面平行（|dyw| 过小）→ 无命中。dyw 为方向的世界 y
    // 分量、量级 O(1)（world_03 wide_cam 合法命中 |dyw|≥0.13，含 aspect/cot
    // 缩放后仍远离 0）；容差 1e-9 只滤浮点消去产生的伪平行——s 除以 dyw
    // 在其→0 时发散，任何更宽的值都会吞掉贴地平线的拒绝语义。
    if (Math.abs(dyw) < 1e-9) { return null; }
    // 射线原点 camPos = target − distance·f（ty=0）；s = −camPos.y/dyw
    const s = -(p.distance * p.sinP) / dyw;
    // CAM-02：交点在射线后方（s<0，内容区内但地平线以上的朝上射线）→
    // 无命中（s=NaN 经同一分支排除）。
    if (!(s > 0)) { return null; }
    const ox = p.tx - p.distance * p.sinY * p.cosP;
    const oz = p.tz - p.distance * p.cosY * p.cosP;
    const wx = ox + s * dxw, wz = oz + s * dzw;
    if (!Number.isFinite(wx) || !Number.isFinite(wz)) { return null; }
    return [wx, wz];
  }
  const p = render.projection;
  const k = CANVAS_SIZE / p.size;              // 画布像素→地形空间像素
  const px = cx / k, py = cy / k;
  // 逆映射（OF-03.B/C，render/camera.py pixel_to_ground，y=0 地面）
  const nx = 2 * px / p.size - 1;
  const ny = 1 - 2 * py / p.size;
  const t = p.distance * p.tanP / (p.tanP - ny / p.cot);
  const dx = t * nx / p.cot;
  const dz = t * ny / (p.cot * p.sinP);
  // CAM-02：默认路径仅加非有限防护（平行→t 发散、退化常数→NaN/Inf）；
  // 合法命中公式与返回值位级不变（C07 合同）。真实默认投影
  // （pitch 40°/fov 60°）整幅画布在地平线以下，防护不触达合法命中。
  if (!Number.isFinite(dx) || !Number.isFinite(dz)) { return null; }
  return [p.cx + dx, p.cz + dz];
}

function onCanvasClick(ev) {
  if (!render.projection || !state.lastSnapshot) { return; }
  const hit = canvasToWorld(ev);
  if (hit === null) {
    // CAM-02：黑带/画布外/平行/反向射线——显式无命中：不改泳道，
    // 提示口径与 A8 非法点击一致（不静默）。
    $("status").textContent = "点击位置无有效泳道（点击地图上标记的泳道点）";
    $("status").className = "error";
    return;
  }
  const [wx, wz] = hit;
  // Runtime START sides come from the normal-level snapshot, including reversal.
  let best = null, bestD = Infinity;
  for (const [lane, pos] of Object.entries(state.starts0 || {})) {
    const d = (pos[0] - wx) ** 2 + (pos[2] - wz) ** 2;
    if (d < bestD) { bestD = d; best = lane; }
  }
  if (best !== null && bestD < 200 * 200) {    // 200u 内才算有效选择
    document.getElementById("lane").value = best;
    $("status").textContent = `已选泳道 ${best}（点击地图）`;
    $("status").className = "ok";
  } else {
    // A8: 非法点击不再静默——明确提示且不改选择
    $("status").textContent = "点击位置无有效泳道（点击地图上标记的泳道点）";
    $("status").className = "error";
  }
}

let loopRaf = 0;             // 逻辑循环 rAF 句柄（唯一所有权）
let activeLoops = 0;         // 诊断：活动逻辑循环数（测试只读 loopStats）
let loopRegCount = 0;        // 诊断：逻辑循环注册次数

function startLoop() {
  stopLoop();                          // 取消既有逻辑循环（不重复注册）
  state.running = true;
  clock.reset();
  activeLoops += 1;
  loopRegCount += 1;
  loopRaf = requestAnimationFrame(loopFrame);
}

function loopFrame(nowMs) {
  if (!state.running) { activeLoops = Math.max(0, activeLoops - 1); return; }
  clock.step(nowMs);
  loopRaf = requestAnimationFrame(loopFrame);
}

function stopLoop() {
  state.running = false;
  if (loopRaf) { cancelAnimationFrame(loopRaf); loopRaf = 0; }
  activeLoops = Math.max(0, activeLoops - 1);
}

// 离开对局回选关屏：淘汰在途回包 + 停止循环 + 重置暂停/错误提示（A17/A2）
function leaveGame() {
  flushCameraInput();
  state.generation += 1;      // 在途 advance/snapshot/events 回包据此被淘汰
  render.cameraReady = false;
  render.cameraControlGeneration = 0;
  render.presetReqSeq += 1;
  if (render.presetController) { render.presetController.abort(); }
  render.presetController = null;
  render.presetPending = null;
  commitCameraView(null, null, null);
  stopLoop();
  audio.stopMusic();
  $("endscreen").hidden = true;
  $("error-box").hidden = true;
  $("overlay").hidden = false;
  $("status").textContent = "请选择关卡并点击开始";
  $("status").className = "";
  state.phase = "selecting";
  state.paused = false;
  state.manualPause = false;
  state.autoPaused = false;
  state.backlog = false;
}

function setPaused(pause, manual = true) {
  if (pause === state.paused) { return; }
  state.paused = pause;
  if (manual) { state.manualPause = pause; }
  if (!pause) {
    state.backlog = false;
    $("error-box").hidden = true;
    clock.reset();                 // 恢复重置锚点：不补算暂停时长
    state.manualPause = false;
  }
  updateUi();
}

function updateUi() {
  const ended = state.winnerLocked();
  // 装载/选关相位锁定全部游戏控件，与 submitBuy 的 E_NOT_RUNNING 契约一致
  // （BUG-02/03：装载窗口内旧买兵栏/暂停按钮仍可点 → 静默 no-op / 新局冻结）
  const loading = state.phase === "loading" || state.phase === "selecting";
  const lock = loading || state.paused || ended;
  for (const btn of document.querySelectorAll("button.buy")) {
    btn.disabled = lock;
  }
  // pause/reset 按钮由 renderBuyBar 动态创建，首次 startGame（装载窗口）尚未
  // 存在 → 空安全守卫（首局装载时无需更新不存在的按钮，后续 renderBuyBar 会建）。
  const pauseBtn = $("pause-btn");
  if (pauseBtn) {
    pauseBtn.textContent = state.paused ? "继续" : "暂停";
    pauseBtn.disabled = loading || ended;
  }
  const resetBtn = $("reset-btn");
  if (resetBtn) {
    resetBtn.disabled = loading;
  }
  updateCameraControl();
}

async function refresh(adv, gen) {
  const g = gen === undefined ? state.generation : gen;
  state.tick = adv.tick;
  $("tick").textContent = adv.tick;
  const s = await call("snapshot", {});
  if (g !== state.generation) { return; }      // 旧局：不再更新 HUD/终局
  if (s.ok) {
    state.lastSnapshot = s.result;
    state.starts0 = {};
    for (const start of s.result.starts) {
      if (start.side === 0) { state.starts0[start.index] = start.pos; }
    }
    updateHud(s.result);
  }
  await pollEvents(g);
  if (g !== state.generation) { return; }
  if (adv.winner !== null) {
    stopLoop();
    setPaused(false, false);
    audio.playEvent(adv.winner === 0 ? "victory_win" : "victory_lose");
    showEndScreen(adv.winner, adv.tick);
  }
}

function updateHud(snap) {
  if (!snap) {
    $("hud-nectar").textContent = "—";
    $("hud-mine").textContent = "";
    $("hud-enemy").textContent = "";
    for (const id of ["mine", "enemy"]) {
      $("hud-" + id).title = "";
      $("hud-" + id + "-fill").style.width = "0%";
    }
    $("hud-units").textContent = "—";
    $("hud-timer").textContent = "";
    return;
  }
  $("hud-nectar").textContent = String(snap.nectar[0]);
  const [mine, theirs] = snap.hives;
  // EXE 0x49AD80 / 0x49179B and enemy 0x47ECB0: hp / 10, not
  // hp / level's initial size. Display easing is still not reproduced.
  for (const [id, h, property] of [["mine", mine, "PlayerBaseSize"],
                                  ["enemy", theirs, "EnemyBaseSize"]]) {
    const absent = Number(state.levelProps?.[property]?.[0]) === 0;
    const ratio = h.hp / 10;
    $("hud-" + id).textContent = absent ? "—" : `${Math.trunc(ratio * 100 + 0.1)}%`;
    $("hud-" + id).title = `${id === "mine" ? "我巢" : "敌巢"} ${h.hp}`;
    // Engineering containment above 100%; original >1 UV/wrap behaviour remains
    // unverified. Normal [0,1] width and left/right crop follow STATIC HUD data.
    $("hud-" + id + "-fill").style.width = absent ? "0%"
      : `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  }
  $("hud-units").textContent = String((snap.bugs || []).filter(b => b.side === 0).length);
  // defense/multi 倒计时（静态关卡配置推导；battle 关不显示）
  const dt = state.levelProps?.DefenseTime?.[0];
  if (dt !== undefined && dt !== null) {
    const deadline = Math.round((parseFloat(dt) + 0.5) * TICK_HZ);
    const left = Math.max(0, deadline - snap.tick);
    $("hud-timer").textContent = `倒计时 ${(left / TICK_HZ).toFixed(1)}s`;
  } else {
    $("hud-timer").textContent = "";
  }
  // OF-02：每兵种 ReloadTime 倒计时展示（快照 reload=剩余 tick；纯展示非门禁）
  const reload = snap.reload || {};
  for (const btn of document.querySelectorAll("button.buy")) {
    const unit = btn.dataset.unit;
    const badge = btn.querySelector(".reload");
    if (!badge) { continue; }
    const left = reload[unit] ?? 0;
    if (left > 0) {
      badge.textContent = `${(left / TICK_HZ).toFixed(0)}s`;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  }
  const failed = [...audio.failed]
    .map((f) => `音频加载失败: ${f}（逻辑不受影响）`).join("；");
  const note = [audio.note, failed].filter(Boolean).join("；");
  if (note) {
    $("audio-note").textContent = note;
    $("audio-note").hidden = false;
  }
}

function showEndScreen(winner, tick) {
  const key = state.levelProps[winner === 0 ? "WinText" : "LoseText"]?.[0];
  const title = $("end-title");
  // A24/PBA-01：原因与胜负是两个字段——endKind 说明为何结束（timeup/survived/rescued），
  // winner 决定胜负样式与文字。多人超时我方 HP 领先时 winner=0 + endKind=timeup 合法，
  // 必须显示玩家获胜而非判负；原因仅作括号说明入状态栏，不覆盖胜负。
  const reason = {timeup: "时间到", survived: "防守成功",
                  rescued: "营救成功"}[state.endKind];
  title.textContent = winner === 0 ? "胜利！" : "失败";
  title.className = winner === 0 ? "win" : "lose";
  $("end-text").textContent = state.texts[key] || key || "";
  $("end-tick").textContent = `tick ${tick}`;
  $("endscreen").hidden = false;
  const who = winner === 0 ? "玩家胜" : "敌方胜";
  $("status").textContent = `终局：${who}${reason ? `（${reason}）` : ""} @tick ${tick}`;
  state.phase = "ended";
  audio.stopMusic();      // A12：终局停循环音乐/环境音（Web 产品选择，非原作事实）
  updateUi();
}

async function pollEvents(gen) {
  const g = gen === undefined ? state.generation : gen;
  const r = await call("read_events", {afterSeq: state.eventCursor});
  if (g !== state.generation) { return; }
  if (!r.ok) { return; }
  const evs = r.result.events;
  state.eventCursor = r.result.nextSeq;
  if (r.result.gap) {
    showError("事件流溢出（保留窗），显示可能缺失早期事件。");
  }
  const log = $("eventlog");
  for (const e of evs) {
    // A24：记录终局原因（timeup=超时判负 / survived=防守存活 / rescued=营救成功）
    if (e.type === "timeup" || e.type === "survived" || e.type === "rescued") {
      state.endKind = e.type;
    }
    if (e.type === "buy_ok") {
      audio.playEvent("buy_ok");
      const {name} = unitInfo(e.data.unit);
      showBuyFeedback(`已购买 ${name}，-${e.data.price} 花蜜（余 ${e.data.nectar}）`,
                      "ok");
    } else if (e.type === "buy_reject") {
      if (e.data.reason === "E_PRICE") {
        const {name} = unitInfo(e.data.unit);
        showBuyFeedback(`花蜜不足：${name} 需 ${e.data.price}（现有 ${e.data.nectar}）`,
                        "reject");
      } else if (e.data.reason === "E_ENDED") {
        showBuyFeedback("对局已终局，无法购买", "reject");
      } else if (e.data.reason === "E_CD") {
        // OFR-02B：泳道冷却门禁（ceStart +0x22c），UI 提示与实际可买状态一致
        const {name} = unitInfo(e.data.unit);
        showBuyFeedback(`泳道 ${e.data.lane} 冷却中，无法购买 ${name}`, "reject");
      }
    }
    const line = document.createElement("div");
    line.textContent = `t${e.tick} ${e.type} ${JSON.stringify(e.data).slice(0, 60)}`;
    log.prepend(line);
  }
  while (log.childElementCount > 30) { log.removeChild(log.lastChild); }
}

// ── 渲染（rAF 呈现层；帧率不改变 RNG/游戏 tick） ─────────────────────
function worldToCanvas(x, z) {
  // Compatibility seam is explicitly ground-only; entity anchors use point3.
  const q = projectCanvasPoint([x, 0, z]);
  return q ? [q.px, q.py] : null;
}

function clipFor(bug) {
  if (bug.dead) { return null; }
  if (bug.attackTick >= 0) { return "normal_attack"; }
  if (bug.mode === "idle" || bug.trapped) { return "idle"; }
  return "walk";                            // patrol/home/lane 行进
}

// ── CAM-03 工程边缘指示（HUD 层，独立于世界层 clip；非原作 UI） ──────
// 预设 letterbox 激活且关键操作目标（我方巢穴/当前选中泳道出生点）投影在
// 内容区外（截断或相机背后）时，在内容区内缘画有界方向标记+文字，并经
// drawLog 登记 px/py/dir（几何断言面）。恢复路径 = setCameraPreset(null)
// 回 overview（研究/测试入口）。原作对应呈现无逆向证据——**工程补偿，
// 不称原作 UI**；original_cam 目标点为混合状态假设（非原作跟随相机实证）。
function targetCamZ(x, z, height = 0) {
  return cameraSpacePoint([x, height, z])[2];
}

function drawTargetIndicator(ctx, name, x, z, slot, offY, contentH, color, height = 0) {
  const projected = projectCanvasPoint([x, height, z]);
  const [px, py] = projected ? [projected.px, projected.py] : [CANVAS_SIZE / 2, offY + 18];
  const behind = targetCamZ(x, z, height) <= 0 || !projected;      // 相机背后：投影已爆炸，只指示存在
  const cx = Math.min(Math.max(px, 16), CANVAS_SIZE - 16);
  // 有界堆叠（CAM-03）：多目标钳到同一边缘点时逐个错位（贴下缘向上堆、
  // 其余向下），避免三角互相覆盖（world_03 original_cam 我方巢穴与出生点
  // 同在相机背后→同钳 (624,138)，首版后者盖掉前者——CAM05 像素探针红端）
  let cy = behind ? offY + 18
    : Math.min(Math.max(py, offY + 18), offY + contentH - 14);
  cy += (behind || py <= offY + contentH ? 1 : -1) * slot * 16;
  cy = Math.min(Math.max(cy, offY + 14), offY + contentH - 10);
  const dirX = behind ? 0 : Math.sign(px - cx);
  const dirY = behind ? -1 : Math.sign(py - cy);
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(Math.atan2(dirY, dirX));
  ctx.fillStyle = color;
  ctx.beginPath();                           // +x 方向实心三角（中心像素纯色）
  ctx.moveTo(8, 0);
  ctx.lineTo(-5, -5);
  ctx.lineTo(-5, 5);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  ctx.font = "11px 'Noto Sans SC', system-ui, sans-serif";
  ctx.fillStyle = color;
  ctx.textBaseline = "top";
  // 文字有界（CAM-03）：贴下内容缘时改画在标记上方、水平居中并钳制在
  // 画布内——工程指示自身不越出内容区，黑带保持纯净（CAM-02 像素探针以
  // 黑带无任何非背景像素为验收，HUD 亦不得污染）。
  const label = state.testMode || state.recordMode ? `${name}·工程指示` : name;
  const tw = ctx.measureText(label).width;
  const tx = Math.min(Math.max(cx - tw / 2, 4), CANVAS_SIZE - tw - 4);
  let ty = cy + 8 + slot * 13;
  if (ty + 13 > offY + contentH) { ty = cy - 21 - slot * 13; }
  ctx.fillText(label, tx, ty);
  render.draws.push({id: `indicator:${name}`, clip: "indicator", frame: 0,
                     px: cx, py: cy, dirX, dirY, behind,
                     target: [x, z], color});
}

function drawTargetIndicators(ctx, snap, offY, contentH) {
  // 我方巢穴 + 当前选中泳道出生点（操作目标）；可见（内容区内）不画
  const targets = [];
  const hive0 = snap.hives.find((h) => h.side === 0);
  if (hive0) { targets.push(["我方巢穴", hive0.pos[0], hive0.pos[2],
                             "#50c850", hive0.pos[1]]); }
  const laneSel = $("lane");
  const cur = laneSel ? Number(laneSel.value) : -1;
  const pos = (cur >= 0 && state.starts0) ? state.starts0[cur] : null;
  if (pos) { targets.push([`出生·泳道${cur}`, pos[0], pos[2], "#e8c84a", pos[1]]); }
  targets.forEach(([label, x, z, color, height], slot) => {
    const q = projectCanvasPoint([x, height, z]);
    const [px, py] = q ? [q.px, q.py] : [NaN, NaN];
    const depth = targetCamZ(x, z, height), p = activeProjection();
    const visible = q && depth >= p.near && depth <= p.far && px >= 0 && px <= CANVAS_SIZE
      && py >= offY && py <= offY + contentH && depth > 0;
    if (!visible) {
      drawTargetIndicator(ctx, label, x, z, slot, offY, contentH, color, height);
    }
  });
}

// OF-03.C：单位世界比例（ScaleFactor，DATA bugs/*.vsc，1.0–1.6）。图集装箱仍
// 128px fit-to-box（不按 ScaleFactor 重排），相对比例在 draw 层缩放。原作单位世界
// 足迹 = 模型体量 × ScaleFactor；atlasScale已恢复fit-to-box前的绝对世界体量。
function unitScale(unit) {
  const spec = (state.units || {})[unit];
  const raw = spec && spec.props && spec.props.ScaleFactor;
  const v = raw ? parseFloat(raw[0]) : NaN;
  return (v > 0) ? v : 1.0;
}

// NC-03：单位公告板（世界尺寸/锚点/飞行高度）。Python 权威实现
// src/bugbits/render/billboard.py，本函数镜像同一公式（跨环境一致由 C03/N05
// 断言）。返回 {px, py, camZ, lam}：px/py = 模型中心投影（内容框中心对齐点），
// lam = 图集像素→画布像素。ScaleFactor 只在此乘一次。
// NC 相机交付：预设激活走一般基向量式（yaw/aspect/letterbox）+ 预设 atlasScale；
// 默认走旧式（位级不变）。
function unitBillboard(b, unit) {
  const spec = state.units[unit] || {};
  const ws = spec.worldSize || {w: 12, h: 7, d: 12};
  const asc = render.activePreset
    ? (render.activePreset.unitAtlasScale[unit] || spec.atlasScale
       || (Math.max(ws.w, ws.h, ws.d) / (0.8 * 128)))
    : (spec.atlasScale || (Math.max(ws.w, ws.h, ws.d) / (0.8 * 128)));
  const sf = unitScale(unit), p = activeProjection();
  const center = [b.pos[0], b.pos[1] + ws.h * sf / 2, b.pos[2]];
  const q = projectCanvasPoint(center, p);
  if (!q || q.camZ < p.near || q.camZ > p.far) { return null; }
  return {...q, lam: asc * sf * p.cot * CANVAS_SIZE / (2 * q.camZ * (p.aspect ?? 1))};
}

// NC-03B：花蜜 props 世界尺寸投影（静态单精灵，无 ScaleFactor）。与 unitBillboard
// 同公式，但 worldSize/atlasScale 取 manifest.props.flower（flower_a.v3d bind AABB）。
// NC 相机交付：预设激活用预设 flowerAtlasScale + 通用式；默认旧式（位级不变）。
function flowerBillboard(pos) {
  const meta = (state.manifest.props && state.manifest.props.flower) || {};
  const ws = meta.worldSize || {w: 21.44, h: 15.53, d: 17.98};
  const asc = render.activePreset
    ? (render.activePreset.flowerAtlasScale || meta.atlasScale || 0.2093)
    : (meta.atlasScale || 0.2093);
  const p = activeProjection(), q = projectCanvasPoint([pos[0], pos[1] + ws.h / 2, pos[2]], p);
  if (!q || q.camZ < p.near || q.camZ > p.far) { return null; }
  return {...q, lam: asc * p.cot * CANVAS_SIZE / (2 * q.camZ * (p.aspect ?? 1))};
}

// NC-03：按稳定瓦片中心锚定绘制单位精灵（NC-03A：与逐帧 alpha bbox cb 分离，
// cb 仅作裁剪/内容宽测量，不作锚点）。瓦片中心 = bind 姿态 AABB 中心投影 ↔
// unitBillboard 投影点；lam = 图集像素→画布像素（世界尺寸合同）。
function drawUnitSprite(ctx, key, px, py, lam) {
  const s = render.atlas.sprites[key];
  if (!s) { return false; }
  const img = render.pages[s.page];
  // 图集页未载入（换关加载中）或已 close（width==0）→ 跳过绘制，不抛 drawImage 异常
  if (!img || img.width === 0) { return false; }
  ctx.drawImage(img, s.x, s.y, s.w, s.h,
                px - (s.w / 2) * lam, py - (s.h / 2) * lam,
                s.w * lam, s.h * lam);
  return true;
}

function resolveClip(unit, clip) {
  // 缺图回退按 atlas 显式 fallbackClip（不静默替换）
  let c = render.atlas.clips[unit][clip];
  const seen = new Set();
  while (c && c.kind === "missing" && c.fallbackClip && !seen.has(clip)) {
    render.fallbackHits[`${unit}.${clip}`] =
      (render.fallbackHits[`${unit}.${clip}`] || 0) + 1;
    seen.add(clip);
    clip = c.fallbackClip;
    c = render.atlas.clips[unit][clip];
  }
  return c && c.kind !== "missing" ? {clip, def: c} : null;
}

function attackElapsedSeconds(bug) {
  // Bridge attackTick is elapsed playback ticks, not the global start tick.
  // Current Sim uses the shared UnitSpec rate; native instance overrides remain open.
  const configured = state.units?.[bug.unit]?.props?.AttackSpeed;
  const speed = configured === undefined ? 1 : Number(configured[0]);
  if (!Number.isFinite(speed)) { throw new TypeError('Attack animation speed'); }
  return Math.max(0, (bug.attackTick || 0) * (speed || 1) / TICK_HZ);
}

function walkPhaseSeconds(bug, clip, duration) {
  const track = bug.walkAnimation;
  if (clip !== 'walk' || track === null || track === undefined) { return null; }
  if (track.scope !== 'normal-ground-walk-track-f32-20hz-v1' || track.clip !== 'walk' ||
      typeof track.phase !== 'number' || !Number.isFinite(track.phase) || track.phase < 0 ||
      track.duration !== duration) { throw new TypeError('Walk snapshot animation phase'); }
  // Sim already performed the native single subtraction. Exact-end and large
  // overshoot must reach the final sampled frame, not wrap a second time here.
  return track.phase;
}

function frameIndex(cdef, bug, nowMs) {
  const frames = cdef.frames;
  if (frames <= 1) { return 0; }
  const frameSec = cdef.duration / frames;
  const walkTime = walkPhaseSeconds(bug, cdef.clip, cdef.duration);
  let t;
  if (cdef.def_kind === "attack") {          // 语义对齐：攻击按游戏 tick
    t = attackElapsedSeconds(bug);
  } else if (walkTime !== null) {
    t = walkTime;
  } else if (state.testMode) {
    // 测试模式：循环帧由游戏 tick 决定（渲染可复现——游戏冻结时帧不随
    // rAF 漂移；生产模式仍用展示时钟）
    t = ((state.tick + bug.id) % frames) * frameSec;
  } else {                                   // 循环 clip：展示时钟
    t = (nowMs / 1000) % cdef.duration;
  }
  return Math.min(frames - 1, Math.max(0, Math.floor(t / frameSec)));
}

// The mesh adapter consumes game time and world heading, independent of camera.
function meshDrawRecords(snapshot) {
  const result = [], units = render.meshAssets.units;
  for (const bug of snapshot.bugs) {
    if (bug.dead) { continue; }
    const unit = units[bug.unit];
    if (!unit) { throw new Error(`Missing mesh unit ${bug.unit}`); }
    let clip = clipFor(bug), cdef = unit.clips[clip];
    const visited = new Set();
    while (cdef && cdef.kind === 'missing' && cdef.fallbackClip && !visited.has(clip)) {
      visited.add(clip); clip = cdef.fallbackClip; cdef = unit.clips[clip];
    }
    if (!cdef || cdef.kind === 'missing') { throw new Error(`Missing mesh clip ${bug.unit}.${clip}`); }
    const previous = render.meshLastPos[bug.id];
    let heading = render.meshHeading[bug.id] || 0;
    const hasDirection = bug.direction !== null && bug.direction !== undefined;
    if (hasDirection) {
      if (!Array.isArray(bug.direction) || bug.direction.length !== 3 ||
          !bug.direction.every(v => typeof v === 'number' && Number.isFinite(v))) {
        throw new TypeError('Mesh body direction');
      }
      if (bug.direction[0] * bug.direction[0] + bug.direction[2] * bug.direction[2] > 0) {
        heading = Math.atan2(bug.direction[0], bug.direction[2]);
      }
    } else if (previous) {
      const dx = bug.pos[0] - previous[0], dz = bug.pos[2] - previous[2];
      if (dx * dx + dz * dz > 1e-9) { heading = Math.atan2(dx, dz); }
    }
    render.meshLastPos[bug.id] = [...bug.pos]; render.meshHeading[bug.id] = heading;
    const count = cdef.frames.length;
    const walkTime = walkPhaseSeconds(bug, clip, cdef.duration);
    const elapsed = clip === 'normal_attack'
      ? attackElapsedSeconds(bug) : walkTime !== null ? walkTime : Math.max(0, snapshot.tick) / TICK_HZ;
    const time = cdef.duration > 0 ? (clip === 'normal_attack'
      ? Math.min(elapsed, cdef.duration) : walkTime !== null ? elapsed : elapsed % cdef.duration) : 0;
    const frame = Math.min(count - 1, Math.floor(time * count / (cdef.duration || 1)));
    const orientation = hasDirection
      ? {directionYup: [...bug.direction], orientationPolicy: 'normal-body-direction-roll0-v1', bodyYawRadians: heading}
      : {headingRadians: heading, orientationPolicy: 'legacy-yaw-v1'};
    result.push({id: bug.id, unitId: bug.unit, clip, frame,
      positionYup: [...bug.pos], ...orientation, scaleFactor: unitScale(bug.unit),
      posePolicy: 'engine-pose-v1', sourceScope: 'engineering',
      rootPolicy: 'engineering-fixed-S-v1', anchorPolicy: 'raw-bind-ground-pivot-v1'});
  }
  return result;
}
// Mesh snapshot adapter end

function meshPropRecords(snapshot) {
  const instances = meshPropInstancesFor(render.meshAssets, state.world, state.levelId, state.manifest);
  if (instances === null) { return []; }
  const byName = new Map();
  for (const instance of instances) {
    if (byName.has(instance.name)) { throw new Error('Duplicate mesh prop name'); }
    byName.set(instance.name, instance);
  }
  const seen = new Set();
  return snapshot.flowers.map(flower => {
    const instance = byName.get(flower.name);
    if (!instance || instance.flowerType !== flower.type || seen.has(flower.name)
        || !Object.hasOwn(render.meshAssets.props, instance.assetId)) {
      throw new Error(`Invalid mesh flower ${flower.name}`);
    }
    seen.add(flower.name);
    let animation={};const asset=render.meshAssets.props[instance.assetId];
    if(asset.animationScope==='normal-flower-node-keys-v1'){
      const c=flower.cycle;
      if(c?.scope!=='normal-flower-animation-edge-f32-v1'||typeof c.phase!=='number'||!Number.isFinite(c.phase)||c.phase<0||c.duration!==asset.animationRig.duration)throw new Error('Flower snapshot animation phase');
      if(flower.pose?.scope!=='cached-world-pose-20hz-v1'||flower.pose.rigSHA256!==asset.animationRig.rigSHA256)throw new Error('Flower snapshot rig identity');
      animation={animationPhase:c.phase};
    }
    return {id: `flower:${flower.name}`, assetId: instance.assetId,
      positionYup: [...flower.pos], scaleFactor: instance.scaleFactor,
      ownerMatrix: [...instance.ownerMatrix], parentMatrix: [...instance.parentMatrix],
      transformPolicy: instance.transformPolicy, transformScope: instance.transformScope,...animation};
  });
}
function meshPropInstancesFor(assets, worldId, levelId, manifest) {
  const world = assets.worlds[worldId];
  if (!world) { throw new Error('Missing mesh prop world'); }
  if (Object.hasOwn(assets, 'propVariantContract')) {
    const contract = 'level-flower-variants-v1';
    const level = manifest?.levels?.find(x => x.id === levelId);
    const selector = level?.deps?.meshProps;
    const variant = level?.type === 'rescue' ? 'rescue' : 'normal';
    if (assets.propVariantContract !== contract || Object.hasOwn(world, 'propInstances')
        || level?.world !== worldId || selector?.contract !== contract
        || selector.world !== worldId || selector.variant !== variant
        || !Array.isArray(world.propVariants?.[variant])) {
      throw new Error('Invalid level mesh prop selector');
    }
    return world.propVariants[variant];
  }
  if (Object.hasOwn(world, 'propVariants')) { throw new Error('Missing mesh prop variant contract'); }
  if (!assets.props && world.propInstances === undefined) { return null; }
  if (!Array.isArray(world.propInstances)) { throw new Error('Missing mesh prop instances'); }
  return world.propInstances;
}
// Mesh prop adapter end

// Bind flower attachment follows the same submitted prop transform in GL.
// tick is an engineering 20Hz clock; original spawn/animation clocks are open.
function meshNectarRecords(snapshot,propRecords,sourcePropRecords=propRecords) {
  const contract=render.meshAssets?.nectarSprites;
  if(!contract)return [];
  if(contract.contract!=='bind-flower-nectar-v1')throw new Error('Nectar sprite contract');
  if(!Number.isSafeInteger(snapshot.tick)||snapshot.tick<0)throw new Error('Nectar tick');
  if(snapshot.nectarLifecycle?.scope!=='nectar-identity-substeps-v1'||!Array.isArray(snapshot.nectarEntities))throw new Error('Nectar entity snapshot contract');
  const entities=new Map(snapshot.nectarEntities.map(n=>[n.id,n]));
  if(entities.size!==snapshot.nectarEntities.length)throw new Error('Nectar duplicate identity');
  const visualFor=id=>{
    const n=entities.get(id);
    if(!Number.isSafeInteger(id)||id<1||!n||n.scope!=='nectar-fields-f32-v1'||!n.alive||!Number.isSafeInteger(n.bornTick)||n.bornTick<0||n.bornTick>snapshot.tick||
      ![n.size,n.glowSize,n.coreAngle,n.glowAngle].every(v=>typeof v==='number'&&Number.isFinite(v))||n.size<0||n.glowSize<0)throw new Error('Nectar entity visual fields');
    return n;
  };
  const flowers=new Map(snapshot.flowers.map(f=>['flower:'+f.name,f]));
  const result=[];
  for(const prop of propRecords){
    const flower=flowers.get(prop.id),asset=render.meshAssets.props[prop.assetId];
    if(!flower)throw new Error('Nectar flower join');
    if(!(flower.nectar>0)||!asset.attachments?.nektar)continue;
    const n=visualFor(flower.nectarId);
    let placement={attachment:{propId:prop.id,name:'nektar'}};
    if(asset.animationScope==='normal-flower-node-keys-v1'){
      if(flower.pose?.scope!=='cached-world-pose-20hz-v1'||flower.pose.rigSHA256!==asset.animationRig.rigSHA256||!Array.isArray(n.positionYup)||n.positionYup.length!==3||!n.positionYup.every(v=>typeof v==='number'&&Number.isFinite(v)))throw new Error('Nectar cached flower position');
      placement={positionYup:[...n.positionYup],placementPolicy:'snapshot-cached-flower-position-v1'};
    }
    const base={...placement,basisPolicy:'queued-camera-basis-v1',
      materialPolicy:'xblended-ctor-conditional-v1',samplerPolicy:'linear-clamp-engineering-v1',nectarEntityId:n.id};
    result.push({...base,id:'nectar:'+flower.name,texture:contract.texture,width:n.size,height:n.size,angleRadians:n.coreAngle,rgbaBytes:[255,255,255,255]});
    result.push({...base,id:'nectar-glow:'+flower.name,texture:contract.glowTexture,width:n.glowSize,height:n.glowSize,angleRadians:n.glowAngle,rgbaBytes:[255,255,192,255]});
  }
  if(render.meshAssets.nectarCarryContract!==undefined){
    if(render.meshAssets.nectarCarryContract!=='same-bug-radius-trajectory-v1')throw new Error('Nectar carry contract');
    const pair=(id,position,nectarId,metadata)=>{
      const n=visualFor(nectarId);
      const base={positionYup:position,basisPolicy:'queued-camera-basis-v1',materialPolicy:'xblended-ctor-conditional-v1',samplerPolicy:'linear-clamp-engineering-v1',nectarEntityId:n.id,...metadata};
      result.push({...base,id,texture:contract.texture,width:n.size,height:n.size,angleRadians:n.coreAngle,rgbaBytes:[255,255,255,255]});
      result.push({...base,id:id+':glow',texture:contract.glowTexture,width:n.glowSize,height:n.glowSize,angleRadians:n.glowAngle,rgbaBytes:[255,255,192,255]});
    };
    for(const item of snapshot.pathNectar??[]){
      if(!item.taken)pair('path-nectar:'+item.id,[...item.pos],item.nectarId,{placementPolicy:'snapshot-path-position-v1'});
    }
    for(const bug of snapshot.bugs??[]){
      if(bug.dead||!bug.carrying)continue;
      const carry=bug.carryingNectar,unit=render.meshAssets.units[bug.unit],source=carry?.source;
      if(!source||!['flower','item'].includes(source.kind)||!Number.isSafeInteger(source.index)||source.index<0||!Array.isArray(source.positionYup))throw new Error('Nectar pickup source');
      let initial=[...source.positionYup],pickupPositionScope='snapshot-item-position-v1';
      if(source.kind==='flower'&&source.positionScope==='snapshot-cached-flower-position-v1'){
        if(initial.length!==3||!initial.every(v=>typeof v==='number'&&Number.isFinite(v)))throw new Error('Nectar cached pickup position');
        pickupPositionScope=source.positionScope;
      }else if(source.kind==='flower'){
        const parents=sourcePropRecords.filter(p=>p.id==='flower:'+source.name);
        if(parents.length!==1)throw new Error('Nectar pickup unique flower');
        const parent=BugBitsMeshScene.effectivePropRecord(render.meshAssets,state.world,state.world==='world_01',parents[0]);
        const asset=render.meshAssets.props[parent.assetId],node=asset.attachments?.nektar;
        if(node){initial=BugBitsMeshScene.transformPropVertex(node.positionRaw,asset,parent);pickupPositionScope='current-bind-flower-attachment-v1';}
        else pickupPositionScope='engineering-source-origin-fallback-v1';
      }
      const n=visualFor(carry.nectarId);
      let position=BugBitsMeshScene.nectarCarryPosition(carry,initial,bug.pos,unit?.radius,snapshot.tick);
      let placementPolicy='pickup-trajectory-20hz-v1';
      if(n.flight?.duration>0){
        if(!Array.isArray(n.positionYup)||n.positionYup.length!==3||!n.positionYup.every(v=>typeof v==='number'&&Number.isFinite(v)))throw new Error('Nectar flight position');
        position=[...n.positionYup];placementPolicy='snapshot-active-flight-position-v1';
      }
      pair('carried-nectar:'+bug.id,position,carry.nectarId,{placementPolicy,pickupPositionScope,carrierId:bug.id,pickupTick:carry.tick});
    }
  }
  return result;
}
// Mesh nectar adapter end

function yawIndex(bug) {
  const prev = render.lastPos[bug.id];
  render.lastPos[bug.id] = bug.pos;
  if (!prev) { return 0; }
  const dx = bug.pos[0] - prev[0], dz = bug.pos[2] - prev[2];
  if (dx * dx + dz * dz < 1e-9) { return render.yaw[bug.id] ?? 0; }
  // NC 相机交付：相机 yaw φ 把世界朝向 θ 的屏幕呈现变为 θ−φ（推导见
  // render/camera.py 基向量约定；引擎 RotY 实际符号 [UNVERIFIED]——本实现
  // 与地形旋转同约定，保持相对朝向自洽）。默认（无预设）φ=0 逐位不变。
  const camYaw = render.activePreset ? render.activePreset.camera.yawDeg : 0;
  const deg = Math.atan2(dx, dz) * 180 / Math.PI - camYaw;
  const idx = ((Math.round(deg / 45) % 8) + 8) % 8;
  render.yaw[bug.id] = idx;
  return idx;
}

function drawSprite(ctx, key, cx, cy, scale = 1.0) {
  const s = render.atlas.sprites[key];
  if (!s) { return false; }
  const img = render.pages[s.page];
  // 图集页未载入（换关加载中）或已 close（width==0）→ 跳过绘制，不抛 drawImage 异常
  if (!img || img.width === 0) { return false; }
  const k = CANVAS_SIZE / 1024 * (1024 / render.projection.size);
  const w = s.w * k * scale, h = s.h * k * scale;
  ctx.drawImage(img, s.x, s.y, s.w, s.h, cx - w / 2, cy - h / 2, w, h);
  return true;
}

function wrapText(ctx, text, maxW) {
  // BUG-05：先按显式换行 \n 分段，再按宽度折行（对话多行并成一行的根因）
  const lines = [];
  for (const para of String(text).split("\n")) {
    let cur = "";
    for (const ch of para) {
      if (cur && ctx.measureText(cur + ch).width > maxW) {
        lines.push(cur);
        cur = ch;
      } else {
        cur += ch;
      }
    }
    lines.push(cur);
  }
  return lines.length ? lines : [text];
}

function renderFrame(nowMs) {
  if (perf._lastFrame) {
    perf.push(perf.frameTimes, nowMs - perf._lastFrame);
  }
  perf._lastFrame = nowMs;
  const cvs = $("scene");
  // NC-04 DPR 清晰度：backing = 逻辑 640 × DPR（上限 2，防 4K 内存膨胀）；
  // 绘制全部留在逻辑 640 坐标系，setTransform 统一缩放到 backing。宽高仅在
  // 变化时赋值（赋值会清空画布；每帧全量重绘故无影响）。DPR=1 时恒等
  // （既有用例像素探针/C03 截图不受影响）。
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const need = Math.round(CANVAS_SIZE * dpr);
  if (cvs.width !== need) { cvs.width = need; cvs.height = need; }
  render.dprScale = need / CANVAS_SIZE;
  const ctx = cvs.getContext("2d");
  ctx.setTransform(render.dprScale, 0, 0, render.dprScale, 0, 0);
  // 图集精灵下行采样（128px→~10-20px）用高质量插值（渲染层选择，非保真声明）
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
  // Leave the presentation loop alive while resource preparation owns the
  // loading budget. Do not redraw old terrain or publish a completed game frame.
  if (state.phase === "loading") {
    render.draws = [];
    requestAnimationFrame(renderFrame);
    return;
  }
  // CAM-02：统一内容区合同——预设激活（letterbox）时**全部世界层**
  // （地形/泳道标记/蜜/花/巢/虫/气泡）经 ctx.save → clip(0,offY,640,contentH)
  // → 绘制 → restore 绘制；黑带保持 clearRect 后的透明（页面背景
  // #0c0e10），世界物体不得泄漏进黑带（审查图像证据：world_03 wide_cam
  // 下黑带有虫）。不得用"涂黑盖住"替代裁剪——绘制泄漏与输入误命中是
  // 两个独立缺陷，盖黑不修输入边界。默认相机内容区=整幅画布：不
  // save/clip，绘制行为位级不变。HUD/工程边缘指示（CAM-03 边缘补偿）
  // 属独立层，未来绘制在 restore 之后，不受世界层 clip 约束。
  const meshOn = !!render.meshScene;
  const presetOn = !!(render.activePreset && (meshOn || (render.presetTerrain
    && render.presetTerrain.width > 0)));
  let contentH = CANVAS_SIZE, offY = 0;
  if (presetOn) {
    contentH = CANVAS_SIZE / render.activePreset.projection.aspect;
    offY = (CANVAS_SIZE - contentH) / 2;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, offY, CANVAS_SIZE, contentH);
    ctx.clip();
  }
  // NC 相机交付：预设地形（letterbox 内容区 640×(640/aspect)，bars 露背景）；
  // 默认方形地形满幅（位级不变）。
  if (!meshOn && presetOn) {
    const p = activeProjection();
    if (p.kind === "matrix-yup-v1") {
      const k = CANVAS_SIZE / (p.size * p.aspect);
      ctx.drawImage(render.presetTerrain, 0, offY,
                    render.presetTerrain.width * k, render.presetTerrain.height * k);
    } else {
      ctx.drawImage(render.presetTerrain, 0, offY, CANVAS_SIZE, contentH);
    }
  } else if (!meshOn && render.terrain && render.terrain.width > 0) {
    ctx.drawImage(render.terrain, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
  }
  render.draws = [];
  const snap = state.lastSnapshot;
  if (meshOn) {
    try {
      updateNativeCamera(snap);
      if (render.meshFollowId != null || render.meshCameraPending || (render.meshZoomFactor || 1) !== 1) {
        updateMeshFollow(snap);
      }
      const props=snap?meshPropRecords(snap):[];
      const output = render.meshScene.renderFrame({snapshot: snap || {tick: 0},
        drawRecords: snap ? meshDrawRecords(snap) : [],
        propRecords: props, spriteRecords:snap?meshNectarRecords(snap,props):[],
        dpr: render.dprScale, worldId: state.world});
      ctx.drawImage(output.canvas, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
      render.draws.push(...output.draws);
      render.draws.push(...(output.propDraws || []));
      render.draws.push(...(output.spriteDraws || []));
    } catch (error) {
      // Context loss or a malformed frame must not publish a mixed camera frame.
      if (presetOn) { ctx.restore(); }
      commitCameraView(null, null, null);
      render.presetError = String(error); updateCameraControl();
      renderFrame(nowMs); return;
    }
  }
  if ($('mesh-controls')) { updateMeshControls(snap); }
  // A8: 我方泳道 START 点标记（可选泳道可见，当前选中泳道高亮）
  if (render.projection && state.starts0) {
    const laneSel = $("lane");
    const cur = laneSel ? Number(laneSel.value) : -1;
    for (const [lane, pos] of Object.entries(state.starts0)) {
      const projected = projectCanvasPoint(pos);
      if (!projected) { continue; }
      const {px, py} = projected;
      const isCur = Number(lane) === cur;
      ctx.fillStyle = isCur ? "#7ec97e" : "#3a5a3a";
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = "11px 'Noto Sans SC', system-ui, sans-serif";
      ctx.fillStyle = isCur ? "#a8e0a8" : "#4a7a4a";
      ctx.fillText(`泳道${lane}`, px + 7, py - 6);
      render.draws.push({id: `lane:${lane}`, clip: "lane", frame: 0,
                         lane: Number(lane), current: isCur});
    }
  }
  if (snap && render.atlas) {
    // 路径蜜（可见小点）
    ctx.fillStyle = "#e8c84a";
    for (const it of snap.pathNectar) {
      if (meshOn && render.meshAssets.nectarCarryContract === 'same-bug-radius-trajectory-v1') { continue; }
      if (it.taken) { continue; }
      const projected = projectCanvasPoint(it.pos);
      if (!projected) { continue; }
      const {px, py} = projected;
      ctx.fillRect(px - 2, py - 2, 4, 4);
      render.draws.push({id: `nectar:${it.id}`, clip: "-", frame: 0});
    }
    // 花（A22: 耗尽花蜜的花降透明度 + 红点标记，不伪装原作枯竭贴图）
    for (const f of snap.flowers) {
      if (meshOn && (Object.hasOwn(render.meshAssets, 'propVariantContract')
          || render.meshAssets.worlds[state.world].propInstances !== undefined)) { continue; }
      const depleted = (f.nectar || 0) <= 0;
      const bb = flowerBillboard(f.pos);
      if (!bb) { continue; }
      if (depleted) { ctx.globalAlpha = 0.4; }
      const {px, py, lam} = bb;
      // NC 相机交付：预设激活时花键同前缀（预设 pitch 烘焙精灵）
      const drew = drawUnitSprite(ctx, activeSpritePrefix()
        + render.atlas.flower, px, py, lam);
      if (depleted) { ctx.globalAlpha = 1.0; }
      if (drew) {
        render.draws.push({id: `flower:${f.name}`, clip: "flower", frame: 0,
                           depleted});
        if (depleted) {
          ctx.fillStyle = "#e07070";
          ctx.fillRect(px - 3, py - 3, 6, 6);
        }
      }
    }
    // 蜂巢占位（无模型证据，placeholder 标注——W5 HUD 完整化）
    for (const h of snap.hives) {
      const projected = projectCanvasPoint(h.pos);
      if (!projected) { continue; }
      const {px, py} = projected;
      ctx.strokeStyle = h.side === 0 ? "#50c850" : "#e05050";
      ctx.lineWidth = 2;
      ctx.strokeRect(px - 8, py - 8, 16, 16);
      ctx.font = "11px 'Noto Sans SC', system-ui, sans-serif";
      ctx.fillStyle = h.side === 0 ? "#50c850" : "#e05050";
      ctx.fillText(`HIVE${h.side}·${h.hp}`, px - 18, py - 12);
      render.draws.push({id: `hive:${h.side}`, clip: "placeholder", frame: 0});
    }
    // 虫（可见存活实体逐只 draw；越界剔除记录原因）
    for (const b of (meshOn ? [] : snap.bugs)) {
      const entry = {id: b.id, unit: b.unit, clip: null, frame: 0, yaw: null,
                     culled: null, trapped: !!b.trapped};
      render.draws.push(entry);
      if (b.dead) { entry.culled = "dead"; continue; }
      const clip = clipFor(b);
      const rc = clip && resolveClip(b.unit, clip);
      if (!rc) { entry.culled = "no-clip"; continue; }
      // NC-03：全相机投影（含高度）+ 世界尺寸 λ；锚点 = 瓦片中心 ↔ 模型中心（NC-03A）。
      // 剔除余量 256px ≥ 最大精灵对角（128×λ_near）
      const bb = unitBillboard(b, b.unit);
      if (!bb) { entry.culled = "camera-depth"; continue; }
      const px = bb.px, py = bb.py;
      if (px < -256 || py < -256 || px > CANVAS_SIZE + 256
          || py > CANVAS_SIZE + 256) {
        entry.culled = "offscreen"; continue;
      }
      // A21: 被困单位明确标记（与关卡目标关联；不改变 trapped/伤害逻辑）
      if (b.trapped) {
        ctx.strokeStyle = "#e8c84a";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(px, py, 10, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#e8c84a";
        ctx.font = "bold 14px 'Noto Sans SC', system-ui, sans-serif";
        ctx.textBaseline = "middle";
        ctx.fillText("!", px - 3, py);
      }
      const idx = frameIndex({frames: rc.def.frames, duration: rc.def.duration,
                              clip: rc.clip,
                              def_kind: rc.clip === "normal_attack"
                                ? "attack" : "loop"}, b, nowMs);
      const y = yawIndex(b);
      // NC 相机交付：预设激活时精灵键加前缀（预设 pitch 烘焙精灵，同图集）
      const key = activeSpritePrefix() + (rc.def.kind === "static"
        ? `${rc.def.prefix}.y${y}`
        : `${rc.def.prefix}.f${idx}.y${y}`);
      if (drawUnitSprite(ctx, key, bb.px, bb.py, bb.lam)) {
        entry.clip = rc.clip; entry.frame = idx; entry.yaw = y;
        entry.key = key; entry.px = bb.px; entry.py = bb.py;
        entry.scale = bb.lam;                       // NC-03：图集像素→画布像素
        entry.camZ = bb.camZ; entry.pos = b.pos;
        // 对话气泡（snapshot.dialogue 文本键 → texts 值；系统字体=表现层简化）
        if (b.dialogue && state.texts) {
          const text = state.texts[b.dialogue] || b.dialogue;
          ctx.font = "12px 'Noto Sans SC', system-ui, sans-serif";
          const maxW = CANVAS_SIZE - 12;
          const lines = wrapText(ctx, text, maxW);      // A18：长文本按字符换行
          const w = Math.min(maxW, ...lines.map((l) =>
            ctx.measureText(l).width + 10));
          const h = lines.length * 16 + 6;
          // A18：气泡钳制在画布内（覆盖顶部/左右角落与窄视口）
          const bx = Math.min(Math.max(0, px - w / 2), CANVAS_SIZE - w);
          const by = Math.min(Math.max(0, py - 62), CANVAS_SIZE - h);
          ctx.fillStyle = "rgba(16,20,16,0.82)";
          ctx.fillRect(bx, by, w, h);
          ctx.fillStyle = "#e8ecd8";
          ctx.textBaseline = "top";
          lines.forEach((ln, i) => ctx.fillText(ln, bx + 5, by + 3 + i * 16));
        }
      } else {
        entry.culled = "no-sprite";
      }
    }
  }
  // CAM-02：世界层结束——恢复 clip（HUD/工程指示自此之后绘制，不受约束）
  if (presetOn) { ctx.restore(); }
  // CAM-03：工程边缘指示（HUD 层）——restore 之后=独立于世界层裁剪（标记
  // 文字可能越过内容区边界，不得被世界 clip 截断）；仅预设 letterbox 激活
  // 时（overview 全图可见，C07 点击合同即其操作面）。
  if (presetOn && snap) {
    drawTargetIndicators(ctx, snap, offY, contentH);
  }
  const fh = Object.keys(render.fallbackHits);
  if (fh.length) {
    $("fallback-report").className = "warn";
  }
  // FRAME-01：绘制结束（全部世界层+HUD/指示层完成）后发布帧标记——
  // draws/drawLog 与本标记同帧自洽（读取方按 seq/tick 配对，不误读旧帧）。
  frameMark.seq += 1;
  frameMark.tick = (snap && typeof snap.tick === "number") ? snap.tick : null;
  frameMark.stateTick = state.tick;
  frameMark.presetReq = render.presetReqSeq || 0;
  frameMark.presetKey = render.activePresetKey;
  frameMark.generation = state.generation;
  frameMark.atMs = nowMs;
  frameMark.stageAspect = render.activePreset ? activeProjection().aspect : 1;
  frameMark.offY = (CANVAS_SIZE - CANVAS_SIZE / frameMark.stageAspect) / 2;
  frameMark.cameraReady = render.cameraReady;
  requestAnimationFrame(renderFrame);
}

async function init() {
  const params = new URLSearchParams(location.search);
  state.testMode = params.get("test") === "1";
  state.recordMode = params.get("record") === "1";   // 真实时钟+只读记录（H3 复放）
  // A7/A20：URL 种子统一校验（NaN/Infinity/非整数/越界 → 默认 + 明确提示）
  const sv = validateSeed(params.get("seed"));
  state.seed = sv.ok ? sv.value : 2026;
  state.seedNote = sv.ok ? "" : sv.error;
  state.levelId = params.get("level") || "level_02";
  state.worker = new Worker("worker.js");
  state.worker.onmessage = handleReply;
  state.worker.onerror = (e) => showError(`Worker 异常: ${e.message}`);
  $("scene").addEventListener("click", onCanvasClick);
  document.addEventListener('pointermove', onCameraPointerMove, {capture: true, passive: true});
  $("end-restart").onclick = () =>
    startGame(null, state.seed).catch((e) => showError(e.message));
  $("end-back").onclick = () => leaveGame();
  document.addEventListener("visibilitychange", () => {
    // 合同 §2.3：标签页隐藏自动暂停；恢复不补算隐藏时长
    if (document.hidden && !state.paused) {
      state.autoPaused = true;
      setPaused(true, false);
    } else if (!document.hidden && state.autoPaused) {
      state.autoPaused = false;
      setPaused(false, false);
    }
  });
}

// ── 测试 hook（?test=1；只读 + 手动推进 + draw/时钟注入，无作弊入口） ──
function installTestHook() {
  window.__bb_test = {
    startGame: (levelId, seed) => startGame(levelId, seed),
    booted: () => state.booted,          // 完整初始化完成（A23：非仅 manifest）
    ready: () => state.started && state.sessionId !== null && render.cameraReady,
    generation: () => state.generation,
    loopStats: () => ({running: state.running, activeLoops,
                       registrations: loopRegCount,
                       generation: state.generation}),
    setReplyDelay: (ms) => { replyDelayMs = ms; },
    setLoadDelay: (ms) => { loadDelayMs = ms; },   // RF-02：延迟位图解码（竞态复现）
    advanceTo: async (tick) => {
      let winner = null;
      let last = -1, stalls = 0;
      while (state.tick < tick) {
        const r = await call("advance",
                             {ticks: Math.min(5, tick - state.tick)});
        if (!r.ok) { throw new Error(r.error); }
        if (r.result.tick === last) {
          if (++stalls >= 3) {
            throw new Error("advance 无进展（可能已冻结/结束）");
          }
        } else { stalls = 0; last = r.result.tick; }
        state.tick = r.result.tick;
        winner = r.result.winner;
        if (winner !== null) { break; }
      }
      await refresh({tick: state.tick, winner});   // 保留真实 winner（A6）
      return state.tick;
    },
    // 时钟注入（H4）：合成帧时刻驱动同一 clock.step，验证 30/60/144Hz+抖动
    // 等价性（相同逻辑 tick 输入 → 相同状态）
    simulateClock: async (timingsMs) => {
      clock.useRealTime = false;
      clock.reset();
      for (const t of timingsMs) { await clock.step(t); }
      const out = {tick: state.tick, paused: state.paused,
                   backlog: state.backlog};
      clock.useRealTime = true;
      return out;
    },
    audit: () => call("audit_state", {}).then((r) => r.result),
    snapshot: () => call("snapshot", {}).then((r) => r.result),
    events: () => call("read_events", {afterSeq: 0}).then((r) => r.result),
    receipt: () => state.lastReceipt,
    receipts: () => state.receipts,
    buy: (unit) => submitBuy(unit),     // 按钮 onclick 同一处理器（无旁路）
    currentTick: () => state.tick,
    seed: () => state.seed,
    levelId: () => state.levelId,
    endKind: () => state.endKind,
    drawLog: () => render.draws,
    // Real depth-tested terrain versus one real snapshot unit. Observe the
    // offscreen GPU canvas, then restore its complete frame even on failure.
    // No simulation, projection, scale, material or depth state is changed.
    meshPixelAudit: () => {
      if (!render.meshScene || !state.lastSnapshot) {
        throw new Error('Mesh snapshot unavailable');
      }
      const snapshot = state.lastSnapshot;
      const records = meshDrawRecords(snapshot);
      const propRecords = meshPropRecords(snapshot);
      const dpr = render.dprScale || 1;
      const probe = document.createElement('canvas');
      const context = probe.getContext('2d', {willReadFrequently:true});
      const draw = (drawRecords) => {
        const frame = render.meshScene.renderFrame({snapshot,drawRecords,propRecords,spriteRecords:meshNectarRecords(snapshot,propRecords),dpr,worldId:state.world});
        probe.width=frame.canvas.width;probe.height=frame.canvas.height;
        context.drawImage(frame.canvas,0,0);
        return context.getImageData(0,0,probe.width,probe.height).data;
      };
      try {
        const terrain = draw([]);
        const units = records.map(record => {
          const pixels = draw([record]);
          let differentPixels=0,minX=probe.width,minY=probe.height,maxX=-1,maxY=-1;
          for (let i=0;i<pixels.length;i+=4) {
            if (pixels[i]!==terrain[i] || pixels[i+1]!==terrain[i+1] ||
                pixels[i+2]!==terrain[i+2] || pixels[i+3]!==terrain[i+3]) {
              const x=(i/4)%probe.width,y=Math.floor(i/4/probe.width);
              differentPixels++;minX=Math.min(minX,x);minY=Math.min(minY,y);
              maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);
            }
          }
          return {...record,differentPixels,bounds:differentPixels ? [minX,minY,maxX,maxY] : null};
        });
        return {tick:snapshot.tick,dpr,backing:[probe.width,probe.height],units,
                projection:JSON.parse(JSON.stringify(activeProjection())),
                scope:'depth-tested GPU unit contribution; no overlay pixels or original equivalence'};
      } finally {
        render.meshScene.renderFrame({snapshot,drawRecords:records,propRecords,spriteRecords:meshNectarRecords(snapshot,propRecords),dpr,worldId:state.world});
      }
    },
    meshPropPixelAudit: () => {
      if (!render.meshScene || !state.lastSnapshot) { throw new Error('Mesh snapshot unavailable'); }
      const snapshot = state.lastSnapshot, records = meshPropRecords(snapshot);
      const drawRecords = meshDrawRecords(snapshot), dpr = render.dprScale || 1;
      const probe = document.createElement('canvas'), context = probe.getContext('2d', {willReadFrequently:true});
      let submittedProps = [];
      const draw = propRecords => {
        const frame = render.meshScene.renderFrame({snapshot,drawRecords,propRecords,spriteRecords:meshNectarRecords(snapshot,propRecords,records),dpr,worldId:state.world});
        submittedProps = frame.propDraws;
        probe.width = frame.canvas.width; probe.height = frame.canvas.height;
        context.drawImage(frame.canvas,0,0);
        return context.getImageData(0,0,probe.width,probe.height).data;
      };
      try {
        const baseline = draw([]);
        const props = records.map(record => {
          const pixels = draw([record]);
          const submitted = submittedProps.find(p => p.id===record.id);
          if (!submitted) { throw new Error('Prop audit missing submitted owner'); }
          let differentPixels=0,minX=probe.width,minY=probe.height,maxX=-1,maxY=-1;
          for (let i=0;i<pixels.length;i+=4) {
            if (pixels[i]!==baseline[i] || pixels[i+1]!==baseline[i+1]
                || pixels[i+2]!==baseline[i+2] || pixels[i+3]!==baseline[i+3]) {
              const x=(i/4)%probe.width,y=Math.floor(i/4/probe.width);
              differentPixels++;minX=Math.min(minX,x);minY=Math.min(minY,y);
              maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);
            }
          }
          return {...record,ownerMatrix:[...submitted.ownerMatrix],ownerPolicy:submitted.ownerPolicy,
                  differentPixels,bounds:differentPixels ? [minX,minY,maxX,maxY] : null};
        });
        return {tick:snapshot.tick,dpr,props,attachedSpritesIncluded:!!render.meshAssets.nectarSprites,
                scope:'GPU prop plus attached sprite contribution with units/terrain depth, not original equivalence'};
      } finally {
        render.meshScene.renderFrame({snapshot,drawRecords,propRecords:records,spriteRecords:meshNectarRecords(snapshot,records),dpr,worldId:state.world});
      }
    },
    // FRAME-01：帧完成标记只读查询（本帧绘制结束时发布；test 层专用，
    // 生产冒烟不依赖——等待锚点用 DOM 状态文本/#tick）。
    renderState: () => ({seq: frameMark.seq, tick: frameMark.tick,
                         stateTick: frameMark.stateTick,
                         presetReq: frameMark.presetReq,
                         presetKey: frameMark.presetKey,
                         generation: frameMark.generation,
                         stageAspect: frameMark.stageAspect, offY: frameMark.offY,
                         cameraReady: frameMark.cameraReady,
                         atMs: frameMark.atMs}),
    stageGeometry: () => stageGeometry(),
    fallbackHits: () => render.fallbackHits,
    // FIX-04: 当前已解码图集页（按关卡依赖加载的验证面）
    atlasPagesLoaded: () => ({
      total: render.pages.length,
      loaded: render.pages.map((p, i) => (p ? i : -1)).filter((i) => i >= 0),
    }),
    // NC-03 视口合同：内容框精确逆映射（C07 直接断言面；只读，无副作用）
    mapClient: (x, y) => canvasToWorld({clientX: x, clientY: y}),
    // NC 相机交付：正映射（真实 host.js worldToCanvas，含激活预设；只读）
    mapWorld: (x, z) => worldToCanvas(x, z),
    mapPoint: (point) => projectCanvasPoint(point),
    cameraDepth: (point) => cameraSpacePoint(point)[2],
    // NC-04 DPR 清晰度诊断：backing/逻辑比与 devicePixelRatio（只读）
    dprInfo: () => ({backing: document.getElementById("scene").width,
                     logical: CANVAS_SIZE, dprScale: render.dprScale || 1,
                     devicePixelRatio: window.devicePixelRatio || 1}),
    // The production control and test hook share one request/publication seam.
    setCameraPreset: (key) => setCameraPreset(key),
    // NC 相机交付：激活相机状态（只读）——预设键/激活投影/可用键/letterbox
    cameraInfo: () => {
      const p = activeProjection();
      const aspect = p.aspect || 1.0;
      return {
        activePresetKey: render.activePresetKey,
        presets: render.worldPresets ? Object.keys(render.worldPresets) : [],
        projection: p,
        letterbox: {aspect, contentW: CANVAS_SIZE,
                    contentH: CANVAS_SIZE / aspect,
                    offY: (CANVAS_SIZE - CANVAS_SIZE / aspect) / 2},
        spritePrefix: activeSpritePrefix(),
        meshScope: render.meshScene ? 'engine-mesh-v1' : null,
        meshFollowId: render.meshFollowId, meshZoomFactor: render.meshZoomFactor,
        meshTargetYup: render.meshTargetYup,
        pending: render.presetPending !== null, error: render.presetError,
      };
    },
    // RF-02: 渲染资源所有权诊断（切世界地形释放/图集页/音频）。
    // CAM-01: presetTerrainCloseCount = 预设位图 close 总数（null 复位/换预设
    // 替换/在途淘汰/换关重置；与 terrainCloseCount/atlasCloseCount 同口径）。
    resourceState: () => ({
      terrainWorld: render.terrainWorld,
      terrainCloseCount: render.terrainCloseCount,
      terrainW: render.terrain ? render.terrain.width : 0,
      atlasLoaded: render.pages.map((p, i) => (p ? i : -1)).filter((i) => i >= 0),
      atlasCloseCount: render.atlasCloseCount,
      presetTerrainCloseCount: render.presetTerrainCloseCount,
      meshSceneActive: !!render.meshScene, meshDisposeCount: render.meshDisposeCount,
    }),
    audioMusicRef: () => audio.music,
    // 暂停/重开/状态（只读 + 等价用户操作路径）
    pause: () => setPaused(true),
    resume: () => setPaused(false),
    isPaused: () => state.paused,
    resetGame: (seed) => startGame(null, seed),
    resetCount: () => state.resetCount,
    audioState: () => ({muted: state.muted, unlocked: audio.unlocked,
                        note: audio.note,
                        sfxLoaded: Object.keys(audio.sfx)}),
    // 模拟标签页隐藏/恢复（H4）：覆写 document.hidden + 派发事件
    hiddenPause: (hidden) => {
      Object.defineProperty(document, "hidden",
                            {get: () => hidden, configurable: true});
      document.dispatchEvent(new Event("visibilitychange"));
      return state.paused;
    },
    uiState: () => ({
      paused: state.paused, manualPause: state.manualPause,
      backlog: state.backlog, sessionId: state.sessionId,
      eventCursor: state.eventCursor, tick: state.tick,
      buyDisabled: Array.from(document.querySelectorAll("button.buy"))
        .map((b) => b.disabled),
    }),
    canvasClickAt: (px, py) => onCanvasClick({
      clientX: px, clientY: py,
    }),
    lane: () => document.getElementById("lane").value,
    // 性能仪表（W6/H5；只读）
    perfStats: () => ({
      frameTimes: perf.frameTimes.slice(),
      advanceMs: perf.advanceMs.slice(),
      mem: performance.memory
        ? {usedJSHeapMB: Math.round(performance.memory.usedJSHeapSize / 1048576),
           totalJSHeapMB: Math.round(performance.memory.totalJSHeapSize / 1048576)}
        : null,          // WASM/Pyodide 堆不可经 performance.memory 测——缺口标注
      tick: state.tick, backlog: state.backlog,
    }),
  };
}

init();
if (state.testMode || state.recordMode) { installTestHook(); }
