"""
update_catalysts.py - 매크로 이벤트 캘린더 자동 수집

Gemini 2.5 Flash + google_search grounding 으로 향후 7~14일간
시장 영향도 큰 매크로 이벤트를 검색·검증하여 catalysts.json 생성.

호출: python scripts/update_catalysts.py
환경변수: GEMINI_API_KEY (필수)
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pytz
import requests

KST = pytz.timezone("Asia/Seoul")
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "catalysts.json"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
)


def log(msg: str) -> None:
    ts = datetime.now(KST).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def build_prompt(today_kst: str) -> str:
    return f"""오늘은 {today_kst} (KST)입니다. 향후 7일간(이벤트가 3개 미만이면 14일까지 확장) 미국·글로벌 금융시장에 영향을 주는 confirmed major events를 웹에서 검색하여 정확히 찾으세요.

포함 카테고리:
- fed_fomc: FOMC 회의/성명, Fed 의장 발언, 잭슨홀
- economic_data: NFP, CPI, PPI, PCE, GDP, ISM PMI, 소매판매, JOLTS, 실업청구
- earnings: Mag7 (AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA) + 주요 시장 mover (JPM/BAC/NFLX 등)
- tech_conf: Apple/Google/MSFT/NVIDIA/Meta/OpenAI 컨퍼런스 + 제품 발표 (WWDC, I/O, Build, GTC, DevDay 등)
- treasury_auction: 10Y, 30Y 미국 국채 입찰만 (단기물 제외)
- geopolitical: OPEC+ 회의, G7/G20, 미중 정상회담, 잭슨홀, 다보스
- market_structure: Quad/Triple Witching, MSCI/Russell rebalance

importance 4 이상만 포함:
- 5 = 시장 전체 mover (FOMC, NFP, CPI, 빅테크 실적, 대선)
- 4 = 큰 단기 변동 (PMI, GDP, BoJ, GTC, iPhone event, OPEC+, Treasury auction 10Y/30Y)

각 이벤트 schema (모든 필드 필수, 누락 시 null):
{{
  "date": "YYYY-MM-DD",
  "title": "한글 제목 (60자 이내)",
  "category": "위 카테고리 ID 중 하나",
  "importance": 4 또는 5,
  "impact": ["VIX","yields","equities","USD","oil"] 같은 배열,
  "consensus": "+25bp" 또는 "3.2% YoY" 또는 null,
  "source_url": "공식 publisher 도메인 short URL"
}}

엄격 규칙:
1. 응답은 JSON 배열만. 코드블록(```json) 또는 설명 텍스트 절대 금지.
2. 모든 date는 {today_kst} 이후의 미래 날짜.
3. **source_url은 반드시 공식 publisher 도메인의 짧은 URL** (예: "https://www.federalreserve.gov/", "https://www.bls.gov/cpi/", "https://investor.nvidia.com/"). 절대 "vertexaisearch.cloud.google.com" 또는 검색엔진 redirect URL 사용 금지. 도메인 root 또는 짧은 path만. 최대 80자.
4. FOMC 일정은 federalreserve.gov, 거시 데이터는 bls.gov/bea.gov, earnings는 IR 페이지를 우선 참조.
5. 최대 8개 항목, 날짜 오름차순 정렬.
6. 추측·환각 금지. 확신 없으면 제외.
"""


def call_gemini_with_search(prompt: str, api_key: str) -> str | None:
    """2026-11 보강: 일시 오류(429·5xx·빈 응답)는 최대 3번 다시 시도하고,
    google_search 를 켜면 답이 여러 parts 로 쪼개져 올 수 있어 모든 text 를 이어 붙인다
    (예전엔 parts[0] 만 읽었다). 11-18·19 갱신 실패 대응."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }
    for attempt in range(1, 4):
        try:
            r = requests.post(
                f"{GEMINI_URL}?key={api_key}", json=payload, timeout=120
            )
            if r.status_code != 200:
                log(f"   ⚠️ Gemini error {r.status_code} (시도 {attempt}/3): {r.text[:200]}")
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(20 * attempt)
                    continue
                return None
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            if text.strip():
                return text
            log(f"   ⚠️ Gemini 빈 응답 (시도 {attempt}/3, finishReason={cand.get('finishReason')})")
        except Exception as ex:
            log(f"   ⚠️ Gemini exception (시도 {attempt}/3): {ex}")
        if attempt < 3:
            time.sleep(20 * attempt)
    return None


def parse_events(text: str) -> list[dict]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    # 가장 바깥 [ ... ] 추출 (greedy 으로 마지막 ]까지)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def sanitize_url(url: str | None) -> str | None:
    """grounding redirect URL을 차단하고 None 또는 공식 URL만 반환."""
    if not url or not isinstance(url, str):
        return None
    blocked = ("vertexaisearch.cloud.google.com", "google.com/url?")
    if any(b in url for b in blocked):
        return None
    if not url.startswith(("http://", "https://")):
        return None
    return url[:200]


def validate_event(ev: dict, today: str) -> bool:
    required = {"date", "title", "category", "importance"}
    if not required.issubset(ev.keys()):
        return False
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(ev["date"])):
        return False
    if ev["date"] < today:
        return False
    if ev["importance"] not in (4, 5):
        return False
    return True


def load_existing() -> dict | None:
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("❌ GEMINI_API_KEY 누락")
        return 1

    today_kst = datetime.now(KST).strftime("%Y-%m-%d (%A)")
    today_iso = datetime.now(KST).strftime("%Y-%m-%d")
    log(f"🔍 검색 시작: {today_kst}")

    raw_events = None
    for attempt in range(1, 3):
        text = call_gemini_with_search(build_prompt(today_kst), api_key)
        if not text:
            break
        try:
            raw_events = parse_events(text)
            break
        except json.JSONDecodeError as ex:
            log(f"   ⚠️ JSON 파싱 실패 (시도 {attempt}/2): {ex}")
            log(f"   응답 일부: {text[:300]}")

    if raw_events is None:
        # 새로 못 받아도 지난 일정은 지운다 — 화면에 D-0 으로 남지 않게.
        # generated_at 은 마지막 성공 시각 그대로 두어 대시보드가 '갱신 멈춤'을 보여 주게 하고,
        # 종료 코드는 실패(1)로 두어 관제실·Actions 가 실패를 알게 한다 (커밋 단계는 always 로 돈다).
        existing = load_existing() or {}
        kept = [x for x in existing.get("events", []) if str(x.get("date", "")) >= today_iso]
        if existing and len(kept) != len(existing.get("events", [])):
            existing["events"] = kept
            existing["fetch_failed"] = True
            existing["pruned_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
            OUTPUT_PATH.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"   🧹 지난 일정 정리: {len(kept)} events 유지")
        log("❌ Gemini 수집 실패. 기존 일정(지난 것 제외) 보존.")
        return 1

    for e in raw_events:
        if "source_url" in e:
            e["source_url"] = sanitize_url(e.get("source_url"))
    valid = [e for e in raw_events if validate_event(e, today_iso)]
    valid.sort(key=lambda e: e["date"])
    valid = valid[:8]

    log(f"✅ {len(valid)}/{len(raw_events)} 이벤트 검증 통과")

    output = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "events": valid,
    }
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"💾 {OUTPUT_PATH.name} 저장 완료 ({len(valid)} events)")
    for e in valid:
        log(f"   {e['date']}  [{e['importance']}]  {e['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
