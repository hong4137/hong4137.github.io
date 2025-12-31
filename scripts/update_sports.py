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
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    today = datetime.date.today()
    # 검색 범위: 어제 ~ 7일 뒤
    start_date = today - datetime.timedelta(days=2)
    end_date = today + datetime.timedelta(days=8)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 3. 프롬프트 작성 (키 이름을 과거/현재 모두 호환되도록 요청)
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules and results: {date_range_str}.
    Current Date: {today}

    IMPORTANT: Return ONLY raw JSON. No Markdown.
    
    Structure Requirements (Compulsory for dashboard compatibility):
    
    1. **EPL**:
       - Each match object MUST have 'teams' (Full string like "Arsenal vs Brighton").
       - Also provide 'time' (Score or Time).
    
    2. **NBA**:
       - 'ranking': Conference rank (e.g. "#3 Pacific"). MUST use key 'ranking'.
       - 'record': Win-Loss (e.g. "28-7").
       - 'schedule': Array of objects. Each object must have 'teams' (e.g. "vs OKC") and 'time'.
       
    Target JSON Format:
    {{
        "epl": [
            {{ 
                "teams": "Chelsea vs Newcastle", 
                "time": "2-1" 
            }},
            {{ 
                "teams": "Man Utd vs Liverpool", 
                "time": "01.05 20:30" 
            }}
        ],
        "nba": {{
            "team": "GS Warriors",
            "record": "18-16",
            "ranking": "#3 Pacific", 
            "recent": "vs ORL W (120-97)",
            "schedule": [
                {{ "teams": "vs DAL", "time": "12.30 09:00" }},
                {{ "teams": "vs PHX", "time": "01.02 11:00" }}
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

    raw_text = response.text.strip()
    if "```" in raw_text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
    
    try:
        data = json.loads(raw_text)
        
        # [Python 후처리] 대시보드가 옛날 키('teams')를 찾을 수도 있고 새 키('match')를 찾을 수도 있음.
        # 그래서 그냥 다 만들어줌 (호환성 100% 보장)
        
        # 1. EPL 보정
        if 'epl' in data and isinstance(data['epl'], list):
            for item in data['epl']:
                # 'match'나 'teams' 중 하나만 있어도 나머지를 채워줌
                main_text = item.get('teams') or item.get('match') or "Unknown vs Unknown"
                item['teams'] = main_text  # 구버전 호환
                item['match'] = main_text  # 신버전 호환
        
        # 2. NBA 보정
        if 'nba' in data:
            nba = data['nba']
            # 'rank' vs 'ranking' 호환
            rank_text = nba.get('ranking') or nba.get('rank') or ""
            nba['ranking'] = rank_text
            nba['rank'] = rank_text
            
            # 스케줄 호환
            if 'schedule' in nba and isinstance(nba['schedule'], list):
                for item in nba['schedule']:
                    sch_text = item.get('teams') or item.get('match') or "vs Unknown"
                    item['teams'] = sch_text
                    item['match'] = sch_text

        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print("최종 데이터(EPL):", json.dumps(data.get('epl', [])[:1], ensure_ascii=False))

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
