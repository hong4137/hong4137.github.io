import os
import json
import datetime
import traceback
import re
from google import genai

# ---------------------------------------------------------
# 설정값
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json'

# [긴급 수정] 2.0-flash는 꽉 찼습니다(429).
# 리스트에 있는 'Lite(경량화)' 모델로 우회하여 트래픽 제한을 피합니다.
MODEL_NAME = 'gemini-2.0-flash-lite-preview-02-05'

def update_sports_data():
    # 1. API 키 확인
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    # 2. 날짜 범위 설정 (시차 문제 해결을 위해 앞뒤로 넉넉하게 잡음)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=2)  # 어제 경기 결과도 확인
    end_date = today + datetime.timedelta(days=8)    # 일주일 뒤까지
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 3. 프롬프트 작성
    prompt = f"""
    You are a sports data assistant. Retrieve the match schedules and results for the following period: {date_range_str}.
    
    Current Date for reference: {today}

    Please find information for these 4 categories:
    1. **English Premier League (EPL)**:
       - Focus on matches between {start_date} and {end_date}.
       - Look for recent match results (Dec 25-Jan 1) and upcoming matches.
       - Include match score if finished, or time if scheduled.
    2. **Golden State Warriors (NBA)**:
       - Find upcoming or recent games within the period.
    3. **Carlos Alcaraz (Tennis)**:
       - Find upcoming matches or recent results.
    4. **Formula 1**:
       - Find the next Grand Prix schedule (even if it is far in the future).

    IMPORTANT: Return the result ONLY as a raw JSON object. Do not use Markdown formatting (```json ... ```).
    The JSON structure must be exactly like this:
    {{
        "epl": [
            {{ "teams": "Home vs Away", "time": "MM.DD(Day) HH:MM" or "Score" }}
        ],
        "nba": {{
            "team": "GS Warriors",
            "record": "Win-Loss record (e.g. 15-15)",
            "ranking": "Conference Ranking (e.g. 3rd Pacific)",
            "recent": "vs Opponent Result (e.g. vs ORL W 120-97)",
            "schedule": [
                "vs TEAM MM.DD(Day) HH:MM",
                "vs TEAM MM.DD(Day) HH:MM"
            ]
        }},
        "tennis": {{
            "player": "Carlos Alcaraz",
            "status": "Tournament Name or 'Off-Season'",
            "match": "vs Opponent",
            "time": "MM.DD HH:MM"
        }},
        "f1": {{
            "grand_prix": "Grand Prix Name",
            "time": "MM.DD(Day) HH:MM",
            "circuit": "Circuit Name"
        }}
    }}
    """

    # 4. Gemini 클라이언트 초기화 및 호출
    client = genai.Client(api_key=api_key)
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
    except Exception as api_error:
        print(f"❌ API 호출 중 에러 발생: {api_error}")
        raise api_error

    if not response.text:
        raise ValueError("❌ API 응답이 비어있습니다!")

    # 5. 응답 데이터 전처리
    raw_text = response.text.strip()
    if "```" in raw_text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
    
    # 6. JSON 파싱 및 저장
    try:
        data = json.loads(raw_text)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print("내용 미리보기:", json.dumps(data, ensure_ascii=False)[:200], "...")

    except json.JSONDecodeError as e:
        print("❌ JSON 파싱 실패! AI가 이상한 데이터를 보냈습니다.")
        print(f"받은 데이터: {raw_text}")
        raise e

# ---------------------------------------------------------
# 메인 실행 블록
# ---------------------------------------------------------
if __name__ == "__main__":
    try:
        print("🚀 Script Start: update_sports.py is running...")
        update_sports_data()
        
    except Exception as e:
        print("\n\n")
        print("❌ [FATAL ERROR] 스크립트 실행 중 치명적인 오류 발생!")
        print(f"에러 메시지: {e}")
        print("-" * 30)
        traceback.print_exc() 
        print("-" * 30)
        raise e
