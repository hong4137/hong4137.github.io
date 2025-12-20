import json
import requests
from datetime import datetime
import pytz
import sys

# 타임존 설정 (한국 시간, 협정 세계시)
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 기본 데이터 골격
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "last": {}, "schedule": []},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집 (ESPN Source)...")
    try:
        # 여기가 핵심! ESPN 주소인지 확인하세요.
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        res = requests.get(url, timeout=10)
        data = res.json()
        
        events = data.get('events', [])
        
        completed_games = []
        future_games = []

        for event in events:
            # 날짜 파싱
            game_date_str = event['date'] # 예: 2024-10-24T02:00Z
            game_date = datetime.strptime(game_date_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            
            # 경쟁 팀 정보 찾기
            competition = event['competitions'][0]
            competitors = competition['competitors']
            
            gsw = next((t for t in competitors if t['team']['abbreviation'] == 'GS'), None)
            opp = next((t for t in competitors if t['team']['abbreviation'] != 'GS'), None)
            
            if not gsw or not opp: continue

            # 기본 정보 구성
            game_info = {
                "date_obj": game_date, 
                "date": game_date.astimezone(KST).strftime("%m.%d(%a)"),
                "time": game_date.astimezone(KST).strftime("%H:%M"),
                "opp": opp['team']['abbreviation'],
                "is_home": gsw['homeAway'] == 'home'
            }

            # 경기 상태 확인 (STATUS_FINAL: 종료된 경기)
            status_type = competition['status']['type']['name']
            
            if status_type == 'STATUS_FINAL':
                my_score = int(gsw.get('score', {}).get('value', 0))
                opp_score = int(opp.get('score', {}).get('value', 0))
                result = 'W' if my_score > opp_score else 'L'
                
                game_info['result'] = result
                game_info['score'] = f"{my_score}-{opp_score}"
                completed_games.append(game_info)
            else:
                future_games.append(game_info)

        # 1. 지난 경기
        last_game_data = {}
        if completed_games:
            completed_games.sort(key=lambda x: x['date_obj'])
            last = completed_games[-1]
            last_game_data = {
                "date": last['date'],
                "opp": last['opp'],
                "result": last['result'],
                "score": last['score']
            }

        # 2. 향후 일정
        schedule_list = []
        if future_games:
            future_games.sort(key=lambda x: x['date_obj'])
            schedule_list = future_games[:2]

        # 데이터 저장
        dashboard_data['nba'] = {
            "status": "Active",
            "last": last_game_data,
            "schedule": schedule_list
        }
        print(f"✅ NBA 완료: 지난경기({bool(last_game_data)}), 예정({len(schedule_list)})")

    except Exception as e:
        print(f"❌ NBA 에러: {e}")
        dashboard_data['nba'] = {"status": "Error", "msg": "ESPN 연결 실패"}

def get_f1_schedule():
    print("🏎️ F1 데이터 수집 시작...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10)
        data = res.json()
        race_table = data.get('MRData', {}).get('RaceTable', {})
        
        if not race_table.get('Races'):
            dashboard_data['f1'] = {"status": "Off Season", "name": "2026 Season", "date": "Waiting...", "circuit": "-"}
        else:
            race = race_table['Races'][0]
            race_time_utc = f"{race['date']} {race.get('time', '00:00:00Z')}"
            utc_dt = datetime.strptime(race_time_utc, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=pytz.utc)
            kst_dt = utc_dt.astimezone(KST)

            dashboard_data['f1'] = {
                "status": "Next GP",
                "name": race['raceName'].replace(" Grand Prix", " GP"),
                "date": kst_dt.strftime("%m.%d(%a) %H:%M"),
                "circuit": race['Circuit']['circuitName']
            }
        print("✅ F1 완료")
    except Exception as e:
        print(f"❌ F1 에러: {e}")
        dashboard_data['f1'] = {"status": "Error", "name": "Check Data"}

if __name__ == "__main__":
    try:
        get_nba_gsw_espn()
        get_f1_schedule()
    except Exception as e:
        print(f"🔥 치명적 오류: {e}")
    
    try:
        with open('sports.json', 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
            print("💾 sports.json 저장 완료")
    except Exception as e:
        print(f"파일 저장 실패: {e}")
        sys.exit(0)

    sys.exit(0)
