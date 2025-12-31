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
    log("🔧 [Processing] Robust Normalization...")

    # 1. EPL
    if 'epl_round' not in data:
        data['epl_round'] = "R--"
    else:
        raw_round = str(data['epl_round'])
        nums = re.findall(r'\d+', raw_round)
        if nums:
            data['epl_round'] = f"R{nums[0]}"
        elif not raw_round.startswith('R'):
             data['epl_round'] = f"R{raw_round}"

    if 'epl' in data and isinstance(data['epl'], list):
        for item in data['epl']:
            # [핵심 수정] 파이썬 분기 로직 강화
            # AI가 home/away를 안 줬을 경우를 대비해 'v', 'vs', '-' 모두 체크
            if not item.get('home') or not item.get('away'):
                raw_teams = item.get('teams') or item.get('match') or ""
                
                # 영국식(v), 일반(vs), 하이픈(-) 순차 체크
                if ' vs ' in raw_teams:
                    h, a = raw_teams.split(' vs ')
                elif ' v ' in raw_teams:
                    h, a = raw_teams.split(' v ')
                elif ' - ' in raw_teams:
                    h, a = raw_teams.split(' - ')
                else:
                    # 분리 실패 시 통째로라도 넣어서 undefined 방지
                    h, a = raw_teams, ""
                
                item['home'] = h.strip()
                item['away'] = a.strip()

            # 부가 정보 보정
            if not item.get('channel') or item.get('channel') == "TBD": 
                pass # 프론트엔드가 처리하게 둠
            
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
            if 'opp' not in item:
                raw = item.get('teams') or item.get('match') or ""
                if 'vs' in raw:
                    item['opp'] = raw.split('vs')[-1].strip()
                elif '@' in raw:
                    item['opp'] = raw.split('@')[-1].strip()
                else:
                    item['opp'] = raw.replace("GS Warriors", "").strip() or "TBD"
            
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
    
    # [Prompt] home, away 분리 요청 + v/vs 이슈 원천 차단
    prompt = f"""
    Current Date: {today}
    TASK: Search for OFFICIAL 2026 schedules.
    
    *** STRICT EPL MATCH SELECTION (NO FILLERS) ***
    Filter the upcoming fixtures and return matches that meet AT LEAST ONE of the following 6 Criteria.
    If 0 matches meet criteria, return []. If 10 matches meet criteria, return all 10.

    [Context] Big 6: Man City, Man Utd, Liverpool, Arsenal, Chelsea, Tottenham.
    
    [Selection Criteria]
    1. **Big Match:** Big 6 vs Big 6.
    2. **Top Tier:** Current Top 4 vs Current Top 4.
    3. **Challenger:** Current Top 4 vs Big 6.
    4. **Prime Time:** Sunday 16:30 (UK Time).
    5. **Early KO:** Saturday 12:30 (UK Time).
    6. **Leader:** Match featuring League Leader.
    
    *** OTHER TASKS ***
    1. **EPL Info**: Find specific UK Broadcaster (Sky/TNT/Amazon).
    2. **Tennis (Alcaraz)**: Check for EXHIBITION matches (e.g. Kooyong) or Tournaments.
    3. **NBA**: Next 4 games (Find Opponent Name).
    4. **F1**: Next 2026 GP.

    TARGET JSON STRUCTURE (Must separate Home/Away):
    {{
        "epl_round": "Current Matchweek Number (e.g. 20)",
        "epl": [
            {{ 
              "home": "Home Team Name",
              "away": "Away Team Name",
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
            
        log(f"✅ [Success] Data updated (v/vs Safe Mode).")
        log(f"   - EPL Matches Selected: {len(data.get('epl', []))}")
        
        # 로그 확인용 (첫 번째 경기의 홈팀이 잘 들어갔는지)
        if data.get('epl'):
            log(f"   - Sample: {data['epl'][0].get('home')} vs {data['epl'][0].get('away')}")

    except Exception as e:
        log(f"❌ API Call Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    update_sports_data()
