# kr-topn-etf-tracker

한국 상장 **압축형 TOP-N ETF**(반도체TOP10, AI반도체TOP2+, 조선TOP3+ 등)의 **리밸런싱 일정**과 **구성종목**을 수집·검증해 웹 대시보드로 보여주는 엔진.

압축형 ETF는 소수 종목에 집중되어 있어, 정기변경(리밸런싱) 시 지수 규칙에 따라 강제 매매가 발생하고 구성종목 가격에 임팩트를 준다. 이 엔진은 그 **리밸 일정과 바스켓을 한눈에 추적**하는 것을 목표로 한다.

> ⚠️ 본 저장소는 정보 제공·리서치 목적이며 **투자자문이 아니다.** 모든 수치는 출처·기준일과 함께 검증 상태를 병기한다.

## 구조

```
etf-rebal-engine/
├── web/
│   └── index.html        # 단일 파일 대시보드 (인라인 CSS/JS, data/universe.json을 fetch)
├── data/
│   └── universe.json     # 수집 데이터 (크롤러가 갱신 → 화면 자동 반영)
└── docs/
    └── RUBRIC.md         # 데이터 신뢰도 루브릭 (출처 tier · invariant · confidence)
```

## 실행

정적 서버로 열면 된다(로컬 파일 fetch 때문에 `file://` 직접 열기는 불가):

```bash
cd etf-rebal-engine
python3 -m http.server 8787
# → http://localhost:8787/web/index.html
```

## 화면

- **리밸 캘린더** — 다음 리밸일 순 정렬, D-day 배지, 일정 미확보는 하단 분리
- **ETF 전체** — 정렬·검색·테마/신뢰도 필터 테이블
- **상세 드로어** — 기본정보 · 리밸규칙 · 구성종목 · 데이터 품질(루브릭 invariant) · 출처(T0~T3 tier + 링크)

## 데이터 신뢰도 루브릭

모든 값은 4개 축으로 채점해 `High / Med / Low`로 접는다 — 자세한 정의는 [docs/RUBRIC.md](docs/RUBRIC.md).

1. **출처 권위** T0(공식원본) ~ T3(비공식)
2. **추출 방식** E0(구조화) ~ E3(규칙계산)
3. **도메인 정합성(invariant)** 비중합≈100%, 종목수=규칙, 리밸일>오늘 등
4. **교차검증 × 신선도** 2소스 일치, 필드별 SLA

핵심 철학: **값과 검증은 별개 상태다** — invariant를 통과해야 믿는다. 정량은 T0/T1+2소스, Low는 버리지 않고 격리해 재수집 큐로.

## 수집 현황 (2026-07-05 기준)

| 레이어 | 상태 |
|---|---|
| 유니버스 | 34종 (5대 운용사 + 한화PLUS·NH, 13개 테마) |
| 리밸 일정 | 31/34 — 지수 방법론 원문(T0) 기반, 액티브 3종은 정기변경 비적용 |
| 구성종목 | 28/34 — 운용사 공식 PDF API(T0) 위주. 나머지 6은 파생승계 4·합성 1·미상장 1 |
| 데이터 신뢰도 | **95/100** (High 30 · Med 3 · Low 0, 미상장 1종 분모 제외) |

잔여 Med 3종은 원출처가 현재 비공개인 항목(KODEX 방산TOP10 시행일 원문, Solactive China selection day) — 수집 가능한 공개 정보 기준 커버리지 100%. 해소 경로는 `rubric_scoreboard.remaining_med`에 기록.

### 확보된 T0 수집 경로 (자동화용)

- KODEX: `samsungfund.com/api/v1/kodex/product-pdf/{fId}.do?gijunYMD=YYYY.MM.DD`
- SOL: `soletf.com/api/etf/pds/pdf/{fundNo}`
- ACE: `papi.aceetf.co.kr/api/funds/{fundCd}/pdf/down`
- PLUS: `plusetf.co.kr/api/v1/product/pdf/list?n={n}`
- RISE: 상품페이지 서버렌더 표 + 네이버 `m.stock.naver.com/api/stock/{ticker}/etfAnalysis`
- FnGuide 방법론: `file.fnguide.com/fnindex/files/*.pdf` / Akros: `akrostec.com/indices/{code}` / Solactive: `solactive.com/downloads/Guideline-*.pdf`

## 분석 리포트

- [2026-07-13 AI반도체 리밸 프리뷰](analysis/2026-07-13-ai-semi-rebal-preview.md) — SOL AI반도체TOP2플러스(7.3조)·RISE AI반도체TOP10. 핵심: 삼성전기 **-8,640억(ADV 1.0일치) 강제매도** 추정, 한미반도체 편입 시 +4,380억. 선반영 리스크 병기.

## 로드맵

- [x] Round 1 — 유니버스 수집 (테마별 병렬 크롤)
- [x] Round 2 — 리밸 일정(지수 방법론 T0 파싱) + 구성종목(운용사 PDF API)
- [x] Round 3 — 갭 해소(AUM·상충 판정) + 루브릭 재채점
- [ ] 상장 후속: ACE K방산TOP5+ 티커·구성종목 (2026-07-07 상장)
- [ ] 12월 KIND 공시로 KODEX 방산TOP10 시행일 상충 해소
- [ ] 일일 자동 수집기 (위 T0 API 경로 활용)
- [ ] (v2) 리밸 예측기 — 편입/편출 예측 + 임팩트 스코어(거래대금 대비)
