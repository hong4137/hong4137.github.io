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

# ---------------------------------------------------------
# [핵심] 데이터 검증 및 복구 함수 (이게 빠져서 에러가 났던 겁니다)
# ---------------------------------------------------------
def normalize_data(data):
    """
    AI가 준 데이터가 대시보드(HTML)와 안 맞을 경우를 대비해
    강제로 키 이름을 통일하고, 빈 값은 채워주는 함수
    """
    print("🔧 데이터 정규화(Normalization) 작업 시작...")

    # 1. EPL 데이터 보정
    if 'epl' in data and isinstance(data['epl'], list):
        for item in data['epl']:
            # 'teams'나 'match' 중 하나라도 있으면 가져옴
            team_text = item.get('teams') or item.get('match') or item.get('game')
            
            # 만약 둘 다 없으면 home/away를 합쳐서라도 만듦
            if not team_text and item.get('home') and item.get('away'):
                team_text = f"{item['home']} vs {item['away']}"
            
            # 그래도 없으면 기본값
            if not team_text:
                team_text = "Match Info Unavailable"

            # 대시보드가 'match'를 찾든 'teams'를 찾든 다 되게 둘 다 넣어줌
            item['teams'] = team_text
            item['match'] = team_text 
            
            # 시간/점수 확인
            if not item.get('time'):
                item['time'] = item.get('score') or "Scheduled"

    # 2. NBA 데이터 보정
    if 'nba' in data:
        nba = data['nba']
        # 'rank' vs 'ranking' 호환성 해결
        rank_val = nba.get('ranking') or nba.get('rank') or ""
        nba['ranking'] = rank_val
        nba['rank'] = rank_val  # 둘 다 넣어둠
        
        # 'schedule'이 리스트가 아니라 문자열로 왔을 경우 대비
        if 'schedule' in nba and isinstance(nba['schedule'], str):
             # AI가 가끔 리스트 대신 그냥 줄글로 줄 때가 있음 -> 리스트로 변환 시도
             nba['schedule'] = [{"match": nba['schedule'], "time": ""}]

        # 스케줄 내부 아이템 보정
        if 'schedule' in nba and isinstance(nba['schedule'], list):
            for item in nba['schedule']:
                if isinstance(item, str): # 문자열로 되어있으면 객체로 변환
                    item = {"match": item, "time": ""}
                
                # match key 보정
                match_text = item.get('match') or item.get('teams') or "vs Unknown"
                item['match'] = match_text
                item['teams'] = match_text
                
                # time key 보정
                if not item.get('time'):
                    item['time'] = "TBD"

    # 3. 테니스/F1 등 나머지 보정
    if 'tennis' in data:
        # match 키 보장
        if not data['tennis'].get('match'):
             data['tennis']['match'] = data['tennis'].get('tournament') or "No Match"

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    today = datetime.date.today()
    # 검색 범위 넉넉하게
    start_date = today - datetime.timedelta(days=2)
    end_date = today + datetime.timedelta(days=8)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 프롬프트: 최대한 JSON 포맷을 지키라고 명령
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules and results: {date_range_str}.
    Current Date: {today}

    IMPORTANT: Return ONLY raw JSON. No Markdown.
    
    Target JSON Format (Strictly follow this structure):
    {{
        "epl": [
            {{ "match": "Chelsea vs Newcastle", "time": "2-1" }},
            {{ "match": "Man Utd vs Liverpool", "time": "01.05 20:30" }}
        ],
        "nba": {{
            "team": "GS Warriors",
            "record": "18-16",
            "ranking": "#3 Pacific", 
            "recent": "vs ORL W (120-97)",
            "schedule": [
                {{ "match": "vs DAL", "time": "12.30 09:00" }},
                {{ "match": "vs PHX", "time": "01.02 11:00" }}
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
        
        # 2. [중요] 데이터 정규화 함수 실행 (여기가 핵심!)
        # AI가 준 날것의 데이터를 파이썬이 예쁘게 다듬습니다.
        data = normalize_data(data)
        
        # 3. 파일 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        
        # 결과 확인용 로그
        print("EPL Sample:", json.dumps(data.get('epl', [])[:1], ensure_ascii=False))
        print("NBA Sample:", json.dumps(data.get('nba', {}).get('schedule', [])[:1], ensure_ascii=False))

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
