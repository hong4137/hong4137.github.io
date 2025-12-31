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
# [확정] 현재 가장 안정적인 모델
MODEL_NAME = 'gemini-flash-latest'

# ---------------------------------------------------------
# [핵심] 데이터 안전장치 (과거에 있던 그 '긴 코드' 복원)
# ---------------------------------------------------------
def normalize_data(data):
    """
    AI가 준 데이터가 대시보드(HTML)와 키 값이 안 맞을 경우를 대비해
    가능한 모든 변수명을 다 만들어주는 '호환성 끝판왕' 함수
    """
    print("🔧 [Processing] 데이터 규격화 작업을 수행합니다...")

    # 1. EPL 데이터 정밀 가공
    if 'epl' in data and isinstance(data['epl'], list):
        for item in data['epl']:
            # (1) 팀 이름 확보
            # match, teams, game 중 하나라도 있으면 가져옴
            raw_match = item.get('match') or item.get('teams') or item.get('game')
            
            # 만약 match 문구가 없는데 home/away가 있다면 합쳐서라도 만듦
            if not raw_match and item.get('home') and item.get('away'):
                raw_match = f"{item['home']} vs {item['away']}"
            
            if not raw_match: 
                raw_match = "Match Info Unavailable"

            # (2) 모든 키에 다 때려박기 (대시보드가 뭘 찾든 걸리게 함)
            item['teams'] = raw_match
            item['match'] = raw_match
            
            # (3) Home / Away 분리 (vs 기준으로 쪼개기)
            if 'vs' in raw_match:
                try:
                    parts = raw_match.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except:
                    item['home'] = raw_match
                    item['away'] = ""
            
            # (4) 시간/점수 확보
            raw_time = item.get('time') or item.get('score') or "Scheduled"
            item['time'] = raw_time
            item['score'] = raw_time # 호환성

    # 2. NBA 데이터 정밀 가공
    if 'nba' in data:
        nba = data['nba']
        
        # (1) 랭킹/전적 호환성
        rank = nba.get('ranking') or nba.get('rank') or ""
        record = nba.get('record') or ""
        
        nba['ranking'] = rank
        nba['rank'] = rank
        nba['record'] = record
        
        # (2) 스케줄 리스트 가공
        # 가끔 AI가 리스트가 아니라 그냥 글자(string)로 줄 때가 있음 -> 리스트로 변환
        if 'schedule' in nba and isinstance(nba['schedule'], str):
             nba['schedule'] = [{"match": nba['schedule'], "time": ""}]

        if 'schedule' in nba and isinstance(nba['schedule'], list):
            for item in nba['schedule']:
                # 리스트 안에 글자만 덜렁 있는 경우 방지 (예: ["vs LAL", "vs BOS"])
                if isinstance(item, str):
                    item = {"match": item, "time": ""}
                
                # match, teams 키 통일
                sch_match = item.get('match') or item.get('teams') or "vs Unknown"
                item['match'] = sch_match
                item['teams'] = sch_match # 대시보드가 teams를 찾을 수도 있음
                
                if not item.get('time'):
                    item['time'] = "TBD"

    # 3. 테니스/F1 데이터 보정
    if 'tennis' in data:
        t = data['tennis']
        # match 키가 없으면 만들어줌
        if not t.get('match'):
             t['match'] = t.get('tournament') or "No Match"
        if not t.get('time'):
             t['time'] = ""

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=2)
    end_date = today + datetime.timedelta(days=8)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 프롬프트: AI에게 최대한 정확하게 달라고 요청하지만, 틀려도 위 함수가 고쳐줄 것임
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules and results: {date_range_str}.
    Current Date: {today}

    IMPORTANT: Return ONLY raw JSON. No Markdown.
    
    Structure Requirements:
    
    1. **EPL**:
       - Array of objects.
       - Key 'teams': "HomeTeam vs AwayTeam" (String).
       - Key 'time': Score (if finished) or Time (e.g. "01.05 20:30").
    
    2. **NBA**:
       - 'team': "GS Warriors"
       - 'record': "Win-Loss"
       - 'ranking': "Conference Rank"
       - 'schedule': Array of objects. Each has 'teams' (e.g. "vs LAL") and 'time'.
       
    Target JSON Format:
    {{
        "epl": [
            {{ "teams": "Chelsea vs Newcastle", "time": "2-1" }},
            {{ "teams": "Man Utd vs Liverpool", "time": "01.05 20:30" }}
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
            "match": "vs Opponent",
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

    # 마크다운 제거
    raw_text = response.text.strip()
    if "```" in raw_text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
    
    try:
        # 1. JSON 파싱
        data = json.loads(raw_text)
        
        # 2. [중요] 데이터 정규화 함수 실행
        # 여기서 'undefined' 문제를 원천 차단합니다.
        data = normalize_data(data)
        
        # 3. 파일 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        
        # 로그로 데이터 확인
        print("EPL Sample Check:", json.dumps(data.get('epl', [])[:1], ensure_ascii=False))

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
