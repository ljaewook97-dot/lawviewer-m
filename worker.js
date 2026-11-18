// 법령 뷰어 모바일 워커: Pyodide 를 불러 lawcore.py(데스크톱과 같은 분석 코드)를 돌린다.
const q = new URL(self.location.href).searchParams;
const PYO = q.get("pyo") || "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
let py = null, api = null, bootP = null;

self.onmessage = async (e) => {
  const { id, fn, args } = e.data;
  try {
    if (!py) await (bootP || (bootP = boot()));
    const r = api.call(fn, JSON.stringify(args || []));
    self.postMessage({ id, res: JSON.parse(r) });
  } catch (err) {
    self.postMessage({ id, res: { err: "엔진 오류: " + (err && err.message || err) } });
  }
};

async function boot() {
  self.postMessage({ id: 0, status: "엔진을 내려받는 중… (처음 한 번만 오래 걸립니다)" });
  const srcP = Promise.all(["lawcore.py", "mobile_api.py"].map((f) => fetch(f + "?v=" + (q.get("v") || "")).then((r) => r.text())));   // 엔진을 받는 동안 분석 코드도 같이 받는다
  importScripts(PYO + "pyodide.js");
  py = await loadPyodide({ indexURL: PYO });
  self.postMessage({ id: 0, status: "법령 분석 코드를 준비하는 중…" });
  const srcs = await srcP;
  ["lawcore.py", "mobile_api.py"].forEach((f, i) => py.FS.writeFile("/home/pyodide/" + f, srcs[i]));
  py.runPython("import sys; sys.path.insert(0,'/home/pyodide')");
  api = py.pyimport("mobile_api");
  const base = q.get("api");
  if (base) api.set_api_base(base);
  self.postMessage({ id: 0, status: "ready" });
}
