"""
test_web_search.py — 스포츠 보강 세 기능을 Claude 웹 검색으로 한 번씩 직접 불러 본다 (데이터 파일은 안 바꿈).

평소 실행에서는 F1 순위(직접 fetch 실패 때만)·한국 선수(API 실패 때만)가 거의 불리지 않아서,
2026-11-20 Serper → Claude 웹 검색 교체를 실제로 확인하려고 만든 수동 시험.
호출: python scripts/test_web_search.py   (환경변수 ANTHROPIC_API_KEY)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_sports as u  # noqa: E402

key = os.environ.get("ANTHROPIC_API_KEY")
if not key:
    print("❌ ANTHROPIC_API_KEY 없음")
    sys.exit(1)

ok = 0

print("\n=== 1. F1 세션 시간 (다음 GP) ===")
gp = u.get_f1_next_race()
print("GP:", gp and gp.get("name"))
sched = u.get_f1_schedule_from_search(gp, None, key) if gp else None
print(json.dumps(sched, ensure_ascii=False, indent=1))
ok += bool(sched)

print("\n=== 2. F1 드라이버 순위 (웹 검색 경로 직접) ===")
st = u.get_f1_standings_via_web(key)
print(json.dumps(st, ensure_ascii=False, indent=1))
ok += bool(st)

print("\n=== 3. 한국 선수 다음 경기 (LAFC · 손흥민) ===")
m = u.get_korean_player_match_from_search("LAFC", None, key, "MLS")
print(json.dumps(m, ensure_ascii=False, indent=1))
ok += bool(m)

def notice(title, obj):
    # GitHub Actions 알림(annotation)은 로그인 없이 API 로 읽힌다 — 결과 확인용으로 한 줄씩 남긴다
    s = json.dumps(obj, ensure_ascii=False)[:900].replace("\n", " ")
    print(f"::notice title={title}::{s}")


notice("F1 세션 시간", sched)
notice("F1 순위", [(d.get("pos"), d.get("driver"), d.get("points")) for d in (st or []) if isinstance(d, dict)][:5])
notice("LAFC 다음 경기", m)
print(f"\n결과: {ok}/3 채워짐")
print(f"::notice title=결과::{ok}/3 채워짐")
sys.exit(0 if ok == 3 else 1)
