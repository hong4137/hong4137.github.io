import json
import requests
from google import genai
import os
from datetime import datetime
import pytz

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 그릇 (기본값)
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "f1": {"status": "Loading...", "name": "-", "date": "-"},
    "tennis": {"status": "Off", "info": "Data Loading...", "detail": "-"} 
}

# ---------------------------------------------------------
# 1. Tennis: Gemini AI (Verified Model: gemini-2.5-flash)
# ---------------------------------------------------------
def get_tennis_gemini():
    print("🎾 Tennis 데이터 수집 (Gemini 2.5)...")
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("⚠️ GEMINI_API_KEY 없음. 건너뜀 (기본값 유지).")
        return

    try:
        client = genai.Client(api_key=api_key)
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        
        prompt = f"""
        Current Time: {today_str}
        Search for the latest schedule of tennis player 'Carlos Alcaraz'.
        
        Based on the search, determine his status into one of these 3 scenarios:

        [Scenario 1: Scheduled] (Match is confirmed with opponent & time)
        - status: "Scheduled"
        - info: Tournament Name + Round (e.g. "Aus Open (QF)")
        - detail: "vs [Opponent Name]"
        - time: Match time in KST (Format: "MM.DD HH:MM")

        [Scenario 2: Waiting] (Tournament active, but opponent/time NOT set yet)
        - status: "Waiting"
        - info: Tournament Name + Current Result (e.g. "Aus Open (Into SF)")
        - detail: "Opponent TBD"
        - time: "Time TBD"

        [Scenario 3: Off] (No active tournament right now)
        - status: "Off"
        - info: "Next: [Upcoming Tournament Name]"
        - detail: "Starts [Date]"
        - time: "-"

        Output must be ONLY valid JSON string. No markdown formatting.
        {{
            "status": "...",
            "info": "...",
            "detail": "...",
            "time": "..."
        }}
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        tennis_data = json.loads(clean_text)
        
        dashboard_data['tennis'] = tennis_data
        print(f"✅ Tennis 완료: {tennis_data['status']}")

    except Exception as e:
        print(f"❌ Tennis AI 에러: {e}")

# ---------------------------------------------------------
# 2. NBA: ESPN API
# ---------------------------------------------------------
def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집 (ESPN)...")
    try:
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        
        res = requests.get(schedule_url, timeout=10).json()
        res_team = requests.get(team_url, timeout=10).json()
        
        team_record = "0-0"
        team_rank = "-"
        try:
            team_record = res_team['team']['record']['items'][0]['summary']
            
            # [수정된 부분] 순위 텍스트 파싱 ("3rd in Pacific Division" -> "3rd Pacific")
            summary = res_team['team'].get('standingSummary', '')
            if summary:
                if ' in ' in summary:
                    parts = summary.split(' in ') # ['3rd', 'Pacific Division']
                    rank_val = parts[0] # "3rd"
                    division = parts[1].split(' ')[0] # "Pacific"
                    team_rank = f"#{rank_val} {division}"
                else:
                    team_rank = f"#{summary}"
        except: pass

        events = res.get('events', [])
        completed = []
        future = []
        
        for event in events:
            date_obj = datetime.strptime(event['date'], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            competition = event['competitions'][0]
            gsw = next((t for t in competition['competitors'] if t['team']['abbreviation'] == 'GS'), None)
            opp = next((t for t in competition['competitors'] if t['team']['abbreviation'] != 'GS'), None)
            if not gsw or not opp: continue
            
            game_data = {
                "dt": date_obj,
                "date": date_obj.astimezone(KST).strftime("%m.%d(%a)"),
                "time": date_obj.astimezone(KST).strftime("%H:%M"),
                "opp": opp['team']['abbreviation'],
                "is_home": gsw['homeAway'] == 'home'
            }
            
            if competition['status']['type']['name'] == 'STATUS_FINAL':
                ms, os = int(gsw['score']['value']), int(opp['score']['value'])
                game_data.update({"result": 'W' if ms > os else 'L', "score": f"{ms}-{os}"})
                completed.append(game_data)
            else:
                future.append(game_data)

        last = sorted(completed, key=lambda x: x['dt'])[-1] if completed else {}
        if last: del last['dt']
        
        sched = []
        for g in sorted(future, key=lambda x: x['dt'])[:2]:
            del g['dt']
            sched.append(g)

        dashboard_data['nba'] = {"status": "Active", "record": team_record, "rank": team_rank, "last": last, "schedule": sched}
        print("✅ NBA 완료")
    except Exception as e:
        print(f"❌ NBA 에러: {e}")

# ---------------------------------------------------------
# 3. F1: Jolpica API
# ---------------------------------------------------------
def get_f1_schedule():
    print("🏎️ F1 데이터 수집...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10).json()
        race_table = res.get('MRData', {}).get('RaceTable', {})
        if not race_table.get('Races'):
            dashboard_data['f1'] = {"status": "Off Season", "name": "2026 Season", "date": "Waiting...", "circuit": "-"}
        else:
            race = race_table['Races'][0]
            dt = datetime.strptime(f"{race['date']} {race['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=UTC)
            dashboard_data['f1'] = {
                "status": "Next GP",
                "name": race['raceName'].replace(" Grand Prix", " GP"),
                "date": dt.astimezone(KST).strftime("%m.%d(%a) %H:%M"),
                "circuit": race['Circuit']['circuitName']
            }
        print("✅ F1 완료")
    except Exception as e:
        print(f"❌ F1 에러: {e}")

if __name__ == "__main__":
    get_tennis_gemini()
    get_nba_gsw_espn()
    get_f1_schedule()
    
    with open('sports.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
        print("💾 sports.json 저장 완료")
