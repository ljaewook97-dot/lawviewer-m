# -*- coding: utf-8 -*-
"""법령 조문 빠른 조회: "국토계획법 시행령 71조" 처럼 치면 국가법령정보센터 Open API 로 그 조문 본문을 가져온다.
- 인증키(OC)는 사용자가 설정에서 넣는다(open.law.go.kr 무료 신청). 키가 없거나 조 번호가 없으면 법제처 화면 주소만 만들어 준다.
- 접속은 lawnet 의 접속 사슬(일반 -> WinHTTP -> PowerShell)을 쓴다(딸깍의 launcher_parcel 과 같은 방식).
- 법 이름 약칭(국토계획법 등)은 아래 표로 풀고, 표에 없으면 친 이름 그대로 검색한다."""
import json
import os
import re
import threading
import time
import urllib.parse

API = "http://www.law.go.kr/DRF/"

# 약칭(공백 뺀 것) -> 정식 이름
ALIASES = {
    "국토계획법": "국토의 계획 및 이용에 관한 법률", "국계법": "국토의 계획 및 이용에 관한 법률",
    "국토법": "국토의 계획 및 이용에 관한 법률", "국토의계획및이용에관한법률": "국토의 계획 및 이용에 관한 법률",
    "건축법": "건축법", "도시개발법": "도시개발법", "도시정비법": "도시 및 주거환경정비법", "도정법": "도시 및 주거환경정비법",
    "환경영향평가법": "환경영향평가법", "환평법": "환경영향평가법",
    "교통정비촉진법": "도시교통정비 촉진법", "도시교통정비촉진법": "도시교통정비 촉진법", "도교법": "도시교통정비 촉진법",
    "자연재해대책법": "자연재해대책법", "재대법": "자연재해대책법",
    "군사기지법": "군사기지 및 군사시설 보호법", "군사시설보호법": "군사기지 및 군사시설 보호법",
    "토지보상법": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률", "공익사업법": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률",
    "산지관리법": "산지관리법", "농지법": "농지법", "도로법": "도로법", "하천법": "하천법", "주택법": "주택법",
    "개발제한구역법": "개발제한구역의 지정 및 관리에 관한 특별조치법", "그린벨트법": "개발제한구역의 지정 및 관리에 관한 특별조치법",
    "개발제한구역특별조치법": "개발제한구역의 지정 및 관리에 관한 특별조치법",
    "노후계획도시특별법": "노후계획도시 정비 및 지원에 관한 특별법", "노계법": "노후계획도시 정비 및 지원에 관한 특별법",
    "택지개발촉진법": "택지개발촉진법", "수도권정비계획법": "수도권정비계획법", "매장유산법": "매장유산 보호 및 조사에 관한 법률",
    "도시공원법": "도시공원 및 녹지 등에 관한 법률", "공유재산법": "공유재산 및 물품 관리법", "지적법": "공간정보의 구축 및 관리 등에 관한 법률",
    "건축물관리법": "건축물관리법", "주차장법": "주차장법", "도시철도법": "도시철도법", "철도건설법": "철도의 건설 및 철도시설 유지관리에 관한 법률",
    "자연공원법": "자연공원법", "물환경보전법": "물환경보전법", "대기환경보전법": "대기환경보전법", "소방시설법": "소방시설 설치 및 관리에 관한 법률",
}
for _v in list(ALIASES.values()):                      # 정식 이름을 그대로 쳐도 같은 이름으로 인식
    ALIASES.setdefault(re.sub(r"\s+", "", _v), _v)
SUFFIXES = ("시행규칙", "시행령")


class LawError(Exception):
    pass


def _nospace(s):
    return re.sub(r"\s+", "", str(s or ""))


def parse_query(q):
    """'국토계획법 시행령 71조의2' -> dict(name 정식이름 또는 친 이름, suffix, jo, ji, jo_text). 조 번호가 없으면 jo 는 None."""
    t = _nospace(q)
    if not t:
        raise LawError("법 이름과 조 번호를 입력하세요. 예) 국토계획법 시행령 71조")
    jo = ji = None
    m = re.search(r"제?(\d+)조(?:의(\d+))?", t)
    if m:
        jo = int(m.group(1))
        ji = int(m.group(2)) if m.group(2) else 0
        name_part = t[:m.start()]
    else:
        name_part = re.split(r"별표|제\d+호|제\d+항|비고|\d", t)[0]
    name_part = name_part.strip("의 ,，·")
    suffix = ""
    for sfx in SUFFIXES:
        if name_part.endswith(sfx):
            suffix = sfx
            name_part = name_part[:-len(sfx)]
            break
    if not name_part:
        raise LawError("법 이름을 알 수 없습니다. 예) 국토계획법 시행령 71조")
    full = ALIASES.get(name_part)
    if full is None:
        for k in sorted(ALIASES, key=len, reverse=True):        # '국토계획법상' 처럼 뒤에 글이 붙은 경우
            if name_part.startswith(k):
                full = ALIASES[k]
                break
    name = full or name_part
    return {"name": name, "suffix": suffix, "jo": jo, "ji": ji}


def full_name(p):
    return p["name"] + ((" " + p["suffix"]) if p["suffix"] else "")


def web_url(p):
    """법제처 화면 주소(조 번호가 있으면 그 조, 없으면 법령 첫 화면)."""
    path = "법령/" + _nospace(full_name(p))
    if p["jo"]:
        path += "/제%d조%s" % (p["jo"], ("의%d" % p["ji"]) if p["ji"] else "")
    return "https://www.law.go.kr/" + urllib.parse.quote(path, safe="/")


def jo_label(jo, ji):
    return "제%d조%s" % (jo, ("의%d" % ji) if ji else "")


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_SEARCH_TTL = 12 * 3600                    # 이름·본문 검색 결과는 12시간 재사용(새 개정본이 나오면 곧 반영되도록)
_purged = []


def _ckey(path, params):
    import hashlib
    items = sorted((k, str(v)) for k, v in params.items() if k != "OC")
    return hashlib.md5((path + json.dumps(items, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _purge_cache():
    """오래된 저장 파일 정리: 검색 결과는 2일, 법령 본문은 90일"""
    _purged.append(1)
    try:
        now = time.time()
        for fn in os.listdir(CACHE_DIR):
            fp = os.path.join(CACHE_DIR, fn)
            age = now - os.path.getmtime(fp)
            if age > (90 * 86400 if fn.startswith("S_") else 2 * 86400):
                os.remove(fp)
    except OSError:
        pass


def _get(path, params, getter=None):
    """법제처 조회. 실제 접속(getter 없음)일 때는 받은 응답을 디스크(cache 폴더)에 저장해 두고 다시 쓴다
    — 법령 본문(lawService)은 일련번호마다 내용이 정해져 있으므로 계속, 검색(lawSearch)은 12시간."""
    if getter is not None:
        return getter(API + path, params, timeout=25, tries=2)
    import lawnet
    if not _purged:
        _purge_cache()
    is_svc = path == "lawService.do"
    fp = os.path.join(CACHE_DIR, ("S_" if is_svc else "Q_") + _ckey(path, params))
    try:
        if os.path.exists(fp) and (is_svc or time.time() - os.path.getmtime(fp) < _SEARCH_TTL):
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    d = lawnet.get_json(API + path, params, timeout=25, tries=2)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = fp + ".%d.tmp" % threading.get_ident()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, fp)
    except (OSError, TypeError, ValueError):
        pass
    return d


def _dicts_with(o, key, out):
    if isinstance(o, dict):
        if key in o:
            out.append(o)
        for v in o.values():
            _dicts_with(v, key, out)
    elif isinstance(o, list):
        for v in o:
            _dicts_with(v, key, out)


def find_law(oc, name, getter=None):
    """정식 이름 -> {"mst","name","date"} (현행). 못 찾으면 LawError."""
    d = _get("lawSearch.do", {"OC": oc, "target": "law", "type": "JSON", "query": name, "display": 30}, getter)
    rows = []
    _dicts_with(d, "법령명한글", rows)
    want = _nospace(name)
    best = None
    for r in rows:
        nm = _nospace(r.get("법령명한글"))
        cur = str(r.get("현행연혁코드") or "")
        if nm != want or (cur and "현행" not in cur):
            continue
        cand = {"mst": str(r.get("법령일련번호") or ""), "name": str(r.get("법령명한글") or name), "date": str(r.get("시행일자") or "")}
        if cand["mst"] and (best is None or cand["date"] > best["date"]):
            best = cand
    if best is None:                                              # 이름이 조금 달라도 가장 가까운 현행 법령
        for r in rows:
            nm = _nospace(r.get("법령명한글"))
            cur = str(r.get("현행연혁코드") or "")
            if want in nm and (not cur or "현행" in cur) and r.get("법령일련번호"):
                cand = {"mst": str(r["법령일련번호"]), "name": str(r.get("법령명한글") or name), "date": str(r.get("시행일자") or "")}
                if best is None or len(_nospace(cand["name"])) < len(_nospace(best["name"])):
                    best = cand
    if best is None:
        raise LawError("'%s' 법령을 찾지 못했습니다(이름을 정식 이름으로 쳐 보세요)" % name)
    return best


def _lines(v, out, indent=""):
    """글자 또는 글자 목록을 줄로."""
    if isinstance(v, str):
        for ln in v.replace("\r", "").split("\n"):
            ln = ln.strip()
            if ln:
                out.append(indent + ln)
    elif isinstance(v, list):
        for x in v:
            _lines(x, out, indent)


def format_article(unit):
    """조문단위(JSON 조각) -> 읽기 좋은 글. 조문내용 -> 항 -> 호 -> 목 순서."""
    out = []
    _lines(unit.get("조문내용"), out)

    def walk(items, key_text, child_key, child_fn, indent):
        if isinstance(items, dict):
            items = [items]
        for it in items or []:
            if not isinstance(it, dict):
                continue
            _lines(it.get(key_text), out, indent)
            if child_key and child_key in it:
                child_fn(it[child_key])

    def mok(items):
        walk(items, "목내용", None, None, "      ")

    def ho(items):
        walk(items, "호내용", "목", mok, "   ")

    walk(unit.get("항"), "항내용", "호", ho, "")
    return "\n".join(out)


def fetch_article(oc, mst, jo, ji, getter=None):
    """-> (본문 글, 시행일) 또는 LawError."""
    d = _get("lawService.do", {"OC": oc, "target": "law", "type": "JSON", "MST": mst, "JO": "%04d%02d" % (jo, ji or 0)}, getter)
    units = []
    _dicts_with(d, "조문내용", units)
    units = [u for u in units if str(u.get("조문여부") or "조문") == "조문" or u.get("조문번호")]
    if not units:
        raise LawError("%s 이(가) 없습니다(조 번호를 확인하세요)" % jo_label(jo, ji))
    want = str(jo)
    pick = None
    for u in units:
        if str(u.get("조문번호") or "") == want and str(u.get("조문가지번호") or "0") in (str(ji or 0), "") :
            pick = u
            break
    pick = pick or units[0]
    text = format_article(pick)
    if not text:
        raise LawError("%s 본문을 읽지 못했습니다" % jo_label(jo, ji))
    return text, str(pick.get("조문시행일자") or "")


def lookup(oc, query, getter=None):
    """query -> dict(title, text, url, date, jo, ji, p). 조 번호가 없으면 text 는 빈 글(주소만)."""
    p = parse_query(query)
    res = {"p": p, "url": web_url(p), "text": "", "title": full_name(p), "date": ""}
    if p["jo"] is None:
        return res
    law = find_law(oc, full_name(p), getter)
    text, ef = fetch_article(oc, law["mst"], p["jo"], p["ji"], getter)
    res.update(title="%s %s" % (law["name"], jo_label(p["jo"], p["ji"])), text=text, date=ef or law["date"],
               mst=law["mst"], lawname=law["name"])
    return res


# ───────────────────────── 인용 정리 (조문이 가리키는 조문 · 이 조문을 인용하는 조문 · 위임) ─────────────────────────
# 조문 본문의 "제76조부터 제78조까지", "「건축법」 제42조ㆍ제43조", "법 제52조", "대통령령으로 정하는" 같은 표현을 뽑아
# 법제처 화면처럼 본문 곳곳에 링크로 흩어 놓지 않고, 접어 둔 목록으로 모아 준다. 본문은 건드리지 않는다.
_LAW_CACHE = {}          # 법령일련번호 -> 분석 결과(한 번 받으면 같은 법의 다른 조문은 다시 받지 않는다)

AMEND_RE = re.compile(
    r"<[^<>\n]*\d{4}\.\s?\d{1,2}\.\s?\d{1,2}[^<>\n]*>"
    r"|\[[^\[\]\n]*\d{4}\.\s?\d{1,2}\.\s?\d{1,2}[^\[\]\n]*\]"
)
HEADER_RE = re.compile(r"^제\d+조(?:의\d+)?\s*(?:\([^)]*\))?")
TOKEN = re.compile(
    r"「(?P<law>[^」]+)」"
    r"|(?P<same>같은 법 시행령|같은 법|이 법|이 영|이 규칙)"
    r"|(?<![가-힣])(?P<abbr>법|영)(?=\s*제\d+조)"
    r"|제(?P<n>\d+)조(?:의(?P<b>\d+))?"
)
GAP_STRIP = re.compile(r"제\d+[항호](?:의\d+)?|[가-힣]목|ㆍ|,|및|또는|부터|까지|과|와|의|\s+")
DELEG_RE = re.compile(
    r"(대통령령|총리령|[가-힣]{2,12}부령|부령|조례|규칙|고시)"
    r"(?:으로|로)\s*(?:따로\s*|각각\s*)?(?:정|위임)"
)


def _num(v):
    s = str(v or "").strip()
    return int(s) if s.isdigit() else 0


def _split_name(name):
    """'국토의 계획 및 이용에 관한 법률 시행령' -> ('국토의 계획 및 이용에 관한 법률', '시행령')"""
    m = re.match(r"^(.*?)\s*(시행령|시행규칙)$", str(name or "").strip())
    return (m.group(1), m.group(2)) if m else (str(name or "").strip(), "")


def unit_lines(unit):
    """조문단위(JSON 조각) -> [(단계, 글)]  단계: 조문내용 0 · 항 1 · 호 2 · 목 3"""
    out = []

    def add(level, v):
        tmp = []
        _lines(v, tmp)
        out.extend((level, ln) for ln in tmp)

    def walk(items, key_text, child_key, child_fn, level):
        if isinstance(items, dict):
            items = [items]
        for it in items or []:
            if not isinstance(it, dict):
                continue
            add(level, it.get(key_text))
            if child_key and child_key in it:
                child_fn(it[child_key])

    def mok(items):
        walk(items, "목내용", None, None, 3)

    def ho(items):
        walk(items, "호내용", "목", mok, 2)

    add(0, unit.get("조문내용"))
    walk(unit.get("항"), "항내용", "호", ho, 1)
    if "호" in unit and not unit.get("항"):
        ho(unit.get("호"))
    return out


def extract_refs(text, selfname=""):
    """본문에서 조문 인용을 뽑는다 -> [{'law': None(같은 법령)|법령명, 'n', 'b', 'to': (조, 가지)|None}]
    - 「법령명」 뒤에 ㆍ·및·또는·부터 로 이어지는 조문은 그 법령 소속으로 본다.
    - '제76조부터 제78조까지' 는 범위 하나로 묶는다.
    - 시행령·시행규칙 안의 '법 제52조'·'영 제71조' 는 모법·시행령 조문으로 풀어 준다."""
    base, sfx = _split_name(selfname)
    text = AMEND_RE.sub(" ", text)

    def abbr(tok):
        if tok in ("법", "이 법"):
            return None if not sfx else base
        if tok in ("영", "이 영"):
            return None if sfx == "시행령" else base + " 시행령"
        if tok == "이 규칙":
            return None if sfx == "시행규칙" else base + " 시행규칙"
        return None

    refs, seen = [], set()
    cur, last_ext, last_end, prev = None, None, None, None
    for m in TOKEN.finditer(text):
        if m.group("law"):
            cur = m.group("law").strip()
            last_ext, last_end, prev = cur, m.end(), None
            continue
        tok = m.group("same") or m.group("abbr")
        if tok:
            if tok == "같은 법":
                cur = last_ext
            elif tok == "같은 법 시행령":
                cur = (_split_name(last_ext)[0] if last_ext else base) + " 시행령"
            else:
                cur = abbr(tok)
            if cur:
                last_ext = cur
            last_end, prev = m.end(), None
            continue
        n, b = int(m.group("n")), int(m.group("b") or 0)
        gap = text[last_end:m.start()] if last_end is not None else None
        ok = gap is not None and GAP_STRIP.sub("", gap) == ""
        if not ok:
            cur, prev = None, None
        if ok and prev is not None and "부터" in gap and prev["law"] == cur and prev.get("to") is None:
            prev["to"] = (n, b)
            last_end = m.end()
            continue
        ref = {"law": cur, "n": n, "b": b, "to": None}
        last_end, prev = m.end(), ref
        k = (cur, n, b)
        if k in seen:
            prev = None
            continue
        seen.add(k)
        refs.append(ref)
    return refs


def extract_deleg(lines):
    """위임 표현 -> [(항 번호, 종류, 앞뒤 글)]"""
    out = []
    for _lv, txt in lines:
        clean = AMEND_RE.sub("", txt)
        marker = clean.split(" ", 1)[0] if clean else ""
        if not re.match(r"^(?:[①-⑳]|\d+[.의]|\d+의\d+\.|[가-힣]\.)", marker):
            marker = ""
        for m in DELEG_RE.finditer(clean):
            out.append((marker, m.group(1), clean[max(0, m.start() - 22):min(len(clean), m.end() + 14)].strip()))
    return out


def _ref_label(r):
    s = jo_label(r["n"], r["b"])
    if r.get("to"):
        s += "~" + jo_label(r["to"][0], r["to"][1])
    return s


def analyze_units(units, selfname=""):
    """조문단위 목록 -> {'arts': {키: 조문}, 'order': [키…]}  (조문마다 out_int·out_ext·in_keys·deleg 를 채운다)"""
    arts, order, items = {}, [], []
    for u in units:
        if str(u.get("조문여부") or "조문") != "조문":          # 전문(장·절·관 제목)
            tmp = []
            _lines(u.get("조문내용"), tmp)
            if tmp:
                items.append({"kind": "head", "text": " ".join(tmp)})
            continue
        n = _num(u.get("조문번호"))
        if not n:
            continue
        b = _num(u.get("조문가지번호"))
        key = "%d:%d" % (n, b)
        if key in arts:
            continue
        lines = unit_lines(u)
        scan = "\n".join(HEADER_RE.sub("", t, count=1) if lv == 0 else t for lv, t in lines)
        arts[key] = {"key": key, "n": n, "b": b, "label": jo_label(n, b), "title": str(u.get("조문제목") or "").strip(),
                     "lines": lines, "scan": scan, "in_keys": []}
        order.append(key)
        items.append({"kind": "art", "key": key})
    for key in order:
        a = arts[key]
        a["out_int"], a["out_ext"] = [], []
        for r in extract_refs(a["scan"], selfname):
            if r["law"]:
                a["out_ext"].append({"law": r["law"], "n": r["n"], "b": r["b"], "label": "「%s」 %s" % (r["law"], _ref_label(r))})
                continue
            if r["to"]:
                keys = [k for k in order if (r["n"], r["b"]) <= (arts[k]["n"], arts[k]["b"]) <= r["to"]]
            else:
                k = "%d:%d" % (r["n"], r["b"])
                keys = [k] if k in arts else []
            keys = [k for k in keys if k != key]
            if not keys:
                continue
            label = _ref_label(r)
            if r["to"] or len(keys) > 1:
                label += " (%d개 조문)" % len(keys)
            elif arts[keys[0]]["title"]:
                label += " " + arts[keys[0]]["title"]
            a["out_int"].append({"keys": keys, "label": label})
            for k in keys:
                if key not in arts[k]["in_keys"]:
                    arts[k]["in_keys"].append(key)
        a["deleg"] = extract_deleg(a["lines"])
    return {"arts": arts, "order": order, "items": items}


_AX_MARK = [(re.compile(r"^\d+\.\s*"), 1), (re.compile(r"^[가나다라마바사아자차카타파하]\.\s*"), 2), (re.compile(r"^\d+\)\s+"), 3), (re.compile(r"^[가나다라마바사아자차카타파하]\)\s+"), 4),
            (re.compile(r"^\(\d+\)\s*"), 3), (re.compile(r"^[①-⑳]\s*"), 2), (re.compile(r"^[ㄱ-ㅎ]\.\s*"), 3), (re.compile(r"^[ⅰ-ⅹ]\.\s*"), 4)]


def _raw_lines(v, out):
    """글자 목록을 줄로(줄 끝 공백은 남겨 둔다 — 줄 바꿈이 낱말 사이인지 가운데인지 가리는 데 쓴다)."""
    if isinstance(v, str):
        for ln in v.replace("\r", "").split("\n"):
            if ln.strip():
                out.append(ln.lstrip() if not ln.startswith("  ") else ln)
    elif isinstance(v, list):
        for x in v:
            _raw_lines(x, out)


_LET = "가나다라마바사아자차카타파하"
_AX_KIND = [("d1", re.compile(r"^(\d+)\.\s*"), 1), ("k1", re.compile(r"^([가나다라마바사아자차카타파하])\.\s*"), 2), ("d2", re.compile(r"^(\d+)\)\s+"), 3),
            ("k2", re.compile(r"^([가나다라마바사아자차카타파하])\)\s+"), 4), ("p", re.compile(r"^\((\d+)\)\s*"), 3), ("c", re.compile(r"^([①-⑳])\s*"), 2)]
_AX_DEEP = {"d1": ("k1", "d2", "k2", "p"), "k1": ("d2", "k2", "p"), "d2": ("k2",), "k2": (), "p": (), "c": ("d1", "k1", "d2", "k2")}


def _ax_val(kind, g):
    if kind in ("k1", "k2"):
        return _LET.find(g) + 1
    if kind == "c":
        return "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳".index(g) + 1
    return int(g)


def _format_annex_text(raw, title=""):
    """별표 본문(줄 목록) -> [(단계, 글)]. 번호(1. 가. 1) 가) (1) ①)를 보고 들여쓸 단계를 정하되, 번호가 차례(1,2,3 / 가,나,다)로 이어질 때만 번호로 인정한다
    ('…이하 같\n다) 및 …'처럼 잘린 줄의 '다)'를 번호로 착각하지 않게). 번호 없이 이어지는 줄(고정 너비로 잘린 줄 바꿈)은 앞 줄에 이어 붙인다.
    HTML 문자(&lt; 등)는 풀고, 첫머리의 중복된 제목 줄은 뺀다."""
    import html
    lines = [html.unescape(x) for x in raw]
    nz = [len(x.strip()) for x in lines if x.strip()]
    width = max(nz) if nz else 0
    tt = re.sub(r"\s+", "", re.sub(r"^\[[^\]]*\]\s*", "", html.unescape(title)))
    out, last = [], {}
    for i, ln in enumerate(lines):
        st = ln.strip()
        if not st:
            continue
        if i < 4 and (re.match(r"^[■□▣◆]\s*.*\[(별표|서식)", st) or (tt and re.sub(r"\s+", "", st) == tt)):
            continue                                        # 맨 앞의 '■ ○○법 [별표 1]'·제목 되풀이는 뺀다
        lv, kind_ok = 0, None
        for kind, rx, l in _AX_KIND:
            m = rx.match(st)
            if not m:
                continue
            v = _ax_val(kind, m.group(1))
            if v == last.get(kind, 0) + 1 or v == 1:         # 차례대로 이어지거나 새로 1부터 시작할 때만 번호
                lv, kind_ok = l, (kind, v)
            break
        if kind_ok:
            last[kind_ok[0]] = kind_ok[1]
            for d in _AX_DEEP[kind_ok[0]]:
                last[d] = 0
        is_item = lv > 0 or re.match(r"^[※■□▣◆●○ㆍ·\-]\s*|^(비고|주)\b", st) is not None or "|" in st
        if out and not is_item and "|" not in out[-1][1] and out[-1][2] >= 0.5 * width and width >= 20 and not re.search(r"[.:;]$", out[-1][1]):
            prev_lv, prev, _w = out[-1]
            # 줄 끝 공백은 믿을 수 없어(모든 줄에 붙어 오기도 함) 낱말 끝 글자로만 판단: 조사·어미 뒤에서 끊겼으면 띄우고, 낱말 가운데면 붙인다
            joiner = " " if (re.search(r"(를|을|는|은|에|의|와|과|로|고|며|서|면|어|여|아|도)$|하여$|하고$|하는$", prev) and not re.match(r"^[)\]」·,.]|^(이|가|을|를|은|는|의|에|로|와|과|도|만)(\s|$)", st)) else ""
            out[-1] = (prev_lv, prev + joiner + st, len(st))
            continue
        out.append((lv, st, len(st)))
    return [(lv, t) for lv, t, _w in out]


_VB = set("│┃|")                                   # 세로줄
_JB = set("┌┐└┘├┤┬┴┼╋┏┓┗┛┣┫┳┻┿┠┨┯┷┝┥╂╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬")                       # 모서리·교차
_HB = set("─━═-")                                   # 가로줄
_BOXCH = _VB | _JB | _HB | set("+ \t")
_ITEM = re.compile(r"^(?:\d+\.|[가-하]\.|\d+\)|[가-하]\)|\(\d+\)|[①-⑳]|[※■□▣◆●○ㆍ·]|\-\s|비고|주\b)")


def _dw(ch):
    import unicodedata
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _is_border(ln):
    st = ln.strip()
    return len(st) >= 3 and all(c in _BOXCH for c in st) and sum(c in _HB or c in _JB for c in st) >= 3


def _is_trow(ln):
    st = ln.strip()
    return sum(c in "│┃" for c in st) >= 2 or (st.count("|") >= 2 and not st.startswith("※")) or _is_border(ln)


_JUNK = re.compile(r"[─━═║┌┐└┘├┤┬┴┼╋┏┓┗┛┣┫┳┻┿┠┨┯┷┝┥╂╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬│┃]+|-{3,}|={3,}|_{3,}")


def _bars(ln):
    """한 줄에서 세로줄(칸 경계)의 화면 칸 위치와, 그 사이의 글(칸 내용). 줄 앞뒤의 바깥 글도 한 칸으로, 칸 안의 선 조각은 지운다"""
    col, cuts = 0, []
    for i, c in enumerate(ln):
        if c in _VB or (c in _JB):
            cuts.append((col, i))
        col += _dw(c)
    if not cuts:
        return []
    st = ln.strip()
    if st and st[0] not in _VB and st[0] not in _JB:
        cuts.insert(0, (0, -1))
    if st and st[-1] not in _VB and st[-1] not in _JB:
        cuts.append((col, len(ln)))
    cells = []
    for a, b in zip(cuts, cuts[1:]):
        cells.append((a[0], b[0], _JUNK.sub("", ln[a[1] + 1:b[1]]).strip()))
    return cells


def _join_cell(lines):
    """한 칸 안의 줄들을 문단으로: 번호로 시작하면 새 문단, 아니면 앞 줄에 이어 붙임(조사·어미 뒤면 띄우고 낱말 가운데면 붙임)"""
    out = []
    for t in lines:
        if not t:
            continue
        if not out or _ITEM.match(t):
            out.append(t)
            continue
        prev = out[-1]
        joiner = " " if ((re.search(r"(를|을|는|은|에|의|와|과|로|고|며|서|면|도)$|하여$|하고$|하는$", prev) and not re.match(r"^[)\]」·,.]|^(이|가|을|를|은|는|의|에|로|와|과|도|만)(\s|$)", t)) or re.search(r"[,;:]$", prev)) else ""
        out[-1] = prev + joiner + t
    return "\n".join(out)


def _format_table(block):
    """글자로 그린 표(│ ─ ┬ ┼)를 칸 단위로 다시 읽어 [[칸수, 글], ...] 행 목록으로"""
    groups, cur, has_sep = [], [], False
    for ln in block:
        if _is_border(ln):
            has_sep = True
            if cur:
                groups.append(cur)
                cur = []
        elif ln.strip():
            cur.append(ln)
    if cur:
        groups.append(cur)
    if not has_sep:                                   # 가로줄이 없으면 한 줄이 한 행
        groups = [[g] for grp in groups for g in grp]
    ncell = {len(_bars(ln)) for g in groups for ln in g}
    if len(ncell) == 1 and ncell != {0}:             # 모든 줄의 칸 수가 같으면 '몇 번째 칸'으로 맞춘다(글자 폭 계산 오차에 안전)
        n = ncell.pop()
        rows = []
        for g in groups:
            cols = [[] for _ in range(n)]
            for ln in g:
                for j, (_a, _b, t) in enumerate(_bars(ln)):
                    cols[j].append(t)
            row = [[1, _join_cell(c)] for c in cols]
            if any(t for _sp, t in row):
                rows.append(row)
        return rows
    # 전체 칸 경계(화면 칸 위치) 모으기
    allb = sorted({x for g in groups for ln in g for a, b, _t in _bars(ln) for x in (a, b)})
    if len(allb) < 3:
        return None
    idx = {x: i for i, x in enumerate(allb)}
    rows = []
    for g in groups:
        cols = {}                                       # 시작 경계 -> [끝 경계, [줄들]]
        for ln in g:
            for a, b, t in _bars(ln):
                if a not in cols:
                    cols[a] = [b, []]
                else:
                    cols[a][0] = max(cols[a][0], b) if cols[a][0] == b else cols[a][0]
                cols[a][1].append(t)
        row = []
        for a in sorted(cols):
            b, texts = cols[a]
            row.append([idx[b] - idx[a], _join_cell(texts)])
        if any(t for _sp, t in row):
            rows.append(row)
    return rows


def format_annex(raw, title=""):
    """별표 본문: 글자로 그린 표는 표로, 나머지는 번호 들여쓰기 글로. 표 한 행은 (9, JSON[[칸수,글],...])"""
    import json
    import html
    raw = [html.unescape(x) for x in raw]
    out, buf, tbl, i = [], [], [], 0
    def flush_text():
        nonlocal buf
        if buf:
            out.extend(_format_annex_text(buf, title if not out else ""))
            buf = []
    def flush_tbl():
        nonlocal tbl
        if tbl:
            nb = sum(1 for x in tbl if _is_border(x))
            rows = _format_table(tbl) if (sum(1 for x in tbl if not _is_border(x)) >= 2 or nb >= 1) else None
            if rows:
                flush_text()
                for r in rows:
                    out.append((9, json.dumps(r, ensure_ascii=False)))
            else:
                buf.extend(tbl)
            tbl = []
    for ln in raw:
        if _is_trow(ln):
            tbl.append(ln)
        elif not ln.strip() and tbl:
            continue
        else:
            flush_tbl()
            buf.append(ln)
    flush_tbl()
    flush_text()
    return out



def extract_annex(d):
    """응답 JSON 에서 별표·서식을 뽑는다 -> [{'label': '별표 1', 'kind', 'no', 'bn', 'title', 'text': [(단계, 글)], 'link', 'pdf', 'deleted'}]"""
    import html
    rows = []
    _dicts_with(d, "별표제목", rows)
    out, seen = [], set()
    for r in rows:
        kind = str(r.get("별표구분") or "별표").strip() or "별표"
        if kind not in ("별표", "서식", "별지", "도표"):
            kind = "별표" if "별표" in kind else "서식" if "서식" in kind else kind
        no, bn = _num(r.get("별표번호")), _num(r.get("별표가지번호"))
        title = html.unescape(str(r.get("별표제목") or "")).strip()
        label = "%s %d%s" % (kind, no, ("의%d" % bn) if bn else "") if no else (kind + (" " + title[:10] if title else ""))
        k = (label, title)
        if k in seen:
            continue
        seen.add(k)
        raw = []
        _raw_lines(r.get("별표내용"), raw)
        ttl = re.sub(r"^\[[^\]]*\]\s*", "", title)
        link = str(r.get("별표서식파일링크") or r.get("별표서식파일링크URL") or "")
        pdf = str(r.get("별표서식PDF파일링크") or "")
        out.append({"label": label, "kind": kind, "no": no, "bn": bn, "title": ttl, "text": format_annex(raw, title), "link": link, "pdf": pdf,
                    "deleted": ttl.strip().startswith("삭제")})
    return out


def annex_url(link):
    link = str(link or "")
    if not link:
        return ""
    return link if link.startswith("http") else "https://www.law.go.kr" + link


def load_whole(oc, mst, lawname, getter=None):
    """법령 전체를 한 번 받아 인용 관계를 계산(같은 법령일련번호는 이 실행 동안 재사용)."""
    if mst in _LAW_CACHE:
        return _LAW_CACHE[mst]
    d = _get("lawService.do", {"OC": oc, "target": "law", "type": "JSON", "MST": mst}, getter)
    units = []
    _dicts_with(d, "조문내용", units)
    if not units:
        raise LawError("법령 전체 조문을 읽지 못했습니다")
    law = analyze_units(units, lawname)
    law["annex"] = extract_annex(d)
    _LAW_CACHE[mst] = law
    return law


def refs_for(oc, mst, jo, ji, lawname, getter=None):
    """한 조문의 인용 정리 -> {'out': [(글, 조회어)], 'in': [...], 'deleg': [(글, None)]}  조회어는 법령 조문 조회 창에 그대로 넣으면 그 조문이 열린다."""
    law = load_whole(oc, mst, lawname, getter)
    a = law["arts"].get("%d:%d" % (jo, ji or 0))
    if a is None:
        raise LawError("이 조문의 인용 정보를 찾지 못했습니다")
    arts = law["arts"]
    out = []
    for r in a["out_int"]:
        f = arts[r["keys"][0]]
        out.append((r["label"], "%s %s" % (lawname, jo_label(f["n"], f["b"]))))
    for r in a["out_ext"]:
        out.append((r["label"], "%s %s" % (r["law"], jo_label(r["n"], r["b"]))))
    inn = [("%s %s" % (arts[k]["label"], arts[k]["title"]), "%s %s" % (lawname, arts[k]["label"])) for k in a["in_keys"]]
    deleg = [(("%s %s — …%s…" % (mk, kind, ctx)).strip(), None) for mk, kind, ctx in a["deleg"]]
    return {"out": out, "in": inn, "deleg": deleg}


# ───────────────────────── 본문 속 인용 위치 (화면에서 눌러 볼 수 있게) ─────────────────────────
_SUB = re.compile(r"(?:\s?제(?P<h>\d+)항(?:의(?P<h2>\d+))?)?(?:\s?제(?P<o>\d+)호(?:의(?P<o2>\d+))?)?(?:\s?(?P<m>[가나다라마바사아자차카타파하])목)?")
_EXT_O = re.compile(r"\s?(?:ㆍ|·|,|및|또는)\s?제(\d+)호(?:의(\d+))?")
_EXT_H = re.compile(r"\s?(?:ㆍ|·|,|및|또는)\s?제(\d+)항(?:의(\d+))?")
_CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟"


SAME_ART = re.compile(r"같은\s?조(?=\s?제\d+[항호]|\s?[가-하]목)")


def _extend_sub(clean, e0, sub):
    """첫 항·호 뒤에 이어진 'ㆍ제2호' · '및 제3항' 을 sub['more'] 로 모으고 끝 위치를 늘린다."""
    more = []
    if sub["o"] and not sub["m"]:
        while True:
            xm = _EXT_O.match(clean, e0)
            if not xm:
                break
            more.append({"h": sub["h"], "o": (int(xm.group(1)), int(xm.group(2) or 0)), "m": None})
            e0 = xm.end()
    elif sub["h"] and not sub["o"] and not sub["m"]:
        while True:
            xm = _EXT_H.match(clean, e0)
            if not xm:
                break
            more.append({"h": (int(xm.group(1)), int(xm.group(2) or 0)), "o": None, "m": None})
            e0 = xm.end()
    if more:
        sub["more"] = more
    return e0, sub


def cite_spans(text, selfname=""):
    """한 줄의 글에서 조문 인용 위치를 뽑는다 -> [{'start','end','law'(None=같은 법령 | 법령명),'n','b','sub'}]
    start·end 는 글 안 글자 위치(「법령명」·법 같은 앞말을 포함, 제N항·제N호·가목 같은 뒷말도 포함).
    sub 는 {'h':(항,가지)|None,'o':(호,가지)|None,'m':목|None} 또는 None. 개정 표시(<개정 …>)는 같은 길이의 공백으로 지우고 읽는다."""
    base, sfx = _split_name(selfname)
    clean = AMEND_RE.sub(lambda m: " " * len(m.group(0)), text)

    def abbr(tok):
        if tok in ("법", "이 법"):
            return None if not sfx else base
        if tok in ("영", "이 영"):
            return None if sfx == "시행령" else base + " 시행령"
        if tok == "이 규칙":
            return None if sfx == "시행규칙" else base + " 시행규칙"
        return None

    out = []
    cur, last_ext, last_end, tok_start = None, None, None, None
    for m in TOKEN.finditer(clean):
        if m.group("law"):
            cur = m.group("law").strip()
            last_ext, last_end, tok_start = cur, m.end(), m.start()
            continue
        tok = m.group("same") or m.group("abbr")
        if tok:
            if tok == "같은 법":
                cur = last_ext
            elif tok == "같은 법 시행령":
                cur = (_split_name(last_ext)[0] if last_ext else base) + " 시행령"
            else:
                cur = abbr(tok)
            if cur:
                last_ext = cur
            last_end, tok_start = m.end(), m.start()
            continue
        n, b = int(m.group("n")), int(m.group("b") or 0)
        gap = clean[last_end:m.start()] if last_end is not None else None
        ok = gap is not None and GAP_STRIP.sub("", gap) == ""
        if not ok:
            cur, tok_start = None, None
        s0 = tok_start if (ok and gap.strip() == "" and tok_start is not None) else m.start()
        sm = _SUB.match(clean, m.end())
        e0 = sm.end() if sm else m.end()
        sub = None
        if sm and (sm.group("h") or sm.group("o") or sm.group("m")):
            sub = {"h": (int(sm.group("h")), int(sm.group("h2") or 0)) if sm.group("h") else None,
                   "o": (int(sm.group("o")), int(sm.group("o2") or 0)) if sm.group("o") else None,
                   "m": sm.group("m")}
        if sub:                                           # '제1항제1호ㆍ제2호' · '제2항 및 제3항' 처럼 이어진 호·항도 함께 인용으로 잡는다
            e0, sub = _extend_sub(clean, e0, sub)
        out.append({"start": s0, "end": e0, "law": cur if ok else None, "n": n, "b": b, "sub": sub})
        last_end, tok_start = e0, None
    # '… 제11조제1항제1호ㆍ제2호, 같은 조 제2항 및 제3항' : 바로 앞 인용과 같은 조문의 항·호를 가리키는 '같은 조 …'도 인용으로 잡는다
    extra = []
    for sm0 in SAME_ART.finditer(clean):
        prev = None
        for c in out + extra:
            if c["end"] <= sm0.start():
                prev = c
        if prev is None or GAP_STRIP.sub("", clean[prev["end"]:sm0.start()]) not in ("", "에", "에서"):
            continue
        if sm0.start() - prev["end"] > 12:
            continue
        sm = _SUB.match(clean, sm0.end())
        if not sm or not (sm.group("h") or sm.group("o") or sm.group("m")):
            continue
        e0 = sm.end()
        sub = {"h": (int(sm.group("h")), int(sm.group("h2") or 0)) if sm.group("h") else None,
               "o": (int(sm.group("o")), int(sm.group("o2") or 0)) if sm.group("o") else None,
               "m": sm.group("m")}
        e0, sub = _extend_sub(clean, e0, sub)
        extra.append({"start": sm0.start(), "end": e0, "law": prev["law"], "n": prev["n"], "b": prev["b"], "sub": sub})
    if extra:
        out = sorted(out + extra, key=lambda c: c["start"])
    return out


def find_sub(lines, sub):
    """조문의 줄 목록에서 인용이 가리키는 항·호·목의 줄 범위 [시작, 끝) 를 찾는다. 못 찾으면 None."""
    if not sub:
        return None
    lo, hi = 0, len(lines)

    def scan(level, pred, lo, hi):
        for i in range(lo, hi):
            lv, t = lines[i]
            if lv == level and pred(AMEND_RE.sub("", t).strip()):
                j = i + 1
                while j < hi and lines[j][0] > level:
                    j += 1
                return i, j
        return None

    if sub.get("h"):
        n = sub["h"][0]
        if not 1 <= n <= len(_CIRC):
            return None
        r = scan(1, lambda t: t.startswith(_CIRC[n - 1]), lo, hi)
        if not r:
            return None
        lo, hi = r
    if sub.get("o"):
        n, g = sub["o"]
        pat = ("%d의%d." % (n, g)) if g else ("%d." % n)
        r = scan(2, lambda t: t.startswith(pat), lo, hi)
        if not r:
            return (lo, hi) if sub.get("h") else None
        lo, hi = r
    if sub.get("m"):
        r = scan(3, lambda t: t.startswith(sub["m"] + "."), lo, hi)
        if r:
            lo, hi = r
    return lo, hi


def expand_subs(subs):
    """인용 sub 목록(이어진 호·항 'more' 포함)을 하나씩 풀어 준다."""
    out = []
    for sb in subs or []:
        if not sb:
            continue
        out.append(sb)
        out.extend(sb.get("more") or [])
    return out


def sub_label(sb):
    """sub -> '제1항 제1호' 같은 말"""
    t = []
    if sb.get("h"):
        t.append("제%d항%s" % (sb["h"][0], ("의%d" % sb["h"][1]) if sb["h"][1] else ""))
    if sb.get("o"):
        t.append("제%d호%s" % (sb["o"][0], ("의%d" % sb["o"][1]) if sb["o"][1] else ""))
    if sb.get("m"):
        t.append("%s목" % sb["m"])
    return " ".join(t)


def cite_summary(art, subs, maxlen=34):
    """미리보기 위에 붙일 한 줄 요약. 인용한 항·호가 무엇이고 첫머리가 무엇인지: '제1항 제1호 — 광역계획권이 같은 …  |  제2호 — …'"""
    subs = expand_subs(subs)
    head = "%s %s" % (art.get("label", ""), art.get("title", ""))
    if not subs:
        return "인용  %s  (조 전체)" % head.strip()
    parts, seen = [], set()
    for sb in subs:
        r = find_sub(art["lines"], sb)
        lab = sub_label(sb)
        if not r:
            parts.append("%s — (본문에서 찾지 못함)" % lab)
            continue
        if (r[0], r[1]) in seen:
            continue
        seen.add((r[0], r[1]))
        txt = AMEND_RE.sub("", art["lines"][r[0]][1]).strip()
        txt = re.sub(r"^(?:[①-㉟]|\d+(?:의\d+)?\.|[가-힣]\.)\s*", "", txt)
        txt = re.sub(r"\s+", " ", txt)
        parts.append("%s — %s" % (lab, txt[:maxlen] + ("…" if len(txt) > maxlen else "")))
    if len(parts) > 3:
        parts = parts[:3] + ["외 %d곳" % (len(parts) - 3)]
    return "인용  %s  ▸  %s" % (head.strip(), "  |  ".join(parts))


# ───────────────────────── 지자체 조례 (자치법규) ─────────────────────────
# 법제처 Open API target=ordin: lawSearch.do(자치법규명·자치법규일련번호·지자체기관명·시행일자), lawService.do(MST) -> 조문.
# 조문 모양은 법령과 비슷해서 같은 분석(analyze_units)을 쓴다. 조문번호는 '000100'(조 4자리+가지 2자리) 꼴일 수 있어 풀어 준다.
ORDIN_NAMES = ("도시계획 조례", "도시ㆍ군계획 조례", "도시·군계획 조례", "군계획 조례", "도시관리계획 조례")
_ORDIN_BASE = (("도시계획", "국토의 계획 및 이용에 관한 법률"), ("도시ㆍ군계획", "국토의 계획 및 이용에 관한 법률"),
               ("도시·군계획", "국토의 계획 및 이용에 관한 법률"), ("군계획", "국토의 계획 및 이용에 관한 법률"),
               ("도시관리계획", "국토의 계획 및 이용에 관한 법률"), ("건축", "건축법"))


def ordin_refname(name):
    """조례 안의 '법 제77조'·'영 제84조' 가 어느 법을 가리키는지 정하기 위한 가짜 이름(시행규칙 꼴) -> 없으면 ''"""
    for kw, base in _ORDIN_BASE:
        if kw in name:
            return base + " 시행규칙"
    return ""


def parse_ordin_query(q):
    """'고양시 도시계획 조례 제55조' -> ('고양시 도시계획 조례', 55, 0). 조 번호가 없으면 jo 는 None. 띄어쓰기는 그대로 둔다."""
    q = str(q or "").strip()
    m = re.search(r"\s*제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*$", q)
    if m:
        return q[:m.start()].strip(), int(m.group(1)), int(m.group(2) or 0)
    return q, None, None


def ordin_web_url(name, jo=None, ji=0):
    path = "자치법규/" + _nospace(name)
    if jo:
        path += "/제%d조%s" % (jo, ("의%d" % ji) if ji else "")
    return "https://www.law.go.kr/" + urllib.parse.quote(path, safe="/")


ORD_WORD = re.compile(r"조례")


def ordin_spans(text, taken=()):
    """한 줄 글에서 '조례'라는 말의 위치 -> [(start, end)]. 이미 다른 인용으로 잡힌 자리(taken)와 겹치거나, 「…조례」처럼 이름이 붙은 것은 뺀다."""
    out = []
    for m in ORD_WORD.finditer(text):
        a, b = m.start(), m.end()
        if any(a < e and b > s for s, e in taken):
            continue
        out.append((a, b))
    return out


DELEGW_RE = re.compile(r"대통령령|총리령|[가-힣]{2,7}부령")


def deleg_spans(text, selfname, taken=()):
    """'대통령령으로'·'국토교통부령으로' 같은 위임 말의 위치 -> [(start, end, '시행령'|'시행규칙')].
    법 본문의 대통령령 -> 시행령, 법·시행령 본문의 총리령·부령 -> 시행규칙. 시행규칙 본문에서는 찾지 않는다."""
    base, sfx = _split_name(selfname)
    out = []
    for m in DELEGW_RE.finditer(text):
        a, b = m.start(), m.end()
        if any(a < e and b > s for s, e in taken):
            continue
        w = m.group(0)
        if w == "대통령령":
            if sfx:
                continue
            out.append((a, b, "시행령"))
        elif sfx != "시행규칙":
            out.append((a, b, "시행규칙"))
    return out


def _as_list(v):
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _delegated_targets(oc, mst, n, b, to, getter=None):
    """법제처 위임법령 조회(lsDelegated): 이 법령 제n조(의b)가 위임한 하위 법령 -> [(법령 이름, 일련번호, [조 번호…] 또는 None(모든 조문))].
    '국토교통부령으로 정한다'가 '도시ㆍ군계획시설의 결정ㆍ구조 및 설치기준에 관한 규칙'처럼 시행규칙이 아닌 별도 부령을 가리키는 경우를 잡는다."""
    try:
        d = _get("lawService.do", {"OC": oc, "target": "lsDelegated", "type": "JSON", "MST": mst}, getter)
    except Exception:  # noqa: BLE001
        return []
    rows = []
    _dicts_with(d, "위임조문정보", rows)
    items = []
    for r in rows:
        items += _as_list(r.get("위임조문정보"))
    out = {}
    for it in items:
        jo = it.get("조정보") or {}
        try:
            if int(str(jo.get("조문번호") or 0)) != n or int(str(jo.get("조문가지번호") or 0)) != (b or 0):
                continue
        except ValueError:
            continue
        for w in _as_list(it.get("위임정보")):
            if not isinstance(w, dict) or w.get("위임구분") != to or not w.get("위임법령일련번호"):
                continue
            k = (str(w.get("위임법령제목") or ""), str(w["위임법령일련번호"]))
            arts = out.setdefault(k, [])
            for x in _as_list(w.get("위임법령조문정보")):
                if not isinstance(x, dict):
                    continue
                no = str(x.get("위임법령조문번호") or "0")
                bb = str(x.get("위임법령조문가지번호") or "0")
                arts.append(None if no == "0" else (int(no), int(bb)))
    res = []
    for (nm, ms), arts in out.items():
        res.append((nm, ms, None if (not arts or None in arts) else sorted(set(arts))))
    return res


def deleg_lookup(oc, lawname, to, n, b, title="", getter=None):
    """lawname(법 또는 시행령)의 제n조(의b)를 위임받은 하위 법령(시행령·시행규칙)의 조문 -> 검색결과 꼴.
    먼저 법제처 위임법령 정보(별도 부령 포함)를 쓰고, 없으면 하위 법령 조문 중 '법 제n조'(시행규칙이면 '영 제n조')를 인용한 것, 그것도 없으면 같은 제목 낱말이 든 조문."""
    base, sfx = _split_name(lawname)
    try:
        cur = _find_cached(oc, lawname, getter)
        targets = _delegated_targets(oc, cur["mst"], n, b, to, getter)
    except LawError:
        targets = []
    if targets:
        hits, names, law0 = [], [], None
        for nm, ms, arts in targets:
            try:
                lw = load_whole(oc, ms, nm, getter)
            except Exception:  # noqa: BLE001
                continue
            lw["name"], lw["mst"] = nm, ms
            _LAW_CACHE[ms] = lw
            law0 = law0 or lw
            names.append(nm)
            for k in lw["order"]:
                a = lw["arts"][k]
                if arts is not None and (a["n"], a["b"] or 0) not in arts:
                    continue
                hits.append({"score": 100, "li": 0, "mst": ms, "lawname": nm, "key": k, "label": a["label"], "title": a["title"],
                             "n": a["n"], "b": a["b"], "short": short_law(nm), "snippet": _snippet(a["scan"], [a["label"]])})
        if hits:
            return {"hits": hits[:80], "toks": [], "total": len(hits), "searched": names,
                    "note": "%s %s 이(가) 위임한 %s" % (lawname, jo_label(n, b), " · ".join(names)), "ordname": names[0], "law": law0}
    f = _find_cached(oc, "%s %s" % (base, to), getter)
    law = load_whole(oc, f["mst"], f["name"], getter)
    cur_name = lawname
    tgt_ref = _nospace(cur_name)
    hits = []
    for li_key in law["order"]:
        a = law["arts"][li_key]
        ok = False
        for lv, line in a["lines"]:
            for sp in cite_spans(line, f["name"]):
                if sp["n"] == n and (sp["b"] or 0) == (b or 0) and sp["law"] and _nospace(sp["law"]) == tgt_ref:
                    ok = True
                    break
            if ok:
                break
        if ok:
            hits.append({"score": 100, "li": 0, "mst": f["mst"], "lawname": f["name"], "key": li_key, "label": a["label"], "title": a["title"],
                         "n": a["n"], "b": a["b"], "short": short_law(f["name"]), "snippet": _snippet(a["scan"], [jo_label(n, b)])})
    note = "%s 에서 %s 을(를) 인용한 조문" % (f["name"], jo_label(n, b))
    toks = [jo_label(n, b)]
    if not hits:
        toks = []
        for w in re.split(r"[\s·ㆍ,()]+", title or ""):
            w = re.sub(r"(에서의|에서|으로의|의)$", "", w)
            if len(w) >= 2 and w not in ("및", "경우", "기준", "관한", "대한", "관련") and w not in toks:
                toks.append(w)
        if toks:
            hits = _grep_laws([{"mst": f["mst"], "name": f["name"], "date": f.get("date", ""), "law": law}], toks, False)
            note = "%s — 인용한 조문이 없어 같은 제목 낱말로 찾았습니다" % f["name"]
    return {"hits": hits[:80], "toks": toks, "total": len(hits), "searched": [f["name"]], "note": note, "ordname": f["name"], "law": law}


# ───────────────────────── 행정규칙(지침·고시·훈령·예규) ─────────────────────────
ADM_RE = re.compile(r"(?:정하여|정하는|따로\s*정하는|정한)\s*(?:바에\s*따라\s*)?고시|고시로\s*정|훈령|예규|지침")


def adm_spans(text, taken=()):
    """'국토교통부장관이 정하여 고시한다' 같은 위임 말의 위치 -> [(start, end)]"""
    out = []
    for m in ADM_RE.finditer(text):
        a, b = m.start(), m.end()
        if any(a < e and b > s for s, e in taken):
            continue
        out.append((a, b))
    return out


def adm_web_url(name):
    return "https://www.law.go.kr/" + urllib.parse.quote("행정규칙/" + _nospace(name), safe="/")


def _adm_hit(r):
    nm = str(r.get("행정규칙명") or "").strip()
    dt = str(r.get("시행일자") or r.get("발령일자") or "")
    dt = "%s.%s.%s" % (dt[:4], dt[4:6], dt[6:8]) if len(dt) == 8 else dt
    info = " · ".join(x for x in (str(r.get("행정규칙종류") or ""), str(r.get("발령번호") or ""), ("시행 " + dt) if dt else "") if x)
    return {"score": 1, "li": 0, "mst": "a" + str(r.get("행정규칙일련번호")), "rawmst": str(r.get("행정규칙일련번호")), "lawname": nm,
            "key": "", "label": nm, "title": "", "n": 0, "b": 0, "short": str(r.get("소관부처명") or r.get("발령기관명") or "행정규칙"),
            "snippet": info, "adm": True, "date": str(r.get("시행일자") or "")}


def adm_cites(law, name, cite):
    """행정규칙 본문(분석된 law)에 cite=(법 이름, 조, 가지)를 인용한 글이 있으면 그 자리 이름('제1조(목적)')을 돌려준다. 없으면 None.
    '「국토의 계획 및 이용에 관한 법률」 제35조의2, 제40조의3 및 제40조의4'처럼 법 이름이 앞에 한 번만 나오는 열거도 읽는다."""
    cb, cn, cbb = cite
    want = _nospace(cb)
    for key in law["order"]:
        a = law["arts"][key]
        for lv, line in a["lines"]:
            for sp in cite_spans(line, name):
                if sp["n"] == cn and (sp["b"] or 0) == (cbb or 0) and (sp["law"] is None or _nospace(sp["law"]) == want):
                    return "%s%s에서 %s 인용" % (a["label"], ("(%s)" % a["title"]) if a["title"] else "", jo_label(cn, cbb))
    return None


def _verify_cites(oc, rows, cite, stems, getter):
    """후보 행정규칙들을 내려받아 실제로 그 조문을 인용하는 것만 고른다 -> [(행, 인용 자리)]. 이름이 핵심 말과 맞는 것을 먼저, 최대 24건."""
    from concurrent.futures import ThreadPoolExecutor
    def pri(it):
        nm = re.sub(r"[\sㆍ·]", "", str(it[3].get("행정규칙명") or ""))
        return (-sum(1 for w in stems if w in nm), 0 if "지침" in nm else 1, it[0])
    cand = sorted(rows, key=pri)[:24]

    def check(it):
        r = it[3]
        nm = str(r.get("행정규칙명") or "").strip()
        try:
            law = load_adm(oc, str(r.get("행정규칙일련번호")), nm, str(r.get("시행일자") or ""), getter)
            w = adm_cites(law, nm, cite)
            return (r, w) if w else None
        except Exception:  # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = [x for x in ex.map(check, cand) if x]
    return res


ADM_EXTRA = {                      # 법 이름 -> 함께 찾아볼 대표 지침(이름 검색어)
    "국토의 계획 및 이용에 관한 법률": ["지구단위계획수립지침", "도시ㆍ군관리계획수립지침", "도시ㆍ군기본계획수립지침", "개발행위허가운영지침", "도시ㆍ군계획시설"],
}
_JIM_WORDS = ("지침", "고시", "훈령", "예규")
_STOP = ("지정", "변경", "결정", "수립", "운영", "세부", "사항", "기준", "방법", "절차", "내용", "이하", "이상", "제한", "특례", "신청", "허가", "인가", "승인", "고시", "공고", "대한", "관한", "관련")


def _both_dots(q):
    return [q] if "ㆍ" not in q and "·" not in q else [q, q.replace("ㆍ", "·"), q.replace("·", "ㆍ")]


def adm_search(oc, title, lawname="", scan="", typed=None, line="", cite=None, getter=None):
    """관련 행정규칙(지침·고시·훈령·예규) 찾기 -> 검색결과 꼴(hits 의 adm=True).
    typed 가 있으면 그 낱말로, 없으면 조문 제목 낱말·본문에 자주 나오는 '○○계획/○○구역' 말·그 법의 대표 지침(수립지침 등)으로 찾는다."""
    toks = []
    src = typed if typed is not None else title
    for w in re.split(r"[\s,()]+", src or ""):
        w = re.sub(r"(에서의|에서|으로의|의)$", "", w)
        if len(w) >= 2 and w not in ("및", "경우", "기준", "관한", "대한", "관련") and w not in toks:
            toks.append(w)
    if not toks:
        raise LawError("찾을 낱말을 얻지 못했습니다")
    plain = [w for w in toks if w not in _JIM_WORDS]
    stems = []                                             # 이름에 꼭 들어 있어야 하는 핵심 말(관련 없는 지침을 걸러낸다)
    for w in plain + (re.findall(r"[가-힣ㆍ·]{2,14}(?:계획|구역|지구)", line or "") if typed is None else []):
        w = re.sub(r"[ㆍ·]", "", re.sub(r"(에서의|에서|으로의|의)$", "", w))
        w2 = re.sub(r"(계획|구역|지구|시설|사업)$", "", w)
        if len(w2) >= 2:
            w = w2
        if len(w) >= 2 and w not in _STOP and w not in stems:
            stems.append(w)
    queries = []                                           # (검색어, 검색방식 1=이름 2=본문)
    for w in plain[:3]:
        for v in _both_dots(w):
            queries += [(v + " 지침", 1), (v, 1)]
    if typed is None:
        cnt = {}
        for m in re.finditer(r"[가-힣ㆍ·]{2,14}(?:계획|구역|지구)", scan or ""):
            cnt[m.group(0)] = cnt.get(m.group(0), 0) + 1
        for w, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:3]:
            if w not in plain and not w.startswith(("이 ", "같은")):
                for v in _both_dots(w):
                    queries += [(v + " 수립지침", 1), (v + " 지침", 1)]
        base = _split_name(lawname)[0]
        for e in ADM_EXTRA.get(base, []):
            for v in _both_dots(e):
                queries.append((v, 1))
        for w in plain[:2]:
            queries.append((w, 2))
        if cite:                                            # 그 조문을 인용한 지침을 본문 검색으로도 찾아 후보에 넣는다
            cb, cn, cbb = cite
            jo = "제%d조%s" % (cn, ("의%d" % cbb) if cbb else "")
            queries += [("%s %s" % (cb, jo), 2), (jo, 2)]
    else:
        queries += [(w + " 지침", 1) for w in plain[:3]] + [(" ".join(plain), 1), (" ".join(plain), 2)]
    rows, seen = [], set()
    for k, (q, srch) in enumerate(queries):
        try:
            d = _get("lawSearch.do", {"OC": oc, "target": "admrul", "type": "JSON", "query": q, "display": 30, "search": srch}, getter)
        except Exception:  # noqa: BLE001
            continue
        got = []
        _dicts_with(d, "행정규칙명", got)
        for r in got:
            mst = str(r.get("행정규칙일련번호") or "")
            if not mst or mst in seen:
                continue
            if str(r.get("현행연혁구분") or "현행") not in ("현행", ""):
                continue
            seen.add(mst)
            rows.append((k, srch, q, r))
    all_rows = list(rows)
    verified = []
    if cite and all_rows:
        verified = _verify_cites(oc, all_rows, cite, stems, getter)
    if verified:
        hits = []
        for r, where in verified:
            h = _adm_hit(r)
            h["snippet"] = where + " · " + h["snippet"]
            hits.append(h)
        cb, cn, cbb = cite
        note = "'%s' %s 을(를) 직접 인용한 행정규칙" % (short_law(cb), jo_label(cn, cbb))
        return {"hits": hits, "toks": [jo_label(cn, cbb)], "total": len(hits), "searched": [], "note": note, "ordname": "행정규칙"}
    if stems:
        rows = [it for it in rows if any(w in re.sub(r"[\sㆍ·]", "", str(it[3].get("행정규칙명") or "")) for w in stems)]
    if not rows:
        raise LawError("'%s' 와(과) 직접 관련된 행정규칙(지침·고시)을 찾지 못했습니다.\n위쪽 검색창에 '○○ 지침' 처럼 이름을 직접 넣어 보세요." % " ".join(stems or toks))
    allw = plain + [w for w in re.findall(r"[가-힣]{2,}", " ".join(q for q, _ in queries)) if w not in plain]

    def rank(item):
        k, srch, q, r = item
        nm = re.sub(r"[\sㆍ·]", "", str(r.get("행정규칙명") or ""))
        hit = sum(1 for w in set(allw + stems) if re.sub(r"[ㆍ·]", "", w) in nm) + 3 * sum(1 for w in stems if w in nm)
        return (-hit, 0 if "수립지침" in nm else 1 if "지침" in nm else 2, srch, k)
    rows.sort(key=rank)
    hits = [_adm_hit(r) for k, srch, q, r in rows[:40]]
    return {"hits": hits, "toks": toks, "total": len(hits), "searched": [], "note": "행정규칙(지침·고시·훈령·예규) — 조문 인용은 확인하지 못해 이름이 비슷한 것만 보여 줍니다", "ordname": "행정규칙"}


_HANG_CH = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_MOK_CH = "가나다라마바사아자차카타파하"
_MARK = re.compile(r"(?P<h>[①-⑳])|\((?P<p>\d{1,2})\)|(?<![0-9-])(?P<o>\d{1,2})\.(?=\s*[^\s\d.])|(?<![가-힣0-9])(?P<m>[가나다라마바사아자차카타파하])\.(?=[\s「『(])|(?P<m2>[가나다라마바사아자차카타파하])\.(?=[\s「『(])")


_REF_NOSP = re.compile(r"^(?:[,·)]|(?:의|과|와|및|또는|부터|까지|에도|에서|에|을|를|은|는|이|가|로|으로|도|만|중)(?=[\s,.)·]|$))")
_REF_SP = re.compile(r"^\s*(?:[,·]|(?:의|과|와|및|또는|부터|까지)(?=[\s,.)·]|$))")


def _is_ref_marker(text, start, end, plen=1):
    """①②(원숫자)·(n)이 새 항의 머리가 아니라 다른 조항을 가리키는 말('3-2-3(4)①의 규정', '①, ②의 경우')인지"""
    before, after = text[:start], text[end:]
    if re.search(r"\d-\d+(?:\(\d{1,2}\))?$", before):                   # 번호 인용 바로 뒤에 붙음
        return True
    if after[:1] and not after[:1].isspace():
        return bool(_REF_NOSP.match(after))
    return bool(_REF_SP.match(after))


def split_flat_article(text):
    """한 줄로 이어 붙은 행정규칙 조문('① … ② … 1. … 2. … 가. …')을 항·호·목으로 나눈다.
    번호가 차례대로 이어지는 것만(항 ①②…, 호 1.2.…, 목 가.나.…) 표지로 받아들여 '제35조의2.' 같은 우연한 글자에 속지 않는다.
    -> {'조문내용': 머리글, '항': [{'항내용','호':[{'호내용','목':[{'목내용'}]}]}]} (항 없이 호만 있으면 '호')"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    marks, hang, ho, mok, par, sub = [], 0, 1, 0, 1, 1
    paren, circ, circ_used = False, 0, False                 # (1)(2)… 밑에서 ①②… 가 새로 시작하면 그 항의 호로 본다
    for m in _MARK.finditer(text):
        if m.group("p"):                                    # (1) (2) … 도 항처럼 차례대로 이어질 때만
            if int(m.group("p")) == par and not re.search(r"\d-\d+\.$", text[:m.start()]) \
                    and not _is_ref_marker(text, m.start(), m.end()):        # '3-5-1.(1)' 같은 번호 인용 뒤의 (1)은 항이 아님
                marks.append((m.start(), "h")); par += 1; ho, mok, sub = 1, 0, 1
                paren, circ, circ_used = True, 0, False
        elif m.group("h"):
            if _is_ref_marker(text, m.start(), m.end()):    # '①, ②의 경우'·'3-2-3(4)①의 규정' 같은 인용은 항이 아님
                continue
            idx = max(_HANG_CH.find(m.group("h")), 0)
            if paren and idx == circ:                       # (n) 밑의 ①②③ -> 호
                marks.append((m.start(), "o")); circ = idx + 1; circ_used = True; mok = 0; sub = 1
            elif idx >= hang and not (paren and circ_used and idx < circ):    # ① 다음은 ②(삭제된 항이 있으면 건너뛸 수 있음)
                marks.append((m.start(), "h")); hang = idx + 1; ho, mok = 1, 0
                paren, circ, circ_used = False, 0, False
        elif m.group("o"):
            if paren and circ_used:                         # (n) 밑 ①②… 호 안의 '1. 2. 3.' 은 그 호의 목으로(차례대로 이어지고 '2.'가 뒤에 있을 때만)
                if int(m.group("o")) == sub and any(k == "o" for _, k in marks[-3:]) and not re.search(r"조의$", text[:m.start()]) \
                        and (sub > 1 or re.search(r"(?<![0-9-])2\.", text[m.end():])):
                    marks.append((m.start(), "m")); sub += 1
                continue
            if int(m.group("o")) == ho and not re.search(r"조의$", text[:m.start()]):
                marks.append((m.start(), "o")); ho += 1; mok = 0
        elif m.group("m2") and not m.group("m"):             # 앞 글자와 붙어 버린 목('지방자치단체나. 한국토지주택공사다. …'): 바로 앞이 목이고 차례가 맞을 때만
            lt = m.group("m2")
            glued = text[m.end():m.end() + 1] in "「『("                         # 마침표 바로 뒤에 공백 없이 인용부호가 붙음 = 문장 끝이 아니라 붙어 버린 목
            if marks and marks[-1][1] == "m" and _MOK_CH.find(lt) == mok and m.start() > 0 \
                    and (glued or (m.start() - marks[-1][0] <= 60 and "." not in text[marks[-1][0] + 2:m.start()])) \
                    and not (lt == "다" and text[m.start() - 1] in "하한했할되된될는있없니"):
                marks.append((m.start(), "m")); mok += 1
        else:
            last_h = max([i for i, (_, k) in enumerate(marks) if k == "h"] or [-1])
            if any(k == "o" for _, k in marks[last_h + 1:]) and _MOK_CH.find(m.group("m")) == mok:     # 목은 같은 항 안의 호 밑에서만
                marks.append((m.start(), "m")); mok += 1
    if not marks:
        return {"조문내용": text}
    cuts = [x for x, _ in marks] + [len(text)]
    head = text[:marks[0][0]].strip()
    out = {"조문내용": head}
    hangs, cur_h, cur_o = [], None, None
    for i, (pos, kind) in enumerate(marks):
        seg = text[pos:cuts[i + 1]].strip()
        if kind == "h":
            cur_h = {"항내용": seg}
            hangs.append(cur_h)
            cur_o = None
        elif kind == "o":
            if cur_h is None:
                cur_h = {"항내용": ""}
                hangs.append(cur_h)
                cur_h["_noh"] = True
            cur_o = {"호내용": seg}
            cur_h.setdefault("호", []).append(cur_o)
        elif cur_o is not None:
            cur_o.setdefault("목", []).append({"목내용": seg})
        elif cur_h is not None:                                 # 호가 없는 자리의 목은 앞 글에 이어 붙임
            cur_h["항내용"] = (cur_h["항내용"] + " " + seg).strip()
    if len(hangs) == 1 and hangs[0].get("_noh"):
        out["호"] = hangs[0].get("호", [])
    else:
        for h in hangs:
            h.pop("_noh", None)
        out["항"] = hangs
    return out


def _safe_split(text):
    """항·호·목 나누기가 어떤 글에서든 지침 전체를 못 열게 만들지 않도록: 실패하면 그 조문은 통째로 한 덩어리로 둔다"""
    try:
        return split_flat_article(text)
    except Exception:  # noqa: BLE001
        return {"조문내용": re.sub(r"\s+", " ", str(text or "")).strip()}


_DOC_HEAD = re.compile(r"제(?P<n>\d{1,2})(?P<k>편|장|절)\s+(?!(?:및|에|의|과|또는|부터|까지|등|중|을|를|은|는|이|가|으로|에서|이나|와)\b)")
_DOC_CODE = re.compile(r"(?<![\d-])(?P<c>\d{1,2}(?:-\d{1,2}){1,3})\.(?!\d)")


def parse_doc_flat(text):
    """'제1편 총 칙제1장 지침의 목적1-1-1. … 1-1-2. …'처럼 조(제N조) 없이 편·장·절과 '1-1-1.' 번호로 짜인 지침을 나눈다.
    -> (units, labels): 편·장·절 제목은 전문(제목 줄), '1-1-1.' 하나하나는 한 건(조문)으로, 그 안의 (1)·①·1.·가.는 항·호·목으로.
    labels 는 조문 건마다 보여 줄 이름('1-1-1'). 나눌 것이 거의 없으면 None."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    heads = list(_DOC_HEAD.finditer(text))
    codes = list(_DOC_CODE.finditer(text))
    starts = sorted([m.start() for m in heads] + [m.start() for m in codes])
    import bisect

    def gap(end):                                           # 이 표지 끝에서 다음 표지(제목·번호)까지의 글자 수 = 제목이라면 제목 길이
        i = bisect.bisect_left(starts, end)
        return (starts[i] if i < len(starts) else len(text)) - end

    ev, seq = [], {"편": 0, "장": 0, "절": 0}
    last = None
    cand = sorted([(m.start(), 0, m) for m in heads] + [(m.start(), 1, m) for m in codes], key=lambda x: (x[0], x[1]))
    for _, is_code, m in cand:                              # 제목과 번호를 글에 나온 순서대로 보며, 지금 어느 장·절 안인지를 기준으로 판단한다
        if not is_code:
            k, n = m.group("k"), int(m.group("n"))
            # 진짜 제목은 번호가 꼭 '앞 번호+1'(장이 바뀌면 절은 1)이고, 제목이 짧으며(<=50자), 문장 중간의 '법 제4장 제4절 제49조…' 같은 인용이 아니다
            ok = (n == seq[k] + 1) and gap(m.end()) <= 50
            if ok and re.match(r"\s*제\d", text[m.end():m.end() + 6]) and gap(m.end()) > 20:
                ok = False
            if ok:
                seq[k] = n
                if k == "편":
                    seq["장"] = 0; seq["절"] = 0
                elif k == "장":
                    seq["절"] = 0
                ev.append((m.start(), m.end(), "head", "제%d%s" % (n, k)))
            continue
        t = tuple(int(x) for x in m.group("c").split("-"))
        if len(t) == 3:
            if re.match(r"\s*(?:과|와|의|에|을|를|은|는|및|또는|이나)(?:\s|$)", text[m.end():m.end() + 4]):
                continue                                    # '1-2-1. 과 같다' 같은 인용
            a, b, c = t
            if seq["장"] > 0 and a == seq["장"] and (seq["절"] == 0 or b == seq["절"]):     # 지금 장·절의 번호('4장 1절' 안이면 4-1-N)
                if last is not None and last[:2] == (a, b):
                    if not 0 < c - last[2] <= 20:
                        continue
                elif c > 3:
                    continue
            elif last is not None:                           # 제목을 못 읽은 곳: 앞 번호의 다음 번호일 때만
                la, lb, lc = last
                if not ((a == la and b == lb and 0 < c - lc <= 20) or (a == la and 0 < b - lb <= 3 and c <= 2) or (a - la == 1 and b == 1 and c <= 2)):
                    continue
            last = t
        ev.append((m.start(), m.end(), "code", m.group("c")))
    ev.sort()
    if sum(1 for e in ev if e[2] == "code") < 2:
        return None
    # 편·장·절 제목: 제목 글자 앞쪽 40자, 다음 사건 앞까지
    units, labels = [], []
    pre = text[:ev[0][0]].strip()
    nxt = lambda i: ev[i + 1][0] if i + 1 < len(ev) else len(text)
    if pre:
        units.append({"조문번호": "0", "조문여부": "전문", "조문내용": pre[:60]})
    n = 0
    for i, (a, b, kind, val) in enumerate(ev):
        seg = text[b:nxt(i)].strip()
        if kind == "head":
            title = seg[:40].strip()
            rest = seg[40:].strip()
            units.append({"조문번호": "0", "조문여부": "전문", "조문내용": "%s %s" % (val, title)})
            if rest:
                n += 1
                d = _safe_split(rest)
                d.update({"조문번호": str(n), "조문여부": "조문", "조문제목": rest[:16]})
                units.append(d); labels.append("")
        else:
            n += 1
            d = _safe_split(seg)
            d["조문내용"] = "%s. %s" % (val, d.get("조문내용", "")) if d.get("조문내용") else "%s." % val
            d.update({"조문번호": str(n), "조문여부": "조문", "조문제목": (seg[:16]).strip()})
            units.append(d); labels.append(val)
    return units, labels


def family_search(oc, q, getter=None):
    """'건축법'처럼 법 이름을 치면 법·시행령·시행규칙과 관련 행정규칙(지침)을 한 목록으로 -> 검색결과 꼴(첫 항목이 법). 법을 못 찾으면 None."""
    names, rest = split_query(q)
    if names and not rest:
        base = _split_name(names[0])[0]
    else:
        try:
            base = _split_name(find_law(oc, q.strip(), getter)["name"])[0]
        except LawError:
            return None
    hits = []
    for sfx in ("", "시행령", "시행규칙"):
        nm = base + ((" " + sfx) if sfx else "")
        try:
            f = _find_cached(oc, nm, getter)
        except LawError:
            continue
        dt = f.get("date", "")
        hits.append({"score": 1, "li": 0, "mst": f["mst"], "rawmst": f["mst"], "lawname": f["name"], "key": "", "label": f["name"], "title": "", "n": 0, "b": 0,
                     "short": "법령 · " + (sfx or "법"), "snippet": ("시행 %s.%s.%s" % (dt[:4], dt[4:6], dt[6:8])) if len(dt) == 8 else "", "kind": "law", "date": dt, "adm": False,
                     "_rank": (0, 0, len(hits))})
    if not hits:
        return None
    keys = {re.sub(r"[\sㆍ·]", "", x) for x in (q, base)}
    seen = set()
    for qq in [q.strip(), base] + ADM_EXTRA.get(base, [])[:4]:
        try:
            d = _get("lawSearch.do", {"OC": oc, "target": "admrul", "type": "JSON", "query": qq, "display": 30}, getter)
        except Exception:  # noqa: BLE001
            continue
        rows = []
        _dicts_with(d, "행정규칙명", rows)
        for r in rows:
            nm = str(r.get("행정규칙명") or "").strip()
            mst = str(r.get("행정규칙일련번호") or "")
            n = re.sub(r"[\sㆍ·]", "", nm)
            if not mst or mst in seen or str(r.get("현행연혁구분") or "현행") not in ("현행", ""):
                continue
            extra = qq in ADM_EXTRA.get(base, [])
            if extra:
                if re.sub(r"[\sㆍ·]", "", qq) not in n:
                    continue
            elif not any(k in n for k in keys):
                continue
            seen.add(mst)
            h = _adm_hit(r)
            h["short"] = "행정규칙 · " + str(r.get("소관부처명") or r.get("발령기관명") or "")
            h["kind"] = "adm"
            h["_rank"] = (1, 2, len(n))
            hits.append(h)
    return {"hits": hits[:40], "toks": [x for x in re.split(r"\s+", q.strip()) if x], "total": len(hits), "searched": [], "note": "%s — 법·시행령·시행규칙·지침" % short_law(base), "ordname": "이름"}


def name_search(oc, q, getter=None):
    """이름으로 법령·행정규칙·자치법규를 한꺼번에 찾는다 -> 검색결과 꼴(hit['kind'] = law | adm | ordin). 낱말이 모두 들어간 이름만, 이름이 같은 것을 맨 위로."""
    from concurrent.futures import ThreadPoolExecutor
    toks = [x for x in re.split(r"[\s,]+", str(q or "").strip()) if x]
    if not toks:
        raise LawError("찾을 이름을 넣어 주세요")
    norm = lambda x: re.sub(r"[\sㆍ·]", "", x)
    nt = [norm(t) for t in toks]

    def run(target, keyname):
        try:
            d = _get("lawSearch.do", {"OC": oc, "target": target, "type": "JSON", "query": q, "display": 30}, getter)
        except Exception:  # noqa: BLE001
            return []
        rows = []
        _dicts_with(d, keyname, rows)
        return rows
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_law = ex.submit(run, "law", "법령명한글")
        f_ord = ex.submit(run, "ordin", "자치법규명")
        f_adm = ex.submit(run, "admrul", "행정규칙명")
        r_law, r_ord, r_adm = f_law.result(), f_ord.result(), f_adm.result()
    hits = []

    def add(kind, nm, mst, short, info, date):
        n = norm(re.sub(r"\[[^\]]*\]", "", nm))
        if not nm or not mst or not all(t in n for t in nt):
            return
        rank = 0 if n == "".join(nt) else 1
        hits.append({"score": 1, "li": 0, "mst": ("a" if kind == "adm" else "o" if kind == "ordin" else "") + mst, "rawmst": mst, "lawname": nm.strip(),
                     "key": "", "label": nm.strip(), "title": "", "n": 0, "b": 0, "short": short, "snippet": info, "kind": kind, "date": date,
                     "adm": kind == "adm", "_rank": (rank, {"law": 0, "ordin": 1, "adm": 2}[kind], len(n))})
    seen = set()
    for r in r_law:
        if str(r.get("현행연혁코드") or "현행") not in ("현행", ""):
            continue
        m = str(r.get("법령일련번호") or "")
        if m in seen:
            continue
        seen.add(m)
        dt = str(r.get("시행일자") or "")
        add("law", str(r.get("법령명한글") or ""), m, "법령 · " + str(r.get("소관부처명") or ""), ("시행 %s.%s.%s" % (dt[:4], dt[4:6], dt[6:8])) if len(dt) == 8 else "", dt)
    for r in r_ord:
        dt = str(r.get("시행일자") or "")
        if dt.startswith("9999"):
            continue
        add("ordin", str(r.get("자치법규명") or ""), str(r.get("자치법규일련번호") or ""), "자치법규 · " + str(r.get("지자체기관명") or ""),
            ("시행 %s.%s.%s" % (dt[:4], dt[4:6], dt[6:8])) if len(dt) == 8 else "", dt)
    for r in r_adm:
        if str(r.get("현행연혁구분") or "현행") not in ("현행", ""):
            continue
        dt = str(r.get("시행일자") or r.get("발령일자") or "")
        info = " · ".join(x for x in (str(r.get("행정규칙종류") or ""), str(r.get("발령번호") or ""), ("시행 %s.%s.%s" % (dt[:4], dt[4:6], dt[6:8])) if len(dt) == 8 else "") if x)
        add("adm", str(r.get("행정규칙명") or ""), str(r.get("행정규칙일련번호") or ""), "행정규칙 · " + str(r.get("소관부처명") or r.get("발령기관명") or ""), info, str(r.get("시행일자") or ""))
    hits.sort(key=lambda h: h["_rank"])
    return {"hits": hits[:60], "toks": toks, "total": len(hits), "searched": [], "note": "법령·행정규칙·자치법규 이름", "ordname": "이름"}


def load_adm(oc, mst, name, date="", getter=None):
    """행정규칙 한 건을 받아 법령과 같은 구조로 분석"""
    k = "a" + str(mst)
    if k in _LAW_CACHE:
        return _LAW_CACHE[k]
    d = _get("lawService.do", {"OC": oc, "target": "admrul", "type": "JSON", "ID": mst}, getter)
    holders = []
    _dicts_with(d, "조문내용", holders)
    lines = []
    for h in holders:
        _lines(h.get("조문내용"), lines)
    if not lines:
        d = _get("lawService.do", {"OC": oc, "target": "admrul", "type": "JSON", "MST": mst}, getter)
        holders = []
        _dicts_with(d, "조문내용", holders)
        for h in holders:
            _lines(h.get("조문내용"), lines)
    if not lines:
        raise LawError("행정규칙 본문을 읽지 못했습니다 — 응답 구조: " + _shape(d))
    units, cur = [], None
    art_re = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(([^)]*)\))?")
    for ln in lines:
        m = art_re.match(ln)
        if m:
            cur = {"조문번호": m.group(1), "조문여부": "조문", "조문제목": m.group(3) or "", "조문내용": [ln]}
            if m.group(2):
                cur["조문가지번호"] = m.group(2)
            units.append(cur)
        elif re.match(r"^제\s*\d+\s*(장|절|편)", ln) and len(ln) < 60:
            units.append({"조문번호": "0", "조문여부": "전문", "조문내용": ln})
            cur = None
        elif cur is not None:
            cur["조문내용"].append(ln)
        else:
            units.append({"조문번호": "0", "조문여부": "전문", "조문내용": ln})
    labels = None
    if not any(u["조문여부"] == "조문" for u in units):        # 조 구분이 없는 지침: 편·장·절과 '1-1-1.' 번호로 나누고, 안 되면 통째로 한 건
        doc = parse_doc_flat(" ".join(lines))
        if doc:
            units, labels = doc
        else:
            units = [{"조문번호": "1", "조문여부": "조문", "조문제목": "전문", "조문내용": lines}]
    for u in units:
        if u.get("조문여부") == "조문" and isinstance(u.get("조문내용"), list):
            u.update(_safe_split(" ".join(u["조문내용"])))
    m_law = re.search(r"「([^」]{3,60}?)」", " ".join(lines))                 # 지침 속 '법'·'영'은 그 지침이 근거로 삼는 법령을 가리킨다
    ref = (_split_name(m_law.group(1))[0] + " 시행규칙") if m_law else name
    law = analyze_units(units, ref)
    for a_ in law["arts"].values():                                           # 지침의 조문 번호(1-1-1 …)는 법령 조 번호와 무관하므로 안쪽 연결은 끈다
        a_["out_int"], a_["in_keys"] = [], []
    if labels:
        for key, lab in zip(law["order"], labels):
            if lab:
                law["arts"][key]["label"] = lab
    law["kind"], law["refname"], law["date"] = "adm", ref, date
    law["name"], law["mst"] = name, k
    law["annex"] = extract_annex(d)
    _LAW_CACHE[k] = law
    return law


def ordin_lookup(oc, city, toks, getter=None):
    """그 시·군 조례에서 toks(낱말)가 들어간 조문을 찾는다 -> {'hits','toks','note','ordname'}"""
    o = _try_city_ordin(oc, city, getter)
    if not o:
        raise LawError("'%s' 도시계획 조례를 찾지 못했습니다(설정의 기본 자치단체를 확인하세요)\n" % city + "\n".join(LAST_ORD_ERR[-3:]))
    laws = [{"mst": o["mst"], "name": o["name"], "date": o["date"], "law": o["law"]}]
    hits = _grep_laws(laws, toks, False)
    for h in hits:
        h["ord"] = True
    return {"hits": hits[:80], "toks": toks, "total": len(hits), "searched": [o["name"]], "note": o["name"], "ordname": o["name"]}


def find_ordin(oc, name, getter=None, exact=False):
    """조례 이름 -> {'mst','name','date','org'}. 이름이 같은 것을 먼저, 없으면 낱말이 모두 들어간 것 중 가장 짧은 이름·최신 시행일."""
    d = _get("lawSearch.do", {"OC": oc, "target": "ordin", "type": "JSON", "query": name, "display": 50}, getter)
    rows = []
    _dicts_with(d, "자치법규명", rows)
    want = _nospace(name)
    toks = [_nospace(x) for x in re.split(r"\s+", name.strip()) if x]
    best = None
    for r in rows:
        nm = _nospace(re.sub(r"\[[^\]]*\]", "", str(r.get("자치법규명") or "")))
        date = str(r.get("시행일자") or "")
        mst = str(r.get("자치법규일련번호") or "")
        if not nm or not mst or date.startswith("9999"):
            continue
        if nm == want:
            rank = 0
        elif not exact and all(t in nm for t in toks):
            rank = 1
        else:
            continue
        key = (rank, len(nm), "".join(chr(0x10FFFF - ord(c)) for c in date))          # 같으면 시행일 최신
        if best is None or key < best[0]:
            best = (key, {"mst": mst, "name": str(r.get("자치법규명")).strip(), "date": date, "org": str(r.get("지자체기관명") or "")})
    if best is None:
        raise LawError("'%s' 조례를 찾지 못했습니다" % name)
    return best[1]


def _first(v):
    """응답 값이 ['000100', '000100'] 처럼 목록으로 오기도 한다 -> 첫 번째 값(글자)"""
    if isinstance(v, list):
        for x in v:
            x = _first(x)
            if x not in (None, ""):
                return x
        return ""
    return v


def _norm_ordin_unit(u):
    u = dict(u)
    for k in ("조문번호", "조문가지번호", "조문여부", "조제목", "조문제목"):
        if k in u:
            u[k] = _first(u[k])
    no = str(u.get("조문번호") or "").strip()
    if len(no) == 6 and no.isdigit():
        n, b = int(no[:4]), int(no[4:])
    else:
        n, b = _num(no), _num(u.get("조문가지번호"))
    c = u.get("조문내용")
    txt = " ".join(str(x) for x in c) if isinstance(c, list) else str(c or "")
    mj = re.match(r"\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", txt)
    if mj:                                              # 조 번호는 글자('제12조의2(…)')가 가장 믿을 만하다
        n, b = int(mj.group(1)), int(mj.group(2) or 0)
    u["조문번호"] = str(n)
    if b:
        u["조문가지번호"] = str(b)
    yn = str(u.get("조문여부") or "").strip()
    if re.match(r"\s*제\s*\d+\s*[편장절관](?!\S*조)", txt) and not re.match(r"\s*제\s*\d+\s*조", txt):
        u["조문여부"] = "전문"                              # '제1장 총칙' 같은 제목 줄
    elif re.match(r"\s*제\s*\d+\s*조", txt):
        u["조문여부"] = "조문"
    else:
        u["조문여부"] = "전문" if yn in ("N", "전문", "장", "절", "편", "관") else "조문"
    return u


def _walk_units(o, out):
    """자치법규 응답에서 조문 건을 나온 순서대로 모은다. 제목 줄('조문내용')과 조문 줄('조내용')이 이름을 섞어 쓰더라도 둘 다 읽는다."""
    if isinstance(o, dict):
        if "조문내용" in o or "조내용" in o:
            u = dict(o)
            c = u.get("조문내용")
            if c in (None, "", []):
                c = u.get("조내용")
            u["조문내용"] = c
            if "조문제목" not in u and u.get("조제목") is not None:
                u["조문제목"] = u.get("조제목")
            out.append(u)
            return
        for v in o.values():
            _walk_units(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_units(v, out)


def _shape(o, depth=0):
    """응답 JSON의 뼈대(키 이름)를 짧게 적는다(오류 기록용)."""
    if depth > 4:
        return "…"
    if isinstance(o, dict):
        return "{" + ", ".join("%s:%s" % (k, _shape(v, depth + 1)) for k, v in list(o.items())[:14]) + "}"
    if isinstance(o, list):
        return "[%d개 " % len(o) + (_shape(o[0], depth + 1) if o else "") + "]"
    return type(o).__name__ if not isinstance(o, str) else "'%s'" % o[:12]


def load_ordin(oc, mst, name, getter=None):
    """조례 전체를 받아 법령과 같은 구조로 분석(같은 일련번호는 이 실행 동안 재사용)."""
    k = "o" + str(mst)
    if k in _LAW_CACHE:
        return _LAW_CACHE[k]
    d = _get("lawService.do", {"OC": oc, "target": "ordin", "type": "JSON", "MST": mst}, getter)
    units = []
    _walk_units(d, units)
    if not units:
        raise LawError("조례 조문을 읽지 못했습니다 — 응답 구조: " + _shape(d))
    ref = ordin_refname(name)
    nu = [_norm_ordin_unit(u) for u in units]
    law = analyze_units(nu, ref or name)
    if not law["order"]:                                # 제목만 읽히고 조문이 하나도 없으면 구조를 못 맞춘 것 — 구조를 알려 준다
        raise LawError("조례 조문을 하나도 읽지 못했습니다 — 응답 구조: " + _shape(d) + " | 첫 건: " + _shape(units[0]))
    for a_ in law["arts"].values():                    # 한 덩어리 글로 온 조례 조문: 줄 머리의 번호로 항(①)·호(1.)·목(가.) 들여쓰기 단계를 매김
        ln = a_["lines"]
        if len(ln) > 1 and all(lv == 0 for lv, _ in ln):
            a_["lines"] = [ln[0]] + [((1 if re.match(r"^[①-⑳]|^\(\d+\)", t) else 2 if re.match(r"^\d+(?:의\d+)?\.\s", t) else 3 if re.match(r"^[가나다라마바사아자차카타파하]\.\s", t)
                                       else 4 if re.match(r"^\d+\)\s|^[가나다라마바사아자차카타파하]\)\s", t) else 0), t) for lv, t in ln[1:]]
    law["kind"], law["refname"] = "ordin", ref
    law["annex"] = extract_annex(d)
    _LAW_CACHE[k] = law
    return law


# ───────────────────────── 키워드 검색 (법령명을 몰라도 키워드로 관련 조문을 찾는다) ─────────────────────────
# 검색어 하나로 세 가지를 구분한다.
#   "국토계획법 시행령 71조"        -> 조문 직접 조회(기존)
#   "국토계획법"                    -> 법제처 화면 열기(기존)
#   "지구단위계획 용적률 완화"      -> 키워드 검색: 아래 범위의 법령 조문 전체에서 찾아 목록으로
#   "국토계획법 시행령 용적률"      -> 그 법령(·시행령·시행규칙) 안에서만 키워드 검색
# 범위: 설정 law_scope(법령 이름 목록)이 있으면 그것, 없으면 DEFAULT_SCOPE. 범위에서 하나도 못 찾으면 법제처 본문검색으로 후보 법령을 넓혀 다시 찾는다.
DEFAULT_SCOPE = [
    "국토의 계획 및 이용에 관한 법률", "국토의 계획 및 이용에 관한 법률 시행령", "국토의 계획 및 이용에 관한 법률 시행규칙",
    "개발제한구역의 지정 및 관리에 관한 특별조치법", "개발제한구역의 지정 및 관리에 관한 특별조치법 시행령",
    "건축법", "건축법 시행령",
]
_FIND_CACHE = {}
_SHORT = {}
for _k, _v in ALIASES.items():                       # 법 이름 -> 가장 먼저 등록된 약칭(국토계획법 등)
    _SHORT.setdefault(_v, _k)


def split_query(q):
    """'국토계획법 시행령 용적률 완화' -> (['국토의 계획 및 이용에 관한 법률 시행령'], ['용적률', '완화']).
    앞부분이 법 약칭이면 그 법령으로 범위를 좁히고(시행령·시행규칙을 붙이면 그것만), 아니면 (None, 낱말들)."""
    toks = [x for x in re.split(r"[\s,]+", str(q or "").strip()) if x]
    for k in range(min(len(toks), 6), 0, -1):
        base = _nospace("".join(toks[:k]))
        sfx = ""
        for s in SUFFIXES:
            if base.endswith(s):
                base, sfx = base[:-len(s)], s
                break
        full = ALIASES.get(base)
        if full:
            rest = toks[k:]
            if not sfx and rest and rest[0] in SUFFIXES:
                sfx, rest = rest[0], rest[1:]
            names = [full + " " + sfx] if sfx else [full, full + " 시행령", full + " 시행규칙"]
            return names, rest
    return None, toks


def query_kind(q):
    """'art'(조문 직접) · 'law'(법령만) · 'kw'(키워드 검색) · 'empty'"""
    t = _nospace(q)
    if not t:
        return "empty"
    if re.search(r"제?\d+조", t):
        return "art"
    names, kw = split_query(q)
    if kw:
        return "kw"
    return "law" if names else "empty"


def short_law(lawname):
    base, sfx = _split_name(lawname)
    return _SHORT.get(base, base) + ((" " + sfx) if sfx else "")


def _find_cached(oc, name, getter):
    k = _nospace(name)
    if k not in _FIND_CACHE:
        _FIND_CACHE[k] = find_law(oc, name, getter)
    return _FIND_CACHE[k]


def body_candidates(oc, kw, getter=None, limit=5, search=2):
    """법제처 검색으로 키워드가 들어 있는 현행 법령 후보. search=2 는 본문검색, 1 은 법령명 검색"""
    prm = {"OC": oc, "target": "law", "type": "JSON", "query": kw, "display": 20}
    if search == 2:
        prm["search"] = 2
    d = _get("lawSearch.do", prm, getter)
    rows, out = [], []
    _dicts_with(d, "법령명한글", rows)
    for r in rows:
        cur = str(r.get("현행연혁코드") or "")
        if r.get("법령일련번호") and (not cur or "현행" in cur):
            out.append({"mst": str(r["법령일련번호"]), "name": str(r["법령명한글"]), "date": str(r.get("시행일자") or "")})
        if len(out) >= limit:
            break
    return out


def _snippet(body, toks, width=56):
    body = re.sub(r"\s+", " ", AMEND_RE.sub("", body))
    for tk in toks:
        i = body.find(tk)
        if i >= 0:
            s = max(0, i - width)
            return ("…" if s else "") + body[s:i + len(tk) + width].strip() + "…"
    return body[:width * 2].strip()


def _score(a, toks, need_all):
    head = a["label"] + " " + a["title"]
    score, miss = 0, 0
    for tk in toks:
        c = a["scan"].count(tk)
        t = tk in head
        if not c and not t:
            miss += 1
            continue
        score += (6 if t else 0) + min(c, 5)
    if score == 0 or (need_all and miss):
        return 0
    return score - miss          # 낱말이 덜 들어간 조문은 뒤로


def _grep_laws(laws, toks, need_all):
    hits = []
    for li, lw in enumerate(laws):
        for key in lw["law"]["order"]:
            a = lw["law"]["arts"][key]
            sc = _score(a, toks, need_all)
            if sc > 0:
                hits.append({"score": sc, "li": li, "mst": lw["mst"], "lawname": lw["name"], "key": key,
                             "label": a["label"], "title": a["title"], "n": a["n"], "b": a["b"],
                             "short": short_law(lw["name"]), "snippet": _snippet(a["scan"], toks)})
    hits.sort(key=lambda h: (-h["score"], h["li"], h["n"], h["b"]))
    return hits


def _load_candidate(oc, c, getter):
    try:
        return {"mst": c["mst"], "name": c["name"], "date": c["date"], "law": load_whole(oc, c["mst"], c["name"], getter)}
    except Exception:  # noqa: BLE001
        return None


_CITY_ORD = {}


LAST_ORD_ERR = []


def _try_city_ordin(oc, city, getter):
    """그 시·군의 도시계획 조례를 찾아 내려받는다 -> {'mst','name','date','law','ordin':True} 또는 None (못 찾은 까닭은 LAST_ORD_ERR)"""
    if _CITY_ORD.get(city):
        return _CITY_ORD[city]
    del LAST_ORD_ERR[:]
    out = None
    names = ["%s %s" % (city, nm) for nm in ORDIN_NAMES] + ["%s 계획 조례" % city]
    for k, full in enumerate(names):
        try:
            f = find_ordin(oc, full, getter, exact=(k < len(ORDIN_NAMES)))
            out = {"mst": "o" + f["mst"], "rawmst": f["mst"], "name": f["name"], "date": f["date"], "ordin": True,
                   "law": load_ordin(oc, f["mst"], f["name"], getter)}
            break
        except LawError as e:
            LAST_ORD_ERR.append("%s: %s" % (full, e))
        except Exception as e:  # noqa: BLE001
            LAST_ORD_ERR.append("%s: %s %s" % (full, type(e).__name__, e))
            if len(LAST_ORD_ERR) >= 2 and "조문" not in str(e):
                break
    if out:
        _CITY_ORD[city] = out                 # 실패는 저장하지 않아 다음에 다시 시도
    return out


def _adm_pool(oc, toks, bases, getter, body_limit=4):
    """키워드 검색에 함께 훑을 행정규칙 후보 -> [{'mst':'a<id>','rawmst','name','date'}]
    ① 그 법 계열의 대표 지침(ADM_EXTRA, 예: 지구단위계획수립지침) ② 법제처 행정규칙 본문검색에서 키워드가 든 현행 행정규칙 상위."""
    from concurrent.futures import ThreadPoolExecutor
    norm = lambda x: re.sub(r"[\sㆍ·]", "", x)
    jobs = []
    for base in bases:
        for nm in ADM_EXTRA.get(base, []):
            if nm.endswith("지침"):
                jobs.append(("name", nm))
    for kw in sorted(toks, key=len, reverse=True)[:2]:
        jobs.append(("body", kw))

    def run(job):
        kind, q = job
        out = []
        for qq in (_both_dots(q) if kind == "name" else [q]):
            try:
                prm = {"OC": oc, "target": "admrul", "type": "JSON", "query": qq, "display": 20 if kind == "name" else 10}
                if kind == "body":
                    prm["search"] = 2
                d = _get("lawSearch.do", prm, getter)
            except Exception:  # noqa: BLE001
                continue
            rows = []
            _dicts_with(d, "행정규칙명", rows)
            for r in rows:
                if str(r.get("현행연혁구분") or "현행") not in ("현행", "") or not r.get("행정규칙일련번호"):
                    continue
                if kind == "name" and norm(str(r.get("행정규칙명") or "")) != norm(q):
                    continue
                out.append(r)
                if kind == "name":
                    return out[:1]
                if len(out) >= body_limit:
                    return out
        return out

    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(run, jobs))
    cands, seen = [], set()
    for rows in res:
        for r in rows:
            mst = str(r["행정규칙일련번호"])
            if mst in seen:
                continue
            seen.add(mst)
            cands.append({"mst": "a" + mst, "rawmst": mst, "name": str(r.get("행정규칙명") or "").strip(), "date": str(r.get("시행일자") or "")})
    return cands[:8]


def _load_adm_candidate(oc, c, getter):
    try:
        return {"mst": c["mst"], "rawmst": c["rawmst"], "name": c["name"], "date": c["date"], "adm": True,
                "law": load_adm(oc, c["rawmst"], c["name"], c["date"], getter)}
    except Exception:  # noqa: BLE001
        return None


def keyword_search(oc, q, scope=None, getter=None, limit=80, wide=True, city=""):
    """키워드로 관련 조문 찾기 -> {'hits': [...], 'searched': [법령 이름…], 'note': 안내 글, ...}
    wide=True 이면 기본 범위 밖에서도 그 키워드가 들어 있는 법령(법제처 법령명·본문검색 상위)을 함께 찾아 합친다(hit['ext']=True)."""
    from concurrent.futures import ThreadPoolExecutor
    names, toks = split_query(q)
    explicit = names is not None
    if not toks:
        raise LawError("찾을 키워드를 넣어 주세요. 예) 지구단위계획 용적률 완화")
    scope_names = names or list(scope or DEFAULT_SCOPE)
    laws, skipped, first_err = [], [], None

    def scope_load(nm):
        try:
            f = _find_cached(oc, nm, getter)
            return ("ok", {"mst": f["mst"], "name": f["name"], "date": f["date"], "law": load_whole(oc, f["mst"], f["name"], getter)})
        except LawError:
            return ("skip", nm)
        except Exception as e:  # noqa: BLE001                 # 접속·응답 오류: 그 법령만 건너뛰고 나머지로 계속(하나도 못 받았을 때만 오류로)
            return ("err", nm, e)
    with ThreadPoolExecutor(max_workers=6) as ex:               # 여러 법령을 한꺼번에 받는다
        for r in ex.map(scope_load, scope_names):
            if r[0] == "ok":
                laws.append(r[1])
            else:
                skipped.append(r[1])
                if r[0] == "err":
                    first_err = first_err or r[2]
    if not laws and first_err is not None:
        raise first_err
    note = ""
    ext_names = []
    ord_msts = set()
    if not explicit:                                           # 지자체 조례: 기본 자치단체(설정)와 검색어 속 시·군 이름
        cities = []
        for tk in toks:
            if re.match(r"^[가-힣]{2,4}[시군]$", tk) and tk not in ("도시", "특별시", "광역시", "농촌", "시가", "지구", "구역") and tk not in cities:
                cities.append(tk)
        ctoks = []
        for cname in cities:
            o = _try_city_ordin(oc, cname, getter)
            if o:
                ctoks.append(cname)
                laws.append(o)
                ord_msts.add(o["mst"])
        if ctoks:
            toks = [x for x in toks if x not in ctoks] or toks
        if city and city not in cities:
            o = _try_city_ordin(oc, city, getter)
            if o and o["mst"] not in ord_msts:
                laws.append(o)
                ord_msts.add(o["mst"])
    if not explicit:
        probe = _grep_laws(laws, toks, True)
        if wide or not probe:                                  # 범위 밖 법령까지 넓혀 찾기
            seen = {x["mst"] for x in laws}
            cands = []
            phrase = "".join(toks) if len(toks) > 1 else ""            # '산지 전용' -> '산지전용' 으로도 찾는다(붙여 쓴 말이 법령명·본문에 흔함)
            jobs = [(phrase, s2, 6) for s2 in (1, 2)] if phrase else []
            jobs += [(kw, srch, lim) for kw in sorted(toks, key=len, reverse=True)[:2] for srch, lim in ((1, 12), (2, 6))]

            def cand_job(j):
                try:
                    return body_candidates(oc, j[0], getter, limit=j[2], search=j[1])
                except Exception:  # noqa: BLE001
                    return []
            with ThreadPoolExecutor(max_workers=4) as ex:
                for cs in ex.map(cand_job, jobs):
                    for c in cs:
                        if c["mst"] not in seen:
                            seen.add(c["mst"])
                            cands.append(c)
            cands.sort(key=lambda c: (0 if any(t in c["name"] for t in toks) else 1, len(c["name"])))   # 법령 이름에 검색어가 든 법령을 먼저(예: 산지 -> 산지관리법)
            cands = cands[:12]
            if cands:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    extra = [x for x in ex.map(lambda c: _load_candidate(oc, c, getter), cands) if x]
                ext_names = [x["name"] for x in extra]
                laws += extra
    adm_msts = set()
    if not explicit:                                           # 행정규칙(지침·고시·훈령)도 함께 훑는다
        try:
            acands = _adm_pool(oc, toks, [_split_name(n)[0] for n in scope_names], getter)
            if acands:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    aex = [x for x in ex.map(lambda c: _load_adm_candidate(oc, c, getter), acands) if x]
                laws += aex
                adm_msts = {x["mst"] for x in aex}
        except Exception:  # noqa: BLE001
            pass
    ext_set = set(x["mst"] for x in laws if x["name"] in ext_names)
    hits = _grep_laws(laws, toks, True)
    if not hits and len(toks) > 1:
        hits = _grep_laws(laws, toks, False)
        if hits:
            note = "낱말을 모두 포함한 조문이 없어, 일부만 포함한 조문을 보여 드립니다."
    for h in hits:
        h["ord"] = h["mst"] in ord_msts
        h["adm"] = h["mst"] in adm_msts
        h["ext"] = h["mst"] in ext_set and not h["ord"] and not h["adm"]
        if h["adm"]:
            h["rawmst"] = h["mst"][1:]
            h["short"] = h["lawname"]
    if len(hits) > limit:                                      # 조문이 많아도 지침 결과는 따로 몇 건 남김
        tail = [h for h in hits[limit:] if h["adm"]][:10]
        hits = hits[:limit] + tail
        limit += len(tail)
    if first_err is not None and skipped:
        note = (note + " · " if note else "") + "일부 법령(%s)은 법제처 응답 오류로 받지 못해 빠졌습니다 — 잠시 뒤 다시 검색해 보세요" % ", ".join(short_law(x) for x in skipped[:3])
    ext_found = sorted({h["lawname"] for h in hits if h["ext"]})
    if ext_found:
        note = (note + " · " if note else "") + "기본 범위 밖 법령도 함께 찾았습니다(%s)" % ", ".join(short_law(x) for x in ext_found[:4]) + (" 외" if len(ext_found) > 4 else "")
    for lw in laws:
        lw["law"]["name"], lw["law"]["mst"], lw["law"]["date"] = lw["name"], lw["mst"], lw["date"]
    adms = sorted({h["lawname"] for h in hits if h["adm"]})
    if adms:
        note = (note + " · " if note else "") + "행정규칙(지침) 포함(%s)" % ", ".join(adms[:3]) + (" 외" if len(adms) > 3 else "")
    ords = sorted({h["lawname"] for h in hits if h["ord"]})
    if ords:
        note = (note + " · " if note else "") + "지자체 조례 포함(%s)" % ", ".join(ords)
    return {"hits": hits[:limit], "total": len(hits), "searched": [x["name"] for x in laws], "skipped": skipped, "note": note, "toks": toks}


def article_view(mst, key, lawname):
    """키워드 검색 결과 한 건 -> 조문 조회 결과와 같은 모양의 dict(이미 받아 둔 법령에서 꺼내므로 접속하지 않는다)"""
    law = _LAW_CACHE[mst]
    a = law["arts"][key]
    text = "\n".join(("   " * max(lv - 1, 0)) + t for lv, t in a["lines"])
    p = parse_query("%s %s" % (lawname, a["label"]))
    return {"p": p, "url": web_url(p), "text": text, "title": "%s %s" % (lawname, a["label"]), "date": law.get("date", ""),
            "mst": mst, "lawname": lawname}


# ───────────────────────── 3단 비교 (법 ↔ 시행령 ↔ 시행규칙) ─────────────────────────
_TT_CACHE = {}


def _cites_to(art, selfname, target_names, none_as=None):
    """조문 한 건이 인용하는 다른 법령 조문 -> [(법령 이름, n, b)]  (target_names 에 든 법령만)"""
    out = []
    for lv, line in art["lines"]:
        hm = HEADER_RE.match(line) if lv == 0 else None
        hdr = hm.end() if hm else 0
        for sp in cite_spans(line, selfname):
            if sp["start"] < hdr:
                continue
            lw = sp["law"] or none_as                          # 지침·조례 속 앞말 없는 '제49조'는 none_as(근거 법령)로 본다
            if lw is None:
                continue
            for nm in target_names:
                if _split_name(lw)[0] == _split_name(nm)[0] and _split_name(lw)[1] == _split_name(nm)[1]:
                    t = (nm, sp["n"], sp["b"])
                    if t not in out:
                        out.append(t)
    return out


def three_tier(oc, base, getter=None):
    """법·시행령·시행규칙을 받아 3단 비교표를 만든다.
    -> {'names': [법, 영, 규칙], 'laws': [law|None ×3], 'rows': [{'key': 법 조문 키, 'dec': [시행령 조문 키…], 'rule': [시행규칙 조문 키…]}]}
    시행령 조문은 '법 제N조'를 인용한 것, 시행규칙 조문은 '법 제N조' 또는 '영 제M조'를 인용한 것을 그 줄에 놓는다."""
    base = _split_name(base)[0]
    if base in _TT_CACHE:
        return _TT_CACHE[base]
    names = [base, base + " 시행령", base + " 시행규칙"]
    from concurrent.futures import ThreadPoolExecutor

    def one(nm):
        try:
            f = _find_cached(oc, nm, getter)
            return load_whole(oc, f["mst"], f["name"], getter), f["name"]
        except LawError:
            return None, nm
    with ThreadPoolExecutor(max_workers=3) as ex:               # 법·시행령·시행규칙을 한꺼번에 받는다
        got = list(ex.map(one, names))
    laws = [g[0] for g in got]
    names = [g[1] for g in got]
    if laws[0] is None:
        raise LawError("'%s' 법령을 찾지 못했습니다" % base)
    law0, law1, law2 = laws
    byn = {}
    for k in law0["order"]:
        a = law0["arts"][k]
        byn[(a["n"], a["b"])] = k
    dec = {k: [] for k in law0["order"]}
    rule = {k: [] for k in law0["order"]}
    dkey = {}
    if law1:
        for k in law1["order"]:
            a = law1["arts"][k]
            dkey[(a["n"], a["b"])] = k
            for _, n, b in _cites_to(a, names[1], [names[0]]):
                lk = byn.get((n, b)) or byn.get((n, 0))
                if lk and k not in dec[lk]:
                    dec[lk].append(k)
    if law2:
        for k in law2["order"]:
            a = law2["arts"][k]
            for nm, n, b in _cites_to(a, names[2], [names[0], names[1]]):
                if nm == names[0]:
                    lks = [byn.get((n, b)) or byn.get((n, 0))]
                else:
                    dk = dkey.get((n, b)) or dkey.get((n, 0))
                    lks = [lk for lk, ds in dec.items() if dk and dk in ds]
                for lk in lks:
                    if lk and k not in rule[lk]:
                        rule[lk].append(k)
    out = {"names": names, "laws": laws, "rows": [{"key": k, "dec": dec[k], "rule": rule[k]} for k in law0["order"]]}
    _TT_CACHE[base] = out
    return out


def tt_start(tt, law, key, cur_name):
    """지금 보던 조문(law 의 key)이 3단 비교표의 몇 번째 줄에 해당하는지 -> 줄 번호(없으면 0)"""
    rows = tt["rows"]
    nm = cur_name
    try:
        if law is None or key not in law["arts"]:
            return 0
        a = law["arts"][key]
        if nm == tt["names"][0]:
            return next((i for i, r in enumerate(rows) if r["key"] == key), 0)
        if nm == tt["names"][1]:
            i = next((i for i, r in enumerate(rows) if key in r["dec"]), None)
            if i is not None:
                return i
        if nm == tt["names"][2]:
            i = next((i for i, r in enumerate(rows) if key in r["rule"]), None)
            if i is not None:
                return i
        # 지침·조례처럼 다른 문서: 그 조문이 인용한 법·영·규칙 조문이 있는 첫 줄
        cites = _cites_to(a, law.get("refname") or nm, tt["names"], none_as=tt["names"][0])
        for cn, n, b in cites:
            idx = tt["names"].index(cn)
            laws = tt["laws"][idx]
            if laws is None:
                continue
            ck = "%d:%d" % (n, b)
            if ck not in laws["arts"]:
                ck = "%d:0" % n
            for i, r in enumerate(rows):
                if (idx == 0 and r["key"] == ck) or (idx == 1 and ck in r["dec"]) or (idx == 2 and ck in r["rule"]):
                    return i
    except Exception:  # noqa: BLE001
        pass
    return 0


def prefetch(oc, scope=None):
    """프로그램을 켠 뒤 뒤에서 조용히: 키워드 검색·3단 비교에 쓰는 기본 법령과 대표 지침을 미리 받아 둔다(이미 저장돼 있으면 금방 끝남)."""
    from concurrent.futures import ThreadPoolExecutor
    names = list(scope or DEFAULT_SCOPE)

    def one(nm):
        try:
            f = _find_cached(oc, nm, None)
            load_whole(oc, f["mst"], f["name"], None)
        except Exception:  # noqa: BLE001
            pass
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(one, names))
        for c in _adm_pool(oc, [], [_split_name(n)[0] for n in names], None):
            _load_adm_candidate(oc, c, None)
    except Exception:  # noqa: BLE001
        pass


# ───────────────────────── 검색창 자동완성 ─────────────────────────
_SUG_TAIL = re.compile(r"\s*제?\s*\d+\s*조.*$")


def suggest_split(q):
    """'국토계획법 시행령 71조' -> ('국토계획법', '시행령', ' 71조')  이름 부분 / 시행령·시행규칙 / 조 번호 이하."""
    q = str(q or "")
    m = _SUG_TAIL.search(q)
    tail = q[m.start():] if m else ""
    head = q[:m.start()] if m else q
    h = head.strip()
    sfx = ""
    for s in SUFFIXES:
        if _nospace(h).endswith(s):
            sfx = s
            h = re.sub(r"\s*" + s + r"\s*$", "", h)
            break
    return h.strip(), sfx, tail


def suggest_local(q, limit=8):
    """약칭·정식 이름에서 바로(접속 없이) 찾은 자동완성 -> [이름]. 앞에서부터 맞는 것을 먼저."""
    h, sfx, tail = suggest_split(q)
    nk = _nospace(h)
    if len(nk) < 2 or nk.isdigit():
        return []
    first, rest, seen = [], [], set()
    for ab, full in ALIASES.items():
        fk = _nospace(full)
        if nk in ab or nk in fk:
            if full in seen:
                continue
            seen.add(full)
            (first if (ab.startswith(nk) or fk.startswith(nk)) else rest).append(full)
    out = first + rest
    return [(n + (" " + sfx if sfx else "")) for n in out[:limit]]


def suggest_remote(oc, q, getter=None, limit=8):
    """법제처 이름 검색으로 찾은 자동완성(현행 법령 이름) -> [이름]. 시행령·시행규칙은 그렇게 쳤을 때만."""
    h, sfx, tail = suggest_split(q)
    nk = _nospace(h)
    if len(nk) < 2 or nk.isdigit():
        return []
    full = ALIASES.get(nk, h)
    d = _get("lawSearch.do", {"OC": oc, "target": "law", "type": "JSON", "query": full, "display": 20}, getter)
    rows = []
    _dicts_with(d, "법령명한글", rows)
    out, seen = [], set()
    for r in rows:
        nm = str(r.get("법령명한글") or "").strip()
        cur = str(r.get("현행연혁코드") or "")
        if not nm or nm in seen or (cur and "현행" not in cur):
            continue
        base, s2 = _split_name(nm)
        if sfx and s2 != sfx:
            continue
        if not sfx and s2:
            continue
        if nk not in _nospace(nm) and _nospace(full) not in _nospace(nm):
            continue
        seen.add(nm)
        out.append(nm)
    out.sort(key=lambda n: (0 if _nospace(n).startswith(_nospace(full)) else 1, len(n)))
    return out[:limit]


def suggest(oc, q, getter=None, limit=8):
    """자동완성 후보(약칭 풀이 먼저, 법제처 검색 결과가 뒤) -> [이름]. 조 번호가 이미 붙어 있어도 이름 부분만으로 찾는다."""
    res = suggest_local(q, limit)
    try:
        for n in suggest_remote(oc, q, getter, limit):
            if n not in res:
                res.append(n)
    except Exception:  # noqa: BLE001
        pass
    return res[:limit]
