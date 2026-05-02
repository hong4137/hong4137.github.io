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
  "title": "한글 제목 (영문 보조)",
  "category": "위 카테고리 ID 중 하나",
  "importance": 4 또는 5,
  "impact": ["VIX","yields","equities","USD","oil"] 같은 배열,
  "consensus": "+25bp" 또는 "3.2% YoY" 또는 null,
  "source_url": "검증한 공식 출처 URL"
}}

엄격 규칙:
1. 응답은 JSON 배열만. 코드블록(```json) 또는 설명 텍스트 절대 금지.
2. 모든 date는 {today_kst} 이후의 미래 날짜.
3. FOMC 일정은 federalreserve.gov, 거시 데이터는 bls.gov/bea.gov, earnings는 IR 페이지를 우선 참조.
4. 최대 8개 항목, 날짜 오름차순 정렬.
5. 추측·환각 금지. 확신 없으면 제외.
"""


def call_gemini_with_search(prompt: str, api_key: str) -> str | None:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
    }
    try:
        r = requests.post(
            f"{GEMINI_URL}?key={api_key}", json=payload, timeout=90
        )
        if r.status_code != 200:
            log(f"   ⚠️ Gemini error {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    except Exception as e:
        log(f"   ⚠️ Gemini exception: {e}")
        return None


def parse_events(text: str) -> list[dict]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(0)
    return json.loads(cleaned)


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

    text = call_gemini_with_search(build_prompt(today_kst), api_key)
    if not text:
        log("❌ Gemini 호출 실패. 기존 catalysts.json 보존.")
        return 1

    try:
        raw_events = parse_events(text)
    except json.JSONDecodeError as e:
        log(f"❌ JSON 파싱 실패: {e}")
        log(f"   응답 일부: {text[:300]}")
        return 1

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
