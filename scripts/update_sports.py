import os
import json
import datetime
import traceback
import re
import sys

# ---------------------------------------------------------
# [Configuration]
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json' 
MODEL_NAME = 'gemini-flash-latest' 

def log(message):
    print(message, flush=True)

try:
    from google import genai
    from google.genai import types
except ImportError:
    log("❌ Critical Error: 'google-genai' library not found.")
    sys.exit(1)

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
        log(f"⚠️ JSON Parsing Failed. Text start: {text[:50]}...")
        return {}

def normalize_data(data):
    log("🔧 [Processing] Applying logic & normalization...")

    # 1. EPL
    if 'epl_round' not in data:
        data['epl_round'] = "R--"
    else:
        # 라운드 포맷팅 (Matchweek 20 -> R20)
        raw_round = str(data['epl_round'])
        nums = re.findall(r'\d+', raw_round)
        if nums:
            data['epl_round'] = f"R{nums[0]}"
        elif not raw_round.startswith('R'):
             data['epl_round'] = f"R{raw_round}"

    if 'epl' in data and isinstance(data['epl'], list):
        # [중요] AI가 큐레이션 해온 순서(중요도순)를 유지하기 위해, 
        # 파이썬에서는 별도의 정렬을 하지 않고 그대로 상위 5개를 자릅니다.
        data['epl'] = data['epl'][:5]
        
        for item in data['epl']:
            # Home/Away 분리
            if 'teams' in item and 'vs' in item['teams']:
                try:
                    h, a = item['teams'].split('vs')
                    item['home'] = item.get('home') or h.strip()
                    item['away'] = item.get('away') or a.strip()
                except: pass
            
            # UK TV / 시간 / 상태 보정
            if not item.get('channel') or item.get('channel') == "TBD": pass
            if not item.get('kst_time'): item['kst_time'] = item.get('time', 'TBD')
            if not item.get('local_time'): item['local_time'] = ""
            if not item.get('status'): item['status'] = "Scheduled"

    # 2. NBA
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    nba['record'] = nba.get('record') or "-"
    nba['rank'] = nba.get('ranking') or nba.get('rank') or "-"
    if 'last' not in nba: nba['last'] = {"opp": "-", "result": "-", "score": "-"}

    if 'schedule' in nba and isinstance(nba['schedule'], list):
        nba['schedule'] = nba['schedule'][:4]
        for item in nba['schedule']:
            # 상대팀 추출
            if 'opp' not in item:
                raw = item.get('teams') or item.get('match') or ""
                if 'vs' in raw:
                    item['opp'] = raw.split('vs')[-1].strip()
                elif '@' in raw:
                    item['opp'] = raw.split('@')[-1].strip()
                else:
                    item['opp'] = raw.replace("GS Warriors", "").strip() or "TBD"
            
            # 시간/날짜 분리
            if 'time' in item and not item.get('date'):
                parts = item['time'].split(' ')
                if len(parts) >= 2:
                    item['date'] = parts[0]
                    item['time'] = " ".join(parts[1:])
                else:
                    item['date'] = item['time']

    # 3. Tennis
    if 'tennis' not in data: data['tennis'] = {}
    t = data['tennis']
    if not t.get('info'): t['info'] = "No Match"
    if not t.get('detail'): t['detail'] = "Check Schedule"
    if not t.get('status'): t['status'] = "Season 2026"
    if not t.get('time'): t['time'] = ""

    # 4. F1
    if 'f1' not in data: data['f1'] = {}
    f = data['f1']
    if not f.get('name'): f['name'] = "Next GP"
    if not f.get('circuit'): f['circuit'] = "Circuit TBD"
    if not f.get('status'): f['status'] = "Upcoming"
    if not f.get('date'): f['date'] = f.get('time', '')

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
    
    # [Prompt] The 6-Phase Logic Injection
    prompt = f"""
    Current Date: {today}
    TASK: Search for OFFICIAL 2026 schedules.
    
    *** IMPORTANT: EPL MATCH SELECTION LOGIC ***
    Do NOT just list matches chronologically. You MUST curate the Top 4 matches based on this PRIORITY (Phase 1 to 6):
    
    [Context] Big 6 Teams: Man City, Man Utd, Liverpool, Arsenal, Chelsea, Tottenham.
    
    1. **Phase 1 (Big Match):** Big 6 vs Big 6.
    2. **Phase 2 (Top Tier):** Current Top 4 vs Current Top 4 (Search 'EPL Table' to verify).
    3. **Phase 3 (Challenger):** Current Top 4 vs Big 6.
    4. **Phase 4 (Prime Time):** Sunday 16:30 (UK Time) matches.
    5. **Phase 5 (Early KO):** Saturday 12:30 (UK Time) matches.
    6. **Fallback:** Match featuring the current League Leader.
    
    *INSTRUCTION:* Search for the full fixture list AND the current EPL table. Then apply the logic above to select the best 4-5 matches.

    *** OTHER TASKS ***
    1. **EPL**: Find specific UK Broadcaster (Sky/TNT/Amazon).
    2. **Tennis (Alcaraz)**: Check for EXHIBITION matches (e.g. Kooyong) before Australian Open.
    3. **NBA**: Next 4 games (Find Opponent Name).
    4. **F1**: Next 2026 GP.

    TARGET JSON STRUCTURE:
    {{
        "epl_round": "Current Matchweek Number (e.g. 20)",
        "epl": [
            {{ 
              "teams": "Home vs Away", 
              "kst_time": "MM.DD HH:MM (KST)", 
              "local_time": "MM.DD HH:MM (Local)",
              "channel": "UK TV Channel", 
              "status": "Scheduled"
            }}
        ],
        "nba": {{
            "record": "W-L",
            "rank": "Conf. Rank",
            "last": {{ "opp": "Name", "result": "W/L", "score": "100-90" }},
            "schedule": [ {{ "opp": "Name", "date": "MM.DD", "time": "HH:MM (PST)" }} ]
        }},
        "tennis": {{
            "status": "Exhibition / Tournament Name",
            "info": "Event Name",
            "detail": "Round info",
            "time": "MM.DD HH:MM"
        }},
        "f1": {{
            "status": "Season 2026",
            "name": "Grand Prix Name",
            "circuit": "Circuit Name",
            "date": "MM.DD - MM.DD"
        }}
    }}
    
    Return ONLY the JSON object.
    """

    client = genai.Client(api_key=api_key)
    
    try:
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
            
        log(f"✅ [Success] Data updated with 6-Phase Logic.")
        log(f"   - EPL Matches Selected: {len(data.get('epl', []))}")
        log(f"   - EPL Round: {data.get('epl_round')}")

    except Exception as e:
        log(f"❌ API Call Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    update_sports_data()
