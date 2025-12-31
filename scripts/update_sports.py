import os
import json
import datetime
import traceback
import re
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 설정값
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json'
# [수정] 404 에러를 일으킨 모델명(1.5)을 폐기하고, 
# 로그에서 작동이 검증된 기존 모델명으로 원복합니다.
MODEL_NAME = 'gemini-flash-latest'

def extract_json_content(text):
    """
    [핵심 기능]
    AI가 검색 결과를 설명하느라 잡담을 섞어 보내도,
    텍스트 내에서 JSON 객체({ ... })만 수술하듯 발라냅니다.
    """
    text = text.strip()
    # 마크다운 코드블록 제거
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    
    try:
        # 가장 바깥쪽 중괄호 찾기
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            # 잡담 제거 후 JSON 구간만 추출
            json_str = text[start_idx : end_idx + 1]
            return json.loads(json_str)
        else:
            return json.loads(text)
    except json.JSONDecodeError:
        print(f"❌ JSON 추출 실패. 원본 텍스트: {text[:200]}...")
        raise

def normalize_data(data):
    """
    [데이터 정규화]
    검색된 데이터의 키(Key)가 제각각이어도 대시보드 규격으로 강제 통일합니다.
    (NBA vs undefined 문제 및 데이터 증발 방지)
    """
    print("🔧 [Processing] 검색된 데이터 규격화(Normalization) 수행 중...")

    # 1. EPL
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5] # 최대 5개

        for item in data['epl']:
            # AI가 줄 수 있는 모든 키 확인
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Match Info"
            
            # 대시보드 호환성 (match, teams 둘 다 생성)
            item['teams'] = main_text
            item['match'] = main_text
            item['time'] = item.get('time') or item.get('score') or "Scheduled"
            
            # 로고 표시용 Home/Away 분리
            if 'vs' in main_text and (not item.get('home') or not item.get('away')):
                try:
                    parts = main_text.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except: pass

    # 2. NBA
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    nba['ranking'] = nba.get('ranking') or nba.get('rank') or "-"
    nba['record'] = nba.get('record') or "-"
    
    if 'schedule' in nba:
        # 문자열 예외 처리
        if isinstance(nba['schedule'], str):
            nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
        
        if isinstance(nba['schedule'], list):
            nba['schedule'] = nba['schedule'][:4]
            for item in nba['schedule']:
                if isinstance(item, str): item = {"match": item, "time": ""}
                
                # [NBA undefined 해결]
                # opponent, team 등 다양한 키를 체크하고 'vs'를 붙여줌
                m_text = (item.get('match') or item.get('teams') or 
                          item.get('opponent') or "vs Opponent")
                
                if 'vs' not in m_text and '@' not in m_text:
                    m_text = f"vs {m_text}"

                item['match'] = m_text
                item['teams'] = m_text
                item['time'] = item.get('time') or item.get('date') or "TBD"

    # 3. 테니스/F1 (빈 객체 생성으로 에러 방지)
    if 'tennis' not in data: data['tennis'] = {}
    t = data['tennis']
    t['match'] = t.get('match') or t.get('tournament') or "No Match Found"
    t['time'] = t.get('time') or ""

    if 'f1' not in data: data['f1'] = {}
    f = data['f1']
    f['grand_prix'] = f.get('grand_prix') or "Next GP"
    f['time'] = f.get('time') or ""
    f['circuit'] = f.get('circuit') or ""

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    # [핵심] 구글 검색 도구 정의
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    print(f"🚀 [Start] Gemini API({MODEL_NAME}) + Google Search 호출...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=7)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str} (실제 웹 검색 수행)")

    prompt = f"""
    Current Date: {today}
    
    TASK: Use Google Search to find the OFFICIAL match schedules for the following sports between {date_range_str}.
    Do NOT rely on internal knowledge. SEARCH for the real-time schedule.

    1. **EPL**: Find fixtures for this week (Round dates).
    2. **NBA**: Find Golden State Warriors schedule.
    3. **Tennis**: Find Carlos Alcaraz's next match or current tournament.
    4. **F1**: Find the next scheduled Grand Prix date and location (2026 Season).

    Output Format:
    Provide a JSON object containing the data.
    {{
        "epl": [ {{ "teams": "Home vs Away", "time": "MM.DD HH:MM" }} ],
        "nba": {{ "team": "GS Warriors", "record": "W-L", "ranking": "Rank", "schedule": [ {{ "teams": "vs Team", "time": "MM.DD HH:MM" }} ] }},
        "tennis": {{ "player": "Carlos Alcaraz", "match": "vs Opponent", "time": "MM.DD HH:MM" }},
        "f1": {{ "grand_prix": "Race Name", "time": "MM.DD HH:MM", "circuit": "Location" }}
    }}
    """

    client = genai.Client(api_key=api_key)
    
    try:
        # [핵심] JSON 강제 모드 해제 + 검색 도구 장착
        # response_mime_type을 제거하여 AI가 자유롭게 검색(Thinking)하게 함
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool], 
            )
        )
    except Exception as api_error:
        print(f"❌ API 호출 중 에러 발생: {api_error}")
        raise api_error

    if not response.text:
        raise ValueError("❌ API 응답이 비어있습니다!")

    try:
        # 1. 텍스트(잡담+JSON)에서 JSON 추출
        data = extract_json_content(response.text)
        
        # 2. 데이터 규격화 (undefined 방지)
        data = normalize_data(data)
        
        # 3. 파일 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print(f"EPL Items: {len(data.get('epl', []))}")
        print(f"NBA Schedule: {len(data.get('nba', {}).get('schedule', []))}")

    except Exception as e:
        print("❌ 처리 중 에러 발생")
        traceback.print_exc()
        raise e

if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        exit(1)
