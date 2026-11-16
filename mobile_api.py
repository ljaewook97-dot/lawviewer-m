# -*- coding: utf-8 -*-
"""법령 뷰어 모바일: 브라우저(Pyodide) 안에서 lawcore 를 그대로 돌리는 얇은 층.
worker.js 가 call(함수이름, JSON 인자) 로 부르고, 결과는 JSON 글로 돌려준다.
접속은 브라우저의 동기 XMLHttpRequest(워커 안에서만 허용)로 법제처 API 를 직접 부른다."""
import json
import re
import urllib.parse
import concurrent.futures as _cf

import lawcore as L

L.API = "https://www.law.go.kr/DRF/"
_API_BASE = {"v": None}


# ---- 쓰레드가 없는 환경이라 ThreadPoolExecutor 를 차례로 실행하는 것으로 바꾼다
class _Fut:
    def __init__(self, fn, a, k):
        try:
            self._v, self._e = fn(*a, **k), None
        except BaseException as e:  # noqa: BLE001
            self._v, self._e = None, e

    def result(self, timeout=None):
        if self._e is not None:
            raise self._e
        return self._v


class _SyncPool:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *a, **k):
        return _Fut(fn, a, k)

    def map(self, fn, it):
        return [fn(x) for x in it]


_cf.ThreadPoolExecutor = _SyncPool

_NET = {}


def getter(url, params, timeout=25, tries=2):
    """법제처 JSON 조회(법령 본문은 이 접속 동안 다시 받지 않는다)"""
    from js import XMLHttpRequest
    if _API_BASE["v"]:
        url = url.replace("https://www.law.go.kr/DRF/", _API_BASE["v"])
    full = url + "?" + urllib.parse.urlencode(params)
    ck = full.replace(params.get("OC", ""), "")
    if ck in _NET:
        return _NET[ck]
    last = None
    for _ in range(tries):
        try:
            x = XMLHttpRequest.new()
            x.open("GET", full, False)
            x.send()
            if x.status != 200:
                last = L.LawError("법제처 접속 오류(HTTP %s)" % x.status)
                continue
            d = json.loads(x.responseText)
            if str(url).endswith("lawService.do") or len(_NET) < 200:
                _NET[ck] = d
            return d
        except ValueError:
            last = L.LawError("법제처 응답을 읽을 수 없음(JSON 아님) — 인증키(OC)와 접속 허용 도메인을 확인하세요")
        except Exception as e:  # noqa: BLE001
            last = L.LawError("법제처에 접속하지 못했습니다: %s" % e)
    raise last


def set_api_base(base):
    _API_BASE["v"] = base or None
    return "ok"


# ---- 보내는 모양 만들기
def _spans(text, selfname):
    out = []
    for c in L.cite_spans(text, selfname):
        out.append([c["start"], c["end"], c["law"], c["n"], c["b"], c["sub"]])
    return out


def _art_json(a, selfname, spans=True):
    lines = []
    for lv, t in a["lines"]:
        lines.append([lv, t, _spans(t, selfname) if spans else []])
    return {"key": a["key"], "n": a["n"], "b": a["b"], "label": a["label"], "title": a["title"], "lines": lines}


def _doc_json(law, selfname_target):
    refname = law.get("refname") or law["name"]
    arts = {}
    for k in law["order"]:
        arts[k] = _art_json(law["arts"][k], refname)
    items = []
    for it in law["items"]:
        items.append({"k": "h", "t": it["text"]} if it["kind"] == "head" else {"k": "a", "key": it["key"]})
    base = L._split_name(refname)[0] if law.get("kind") == "adm" else None
    return {"name": law["name"], "kind": law.get("kind", "law"), "mst": law["mst"], "date": law.get("date", ""),
            "refname": refname, "adm_base": base, "items": items, "arts": arts}


# ---- 화면에서 부르는 함수들
def _hits(r):
    return [{"kind": h["kind"], "lawname": h["lawname"], "rawmst": h["rawmst"], "mst": h["mst"], "short": h["short"],
             "info": h.get("snippet", ""), "date": h.get("date", "")} for h in r["hits"]]


def search(oc, q):
    """데스크톱 run()과 같은 순서: 조 번호가 있으면 바로 열기 / 법 이름·약칭이면 법·시행령·시행규칙·지침 목록 / 그 밖엔 이름 검색."""
    q = (q or "").strip()
    kind = "art" if "조례" in q else L.query_kind(q)
    if kind == "empty":
        kind = "name"
    msg = ""
    if kind == "art":
        if "조례" in q:
            name, jo, ji = L.parse_ordin_query(q)
            if not name:
                return {"hits": [], "total": 0, "msg": "조례 이름을 알 수 없습니다. 예) 고양시 도시계획 조례 55조"}
            p = {"name": name, "suffix": "", "jo": jo, "ji": ji}
        else:
            p = L.parse_query(q)
        if p.get("jo"):
            return {"hits": [], "total": 0, "open": {"name": L.full_name(p), "key": "%d:%d" % (p["jo"], p.get("ji") or 0)}}
        kind = "law"
    if kind == "law":
        names, rest = L.split_query(q)
        if names and len(names) == 3 and not rest:
            try:
                r = L.family_search(oc, q, getter)
            except Exception as e:  # noqa: BLE001
                r = None
                msg = "목록을 만들지 못했습니다: %s" % e
            if r and r["hits"]:
                return {"hits": _hits(r), "total": r["total"], "msg": r.get("note", "")}
        if names:
            return {"hits": [], "total": 0, "open": {"name": names[0] if len(names) == 1 else L.full_name(L.parse_query(q)), "key": ""}}
        return {"hits": [], "total": 0, "open": {"name": L.full_name(L.parse_query(q)), "key": ""}}
    r = L.name_search(oc, q, getter)
    return {"hits": _hits(r), "total": r["total"], "msg": msg or ("'%s' 이름의 법령·행정규칙·자치법규를 찾지 못했습니다." % q if not r["hits"] else "")}


def open_doc(oc, kind, rawmst, name, date=""):
    if kind == "ordin":
        law = L.load_ordin(oc, rawmst, name, getter)
        pre = "o"
    elif kind == "adm":
        law = L.load_adm(oc, rawmst, name, date, getter)
        pre = "a"
    else:
        law = L.load_whole(oc, rawmst, name, getter)
        pre = ""
    law["name"], law["mst"], law["date"] = name, pre + rawmst, date
    L._LAW_CACHE[law["mst"]] = law
    return _doc_json(law, name)


def open_by_name(oc, name):
    f = L.find_law(oc, name, getter)
    return open_doc(oc, "law", f["mst"], f["name"], f["date"])


def _find_art(law, n, b):
    k = "%d:%d" % (n, b)
    if k in law["arts"]:
        return law["arts"][k]
    return law["arts"].get("%d:0" % n)


def open_cite(oc, lawname, n, b, subs, ctx_mst=""):
    """인용 조문 미리보기 -> {lawname, mst, art, hl:[[첫줄,끝줄)…], summary}"""
    law = L._LAW_CACHE.get(ctx_mst) if ctx_mst else None
    if law is None or L._nospace(law["name"]) != L._nospace(lawname):
        f = L.find_law(oc, lawname, getter)
        law = L._LAW_CACHE.get(f["mst"]) or L.load_whole(oc, f["mst"], f["name"], getter)
        law["name"], law["mst"] = f["name"], f["mst"]
        L._LAW_CACHE[f["mst"]] = law
    a = _find_art(law, n, b)
    if a is None:
        return {"lawname": law["name"], "mst": law["mst"], "art": None, "label": L.jo_label(n, b)}
    hl = []
    for sb in L.expand_subs(subs):
        r = L.find_sub(a["lines"], sb)
        if r:
            hl.append([r[0], r[1]])
    return {"lawname": law["name"], "mst": law["mst"], "art": _art_json(a, law.get("refname") or law["name"]), "hl": hl,
            "summary": L.cite_summary(a, subs), "label": a["label"]}


def tt_open(oc, base, cur_name, cur_mst, cur_key):
    """3단 비교표 줄 목록과 시작 줄"""
    tt = L.three_tier(oc, base, getter)
    law = L._LAW_CACHE.get(cur_mst)
    start = L.tt_start(tt, law, cur_key, cur_name) if (law and cur_key) else 0
    rows = []
    for r in tt["rows"]:
        a = tt["laws"][0]["arts"][r["key"]]
        rows.append({"key": r["key"], "label": a["label"], "title": a["title"], "nd": len(r["dec"]), "nr": len(r["rule"])})
    return {"names": tt["names"], "rows": rows, "start": start, "have": [x is not None for x in tt["laws"]]}


def tt_row(base, i):
    tt = L._TT_CACHE[L._split_name(base)[0]]
    r = tt["rows"][i]
    cols = []
    for ci, keys in enumerate(([r["key"]], r["dec"], r["rule"])):
        law = tt["laws"][ci]
        arts = []
        if law:
            for k in keys:
                arts.append(_art_json(law["arts"][k], tt["names"][ci]))
        cols.append({"name": tt["names"][ci], "mst": (law or {}).get("mst", ""), "arts": arts, "none": law is None})
    return {"cols": cols}


FUNCS = {"search": search, "open_doc": open_doc, "open_by_name": open_by_name, "open_cite": open_cite,
         "tt_open": tt_open, "tt_row": tt_row, "set_api_base": set_api_base}


def call(fn, args_json):
    try:
        res = FUNCS[fn](*json.loads(args_json))
        return json.dumps({"ok": res}, ensure_ascii=False)
    except L.LawError as e:
        return json.dumps({"err": str(e)}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        import traceback
        return json.dumps({"err": "프로그램 내부 오류(%s: %s)" % (type(e).__name__, e), "tb": traceback.format_exc()[-1500:]}, ensure_ascii=False)
