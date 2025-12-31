import os
import json
import datetime
import traceback
import re
from google import genai
from google.genai import types # [핵심 1] 검색 도구 설정을 위한 모듈

# ---------------------------------------------------------
# 설정값
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json'
# 검색 기능을 안정적으로 지원하는 모델 사용
MODEL_NAME = 'gemini-1.5-flash-latest'

def extract_json_content(text):
    """
    [핵심 2] JSON 추출기 (Parsing)
    AI가 검색 결과를 설명하느라 앞뒤에 사족을 붙여도, 
    가장 바깥쪽 중괄호 {} 사이의 내용만 칼같이 발라냅니다.
    """
    text = text.strip()
    # 마크다운 코드블록 제거
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            text = text[start_idx : end_idx + 1]
        return json.loads(text)
    except json.JSONDecodeError:
        # 1차 실패 시, 혹시 모를 특수문자 등을 제거하고 재시도할 수도 있으나
        # 여기서는 원본 그대로 에러를 던져서 로그를 확인하게 함이 더 안전함
        return json.loads(text)

def normalize_data(data):
    """
    [핵심 3] 데이터 정규화 (Normalization)
    검색된 데이터의 키(Key) 이름이 제각각이어도,
    대시보드가 원하는 이름으로 무조건 강제 변환합니다. (undefined 방지)
    """
    print("🔧 [Processing] 검색된 데이터 규격화(Normalization) 수행 중...")

    # 1. EPL 데이터 보정
    if 'epl' in data and isinstance(data['epl'], list):
        # 화면 레이아웃을 위해 최대 5개로 제한
        data['epl'] = data['epl'][:5]

        for item in data['epl']:
            # AI가 match, teams, game 중 뭘 가져오든 다 잡음
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Match Info"
            
            # 대시보드 호환성을 위해 양쪽 키 모두 생성
            item['teams'] = main_text
            item['match'] = main_text
            
            # 시간 정보 확보
            item['time'] = item.get('time') or item.get('score') or "Scheduled"
            
            # 홈/어웨이 팀 분리 (로고 표시용)
            if 'vs' in main_text and (not item.get('home') or not item.get('away')):
                try:
                    parts = main_text.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except:
                    pass

    # 2. NBA 데이터 보정
    if 'nba' not in data:
        data['nba'] = {}
    
    nba = data['nba']
    # 랭킹/전적 호환성
    nba['ranking'] = nba.get('ranking') or nba.get('rank') or ""
    nba['record'] = nba.get('record') or ""
    
    # 스케줄 리스트 보정
    if 'schedule' in nba:
        # 리스트가 아니라 문자열로 왔을 경우 리스트로 변환
        if isinstance(nba['schedule'], str):
            nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
        
        if isinstance(nba['schedule'], list):
            nba['schedule'] = nba['schedule'][:4] # 4개 제한

            for item in nba['schedule']:
                # 리스트 안에 문자열만 있는 경우 객체로 변환
                if isinstance(item, str): 
                    item = {"match": item, "time": ""}
                
                # 키 값 통일
                m_text = item.get('match') or item.get('teams') or "vs Opponent"
                item['match'] = m_text
                item['teams'] = m_text
                item['time'] = item.get('time') or ""

    # 3. 테니스/F1 보정
    if 'tennis' in data:
        t = data['tennis']
        t['match'] = t.get('match') or t.get('tournament') or ""
        t['time'] = t.get('time') or ""

    if 'f1' in data:
        f = data['f1']
        f['grand_prix'] = f.get('grand_prix') or "Next GP"
        f['time'] = f.get('time') or ""

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    # [핵심 1 복구] 구글 검색 도구 정의
    # 이 부분이 있어야 AI가 인터넷을 검색합니다.
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    print(f"🚀 [Start] Gemini API({MODEL_NAME}) + Google Search를 호출합니다...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=7)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # 프롬프트: 검색 도구를 사용하라고 명시적으로 지시
    prompt = f"""
    Current Date: {today}
    
    TASK: Use Google Search to find the OFFICIAL match schedules for the following sports between {date_range_str}.
    Do NOT use your internal knowledge cutoff. Use the search results to find real-time data.

    1. **EPL (Premier League)**: Find fixtures for this week.
    2. **NBA**: Find schedule for Golden State Warriors.
    3. **Tennis**: Find Carlos Alcaraz's next match or current tournament status.
    4. **F1**: Find the next scheduled Grand Prix date and location (2026 Season).

    Return the result in this JSON structure:
    {{
        "epl": [ {{ "teams": "Home vs Away", "time": "MM.DD HH:MM" }} ],
        "nba": {{ "team": "GS Warriors", "record": "W-L", "ranking": "Rank", "schedule": [ {{ "teams": "vs Team", "time": "MM.DD HH:MM" }} ] }},
        "tennis": {{ "player": "Carlos Alcaraz", "match": "vs Opponent (or Tournament Name)", "time": "MM.DD HH:MM" }},
        "f1": {{ "grand_prix": "Race Name", "time": "MM.DD HH:MM", "circuit": "Location" }}
    }}
    
    IMPORTANT: Return ONLY the raw JSON object.
    """

    client = genai.Client(api_key=api_key)
    
    try:
        # [핵심 1 복구] generate_content 호출 시 tools 파라미터 전달
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool], # 검색 도구 장착
                response_mime_type="application/json" # JSON 응답 유도
            )
        )
    except Exception as api_error:
        print(f"❌ API 호출 중 에러 발생: {api_error}")
        raise api_error

    if not response.text:
        # 검색 결과가 없거나 차단되었을 수 있음
        raise ValueError("❌ API 응답이 비어있습니다! (검색 실패 가능성)")

    try:
        # 1. 안전하게 JSON 추출 (Extra data 에러 해결)
        data = extract_json_content(response.text)
        
        # 2. 데이터 정규화 (undefined 에러 해결)
        data = normalize_data(data)
        
        # 3. 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print(f"EPL Items: {len(data.get('epl', []))}")
        print(f"NBA Schedule: {len(data.get('nba', {}).get('schedule', []))}")

    except json.JSONDecodeError as e:
        print("❌ JSON 파싱 실패! AI 응답을 확인하세요.")
        print(f"Raw Response: {response.text}")
        raise e

if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc() 
        raise e
