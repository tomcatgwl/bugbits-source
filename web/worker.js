// BugBits Web Worker（W2）：Pyodide + bugbits 包装载 + 桥消息循环。
// 单 Worker 串行推进（合同 §2.2）；ready 前不受理游戏命令。
/* global loadPyodide */
importScripts("vendor/pyodide/pyodide.js");

let callFn = null;
let booted = false;

async function boot() {
  const pyodide = await loadPyodide({indexURL: "vendor/pyodide/"});
  const resp = await fetch("py-bundle.json");
  if (!resp.ok) {
    throw new Error(`py-bundle.json 加载失败: ${resp.status}`);
  }
  pyodide.globals.set("BUNDLE_JSON", JSON.stringify(await resp.json()));
  await pyodide.runPythonAsync([
    "import json, sys, pathlib",
    "_b = json.loads(BUNDLE_JSON)",
    "for p, src in _b.items():",
    "    f = pathlib.Path('/py') / p",
    "    f.parent.mkdir(parents=True, exist_ok=True)",
    "    f.write_text(src, encoding='utf-8')",
    "sys.path.insert(0, '/py')",
    "from bugbits.web_bridge import WebBridge, bridge_call",
    "_BRIDGE = WebBridge()",
    "def _bb_call(op, payload):",
    "    return bridge_call(_BRIDGE, op, payload)",
  ].join("\n"));
  callFn = pyodide.globals.get("_bb_call");
  booted = true;
}

boot().then(
  () => postMessage({type: "ready"}),
  (e) => postMessage({type: "bootError", error: String(e && e.message || e)}),
);

onmessage = (ev) => {
  const {id, op, payload} = ev.data || {};
  if (!booted) {
    postMessage({type: "reply", id, ok: false, error: "E_NOT_READY"});
    return;
  }
  try {
    const out = JSON.parse(callFn(op, JSON.stringify(payload || {})));
    postMessage({type: "reply", id, ok: out.ok, result: out.result,
                 error: out.error, detail: out.detail});
  } catch (e) {
    postMessage({type: "reply", id, ok: false, error: "E_WORKER",
                 detail: String(e && e.message || e)});
  }
};
