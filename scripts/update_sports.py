import json
import requests
from google import genai
from google.genai import types
import os
from datetime import datetime
import pytz

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 그릇
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "epl": [], 
    "tennis": {"status": "Off", "info": "Off Season", "detail": "Waiting for 2025"},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

# ---------------------------------------------------------
# 1. Tennis (Gemini 2.0 Flash Exp + Search)
# ---------------------------------------------------------
def get_tennis_gemini(client):
    print("🎾 Tennis 데이터 수집...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        prompt = f"""
        Current Time: {today_str}
        Search for 'Carlos Alcaraz' latest schedule.
        Return JSON object with keys: status, info, detail, time.
        """
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())],
                response_mime_type="application/json"
            )
        )
        dashboard_data['tennis'] = json.loads(response.text)
        print("✅ Tennis 완료")
    except Exception as e:
        print(f"❌ Tennis 에러: {e}")

# ---------------------------------------------------------
# 2. EPL: 2-Pass System (Sequential Chain)
# ---------------------------------------------------------
def get_epl_data(client):
    print("⚽ EPL 데이터 수집 (Step 1: Raw Data Collection)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        
        # [Phase 1] 조사관: 검색만 수행 (판단 X)
        # 구글 검색 도구를 사용하여 현재 상황을 텍스트로 확보합니다.
        search_prompt = f"""
        Current Time: {today_str}
        
        Action: Use Google Search to find the following two sets of information:
        1. The CURRENT English Premier League (EPL) Table/Standings (Identify who is 1st, 2nd, 3rd, 4th).
        2. The FULL list of EPL fixtures/results for the CURRENT matchweek (or the very next upcoming matchweek).
        
        Output: Just list the facts clearly. Do not select "best matches" yet. Just list all matches and the top 4 teams.
        """
        
        # 1차 호출 (검색 활성화)
        response_raw = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())]
            )
        )
        
        raw_context = response_raw.text
        print("📋 EPL 원본 데이터 확보 완료. (Step 2: Logic Application 진입)")

        # [Phase 2] 편집장: 확보된 데이터에 로직 적용 (검색 X, 순수 추론)
        # 1차 결과(raw_context)를 문맥으로 던져주고, 6단계 로직을 수행시킵니다.
        logic_prompt = f"""
        Current Time: {today_str}
        
        CONTEXT (Facts found in Step 1):
        {raw_context}
        
        TASK: Based ONLY on the context above, select exactly 3 matches applying the following Strict Logic Priority (Tier 1 to 6).
        Do not skip tiers. Check them sequentially.

        [DEFINITIONS]
        - Big 6: Man City, Arsenal, Liverpool, Chelsea, Man Utd, Tottenham.
        - Top 4: (Use the standings from Context)

        [LOGIC TIERS]
        1. Big 6 vs Big 6.
        2. Top 4 vs Top 4.
        3. Top 4 vs Big 6.
        4. Sky Sports 'Super Sunday' (Sunday 16:30 UK).
        5. TNT Sports 'Early Kick-off' (Saturday 12:30 UK).
        6. League Leaders (Matches involving 1st, then 2nd, then 3rd place).

        OUTPUT: Return a JSON List of 3 objects.
        [
            {{
                "home": "HomeTeam",
                "away": "AwayTeam",
                "status": "Finished" or "Scheduled",
                "score": "3 - 1" (if Finished) or "-",
                "kst_time": "MM.DD (Day) HH:MM",
                "local_time": "Sat 16:30",
                "channel": "Sky Sports" (or TNT/Amazon)
            }}
        ]
        """
        
        # 2차 호출 (검색 끄기 - 이미 데이터가 있으므로 추론만 집중)
        response_final = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=logic_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        epl_list = json.loads(response_final.text)
        
        # 리스트 검증 및 정렬
        if isinstance(epl_list, list) and len(epl_list) > 0:
            epl_list.sort(key=lambda x: 1 if x.get('status') == 'Finished' else 0)
            dashboard_data['epl'] = epl_list
            print(f"✅ EPL 최종 완료: {len(epl_list)}개 경기 선정 (로직 적용됨)")
        else:
            print("⚠️ EPL 데이터 형식이 올바르지 않음 (Step 2 실패)")
            dashboard_data['epl'] = []

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
# 4. F1 (Jolpica)
# ---------------------------------------------------------
def get_f1_schedule():
    print("🏎️ F1 데이터 수집...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10).json()
        race_table = res.get('MRData', {}).get('RaceTable', {})
        
        if not race_table.get('Races'):
            dashboard_data['f1'] = {"status": "Off Season", "name": "Season Finished", "date": "See you next year!", "circuit": "-"}
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
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
        get_tennis_gemini(client)
        get_epl_data(client)
    else:
        print("⚠️ API Key 없음. AI 기능 건너뜀.")

    get_nba_gsw_espn()
    get_f1_schedule()
    
    with open('sports.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
        print("💾 sports.json 저장 완료")
