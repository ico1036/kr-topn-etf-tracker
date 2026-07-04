#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
압축 ETF 트래커 — 일일 수집기

경로별 소스 (루브릭 tier):
  - 네이버 etfAnalysis API (T1): 전 종목 AUM(totalNav) + Top10 구성종목. 유니버설, 차단 없음.
  - SOL 공식 PDF API (T0): SOL 2종 전량 구성종목 (soletf.com/api/etf/pds/pdf/{fund_no})
  - 네이버 자동완성 (T1): 신규 상장 감지 (ACE K방산TOP5+ 등)
  ※ KODEX/ACE 공식 API는 Cloudflare로 서버측 요청 차단 — 로컬 브라우저 세션에서 보완.

갱신 규칙:
  - 규칙 종목수 ≤ 11 → 네이버 Top10 = 전체 바스켓 → 구성종목 교체
  - 규칙 종목수 > 11 → AUM만 갱신, 구성종목은 유지(오래되면 stale 플래그)
  - 파생/합성/미상장은 AUM만
사용: python3 collect.py [--dry-run]
"""
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "data" / "universe.json"
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
DRY = "--dry-run" in sys.argv

# id → (naver_ticker, full_replace_via_naver, sol_fund_no)
CONFIG = {
    "396500": ("396500", True, None), "488080": ("488080", False, None), "0177R0": ("0177R0", False, None),
    "395160": ("395160", False, None), "0151S0": ("0151S0", True, None), "0167A0": ("0167A0", False, "211106"),
    "0093A0": ("0093A0", True, None), "0164G0": ("0164G0", False, None), "469150": ("469150", False, None),
    "471760": ("471760", False, None), "466920": ("466920", False, "211028"), "494670": ("494670", True, None),
    "0115D0": ("0115D0", True, None), "0080G0": ("0080G0", True, None), "0100K0": ("0100K0", False, None),
    "434730": ("434730", False, None), "364970": ("364970", True, None), "0000Z0": ("0000Z0", False, None),
    "365000": ("365000", True, None), "364990": ("364990", True, None), "0114X0": ("0114X0", True, None),
    "466940": ("466940", True, None), "0177X0": ("0177X0", False, None), "445290": ("445290", False, None),
    "0172Y0": ("0172Y0", False, None), "364980": ("364980", True, None), "412570": ("412570", False, None),
    "465330": ("465330", True, None), "465350": ("465350", False, None), "461950": ("461950", True, None),
    "457990": ("457990", False, None), "487240": ("487240", False, None), "0101N0": ("0101N0", False, None),
}
LISTING_WATCH = [("ACE_K방산TOP5plus", ["방산TOP5", "K방산TOP5"])]
STALE_DAYS = 5  # 구성종목 as_of가 이보다 오래되면 플래그


def fetch_json(url, ua=UA_MOBILE, timeout=20):
    # curl 사용: 로컬 샌드박스·CI 양쪽에서 가장 안정적인 경로
    out = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), "-H", f"User-Agent: {ua}", url],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def parse_eok(s):
    """'7조 3,001억' / '2,491억' → 억원 정수"""
    if not s:
        return None
    s = s.replace(",", "")
    jo = re.search(r"([\d.]+)\s*조", s)
    eok = re.search(r"(?:조\s*)?([\d.]+)\s*억", s)
    # '조' 매치에 쓰인 숫자를 '억' 파서가 재사용하지 않도록 조 이후 부분에서 억을 찾는다
    if jo:
        rest = s[jo.end():]
        eok = re.search(r"([\d.]+)\s*억", rest)
    v = (float(jo.group(1)) * 10000 if jo else 0) + (float(eok.group(1)) if eok else 0)
    v = round(v, 1)
    return v or None


def parse_pct(s):
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else None


def naver_etf(ticker):
    return fetch_json(f"https://m.stock.naver.com/api/stock/{ticker}/etfAnalysis")


def sol_constituents(fund_no):
    d = fetch_json(f"https://www.soletf.com/api/etf/pds/pdf/{fund_no}")
    work_dt = d.get("workDt", "")
    as_of = f"{work_dt[:4]}-{work_dt[4:6]}-{work_dt[6:8]}" if len(work_dt) == 8 else None
    cons = []
    for it in sorted(d.get("items", []), key=lambda x: -parse_pct(x.get("WT_DISP", "0"))):
        w = parse_pct(it.get("WT_DISP"))
        name = it.get("SEC_NM", "").strip()
        code = it.get("STOCK_CODE") or "-"
        if w is None or not name:
            continue
        cons.append({"rank": len(cons) + 1, "name": name, "code": code, "weight": w})
    return cons, as_of


def check_listing(queries):
    for q in queries:
        try:
            d = fetch_json(f"https://ac.stock.naver.com/ac?q={urllib.parse.quote(q)}&target=stock")
            for it in d.get("items", []):
                # 자동완성 항목 구조는 리스트/딕트 혼재 — 문자열화로 방산TOP5 확인
                s = json.dumps(it, ensure_ascii=False)
                if "TOP5" in s and ("방산" in s):
                    return s
        except Exception:
            pass
    return None


def main():
    db = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in db["etfs"]}
    today = date.today().isoformat()
    log, changed = [], 0

    for eid, (ticker, full_replace, sol_no) in CONFIG.items():
        e = by_id.get(eid)
        if not e:
            continue
        # 1) AUM (네이버 T1)
        try:
            d = naver_etf(ticker)
            aum = parse_eok(d.get("totalNav"))
            if aum and aum != e.get("aum_krw_eok"):
                log.append(f"{eid}: AUM {e.get('aum_krw_eok')} -> {aum}")
                e["aum_krw_eok"] = aum
                e["aum_asof"] = today
                changed += 1
            elif aum:
                e["aum_asof"] = today
        except Exception as ex:
            log.append(f"{eid}: naver 실패 {type(ex).__name__}")
            continue
        # 2) 구성종목
        try:
            if sol_no:  # SOL 전량 (T0)
                cons, as_of = sol_constituents(sol_no)
                if len(cons) >= 5:
                    e["constituents"] = cons
                    _mark_asof(e, as_of or today)
                    changed += 1
            elif full_replace:
                top10 = d.get("etfTop10MajorConstituentAssets") or []
                cons = [{"rank": i + 1, "name": t["itemName"], "code": t.get("itemCode", "-"),
                         "weight": parse_pct(t.get("etfWeight"))} for i, t in enumerate(top10)
                        if parse_pct(t.get("etfWeight"))]
                s = sum(c["weight"] for c in cons)
                if len(cons) >= 8 and 80 <= s <= 101:  # top10=전체 바스켓 검증(현금 제외로 완합 미만 허용)
                    e["constituents"] = cons
                    _mark_asof(e, today)
                    changed += 1
                else:
                    log.append(f"{eid}: top10 검증실패 n={len(cons)} sum={s:.1f} — 유지")
            else:
                _flag_stale(e, today)
        except Exception as ex:
            log.append(f"{eid}: 구성종목 실패 {type(ex).__name__}")

    # 3) 신규 상장 감지
    for eid, queries in LISTING_WATCH:
        e = by_id.get(eid)
        if e and not e.get("ticker"):
            hit = check_listing(queries)
            if hit:
                log.append(f"{eid}: 상장 감지! {hit[:120]} — 티커 수동 확정 필요")
                e["data_quality"]["invariants_failed"] = sorted(
                    set(e["data_quality"]["invariants_failed"]) | {"상장 감지됨 — 티커·구성종목 확정 필요"})
                changed += 1

    db["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if DRY:
        print("[dry-run] 변경", changed, "건")
    else:
        UNIVERSE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장 완료. 변경", changed, "건")
    for line in log:
        print(" -", line)


def _mark_asof(e, as_of):
    dq = e["data_quality"]
    dq["invariants_passed"] = sorted(
        {x for x in dq["invariants_passed"] if not x.startswith("구성종목 as_of")} | {f"구성종목 as_of {as_of}"})
    dq["invariants_failed"] = [x for x in dq["invariants_failed"] if "stale" not in x]


def _flag_stale(e, today):
    """전량 수집 경로가 없는 종목: as_of가 오래되면 stale 플래그"""
    dq = e["data_quality"]
    for x in dq["invariants_passed"]:
        m = re.match(r"구성종목 as_of (\d{4}-\d{2}-\d{2})", x)
        if m:
            age = (date.fromisoformat(today) - date.fromisoformat(m.group(1))).days
            if age > STALE_DAYS and e["constituents"]:
                dq["invariants_failed"] = sorted(
                    set(dq["invariants_failed"]) | {f"구성종목 stale({age}일) — 전량 재수집 필요(KODEX/ACE는 로컬 브라우저)"})
            return


if __name__ == "__main__":
    main()
