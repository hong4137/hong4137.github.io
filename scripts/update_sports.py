#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater
=================================================
EPL: Football-Data.org 무료 API 사용 (10 req/min, 무료 영구)
NBA/Tennis/F1: 추후 추가 예정

[EPL 6가지 룰]
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함 경기

[타임존]
- UK (GMT/BST) → KST: 자동 변환
"""

import os
import json
import datetime
import re
import sys
import requests

# =============================================================================
# 타임존 설정
# =============================================================================
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

TZ_KST = ZoneInfo("Asia/Seoul")
TZ_UTC = ZoneInfo("UTC")
TZ_UK = ZoneInfo("Europe/London")
TZ_PST = ZoneInfo("America/Los_Angeles")

# =============================================================================
# 설정
# =============================================================================
SPORTS_FILE = 'sports.json'
FOOTBALL_DATA_API_URL = "https://api.football-data.org/v4"

# Big 6는 고정값
BIG_6 = ["Manchester City", "Manchester United", "Liverpool", "Arsenal", "Chelsea", "Tottenham"]
BIG_6_ALIASES = {
    "Man City": "Manchester City",
    "Manchester City FC": "Manchester City",
    "Man Utd": "Manchester United",
    "Manchester United FC": "Manchester United",
    "Liverpool FC": "Liverpool",
    "Arsenal FC": "Arsenal",
    "Chelsea FC": "Chelsea",
    "Spurs": "Tottenham",
    "Tottenham Hotspur": "Tottenham",
    "Tottenham Hotspur FC": "Tottenham"
}

def log(message):
    """버퍼링 없이 즉시 출력"""
    print(message, flush=True)

# =============================================================================
# 타임존 변환 함수
# =============================================================================
def get_kst_now():
    """현재 한국 시간 반환"""
    return datetime.datetime.now(TZ_KST)

def convert_utc_to_kst(utc_datetime_str):
    """UTC ISO 형식을 KST로 변환"""
    try:
        # "2026-01-04T15:00:00Z" 형식
        utc_dt = datetime.datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        kst_dt = utc_dt.astimezone(TZ_KST)
        uk_dt = utc_dt.astimezone(TZ_UK)
        
        return {
            'kst_date': kst_dt.strftime("%m.%d"),
            'kst_time': kst_dt.strftime("%H:%M"),
            'kst_full': kst_dt.strftime("%m.%d %H:%M (KST)"),
            'uk_time': uk_dt.strftime("%H:%M"),
            'uk_day': uk_dt.strftime("%A"),  # Saturday, Sunday 등
            'datetime_kst': kst_dt,
            'datetime_uk': uk_dt
        }
    except Exception as e:
        log(f"   ⚠️ UTC→KST 변환 실패: {utc_datetime_str} - {e}")
        return None

def convert_pst_to_kst(date_str, time_str):
    """PST(미국 서부) 시간을 KST로 변환"""
    try:
        if '.' in date_str and len(date_str) <= 5:
            month, day = map(int, date_str.split('.'))
            year = get_kst_now().year
            if month < get_kst_now().month - 6:
                year += 1
        else:
            return date_str, time_str, f"{date_str} {time_str} (PT)"
        
        time_str_clean = time_str.upper().replace(' ', '')
        time_str_clean = re.sub(r'\(.*\)', '', time_str_clean)
        
        if 'PM' in time_str_clean:
            time_str_clean = time_str_clean.replace('PM', '')
            hour, minute = map(int, time_str_clean.split(':')) if ':' in time_str_clean else (int(time_str_clean), 0)
            if hour != 12:
                hour += 12
        elif 'AM' in time_str_clean:
            time_str_clean = time_str_clean.replace('AM', '')
            hour, minute = map(int, time_str_clean.split(':')) if ':' in time_str_clean else (int(time_str_clean), 0)
            if hour == 12:
                hour = 0
        elif ':' in time_str_clean:
            hour, minute = map(int, time_str_clean.split(':'))
        else:
            return date_str, time_str, f"{date_str} {time_str} (PT)"
        
        pst_dt = datetime.datetime(year, month, day, hour, minute, tzinfo=TZ_PST)
        kst_dt = pst_dt.astimezone(TZ_KST)
        
        kst_date_str = kst_dt.strftime("%m.%d")
        kst_time_str = kst_dt.strftime("%H:%M")
        kst_full_str = f"{kst_date_str} {kst_time_str} (KST)"
        
        return kst_date_str, kst_time_str, kst_full_str
        
    except Exception as e:
        log(f"   ⚠️ PST→KST 변환 실패: {date_str} {time_str} - {e}")
        return date_str, time_str, f"{date_str} {time_str} (PT)"

# =============================================================================
# 유틸리티 함수
# =============================================================================
def normalize_team_name(name):
    """팀 이름 정규화"""
    if not name:
        return ""
    name = name.strip()
    return BIG_6_ALIASES.get(name, name)

def is_big_6(team_name):
    """Big 6 팀인지 확인"""
    normalized = normalize_team_name(team_name)
    return any(big in normalized for big in BIG_6)

# =============================================================================
# Football-Data.org API 호출
# =============================================================================
def call_football_api(endpoint, api_key):
    """Football-Data.org API 호출"""
    headers = {
        'X-Auth-Token': api_key
    }
    url = f"{FOOTBALL_DATA_API_URL}{endpoint}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        log(f"   ⚠️ API HTTP 에러: {e}")
        return None
    except requests.exceptions.RequestException as e:
        log(f"   ⚠️ API 요청 실패: {e}")
        return None

def get_epl_standings(api_key):
    """EPL 순위표 가져오기"""
    data = call_football_api("/competitions/PL/standings", api_key)
    
    if not data or 'standings' not in data:
        return None, None, None
    
    # TOTAL 타입의 순위표 찾기
    standings = None
    for s in data['standings']:
        if s.get('type') == 'TOTAL':
            standings = s.get('table', [])
            break
    
    if not standings:
        return None, None, None
    
    # 1위 팀
    leader = standings[0]['team']['name'] if standings else None
    
    # Top 4 팀
    top_4 = [normalize_team_name(s['team']['name']) for s in standings[:4]]
    
    # 현재 매치데이
    current_matchday = data.get('season', {}).get('currentMatchday', None)
    
    return leader, top_4, current_matchday

def get_epl_matches(api_key, matchday=None):
    """EPL 경기 일정 가져오기"""
    endpoint = "/competitions/PL/matches"
    if matchday:
        endpoint += f"?matchday={matchday}"
    else:
        # 예정된 경기만 (status=SCHEDULED,TIMED)
        endpoint += "?status=SCHEDULED,TIMED"
    
    data = call_football_api(endpoint, api_key)
    
    if not data or 'matches' not in data:
        return []
    
    return data['matches']

# =============================================================================
# EPL 6가지 룰 검증
# =============================================================================
def check_epl_rules(home, away, uk_day, uk_time, top_4, leader):
    """EPL 6가지 룰 검증하여 해당하는 룰 반환"""
    rules = []
    
    home_norm = normalize_team_name(home)
    away_norm = normalize_team_name(away)
    
    home_is_big6 = is_big_6(home_norm)
    away_is_big6 = is_big_6(away_norm)
    home_is_top4 = home_norm in top_4
    away_is_top4 = away_norm in top_4
    leader_norm = normalize_team_name(leader) if leader else ""
    
    # 1. Big Match: Big 6 vs Big 6
    if home_is_big6 and away_is_big6:
        rules.append("Big Match")
    
    # 2. Top Tier: Top 4 vs Top 4
    if home_is_top4 and away_is_top4:
        rules.append("Top Tier")
    
    # 3. Challenger: Top 4 vs Big 6 (한쪽만)
    if (home_is_top4 and away_is_big6 and not away_is_top4) or \
       (away_is_top4 and home_is_big6 and not home_is_top4):
        rules.append("Challenger")
    
    # 4. Prime Time: 일요일 16:30 UK
    if uk_day == "Sunday" and uk_time == "16:30":
        rules.append("Prime Time")
    
    # 5. Early KO: 토요일 12:30 UK
    if uk_day == "Saturday" and uk_time == "12:30":
        rules.append("Early KO")
    
    # 6. Leader: 1위 팀 포함
    if leader_norm and (leader_norm in home_norm or leader_norm in away_norm):
        rules.append("Leader")
    
    return rules

def process_epl_matches(matches, top_4, leader):
    """EPL 경기 데이터를 처리하고 6가지 룰로 필터링"""
    validated_matches = []
    
    for match in matches:
        home_team = match.get('homeTeam', {}).get('name', '')
        away_team = match.get('awayTeam', {}).get('name', '')
        utc_date = match.get('utcDate', '')
        
        if not home_team or not away_team or not utc_date:
            continue
        
        # 시간 변환
        time_info = convert_utc_to_kst(utc_date)
        if not time_info:
            continue
        
        # 6가지 룰 검증
        rules = check_epl_rules(
            home_team, 
            away_team,
            time_info['uk_day'],
            time_info['uk_time'],
            top_4,
            leader
        )
        
        # 룰에 해당하는 경기만 포함
        if rules:
            validated_matches.append({
                'home': normalize_team_name(home_team),
                'away': normalize_team_name(away_team),
                'kst_time': time_info['kst_full'],
                'uk_time': f"{time_info['uk_day']} {time_info['uk_time']} (UK)",
                'rules': rules,
                'rule_str': ', '.join(rules)
            })
    
    return validated_matches

# =============================================================================
# NBA 데이터 (임시 - 추후 API 연동)
# =============================================================================
def get_nba_data():
    """NBA 데이터 - 임시 placeholder"""
    return {
        "record": "-",
        "rank": "-",
        "last": {"opp": "-", "result": "-", "score": "-"},
        "schedule": []
    }

# =============================================================================
# Tennis/F1 데이터 (임시)
# =============================================================================
def get_tennis_data():
    """Tennis 데이터 - 임시"""
    return {
        "status": "Off-Season",
        "info": "Australian Open",
        "detail": "Melbourne, Australia",
        "time": "01.12-01.26"
    }

def get_f1_data():
    """F1 데이터 - 임시"""
    return {
        "status": "Off-Season",
        "name": "Australian Grand Prix",
        "circuit": "Albert Park, Melbourne",
        "date": "03.14-03.16"
    }

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    # Football-Data.org API 키 확인
    football_api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not football_api_key:
        log("❌ Error: FOOTBALL_DATA_API_KEY Missing")
        log("   Football-Data.org에서 무료 API 키를 발급받으세요:")
        log("   https://www.football-data.org/client/register")
        raise ValueError("API Key Missing")
    
    kst_now = get_kst_now()
    
    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Data Source: Football-Data.org (Free Tier)")
    
    # =========================================================================
    # STEP 1: EPL 순위 가져오기
    # =========================================================================
    log("\n⚽ [Step 1/3] Premier League 순위...")
    
    leader_team, top_4_teams, current_matchday = get_epl_standings(football_api_key)
    
    if leader_team and top_4_teams:
        log(f"   ✅ 1위: {leader_team}")
        log(f"   ✅ Top 4: {', '.join(top_4_teams)}")
        log(f"   ✅ 현재 라운드: R{current_matchday}")
    else:
        log("   ⚠️ 순위 정보를 가져오지 못했습니다. 기본값 사용.")
        leader_team = "Arsenal"
        top_4_teams = ["Arsenal", "Manchester City", "Liverpool", "Chelsea"]
        current_matchday = None
    
    # =========================================================================
    # STEP 2: EPL 경기 일정 가져오기 + 6가지 룰 적용
    # =========================================================================
    log("\n⚽ [Step 2/3] Premier League 경기 일정 + 6가지 룰 적용...")
    
    # 다음 매치데이 경기 가져오기
    if current_matchday:
        matches = get_epl_matches(football_api_key, matchday=current_matchday)
        if not matches:
            # 현재 매치데이에 경기가 없으면 다음 매치데이
            matches = get_epl_matches(football_api_key, matchday=current_matchday + 1)
    else:
        matches = get_epl_matches(football_api_key)
    
    log(f"   📋 총 {len(matches)}경기 조회됨")
    
    # 6가지 룰 적용
    validated_epl = process_epl_matches(matches, top_4_teams, leader_team)
    log(f"   ✅ 6가지 룰 적용 후: {len(validated_epl)}경기 선별")
    
    for match in validated_epl:
        log(f"      • {match['home']} vs {match['away']} [{match['rule_str']}]")
    
    # =========================================================================
    # STEP 3: NBA / Tennis / F1 (임시)
    # =========================================================================
    log("\n🏀🎾🏎️ [Step 3/3] NBA / Tennis / F1 (임시 데이터)...")
    
    nba_data = get_nba_data()
    tennis_data = get_tennis_data()
    f1_data = get_f1_data()
    
    log("   ✅ 임시 데이터 설정 완료 (추후 API 연동 예정)")
    
    # =========================================================================
    # 최종 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")
    
    epl_round = f"R{current_matchday}" if current_matchday else "R--"
    
    final_data = {
        "updated": get_kst_now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "epl_round": epl_round,
        "standings": {
            "leader": normalize_team_name(leader_team) if leader_team else "-",
            "top_4": top_4_teams if top_4_teams else []
        },
        "epl": validated_epl,
        "nba": nba_data,
        "tennis": tennis_data,
        "f1": f1_data
    }
    
    with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    log(f"\n✅ [Complete]")
    log(f"   EPL: {len(validated_epl)}경기")
    log(f"   파일: {SPORTS_FILE}")

# =============================================================================
# 메인 실행
# =============================================================================
if __name__ == "__main__":
    try:
        update_sports_data()
    except ValueError as e:
        log(f"⚠️ 설정 오류: {e}")
        sys.exit(1)
    except Exception as e:
        log(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
