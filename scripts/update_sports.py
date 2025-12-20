import json
import requests
from datetime import datetime, timedelta
import pytz
from nba_api.stats.endpoints import teamgamelog, scoreboardv2
from nba_api.stats.static import teams

# 한국 시간 설정
KST = pytz.timezone('Asia/Seoul')

# 데이터 담을 그릇
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {},
    "f1": {}
}

def get_nba_gsw():
    print("NBA 데이터 수집 시작...")
    try:
        # 1. GSW 팀 ID 찾기 (Golden State Warriors)
        nba_teams = teams.get_teams()
        gsw = [team for team in nba_teams if team['abbreviation'] == 'GSW'][0]
        gsw_id = gsw['id']

        # 2. 최근 경기 결과 (GameLog)
        # 시즌 자동 계산 (예: 2024-25)
        now = datetime.now()
        season_year = f"{now.year-1}-{str(now.year)[2:]}" if now.month < 10 else f"{now.year}-{str(now.year+1)[2:]}"
        
        # 최근 경기 조회
        gamelog = teamgamelog.TeamGameLog(team_id=gsw_id, season=season_year)
        games = gamelog.get_normalized_dict()['TeamGameLog']
        
        last_game_data = {}
        if games:
            last = games[0] # 가장 최신 경기
            # 점수 포맷: 내 점수 - 상대 점수
            score_gap = last['PLUS_MINUS'] # 점수차
            my_score = last['PTS']
            opp_score = my_score - score_gap
            
            last_game_data = {
                "date": datetime.strptime(last['GAME_DATE'], "%b %d, %Y").strftime("%m.%d"),
                "opp": last['MATCHUP'].split(' ')[-1], # LAL, BOS 등 상대팀 코드만 추출
                "result": last['WL'], # W 또는 L
                "score": f"{int(my_score)} - {int(opp_score)}"
            }

        # 3. 향후 일정 (일주일치 검색)
        schedule_list = []
        check_date = now
        
        # 오늘부터 7일간 매일매일 경기가 있는지 확인
        for _ in range(7):
            date_str = check_date.strftime("%m/%d/%Y")
            try:
                board = scoreboardv2.ScoreboardV2(game_date=date_str, timeout=10)
                games_on_date = board.get_normalized_dict()['GameHeader']
                
                for game in games_on_date:
                    # 홈이거나 원정이거나 GSW가 포함된 경기 찾기
                    if game['HOME_TEAM_ID'] == gsw_id or game['VISITOR_TEAM_ID'] == gsw_id:
                        is_home = (game['HOME_TEAM_ID'] == gsw_id)
                        opp_id = game['VISITOR_TEAM_ID'] if is_home else game['HOME_TEAM_ID']
                        # 상대팀 이름 찾기
                        opp_team = [t for t in nba_teams if t['id'] == opp_id][0]['abbreviation']
                        
                        schedule_list.append({
                            "date": check_date.strftime("%m.%d(%a)"),
                            "opp": opp_team,
                            "is_home": is_home
                        })
            except:
                pass # API 타임아웃 등 에러나면 해당 날짜 스킵
            
            check_date += timedelta(days=1)

        dashboard_data['nba'] = {
            "status": "Active",
            "last": last_game_data,
            "schedule": schedule_list
        }
        print("NBA 완료")

    except Exception as e:
        print(f"NBA 에러: {e}")
        dashboard_data['nba'] = {"status": "Error", "msg": str(e)}

def get_f1_schedule():
    print("F1 데이터 수집 시작...")
    try:
        # 다음 경기 정보 요청
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=10)
        data = res.json()
        
        race_table = data.get('MRData', {}).get('RaceTable', {})
        
        if not race_table.get('Races'):
            # 비시즌
            dashboard_data['f1'] = {
                "status": "Off Season",
                "name": "2026 Season",
                "date": "Waiting...",
                "circuit": "-"
            }
        else:
            # 시즌 중 (다음 경기 있음)
            race = race_table['Races'][0]
            # 시간 변환 (UTC -> 한국시간)
            race_time_utc = f"{race['date']} {race.get('time', '00:00:00Z')}"
            utc_dt = datetime.strptime(race_time_utc, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=pytz.utc)
            kst_dt = utc_dt.astimezone(KST)

            dashboard_data['f1'] = {
                "status": "Next GP",
                "name": race['raceName'].replace(" Grand Prix", " GP"),
                "date": kst_dt.strftime("%m.%d(%a) %H:%M"),
                "circuit": race['Circuit']['circuitName']
            }
        print("F1 완료")

    except Exception as e:
        print(f"F1 에러: {e}")
        dashboard_data['f1'] = {"status": "Error", "name": "Check Data"}

if __name__ == "__main__":
    get_nba_gsw()
    get_f1_schedule()
    
    # sports.json 파일로 저장
    with open('sports.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
        print("sports.json 저장 완료")
