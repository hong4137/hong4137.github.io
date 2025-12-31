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
MODEL_NAME = 'gemini-flash-latest'

def update_sports_data():
    # 1. API 키 확인
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    # 2. 날짜 범위 설정
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=2)
    end_date = today + datetime.timedelta(days=8)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 3. 프롬프트 작성 (JSON 키 이름을 대시보드 호환형으로 대폭 수정)
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules and results: {date_range_str}.
    Current Date: {today}

    IMPORTANT: Return ONLY raw JSON. No Markdown.
    
    Structure Requirements (Must match exactly to avoid 'undefined' errors):
    
    1. **EPL**:
       - Provide 'match' (Full string), 'home' (Home Team), 'away' (Away Team), and 'time' (Score or Time).
       - This ensures compatibility with any dashboard format.
    
    2. **NBA**:
       - 'rank': Conference rank (e.g. "#3 Pacific").
       - 'record': Win-Loss (e.g. "18-16").
       - 'schedule': Must be an ARRAY of OBJECTS, not strings. Each object needs 'match' and 'time'.
       
    Target JSON Format:
    {{
        "epl": [
            {{ 
                "match": "Chelsea vs Newcastle", 
                "home": "Chelsea", 
                "away": "Newcastle", 
                "time": "2-1" 
            }},
            {{ 
                "match": "Man Utd vs Liverpool", 
                "home": "Man Utd", 
                "away": "Liverpool", 
                "time": "01.05 20:30" 
            }}
        ],
        "nba": {{
            "team": "GS Warriors",
            "record": "18-16",
            "rank": "#3 Pacific", 
            "recent": "vs ORL W (120-97)",
            "schedule": [
                {{ "match": "vs DAL", "time": "12.30 09:00" }},
                {{ "match": "vs PHX", "time": "01.02 11:00" }}
            ]
        }},
        "tennis": {{
            "player": "Carlos Alcaraz",
            "status": "Off-Season / Training",
            "match": "vs Opponent (if any)",
            "time": "Date Time"
        }},
        "f1": {{
            "grand_prix": "Australian GP",
            "time": "03.08 13:00",
            "circuit": "Albert Park"
        }}
    }}
    """

    # 4. API 호출
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

    # 5. 전처리
    raw_text = response.text.strip()
    if "```" in raw_text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
    
    # 6. 저장
    try:
        data = json.loads(raw_text)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        # 디버깅을 위해 결과 일부 출력
        print("EPL Data Check:", json.dumps(data.get('epl', [])[:1], ensure_ascii=False))
        print("NBA Data Check:", json.dumps(data.get('nba', {}), ensure_ascii=False))

    except json.JSONDecodeError as e:
        print("❌ JSON 파싱 실패! AI가 이상한 데이터를 보냈습니다.")
        print(f"받은 데이터: {raw_text}")
        raise e

if __name__ == "__main__":
    try:
        print("🚀 Script Start: update_sports.py is running...")
        update_sports_data()
        
    except Exception as e:
        print("\n\n")
        print("❌ [FATAL ERROR] 스크립트 실행 중 치명적인 오류 발생!")
        print(f"에러 메시지: {e}")
        traceback.print_exc() 
        raise e
