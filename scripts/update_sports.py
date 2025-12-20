import json
import requests
from datetime import datetime
import pytz
import sys

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 데이터 담을 그릇
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "last": {}, "schedule": []},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집 (ESPN Source)...")
    try:
        # ESPN GSW 스케줄 엔드포인트 (2024-25 시즌 자동 적용됨)
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        res = requests.get(url, timeout=10)
        data = res.json()
        
        events = data.get('events', [])
        
        completed_games = []
        future_games = []
        now = datetime.now(UTC)

        # 전체 경기 분류 (완료 vs 예정)
        for event in events:
            game_date_str = event['date'] # 예: 2024-10-24T02:00Z
            game_date = datetime.strptime(game_date_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            
            # 경기 정보 파싱
            competition = event['competitions'][0]
            competitors = competition['competitors']
            
            # 홈/어웨이 팀 찾기
            gsw_team = next((t for t in competitors if t['team']['abbreviation'] == 'GS'), None)
            opp_team = next((t for t in competitors if t['team']['abbreviation'] != 'GS'), None)
            
            if not gsw_team or not opp_team: continue

            game_info = {
                "date_obj": game_date, # 정렬용
                "date": game_date.astimezone(KST).strftime("%m.%d(%a)"),
                "time": game_date.astimezone(KST).strftime("%H:%M"),
                "opp": opp_team['team']['abbreviation'],
                "is_home": gsw_team['homeAway'] == 'home'
            }

            # 경기 상태 확인 (STATUS_FINAL = 완료)
            status_type = competition['status']['type']['name']
            
            if status_type == 'STATUS_FINAL':
                # 점수 및 승패 처리
                my_score = int(gsw_team.get('score', {}).get('value', 0))
                opp_score = int(opp_team.get('score', {}).get('value', 0))
                result = 'W' if my_score > opp_score else 'L'
                
                game_info['result'] = result
                game_info['score'] = f"{my_score}-{opp_score}"
                completed_games.append(game_info)
            else:
                # 예정된 경기
                future_games.append(game_info)

        # 1. 지난 경기 (가장 최근 것)
        last_game_data = {}
        if completed_games:
            # 날짜순 정렬 후 마지막 요소
            completed_games.sort(key=lambda x: x['date_obj'])
            last = completed_games[-1]
            last_game_data = {
                "date": last['date'],
                "opp": last['opp'],
                "result": last['result'],
                "score": last['score']
            }

        # 2. 향후 경기 (가장 가까운 2개)
        schedule_list = []
        if future_games:
            # 날짜순 정렬 후 앞의 2개
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
        dashboard_data['nba'] = {"status": "Error", "msg": "데이터 수집 실패"}

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
        get_nba_gsw_espn() # 함수명 변경됨
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
