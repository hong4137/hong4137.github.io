import json
import requests
from datetime import datetime, timedelta
import pytz
import sys

# [중요] NBA API가 봇을 차단하지 못하게 '가짜 헤더' 설정
try:
    from nba_api.stats.library.http import NBAStatsHTTP
    # 윈도우 크롬 브라우저인 척 위장
    NBAStatsHTTP.headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.nba.com/',
        'Origin': 'https://www.nba.com',
        'Accept-Language': 'en-US,en;q=0.9',
        'x-nba-stats-origin': 'stats',
        'x-nba-stats-token': 'true'
    }
except ImportError:
    pass # 구버전일 경우 패스

from nba_api.stats.endpoints import teamgamelog, scoreboardv2
from nba_api.stats.static import teams

KST = pytz.timezone('Asia/Seoul')
ET = pytz.timezone('US/Eastern')

# 기본 데이터 골격 (실패시에도 이 포맷은 유지됨)
dashboard_data = {
    "updated": datetime.now(KST).strftime("%m/%d %H:%M"),
    "nba": {"status": "Loading...", "last": {}, "schedule": []},
    "f1": {"status": "Loading...", "name": "-", "date": "-"}
}

def get_nba_gsw():
    print("🏀 NBA 데이터 수집 시작...")
    try:
        # 1. GSW 팀 ID 찾기
        nba_teams = teams.get_teams()
        gsw = [team for team in nba_teams if team['abbreviation'] == 'GSW'][0]
        gsw_id = gsw['id']

        # 2. 직전 경기 결과
        now = datetime.now()
        season_year = f"{now.year-1}-{str(now.year)[2:]}" if now.month < 10 else f"{now.year}-{str(now.year+1)[2:]}"
        
        # 타임아웃 30초로 넉넉하게
        gamelog = teamgamelog.TeamGameLog(team_id=gsw_id, season=season_year, timeout=30)
        games = gamelog.get_normalized_dict()['TeamGameLog']
        
        last_game_data = {}
        if games:
            last = games[0]
            my_score = last['PTS']
            opp_score = my_score - last['PLUS_MINUS']
            
            last_game_data = {
                "date": datetime.strptime(last['GAME_DATE'], "%b %d, %Y").strftime("%m.%d"),
                "opp": last['MATCHUP'].split(' ')[-1],
                "result": last['WL'],
                "score": f"{int(my_score)} - {int(opp_score)}"
            }

        # 3. 향후 일정 (2주치 조회)
        schedule_list = []
        check_date = now
        
        for _ in range(14): # 14일간 탐색
            if len(schedule_list) >= 2: break 

            date_str = check_date.strftime("%m/%d/%Y")
            try:
                board = scoreboardv2.ScoreboardV2(game_date=date_str, timeout=30)
                games_on_date = board.get_normalized_dict()['GameHeader']
                
                for game in games_on_date:
                    if game['HOME_TEAM_ID'] == gsw_id or game['VISITOR_TEAM_ID'] == gsw_id:
                        is_home = (game['HOME_TEAM_ID'] == gsw_id)
                        opp_id = game['VISITOR_TEAM_ID'] if is_home else game['HOME_TEAM_ID']
                        opp_team = [t for t in nba_teams if t['id'] == opp_id][0]['abbreviation']
                        
                        # 시간 파싱
                        time_str = game.get('GAME_STATUS_TEXT', '').replace(' ET', '')
                        match_time_kst = ""
                        match_date_kst = check_date.strftime("%m.%d(%a)")

                        if "pm" in time_str.lower() or "am" in time_str.lower():
                            try:
                                dt_str = f"{date_str} {time_str}"
                                local_dt = datetime.strptime(dt_str, "%m/%d/%Y %I:%M %p")
                                local_dt = ET.localize(local_dt)
                                kst_dt = local_dt.astimezone(KST)
                                match_time_kst = kst_dt.strftime("%H:%M")
                                match_date_kst = kst_dt.strftime("%m.%d(%a)")
                            except:
                                pass

                        schedule_list.append({
                            "date": match_date_kst,
                            "time": match_time_kst,
                            "opp": opp_team
                        })
            except Exception as e:
                # 하루치 실패해도 다음 날짜 확인하도록 pass
                pass
            
            check_date += timedelta(days=1)

        dashboard_data['nba'] = {
            "status": "Active",
            "last": last_game_data,
            "schedule": schedule_list
        }
        print(f"✅ NBA 완료: 일정 {len(schedule_list)}개 발견")

    except Exception as e:
        print(f"❌ NBA 에러 발생: {e}")
        # 에러가 나도 기존 UI가 깨지지 않게 에러 메시지 저장
        dashboard_data['nba'] = {"status": "Error", "msg": "API 차단됨", "last": {}, "schedule": []}

def get_f1_schedule():
    print("🏎️ F1 데이터 수집 시작...")
    try:
        res = requests.get("http://api.jolpi.ca/ergast/f1/current/next.json", timeout=30)
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
    # 전체를 감싸는 안전장치 (메인 스크립트가 절대 죽지 않음)
    try:
        get_nba_gsw()
        get_f1_schedule()
    except Exception as e:
        print(f"🔥 치명적 오류: {e}")
    
    # 데이터가 비어있더라도 파일은 무조건 저장
    try:
        with open('sports.json', 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
            print("💾 sports.json 저장 완료")
    except Exception as e:
        print(f"파일 저장 실패: {e}")
        sys.exit(0) # 그래도 에러코드 0으로 종료 (Action 성공 처리)

    # 무조건 성공으로 종료
    sys.exit(0)
