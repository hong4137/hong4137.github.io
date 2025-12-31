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
    AI 응답에서 순수한 JSON 부분만 정밀하게 추출하는 함수
    (앞뒤에 붙은 마크다운, 공백, 사족 텍스트를 모두 제거)
    """
    try:
        # 1. 가장 먼저 나오는 '{' 찾기
        start_idx = text.find('{')
        # 2. 가장 마지막에 나오는 '}' 찾기
        end_idx = text.rfind('}')

        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            # 순수 JSON 영역만 슬라이싱
            json_str = text[start_idx : end_idx + 1]
            return json.loads(json_str)
        else:
            # 괄호를 못 찾으면 그냥 파싱 시도 (운 좋으면 될 수도)
            return json.loads(text)
    except json.JSONDecodeError:
        # 1차 실패 시, 마크다운 문법 제거 후 재시도
        clean_text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
        start_idx = clean_text.find('{')
        end_idx = clean_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            return json.loads(clean_text[start_idx : end_idx + 1])
        raise

def normalize_data(data):
    """
    데이터 개수 제한 및 'undefined' 방지용 기본값 채우기
    """
    print("🔧 [Processing] 데이터 규격화 및 빈칸 채우기...")

    # [1] EPL 데이터 정리
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5] # 최대 5개

        for item in data['epl']:
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Unknown Match"
            item['teams'] = main_text
            item['match'] = main_text
            
            time_text = item.get('time') or item.get('score') or "Scheduled"
            item['time'] = time_text
            
            if 'vs' in main_text and (not item.get('home') or not item.get('away')):
                try:
                    parts = main_text.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except:
                    pass

    # [2] NBA 데이터 정리
    if 'nba' in data:
        nba = data['nba']
        nba['ranking'] = nba.get('ranking') or nba.get('rank') or "-"
        nba['record'] = nba.get('record') or "-"
        
        if 'schedule' in nba:
            if isinstance(nba['schedule'], str):
                nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
            
            if isinstance(nba['schedule'], list):
                nba['schedule'] = nba['schedule'][:4] # 최대 4개

                for item in nba['schedule']:
                    if isinstance(item, str):
                        item = {"match": item, "time": ""}
                    
                    match_name = item.get('match') or item.get('teams') or "vs Upcoming"
                    item['match'] = match_name
                    item['teams'] = match_name
                    item['time'] = item.get('time') or item.get('date') or "TBD"

    # [3] 테니스/F1 정리
    if 'tennis' in data:
        t = data['tennis']
        t['match'] = t.get('match') or t.get('tournament') or "No Match"
        t['time'] = t.get('time') or ""
        t['status'] = t.get('status') or ""

    if 'f1' in data:
        f = data['f1']
        f['grand_prix'] = f.get('grand_prix') or f.get('name') or "Next GP"
        f['time'] = f.get('time') or ""
        f['circuit'] = f.get('circuit') or ""

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    print(f"🚀 [Start] Gemini API({MODEL_NAME})를 호출합니다...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=6)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    # (주의) f-string 안에서 중괄호는 {{ }} 두 번 써야 함
    prompt = f"""
    You are a sports data assistant. Retrieve match schedules: {date_range_str}.
    Current Date: {today}

    Structure Requirements:
    1. **EPL**: List of matches. Key 'teams' ("Home vs Away"), Key 'time' ("Score" or "MM.DD HH:MM").
    2. **NBA**: 'team': "GS Warriors", 'record': "Win-Loss", 'ranking': "Conf Rank", 'schedule': List of objects [{{'teams': 'vs LAL', 'time': '12.30 09:00'}}].
    3. **Tennis**: 'player': "Carlos Alcaraz", 'match': "vs Opponent", 'time': "MM.DD HH:MM".
    4. **F1**: 'grand_prix': "Race Name", 'time': "MM.DD HH:MM", 'circuit': "Place".

    Return ONLY raw JSON. No markdown, no commentary.
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
        # [수정됨] 단순 로드가 아니라, '{' 와 '}' 사이만 추출해서 로드
        data = extract_json_content(response.text)
        
        # 데이터 규격화 (undefined 방지 + 개수 제한)
        data = normalize_data(data)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print("EPL Items:", len(data.get('epl', [])))

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
