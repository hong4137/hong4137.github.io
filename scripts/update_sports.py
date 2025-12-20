import json
import requests
from datetime import datetime
import pytz
import sys

# 타임존 설정
KST = pytz.timezone('Asia/Seoul')
UTC = pytz.timezone('UTC')

# 기본 데이터 골격
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "record": "-", "rank": "-", "last": {}, "schedule": []},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

def get_nba_gsw_espn():
    print("🏀 NBA 데이터 수집 (ESPN Source)...")
    try:
        # 1. 일정 데이터 가져오기 (기존)
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        res = requests.get(schedule_url, timeout=10)
        data = res.json()
        
        # 2. [추가됨] 팀 순위 & 전적 데이터 가져오기 (NEW)
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        res_team = requests.get(team_url, timeout=10)
        data_team = res_team.json()
        
        # 전적 파싱 (예: "20-8")
        team_record = "0-0"
        try:
            record_items = data_team['team']['record']['items']
            total_record = next((item for item in record_items if item['type'] == 'total'), None)
            if total_record:
                team_record = total_record['summary']
        except:
            pass

        # 순위 파싱 (예: "3rd in Western Conference" -> "3rd West")
        team_rank = "-"
        try:
            standing_text = data_team['team']['standingSummary'] # "3rd in Western Conference"
            if standing_text:
                rank_num = standing_text.split(' ')[0] # "3rd" 만 추출
                team_rank = f"#{rank_num} West"
        except:
            pass

        # --- 기존 일정 로직 (그대로 유지) ---
        events = data.get('events', [])
        completed_games = []
        future_games = []

        for event in events:
            game_date_str = event['date'] 
            game_date = datetime.strptime(game_date_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
            
            competition = event['competitions'][0]
            competitors = competition['competitors']
            
            gsw = next((t for t in competitors if t['team']['abbreviation'] == 'GS'), None)
            opp = next((t for t in competitors if t['team']['abbreviation'] != 'GS'), None)
            
            if not gsw or not opp: continue

            game_info = {
                "date_obj": game_date,  
                "date": game_date.astimezone(KST).strftime("%m.%d(%a)"),
                "time": game_date.astimezone(KST).strftime("%H:%M"),
                "opp": opp['team']['abbreviation'],
                "is_home": gsw['homeAway'] == 'home'
            }

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

        # 지난 경기
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

        # 향후 일정
        schedule_list = []
        if future_games:
            future_games.sort(key=lambda x: x['date_obj'])
            for game in future_games[:2]:
                game_clean = game.copy()
                del game_clean['date_obj'] 
                schedule_list.append(game_clean)

        # 데이터 저장 (순위, 전적 추가됨)
        dashboard_data['nba'] = {
            "status": "Active",
            "record": team_record, # 예: 12-3
            "rank": team_rank,     # 예: #1 West
            "last": last_game_data,
            "schedule": schedule_list
        }
        print(f"✅ NBA 완료: {team_record}, {team_rank}")

    except Exception as e:
        print(f"❌ NBA 에러: {e}")
        dashboard_data['nba'] = {"status": "Error", "msg": "데이터 처리 실패"}

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
