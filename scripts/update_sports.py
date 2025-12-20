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
        # 1. 일정 데이터
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        res = requests.get(schedule_url, timeout=10)
        data = res.json()
        
        # 2. 팀 기본 정보 (전적용)
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        res_team = requests.get(team_url, timeout=10)
        data_team = res_team.json()
        
        # 3. 전체 순위표 (서부 컨퍼런스)
        standings_url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?group=conference"
        res_stand = requests.get(standings_url, timeout=10)
        data_stand = res_stand.json()

        # --- 데이터 가공 ---

        # (1) 전적 (예: "13-15")
        team_record = "0-0"
        try:
            record_items = data_team['team']['record']['items']
            total_record = next((item for item in record_items if item['type'] == 'total'), None)
            if total_record:
                team_record = total_record['summary']
        except:
            pass

        # (2) [핵심 수정] 순위 - ID '10' (GSW) 찾기
        team_rank = "-"
        try:
            # 전체 컨퍼런스 목록 순회
            for conference in data_stand.get('children', []):
                # "Western" 이라는 글자가 들어간 컨퍼런스만 찾음
                if "West" in conference['name']: 
                    
                    entries = conference.get('standings', {}).get('entries', [])
                    
                    # 1등부터 순서대로 내려가며 ID 검사
                    for index, entry in enumerate(entries):
                        team_id = entry['team']['id'] # 팀 ID 추출
                        
                        # GSW의 ID는 '10' 입니다. (문자열 비교)
                        if str(team_id) == '10':
                            rank = index + 1 # 인덱스는 0부터 시작하므로 +1
                            team_rank = f"#{rank} West"
                            print(f"📍 GSW(ID:10) 발견! 순위: {rank}위")
                            break
                    
                    if team_rank != "-": break
        except Exception as e:
            print(f"⚠️ 순위 파싱 에러: {e}")

        # (3) 일정 (기존 코드)
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

        # 데이터 저장
        dashboard_data['nba'] = {
            "status": "Active",
            "record": team_record,
            "rank": team_rank,
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
