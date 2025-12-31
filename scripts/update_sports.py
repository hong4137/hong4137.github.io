import os
import json
import datetime
import traceback
import re
import sys

# ---------------------------------------------------------
# [Configuration]
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json' # 루트 경로에 위치 (분석서 기반)
MODEL_NAME = 'gemini-flash-latest' # [중요] 1.5 버전 사용 금지 (404 방지)

def log(message):
    """GitHub Actions 로그 누락 방지"""
    print(message, flush=True)

try:
    from google import genai
    from google.genai import types
except ImportError:
    log("❌ Critical Error: 'google-genai' library not found.")
    sys.exit(1)

def extract_json_content(text):
    """AI 응답(Thinking 포함)에서 순수 JSON 추출"""
    text = text.strip()
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            return json.loads(text[start_idx : end_idx + 1])
        return json.loads(text)
    except json.JSONDecodeError:
        log(f"⚠️ JSON Parsing Failed. Text start: {text[:50]}...")
        return {}

def normalize_data(data):
    """
    [핵심] 프론트엔드(index.html)와 1:1 매핑을 위한 데이터 정제
    """
    log("🔧 [Processing] Mapping data to Frontend requirements...")

    # 1. EPL (Keys: home, away, kst_time, local_time, status)
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5]
        for item in data['epl']:
            # Home/Away 분리 보장
            if 'teams' in item and 'vs' in item['teams']:
                try:
                    h, a = item['teams'].split('vs')
                    item['home'] = item.get('home') or h.strip()
                    item['away'] = item.get('away') or a.strip()
                except: pass
            
            # 시간 데이터 보정 (없으면 - 표시 방지)
            if not item.get('kst_time'): item['kst_time'] = item.get('time', 'TBD')
            if not item.get('local_time'): item['local_time'] = ""
            if not item.get('status'): item['status'] = "Scheduled"

    # 2. NBA (Keys: record, rank, schedule[{opp, date, time}])
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    nba['record'] = nba.get('record') or "-"
    nba['rank'] = nba.get('ranking') or nba.get('rank') or "-"
    
    # 지난 경기 정보 (Optional)
    if 'last' not in nba: nba['last'] = {"opp": "-", "result": "-", "score": "-"}

    if 'schedule' in nba and isinstance(nba['schedule'], list):
        nba['schedule'] = nba['schedule'][:4]
        for item in nba['schedule']:
            # [중요] 'opp' 키 생성 로직 (vs undefined 해결)
            if 'opp' not in item:
                # teams나 match에서 상대팀 추출 시도
                raw = item.get('teams') or item.get('match') or ""
                if 'vs' in raw:
                    item['opp'] = raw.split('vs')[-1].strip()
                elif '@' in raw:
                    item['opp'] = raw.split('@')[-1].strip()
                else:
                    item['opp'] = raw.replace("GS Warriors", "").strip() or "TBD"
            
            # 날짜/시간 분리 (프론트엔드가 date, time을 따로 씀)
            if 'time' in item and not item.get('date'):
                # 포맷이 "12.31 10:00" 형태라면 분리 시도
                parts = item['time'].split(' ')
                if len(parts) >= 2:
                    item['date'] = parts[0]
                    item['time'] = " ".join(parts[1:])
                else:
                    item['date'] = item['time']

    # 3. Tennis (Keys: status, info, detail, time)
    if 'tennis' not in data: data['tennis'] = {}
    t = data['tennis']
    
    # 프론트엔드 매핑
    if not t.get('info'): t['info'] = t.get('match') or t.get('tournament') or "No Match"
    if not t.get('detail'): t['detail'] = t.get('round') or "Check Schedule"
    if not t.get('status'): t['status'] = "Season 2026"
    if not t.get('time'): t['time'] = ""

    # 4. F1 (Keys: status, name, date, circuit)
    if 'f1' not in data: data['f1'] = {}
    f = data['f1']
    
    # 프론트엔드 매핑
    if not f.get('name'): f['name'] = f.get('grand_prix') or "Next GP"
    if not f.get('circuit'): f['circuit'] = "Circuit TBD"
    if not f.get('status'): f['status'] = "Upcoming"
    if not f.get('date'): f['date'] = f.get('time', '')

    # 메타데이터 업데이트
    data['updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("❌ Error: GEMINI_API_KEY Missing")
        raise ValueError("API Key Missing")

    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    log(f"🚀 [Start] Gemini API({MODEL_NAME}) initialized.")
    
    today = datetime.date.today()
    log(f"📅 Base Date: {today}")

    # [Prompt] 프론트엔드 스키마에 맞춘 정밀 지시
    prompt = f"""
    Current Date: {today}
    TASK: Search for OFFICIAL 2026 schedules (EPL, NBA, Tennis, F1).
    
    TARGET JSON STRUCTURE (Strictly follow this keys):
    {{
        "epl": [
            {{ 
              "teams": "Home vs Away", 
              "kst_time": "MM.DD HH:MM (KST)", 
              "local_time": "MM.DD HH:MM (Local)",
              "status": "Scheduled"
            }}
        ],
        "nba": {{
            "record": "W-L",
            "rank": "Conf. Rank",
            "last": {{ "opp": "Name", "result": "W/L", "score": "100-90" }},
            "schedule": [
                {{ "opp": "Opponent Name", "date": "MM.DD", "time": "HH:MM (PST)" }}
            ]
        }},
        "tennis": {{
            "status": "In Progress/Upcoming",
            "info": "Tournament Name",
            "detail": "Round (e.g. R16, QF)",
            "time": "MM.DD HH:MM"
        }},
        "f1": {{
            "status": "Season 2026",
            "name": "Grand Prix Name",
            "circuit": "Circuit Name (Specific)",
            "date": "MM.DD - MM.DD"
        }}
    }}

    SEARCH INSTRUCTIONS:
    1. **NBA (GS Warriors)**: Find the next 4 games. MUST extract 'opp' (Opponent Name).
    2. **Tennis (Carlos Alcaraz)**: Find current tournament & round.
    3. **F1**: Find next 2026 GP & Circuit Name.
    4. **EPL**: Next matchweek fixtures.

    Return ONLY the JSON object.
    """

    client = genai.Client(api_key=api_key)
    
    try:
        # JSON 모드 해제 -> 검색(Thinking) 유도
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool]
            )
        )
        
        if not response.text:
            log("⚠️ Warning: Empty response.")
            return

        data = extract_json_content(response.text)
        data = normalize_data(data)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        log(f"✅ [Success] Data updated in {SPORTS_FILE}")
        log(f"   - EPL: {len(data.get('epl', []))} matches")
        log(f"   - NBA Opponent: {data.get('nba', {}).get('schedule', [{}])[0].get('opp')}")

    except Exception as e:
        log(f"❌ API Call Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    update_sports_data()
