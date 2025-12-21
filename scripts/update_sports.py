import json
import requests
from google import genai
import os
from datetime import datetime
import pytz

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 그릇 (기본 구조)
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "epl": [], 
    "tennis": {"status": "Off", "info": "Data Loading...", "detail": "-"},
    "f1": {"status": "Loading...", "name": "-", "date": "-"} # F1 추가
}

# ---------------------------------------------------------
# 1. Tennis (Gemini)
# ---------------------------------------------------------
def get_tennis_gemini(client):
    print("🎾 Tennis 데이터 수집...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        prompt = f"Current Time: {today_str}. Search 'Carlos Alcaraz' schedule. JSON output (status, info, detail, time). No markdown."
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        dashboard_data['tennis'] = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        print("✅ Tennis 완료")
    except Exception as e: print(f"❌ Tennis 에러: {e}")

# ---------------------------------------------------------
# 2. EPL: 6-Tier Logic & 2-State System (Gemini)
# ---------------------------------------------------------
def get_epl_data(client):
    print("⚽ EPL 데이터 수집 (6-Tier Logic)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        
        prompt = f"""
        Current Time: {today_str}
        
        Task 1: Search for the CURRENT English Premier League (EPL) Standings. Identify the Top 4 teams.
        Task 2: Search for the fixtures/results for the current (or upcoming) matchweek.
        
        Task 3: Select exactly 3 "Matches of the Week" based on this strict priority logic (Tier 1 to 6).
        You must fill 3 slots.

        [Selection Logic]
        Tier 1: Big 6 vs Big 6.
        Tier 2: Top 4 vs Top 4.
        Tier 3: Top 4 vs Big 6.
        Tier 4: Sky Sports 'Super Sunday' match (Sunday 16:30 UK time).
        Tier 5: TNT Sports 'Early Kick-off' match (Saturday 12:30 UK time).
        Tier 6: If slots are still empty, pick matches involving 1st, then 2nd, then 3rd place teams.

        Task 4: For each selected match, identify the status:
        - If FINISHED: Provide Final Score.
        - If SCHEDULED: Provide KST Time, Local UK Time, and UK TV Channel.

        Return a JSON List of 3 objects (No markdown):
        [
            {{
                "home": "HomeTeamName",
                "away": "AwayTeamName",
                "status": "Finished" or "Scheduled",
                "score": "3 - 1" (Only if Finished, else "-"),
                "kst_time": "MM.DD (Day) HH:MM",
                "local_time": "Sat 12:30",
                "channel": "Sky Sports"
            }},
            ...
        ]
        """
        
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        epl_list = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        
        # [정렬] 경기 전(0) -> 경기 후(1)
        epl_list.sort(key=lambda x: 1 if x['status'] == 'Finished' else 0)
        
        dashboard_data['epl'] = epl_list
        print(f"✅ EPL 완료: {len(epl_list)}개 경기 선정됨")

    except Exception as e:
        print(f"❌ EPL 에러: {e}")
        dashboard_data['epl'] = []

# ---------------------------------------------------------
# 3. NBA (ESPN)
# ---------------------------------------------------------
def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집...")
    try:
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        res = requests.get(schedule_url, timeout=10).json()
        res_team = requests.get(team_url, timeout=10).json()
        
        team_record = "0-0"
        try:
            team_record = res_team['team']['record']['items'][0]['summary']
            summary = res_team['team'].get('standingSummary', '')
            if ' in ' in summary:
                parts = summary.split(' in ')
                team_rank = f"#{parts[0]} {parts[1].split(' ')[0]}"
            else: team_rank = f"#{summary}"
        except: team_rank = "-"

        events = res.get('events', [])
        completed, future = [], []
        for event in events:
            date_obj = datetime.strptime(event['date'], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            competition = event['competitions'][0]
            gsw = next((t for t in competition['competitors'] if t['team']['abbreviation'] == 'GS'), None)
            opp = next((t for t in competition['competitors'] if t['team']['abbreviation'] != 'GS'), None)
            
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
            else: future.append(game_data)

        last = sorted(completed, key=lambda x: x['dt'])[-1] if completed else {}
        if last: del last['dt']
        sched = []
        for g in sorted(future, key=lambda x: x['dt'])[:2]:
            del g['dt']
            sched.append(g)

        dashboard_data['nba'] = {"status": "Active", "record": team_record, "rank": team_rank, "last": last, "schedule": sched}
        print("✅ NBA 완료")
    except Exception as e: print(f"❌ NBA 에러: {e}")

# ---------------------------------------------------------
# 4. F1 (Jolpica) - [복구 완료]
# ---------------------------------------------------------
def get_f1_schedule():
    print("🏎️ F1 데이터 수집...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10).json()
        race_table = res.get('MRData', {}).get('RaceTable', {})
        
        if not race_table.get('Races'):
            # 시즌 종료 시
            dashboard_data['f1'] = {
                "status": "Off Season", 
                "name": "Season Finished", 
                "date": "See you next year!", 
                "circuit": "-"
            }
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
        dashboard_data['f1'] = {"status": "Error", "name": "-", "date": "-"}

if __name__ == "__main__":
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
        get_tennis_gemini(client)
        get_epl_data(client)
    else:
        print("⚠️ API Key 없음. AI 기능 건너뜀.")

    get_nba_gsw_espn()
    get_f1_schedule() # F1 실행
    
    with open('sports.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
        print("💾 sports.json 저장 완료")
