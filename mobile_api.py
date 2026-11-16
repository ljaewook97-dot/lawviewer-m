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
_ANNEX_RE = re.compile(r"별표\s*(\d+)(?:\s*의\s*(\d+))?|서식\s*제?\s*(\d+)\s*호")
_CODE_RE = re.compile(r"(?<![\d-])\d{1,2}(?:-\d{1,2}){2}(?![\d-])")


def _spans(text, selfname, law=None, lv=0):
    out = []
    taken = []
    for c in L.cite_spans(text, selfname):
        out.append([c["start"], c["end"], c["law"], c["n"], c["b"], c["sub"]])
        taken.append((c["start"], c["end"]))
    hm = L.HEADER_RE.match(text) if lv == 0 else None
    hdr = hm.end() if hm else 0
    if law is not None:                    # '별표 3'·'서식 제2호'(그 법령에 있으면) / 지침의 '2-3-12' -> 눌러서 이동
        try:
            labs = law.get("_axl")
            if labs is None:
                labs = law["_axl"] = {x["label"] for x in (law.get("annex") or [])}
            for m in _ANNEX_RE.finditer(text):
                if m.start() < hdr:
                    continue
                lab = ("별표 %s%s" % (m.group(1), ("의" + m.group(2)) if m.group(2) else "")) if m.group(1) else "서식 %s" % m.group(3)
                if lab in labs:
                    out.append([m.start(), m.end(), "@x", lab, 0, None]); taken.append((m.start(), m.end()))
            if law.get("kind") == "adm":
                codes = law.get("_cdm")
                if codes is None:
                    codes = law["_cdm"] = {x["label"]: k for k, x in law["arts"].items()}
                for m in _CODE_RE.finditer(text):
                    if m.start() < hdr or m.group(0) not in codes or any(x <= m.start() < y for x, y in taken):
                        continue
                    if text[:m.start()].strip() == "" and text[m.end():m.end() + 1] == ".":
                        continue
                    out.append([m.start(), m.end(), "@c", codes[m.group(0)], 0, None]); taken.append((m.start(), m.end()))
        except Exception:  # noqa: BLE001
            pass
    try:                                   # '대통령령으로'·'정하여 고시'·'조례' — 눌러서 관련 조문 목록을 만든다(PC 와 같음)
        for a, b, to in L.deleg_spans(text, selfname, taken):
            out.append([a, b, "@d", to, 0, None]); taken.append((a, b))
        for a, b in L.adm_spans(text, taken):
            out.append([a, b, "@a", "", 0, None]); taken.append((a, b))
        for a, b in L.ordin_spans(text, taken):
            out.append([a, b, "@o", "", 0, None]); taken.append((a, b))
    except Exception:  # noqa: BLE001
        pass
    return out


def _art_json(a, selfname, spans=True, law=None):
    lines = []
    for lv, t in a["lines"]:
        lines.append([lv, t, _spans(t, selfname, law, lv) if spans else []])
    return {"key": a["key"], "n": a["n"], "b": a["b"], "label": a["label"], "title": a["title"], "lines": lines,
            "inn": list(a.get("in_keys") or [])}


def _doc_json(law, selfname_target):
    refname = law.get("refname") or law["name"]
    arts = {}
    for k in law["order"]:
        arts[k] = _art_json(law["arts"][k], refname, True, law)
    items = []
    for it in law["items"]:
        items.append({"k": "h", "t": it["text"]} if it["kind"] == "head" else {"k": "a", "key": it["key"]})
    base = L._split_name(refname)[0] if law.get("kind") == "adm" else None
    annex = []
    for x in (law.get("annex") or []):
        annex.append({"label": x["label"], "title": x["title"], "lines": [[lv, t] for lv, t in x["text"]],
                      "url": L.annex_url(x.get("pdf") or x.get("link") or ""), "deleted": bool(x.get("deleted"))})
    return {"name": law["name"], "kind": law.get("kind", "law"), "mst": law["mst"], "date": law.get("date", ""),
            "refname": refname, "adm_base": base, "items": items, "arts": arts, "annex": annex}


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


def suggest(oc, q):
    """검색창 자동완성: 약칭 풀이 + 법제처 이름 검색 -> {q, items, tail}"""
    return {"q": q, "items": L.suggest(oc, q, getter), "tail": L.suggest_split(q)[2]}


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
    return {"lawname": law["name"], "mst": law["mst"], "art": _art_json(a, law.get("refname") or law["name"], True, law), "hl": hl,
            "summary": L.cite_summary(a, subs), "label": a["label"]}


def cite_titles(items):
    """[[법령명, 조, 가지]…] -> 이미 받아 둔 법령에서 조문 제목을 찾아 같은 순서로 돌려준다(새로 내려받지 않음)"""
    out = []
    for name, n, b in items:
        t = ""
        for law in list(L._LAW_CACHE.values()):
            try:
                if L._nospace(law["name"]) == L._nospace(name) or L._nospace(law.get("refname") or "") == L._nospace(name):
                    ar = _find_art(law, int(n), int(b or 0))
                    if ar is not None:
                        t = ar["title"]
                        break
            except Exception:
                continue
        out.append(t)
    return out


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


def _hit(h):
    mst = str(h["mst"])
    lw = L._LAW_CACHE.get(mst)
    if lw is not None:
        lw.setdefault("name", h["lawname"]); lw.setdefault("mst", mst)
    kind = "adm" if h.get("adm") or mst.startswith("a") else "ordin" if h.get("ord") or mst.startswith("o") else "law"
    return {"kind": kind, "mst": mst, "rawmst": mst[1:] if kind != "law" else mst, "lawname": h["lawname"], "key": h.get("key", ""),
            "label": h.get("label", ""), "title": h.get("title", ""), "short": h.get("short", ""), "snippet": h.get("snippet", ""),
            "ext": bool(h.get("ext"))}


def _hitres(r, note=""):
    return {"hits": [_hit(h) for h in r["hits"]], "total": r["total"], "note": note or r.get("note", ""), "toks": r.get("toks", []),
            "searched": r.get("searched", [])}


def kw_search(oc, q, city=""):
    """키워드로 조문 찾기(PC 의 '키워드 검색')"""
    r = L.keyword_search(oc, q, None, getter, 80, True, city or "")
    return _hitres(r)


def open_cached(mst, key=""):
    """키워드·위임 결과를 누르면, 이미 받아 둔 법령을 본문으로 연다"""
    law = L._LAW_CACHE.get(mst)
    if law is None:
        raise L.LawError("이 법령은 다시 검색해서 열어 주세요")
    d = _doc_json(law, law["name"])
    d["rawmst"] = mst[1:] if mst[:1] in ("a", "o") else mst
    d["kind"] = "adm" if mst.startswith("a") else "ordin" if mst.startswith("o") else "law"
    return d


def _cur_art(mst, key):
    law = L._LAW_CACHE.get(mst)
    a = law["arts"].get(key) if law else None
    if not a:
        raise L.LawError("조문을 찾지 못했습니다")
    return law, a


def list_deleg(oc, mst, key, to):
    """'대통령령으로'를 누르면: 이 조문을 위임받은 시행령(시행규칙) 조문 목록"""
    law, a = _cur_art(mst, key)
    r = L.deleg_lookup(oc, law["name"], to, a["n"], a["b"], a.get("title", ""), getter)
    return _hitres(r)


def list_adm(oc, mst, key, line=""):
    """'정하여 고시한다'를 누르면: 관련 지침·고시"""
    law, a = _cur_art(mst, key)
    r = L.adm_search(oc, a.get("title", ""), law["name"], a.get("scan", ""), line=line, cite=(law["name"], a["n"], a["b"]), getter=getter)
    return _hitres(r)


def list_ordin(oc, mst, key, city=""):
    """'조례'를 누르면: 기본 자치단체 조례에서 이 조문 제목 낱말이 든 조문"""
    import re as _re
    law, a = _cur_art(mst, key)
    toks = []
    for w in _re.split(r"[\s·ㆍ,()]+", a.get("title", "")):
        w = _re.sub(r"(에서의|에서|으로의|의)$", "", w)
        if len(w) >= 2 and w not in ("및", "경우", "기준", "대한", "관한", "관련") and w not in toks:
            toks.append(w)
    if not toks:
        toks = _re.findall(r"[가-힣]{2,}", a.get("scan", ""))[:3]
    r = L.ordin_lookup(oc, city or "고양시", toks, getter)
    return _hitres(r, "%s — '%s' 관련 조문" % (r.get("ordname", ""), " ".join(toks)))


def web_url(kind, name, key=""):
    """법제처에서 열기 주소"""
    n = b = None
    if key:
        n, b = [int(x) for x in key.split(":")]
    if kind == "adm":
        return L.adm_web_url(name)
    if kind == "ordin":
        return L.ordin_web_url(name, n, b or 0)
    q = name + ((" " + L.jo_label(n, b)) if n else "")
    return L.web_url(L.parse_query(q))


FUNCS = {"cite_titles": cite_titles, "web_url": web_url, "kw_search": kw_search, "open_cached": open_cached, "list_deleg": list_deleg, "list_adm": list_adm, "list_ordin": list_ordin,"search": search, "suggest": suggest, "open_doc": open_doc, "open_by_name": open_by_name, "open_cite": open_cite,
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
