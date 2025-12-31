import os
import json
import datetime
import traceback
import re
from google import genai

SPORTS_FILE = 'sports.json'
MODEL_NAME = 'gemini-flash-latest'

def normalize_data(data):
    """
    1. 데이터 개수를 잘라서 레이아웃이 길어지는 것을 방지
    2. 'undefined'가 뜨지 않도록 빈 값을 기본값으로 채움
    """
    print("🔧 [Processing] 데이터 개수 제한 및 빈칸 채우기...")

    # [1] EPL 데이터 정리
    if 'epl' in data and isinstance(data['epl'], list):
        # ★ 핵심: 최대 5개까지만 보여주기 (칸 늘어남 방지)
        data['epl'] = data['epl'][:5]

        for item in data['epl']:
            # 이름표 통일 (match, teams, title 등 뭐가 와도 teams로 만듦)
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Unknown Match"
            item['teams'] = main_text
            item['match'] = main_text
            
            # 시간/점수 통일
            # 점수가 없으면 시간이라도, 시간도 없으면 "Scheduled"
            time_text = item.get('time') or item.get('score') or "Scheduled"
            item['time'] = time_text
            
            # Home/Away가 없으면 텍스트에서 쪼개서라도 만듦 (로고 표시용)
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
        
        # 기본 정보 채우기
        nba['ranking'] = nba.get('ranking') or nba.get('rank') or "-"
        nba['record'] = nba.get('record') or "-"
        
        # 스케줄 정리
        if 'schedule' in nba:
            # 리스트가 아니면 리스트로 변환
            if isinstance(nba['schedule'], str):
                nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
            
            # ★ 핵심: 스케줄도 최대 4개까지만 (칸 늘어남 방지)
            if isinstance(nba['schedule'], list):
                nba['schedule'] = nba['schedule'][:4]

                for item in nba['schedule']:
                    if isinstance(item, str):
                        item = {"match": item, "time": ""}
                    
                    # 'undefined' 원인 제거: match와 teams 양쪽에 다 값을 넣음
                    match_name = item.get('match') or item.get('teams') or "vs Upcoming"
                    item['match'] = match_name
                    item['teams'] = match_name
                    
                    # 시간이 없으면 날짜라도, 없으면 TBD
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
    # 검색 범위: 어제 ~ 6일 뒤 (너무 길게 잡지 않음)
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=6)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str}")

    prompt = f"""
    You are a sports data assistant. Retrieve match schedules: {date_range_str}.
    Current Date: {today}

    Structure Requirements:
    1. **EPL**: List of matches. Key 'teams' ("Home vs Away"), Key 'time' ("Score" or "MM.DD HH:MM").
    2. **NBA**: 'team': "GS Warriors", 'record': "Win-Loss", 'ranking': "Conf Rank", 'schedule': List of objects [{'teams': 'vs LAL', 'time': '12.30 09:00'}].
    3. **Tennis**: 'player': "Carlos Alcaraz", 'match': "vs Opponent", 'time': "MM.DD HH:MM".
    4. **F1**: 'grand_prix': "Race Name", 'time': "MM.DD HH:MM", 'circuit': "Place".

    Return ONLY raw JSON.
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
        
        # 데이터 다듬기 (개수 자르기 + 빈칸 채우기)
        data = normalize_data(data)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print("EPL(5개 제한):", len(data.get('epl', [])))

    except json.JSONDecodeError as e:
        print("❌ JSON 파싱 실패!")
        raise e

if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc() 
        raise e
