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
        # 1. 일정 데이터 (Schedule)
        schedule_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs/schedule"
        res = requests.get(schedule_url, timeout=10)
        data = res.json()
        
        # 2. 팀 기본 정보 (전적용)
        team_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/gs"
        res_team = requests.get(team_url, timeout=10)
        data_team = res_team.json()
        
        # 3. [핵심 수정] 전체 순위표 (Standings) - 여기서 진짜 등수를 찾습니다
        standings_url = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
        res_stand = requests.get(standings_url, timeout=10)
        data_stand = res_stand.json()

        # --- 데이터 가공 시작 ---

        # (1) 전적 파싱 (예: "13-15")
        team_record = "0-0"
        try:
            record_items = data_team['team']['record']['items']
            total_record = next((item for item in record_items if item['type'] == 'total'), None)
            if total_record:
                team_record = total_record['summary']
        except:
            pass

        # (2) 순위 파싱 (디비전 순위가 아닌 '서부 컨퍼런스 시드' 찾기)
        team_rank = "-"
        try:
            # GSW 팀 ID는 '10'입니다.
            # 전체 컨퍼런스 목록(children)을 순회하며 GSW를 찾습니다.
            for conference in data_stand.get('children', []):
                # 서부/동부 컨퍼런스 이름 (예: "Western Conference")
                conf_name = conference['name'] 
                
                # 해당 컨퍼런스의 팀 목록 조회
                for entry in conference.get('standings', {}).get('entries', []):
                    if entry['team']['id'] == '10': # GSW 발견!
                        # 통계 목록(stats)에서 'playoffSeed'(시드 배정 순위) 찾기
                        stats = entry.get('stats', [])
                        seed_stat = next((s for s in stats if s['name'] == 'playoffSeed'), None)
                        
                        if seed_stat:
                            rank_num = int(seed_stat['value']) # 9.0 -> 9
                            # "Western Conference" -> "West"로 줄임
                            short_conf = "West" if "West" in conf_name else "East"
                            team_rank = f"#{rank_num} {short_conf}" # 예: "#9 West"
                        break
                if team_rank != "-": break
        except Exception as e:
            print(f"순위 파싱 에러: {e}")

        # (3) 일정 파싱 (기존 로직 유지)
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

        # 최종 데이터 저장
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
