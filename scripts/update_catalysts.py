"""
update_catalysts.py - 매크로 이벤트 캘린더 자동 수집

Claude(claude-opus-5-5) + 서버 쪽 웹 검색 도구로 향후 7~14일간
시장 영향도 큰 매크로 이벤트를 검색·검증하여 catalysts.json 생성.

2026-11-20 Gemini(gemini-2.5-flash) → Claude 로 교체 (사용자 결정).
11-18·19 Gemini 수집이 연달아 실패했고, 같은 날 투자 노트 파서(cio-parser)도
Gemini 쪽 오류로 Claude 로 옮겼다.

호출: python scripts/update_catalysts.py
환경변수: ANTHROPIC_API_KEY (필수 — GitHub 저장소 Secrets)
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import pytz

KST = pytz.timezone("Asia/Seoul")
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "catalysts.json"
MODEL = "claude-opus-5-5"


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
3. **source_url은 반드시 공식 publisher 도메인의 짧은 URL** (예: "https://www.federalreserve.gov/", "https://www.bls.gov/cpi/", "https://investor.nvidia.com/"). 검색엔진 redirect URL 사용 금지. 도메인 root 또는 짧은 path만. 최대 80자.
4. FOMC 일정은 federalreserve.gov, 거시 데이터는 bls.gov/bea.gov, earnings는 IR 페이지를 우선 참조.
5. 최대 8개 항목, 날짜 오름차순 정렬.
6. 추측·환각 금지. 확신 없으면 제외.
"""


def call_claude_with_search(prompt: str) -> str | None:
    """Claude + 웹 검색(web_search_20260209)으로 일정을 찾아 마지막 답의 text 를 돌려준다.
    429·5xx·연결 오류는 SDK 가 알아서 다시 시도한다(max_retries).
    검색이 길면 stop_reason 이 pause_turn 으로 끊겨 오므로, 받은 내용을 그대로 붙여 이어 부른다."""
    client = anthropic.Anthropic(max_retries=4, timeout=600)
    messages = [{"role": "user", "content": prompt}]
    try:
        for _ in range(6):
            with client.messages.stream(
                model=MODEL,
                max_tokens=32000,
                output_config={"effort": "medium"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 12}],
                messages=messages,
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "refusal":
                log(f"   ⚠️ Claude 거절: {getattr(resp, 'stop_details', None)}")
                return None
            # 검색 중간 설명 글이 앞쪽 text 블록에 섞일 수 있어 마지막 text 블록을 우선 쓰고,
            # JSON 배열이 없으면 전부 이어 붙인다 (parse_events 가 바깥 [ ] 를 골라낸다)
            texts = [b.text for b in resp.content if b.type == "text"]
            for t in reversed(texts):
                if "[" in t and "]" in t:
                    return t
            joined = "".join(texts)
            if joined.strip():
                return joined
            log(f"   ⚠️ Claude 빈 응답 (stop_reason={resp.stop_reason})")
            return None
        log("   ⚠️ Claude 검색이 끝나지 않음 (pause_turn 6회)")
    except anthropic.AuthenticationError:
        log("   ⚠️ Claude 인증 실패 — ANTHROPIC_API_KEY 확인")
    except anthropic.APIStatusError as ex:
        log(f"   ⚠️ Claude API error {ex.status_code}: {str(ex.message)[:200]}")
    except anthropic.APIConnectionError as ex:
        log(f"   ⚠️ Claude 연결 오류: {ex}")
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
    today_kst = datetime.now(KST).strftime("%Y-%m-%d (%A)")
    today_iso = datetime.now(KST).strftime("%Y-%m-%d")

    raw_events = None
    # 키가 없어도 아래 '지난 일정 정리'는 돈다
    attempts = range(1, 3) if os.environ.get("ANTHROPIC_API_KEY") else []
    if not attempts:
        log("❌ ANTHROPIC_API_KEY 누락 — GitHub 저장소 Settings → Secrets 에 등록 필요")
    else:
        log(f"🔍 검색 시작 ({MODEL}): {today_kst}")
    for attempt in attempts:
        text = call_claude_with_search(build_prompt(today_kst))
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
        log("❌ 일정 수집 실패. 기존 일정(지난 것 제외) 보존.")
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
