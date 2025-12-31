import os
import json
import datetime
import traceback
import re
from google import genai
from google.genai import types

# ---------------------------------------------------------
# [시점 확인용] 성공 당시 설정
# 1. 모델명: gemini-flash-latest (작동 확인됨)
# 2. 검색 도구: 켜져 있음 (Tools Enabled)
# 3. JSON 강제: 꺼져 있음 (None) -> 그래서 검색이 작동함
# 4. 정규화: 단순함 (그래서 NBA undefined가 떴음)
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json'
MODEL_NAME = 'gemini-flash-latest'

def extract_json_content(text):
    text = text.strip()
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            return json.loads(text[start_idx : end_idx + 1])
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text)

def normalize_data(data):
    # [성공 당시의 단순한 정규화 로직]
    # 이때는 NBA 'vs' 강제 주입 로직이 없어서 undefined가 떴습니다.
    # 하지만 F1과 테니스 데이터는 원본 그대로 잘 통과시켰습니다.
    
    # 1. EPL
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5]
        for item in data['epl']:
            main_text = item.get('match') or item.get('teams') or "Match"
            item['teams'] = main_text
            item['match'] = main_text
            item['time'] = item.get('time') or "Scheduled"
            
            if 'vs' in main_text:
                try:
                    parts = main_text.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except: pass

    # 2. NBA (당시의 취약점: 'vs'가 없으면 undefined 발생)
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    if 'schedule' in nba and isinstance(nba['schedule'], list):
        nba['schedule'] = nba['schedule'][:4]
        for item in nba['schedule']:
            # [당시 코드] 단순히 있는 그대로 받아적음 -> undefined 원인
            m_text = item.get('match') or item.get('teams') or ""
            item['match'] = m_text
            item['teams'] = m_text
            item['time'] = item.get('time') or ""

    # 3. Tennis/F1 (당시 코드: 별도 처리가 없어도 모델이 잘 주면 잘 떴음)
    if 'tennis' not in data: data['tennis'] = {}
    if 'f1' not in data: data['f1'] = {}

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: raise ValueError("API Key Missing")

    # [핵심 성공 요인] 검색 도구 활성화
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    today = datetime.date.today()
    # [성공 당시] 2026년을 포함하도록 넉넉히 잡았던 기간
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=10) 
    
    prompt = f"""
    Current Date: {today}
    Find OFFICIAL match schedules using Google Search from {start_date} to {end_date}.
    
    1. EPL fixtures.
    2. NBA Golden State Warriors schedule.
    3. Tennis Carlos Alcaraz next match.
    4. F1 next Grand Prix details (2026).

    Return JSON:
    {{
        "epl": [ {{ "teams": "Home vs Away", "time": "MM.DD HH:MM" }} ],
        "nba": {{ "schedule": [ {{ "teams": "vs Opponent", "time": "MM.DD HH:MM" }} ] }},
        "tennis": {{ "match": "Tournament/Round", "time": "Date" }},
        "f1": {{ "grand_prix": "Name", "circuit": "Name", "time": "Date" }}
    }}
    """

    client = genai.Client(api_key=api_key)
    
    # [성공 당시 설정] response_mime_type 없음! (자유롭게 생각 가능)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[google_search_tool]
        )
    )

    if response.text:
        data = extract_json_content(response.text)
        data = normalize_data(data) # 단순 정규화
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
