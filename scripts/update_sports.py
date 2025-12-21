import json
import requests
from google import genai
from google.genai import types
import os
from datetime import datetime
import pytz
import traceback
import time
import re # [추가] 정규표현식 사용

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 그릇
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "epl": [], 
    "tennis": {"status": "Off", "info": "Data Loading...", "detail": "-"},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

# [핵심] AI 응답에서 순수 JSON 문자열만 추출하는 함수
def clean_json_text(text):
    try:
        # 1. ```json ... ``` 패턴 제거
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*$', '', text)
        # 2. 앞뒤 공백 제거
        return text.strip()
    except:
        return text

# ---------------------------------------------------------
# 1. Tennis (Gemini Flash Latest)
# ---------------------------------------------------------
def get_tennis_gemini(client):
    print("🎾 Tennis 데이터 수집 (Gemini Flash Latest)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        prompt = f"""
        Current Time: {today_str}
        Task: Use Google Search to find 'Carlos Alcaraz' next match schedule or latest news.
        
        Output format: Provide ONLY a raw JSON object. Do not use Markdown.
        JSON Structure: {{ "status": "Scheduled/Off", "info": "Tournament Name", "detail": "vs Opponent", "time": "Time" }}
        """
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())], # 검색 도구 유지
                # response_mime_type 제거 (충돌 방지)
            )
        )
        
        # 텍스트 정제 후 파싱
        json_str = clean_json_text(response.text)
        data = json.loads(json_str)
        dashboard_data['tennis'] = data
        print("✅ Tennis 완료")
    except Exception as e:
        print(f"❌ Tennis 실패: {e}")
        # 디버깅용: 실패 시 원본 텍스트가 있다면 출력
        # try: print(f"DEBUG: {response.text}")
        # except: pass

# ---------------------------------------------------------
# 2. EPL (Gemini Flash Latest + 6-Tier Logic)
# ---------------------------------------------------------
def get_epl_data(client):
    print("⚽ EPL 데이터 수집 (Gemini Flash Latest)...")
    try:
        today_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        
        prompt = f"""
        Current Time: {today_str}
        
        [PHASE 1: RESEARCH]
        Use Google Search to find:
        1. The CURRENT English Premier League (EPL) Table (Identify Top 4 teams).
        2. The full fixtures list for the CURRENT matchweek (Round 17).

        [PHASE 2: SELECTION LOGIC]
        Select exactly 3 matches based on this strict priority (Tier 1 is highest):
        
        - Tier 1 (The Titans): Big 6 vs Big 6 (Man City, Arsenal, Liverpool, Chelsea, Man Utd, Spurs).
        - Tier 2 (Title Race): Top 4 vs Top 4 (Based on current standings).
        - Tier 3 (The Challenge): Top 4 vs Big 6.
        - Tier 4 (Super Sunday): Match scheduled for Sunday 16:30 UK time.
        - Tier 5 (Early Kick-off): Match scheduled for Saturday 12:30 UK time.
        - Tier 6 (League Leaders): If slots are empty, pick matches involving 1st, then 2nd, then 3rd place.

        [PHASE 3: OUTPUT]
        Provide ONLY a raw JSON List of 3 matches. Do not use Markdown.
        Example:
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
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())], # 검색 도구 유지
                # response_mime_type 제거 (충돌 방지)
            )
        )
        
        # 텍스트 정제 후 파싱
        json_str = clean_json_text(response.text)
        data = json.loads(json_str)
        
        if isinstance(data, list) and len(data) > 0:
            data.sort(key=lambda x: 1 if x.get('status') == 'Finished' else 0)
            dashboard_data['epl'] = data
            print(f"✅ EPL 완료: {len(data)}개")
        else:
            print("⚠️ EPL 데이터 없음 (빈 리스트)")
            dashboard_data['epl'] = []
            
    except Exception as e:
        print(f"❌ EPL 실패: {e}")
        dashboard_data['epl'] = []

# ---------------------------------------------------------
# 3. NBA & F1 (APIs)
# ---------------------------------------------------------
def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집...")
    try:
        res = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule", timeout=10).json()
        res_team = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs", timeout=10).json()
        
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
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10).json()
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

if __name__ == "__main__":
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            client = genai.Client(api_key=api_key)
            get_tennis_gemini(client)
            get_epl_data(client)
        else:
            print("⚠️ API Key 없음")

        get_nba_gsw_espn()
        get_f1_schedule()
        
    except Exception as e:
        print(f"🔥 시스템 에러: {e}")
        traceback.print_exc()
        
    finally:
        with open('sports.json', 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
            print("💾 sports.json 저장 완료 (Final)")
