import json
import requests
from google import genai
from google.genai import types
import os
from datetime import datetime
import pytz
import traceback
import time

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 그릇
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "epl": [], 
    "tennis": {"status": "Off", "info": "Off Season", "detail": "Waiting"},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

# ---------------------------------------------------------
# 1. Tennis (Gemini 1.5 Flash + Search)
# ---------------------------------------------------------
def get_tennis_gemini(client):
    print("🎾 Tennis 데이터 수집 (Gemini 1.5 Flash)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        prompt = f"""
        Current Time: {today_str}
        Task: Search for 'Carlos Alcaraz' next match schedule or latest news using Google Search.
        Output: JSON object only {{ "status": "Scheduled/Off", "info": "Tournament Name", "detail": "vs Opponent", "time": "Time" }}
        """
        response = client.models.generate_content(
            model="gemini-1.5-flash",  # [변경] 가장 안정적인 모델
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())], # [핵심] 검색 도구 장착
                response_mime_type="application/json" # [핵심] JSON 강제 (루프 방지)
            )
        )
        dashboard_data['tennis'] = json.loads(response.text)
        print("✅ Tennis 완료")
    except Exception as e:
        print(f"❌ Tennis 실패: {e}")

# ---------------------------------------------------------
# 2. EPL (Gemini 1.5 Flash + Search)
# ---------------------------------------------------------
def get_epl_data(client):
    print("⚽ EPL 데이터 수집 (Gemini 1.5 Flash)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        
        # 1.5 Flash가 이해하기 쉽게 명확하고 단순한 지시
        prompt = f"""
        Current Time: {today_str}
        
        Task: Use Google Search to find EPL fixtures/results for the CURRENT matchweek (Round 17).
        
        Goal: Select 3 matches.
        Priority: 
        1. Big 6 teams (Man City, Arsenal, Liverpool, Chelsea, Man Utd, Spurs).
        2. If not enough Big 6 matches, pick Top 4 teams matches.
        
        Output: JSON List of 3 items strictly.
        [
            {{
                "home": "HomeTeam", "away": "AwayTeam",
                "status": "Finished" or "Scheduled",
                "score": "3-1" (if finished) or "-",
                "kst_time": "12.22 (Sun) 01:30",
                "local_time": "Sat 16:30",
                "channel": "Sky Sports"
            }}
        ]
        """
        
        response = client.models.generate_content(
            model="gemini-1.5-flash", # [변경] 가장 안정적인 모델
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())], # [핵심] 검색 도구 장착
                response_mime_type="application/json" # [핵심] JSON 강제 (루프 방지)
            )
        )
        
        data = json.loads(response.text)
        if isinstance(data, list) and len(data) > 0:
            data.sort(key=lambda x: 1 if x.get('status') == 'Finished' else 0)
            dashboard_data['epl'] = data
            print(f"✅ EPL 완료: {len(data)}개")
        else:
            print("⚠️ EPL 데이터 없음 (빈 리스트)")
            
    except Exception as e:
        print(f"❌ EPL 실패: {e}")
        dashboard_data['epl'] = []

# ---------------------------------------------------------
# 3. NBA & F1 (APIs)
# ---------------------------------------------------------
def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집...")
    try:
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        
        res = requests.get(schedule_url, timeout=5).json()
        res_team = requests.get(team_url, timeout=5).json()
        
        team_record = res_team['team']['record']['items'][0]['summary']
        try:
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
    except Exception as e:
        print(f"❌ NBA 실패: {e}")

def get_f1_schedule():
    print("🏎️ F1 데이터 수집...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=5).json()
        race_table = res.get('MRData', {}).get('RaceTable', {})
        
        if not race_table.get('Races'):
            dashboard_data['f1'] = {"status": "Off Season", "name": "Season Finished", "date": "-", "circuit": "-"}
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
        print(f"❌ F1 실패: {e}")

# ---------------------------------------------------------
# Main Execution
# ---------------------------------------------------------
if __name__ == "__main__":
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            client = genai.Client(api_key=api_key)
            
            get_tennis_gemini(client)
            # 1.5-flash는 쿨타임이 필요 없습니다. 바로 실행 가능.
            get_epl_data(client)
        else:
            print("⚠️ API Key 없음. AI 기능 건너뜀.")

        get_nba_gsw_espn()
        get_f1_schedule()
        
    except Exception as e:
        print(f"🔥 시스템 에러: {e}")
        traceback.print_exc()
        
    finally:
        with open('sports.json', 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
            print("💾 sports.json 저장 완료 (Final Save)")
