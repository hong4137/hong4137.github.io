import os
import json
import datetime
import traceback
import re
from google import genai

SPORTS_FILE = 'sports.json'
MODEL_NAME = 'gemini-flash-latest'

def extract_json_content(text):
    """
    [복원된 기능 1] AI 응답에서 순수 JSON 데이터만 추출
    """
    text = text.strip()
    # 마크다운 문법 제거
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            text = text[start_idx : end_idx + 1]
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text)

def normalize_data(data):
    """
    [복원된 기능 2] 데이터 정규화 (undefined 방지)
    - AI가 준 키 값을 대시보드가 원하는 키 값으로 강제 복사
    """
    print("🔧 [Processing] 데이터 규격화(Normalization) 수행 중...")

    # 1. EPL 데이터 보정
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5] # 5개 제한

        for item in data['epl']:
            # 호환성 확보: match, teams, game 중 하나만 있어도 OK
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Match Info"
            
            # 대시보드가 뭘 찾을지 모르니 다 넣어줌 (양다리 전략)
            item['teams'] = main_text
            item['match'] = main_text
            
            # 시간 정보 확보
            item['time'] = item.get('time') or item.get('score') or ""
            
            # 로고 매핑을 위한 home/away 분리
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
    nba['ranking'] = nba.get('ranking') or nba.get('rank') or ""
    nba['record'] = nba.get('record') or ""
    
    # 스케줄 리스트 보정
    if 'schedule' in nba:
        if isinstance(nba['schedule'], str):
            nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
        
        if isinstance(nba['schedule'], list):
            nba['schedule'] = nba['schedule'][:4] # 4개 제한

            for item in nba['schedule']:
                if isinstance(item, str): 
                    item = {"match": item, "time": ""}
                
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

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=7)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # [복원된 기능 3] 문법 오류 수정 ({{ }})
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules: {date_range_str}.
    Current Date: {today}

    Structure Requirements:
    1. **EPL**: List of matches. Key 'teams' ("Home vs Away"), Key 'time' ("Score" or "MM.DD HH:MM").
    2. **NBA**: 'team': "GS Warriors", 'record': "Win-Loss", 'ranking': "Conf Rank", 'schedule': List of objects [{{'teams': 'vs LAL', 'time': '12.30 09:00'}}].
    3. **Tennis**: 'player': "Carlos Alcaraz", 'match': "vs Opponent", 'time': "MM.DD HH:MM".
    4. **F1**: 'grand_prix': "Race Name", 'time': "MM.DD HH:MM", 'circuit': "Place".

    Return ONLY raw JSON. Do not include markdown formatting.
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

    try:
        # 1. 안전하게 JSON 추출
        data = extract_json_content(response.text)
        
        # 2. 데이터 정규화 (undefined 방지)
        data = normalize_data(data)
        
        # 3. 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print(f"EPL Items: {len(data.get('epl', []))}")
        print(f"NBA Schedule: {len(data.get('nba', {}).get('schedule', []))}")

    except json.JSONDecodeError as e:
        print("❌ JSON 파싱 실패!")
        print(f"Raw Response: {response.text}")
        raise e

if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc() 
        raise e
