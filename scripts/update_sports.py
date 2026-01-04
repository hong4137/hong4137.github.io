#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater
=================================================
EPL: Football-Data.org 무료 API (순위, 일정)
EPL 중계/F1/Tennis: Serper API 검색 (월 2,500회 무료)
NBA: 추후 API 연동 예정

[EPL 6가지 룰] - 순서 중요!
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6 - 서로 다른 조건)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함 경기

[데이터 흐름]
1. Football-Data.org → EPL 순위 (1위, Top 4) 확인
2. Football-Data.org → EPL 경기 일정 조회
3. Python에서 6가지 룰 적용하여 경기 필터링
4. Serper API → 선별된 경기의 중계 정보 검색
5. Serper API → F1 다음 그랑프리 검색
6. Serper API → Tennis (Alcaraz) 일정 검색

[타임존]
- UK (GMT/BST) → KST: 자동 변환 (zoneinfo 사용)
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
SERPER_API_URL = "https://google.serper.dev/search"

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
            'uk_date': uk_dt.strftime("%m.%d"),
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
# Serper API 호출
# =============================================================================
def call_serper_api(query, api_key):
    """Serper API로 Google 검색"""
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }
    
    payload = {
        'q': query,
        'gl': 'uk',  # UK 결과 우선
        'hl': 'en',
        'num': 5
    }
    
    try:
        response = requests.post(SERPER_API_URL, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log(f"   ⚠️ Serper API 에러: {e}")
        return None

def search_epl_broadcaster(home, away, match_date, serper_key):
    """EPL 경기 중계 정보 검색"""
    query = f"Premier League {home} vs {away} {match_date} TV channel UK"
    
    result = call_serper_api(query, serper_key)
    if not result:
        return None
    
    # 검색 결과에서 중계사 추출
    broadcasters = ['Sky Sports', 'TNT Sports', 'BBC', 'Amazon Prime']
    
    # organic 결과와 answerBox 확인
    text_to_search = ""
    
    if 'answerBox' in result:
        text_to_search += result['answerBox'].get('snippet', '') + " "
        text_to_search += result['answerBox'].get('answer', '') + " "
    
    for item in result.get('organic', [])[:3]:
        text_to_search += item.get('snippet', '') + " "
        text_to_search += item.get('title', '') + " "
    
    # 중계사 찾기
    for broadcaster in broadcasters:
        if broadcaster.lower() in text_to_search.lower():
            return broadcaster
    
    # BT Sport은 TNT Sports로 리브랜딩됨
    if 'bt sport' in text_to_search.lower():
        return 'TNT Sports'
    
    return None

def search_f1_schedule(serper_key):
    """F1 다음 그랑프리 검색"""
    query = "F1 2026 next Grand Prix schedule date circuit"
    
    result = call_serper_api(query, serper_key)
    if not result:
        return None
    
    f1_data = {
        'status': 'Off-Season',
        'name': 'TBD',
        'circuit': 'TBD',
        'date': ''
    }
    
    text_to_search = ""
    
    if 'answerBox' in result:
        text_to_search += result['answerBox'].get('snippet', '') + " "
        text_to_search += result['answerBox'].get('answer', '') + " "
    
    for item in result.get('organic', [])[:3]:
        text_to_search += item.get('snippet', '') + " "
    
    # 그랑프리 이름 추출
    gp_patterns = [
        r'(Australian|Bahrain|Saudi Arabian|Japanese|Chinese|Miami|Monaco|Canadian|Spanish|Austrian|British|Hungarian|Belgian|Dutch|Italian|Singapore|United States|Mexico|Brazilian|Las Vegas|Abu Dhabi)\s*(?:Grand Prix|GP)',
    ]
    
    for pattern in gp_patterns:
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            f1_data['name'] = f"{match.group(1)} Grand Prix"
            break
    
    # 날짜 패턴 추출 (March 14-16, 2026 등)
    date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:-(\d{1,2}))?,?\s*(\d{4})?'
    date_match = re.search(date_pattern, text_to_search, re.IGNORECASE)
    if date_match:
        month = date_match.group(1)[:3]
        day_start = date_match.group(2)
        day_end = date_match.group(3) or day_start
        f1_data['date'] = f"{month} {day_start}-{day_end}"
    
    # 서킷 추출
    circuit_patterns = [
        r'(Albert Park|Sakhir|Jeddah|Suzuka|Shanghai|Miami|Monaco|Montreal|Barcelona|Red Bull Ring|Silverstone|Hungaroring|Spa|Zandvoort|Monza|Marina Bay|COTA|Austin|Hermanos|Interlagos|Las Vegas|Yas Marina)',
    ]
    
    for pattern in circuit_patterns:
        match = re.search(pattern, text_to_search, re.IGNORECASE)
        if match:
            f1_data['circuit'] = match.group(1)
            break
    
    # 시즌 상태 판단
    kst_now = get_kst_now()
    if kst_now.month >= 3 and kst_now.month <= 12:
        f1_data['status'] = 'Season 2026'
    else:
        f1_data['status'] = 'Off-Season'
    
    return f1_data

def search_tennis_schedule(serper_key):
    """
    Tennis (Alcaraz) 일정 검색
    
    [규칙]
    1. 친선경기(Exhibition)가 있으면 친선경기 우선 표시
    2. 친선경기가 없으면 다음 공식 대회 표시
    """
    # 먼저 친선경기 검색
    exhibition_query = "Carlos Alcaraz exhibition match 2026 January"
    exhibition_result = call_serper_api(exhibition_query, serper_key)
    
    exhibition_text = ""
    if exhibition_result:
        if 'answerBox' in exhibition_result:
            exhibition_text += exhibition_result['answerBox'].get('snippet', '') + " "
            exhibition_text += exhibition_result['answerBox'].get('answer', '') + " "
        for item in exhibition_result.get('organic', [])[:3]:
            exhibition_text += item.get('snippet', '') + " "
            exhibition_text += item.get('title', '') + " "
    
    # 친선경기 감지
    exhibition_keywords = ['exhibition', 'showdown', 'friendly', 'charity', 'invitational']
    is_exhibition = any(kw in exhibition_text.lower() for kw in exhibition_keywords)
    
    if is_exhibition:
        tennis_data = {
            'status': 'Exhibition',
            'info': 'Exhibition Match',
            'detail': '',
            'time': ''
        }
        
        # 상대 선수 추출 (Sinner, Djokovic 등)
        top_players = ['Sinner', 'Djokovic', 'Nadal', 'Federer', 'Medvedev', 'Zverev', 'Ruud', 'Tsitsipas']
        for player in top_players:
            if player.lower() in exhibition_text.lower():
                tennis_data['detail'] = f"vs {player}"
                break
        
        # 장소 추출
        locations = ['Seoul', 'Incheon', 'Hong Kong', 'Abu Dhabi', 'Riyadh', 'Melbourne', 'Sydney']
        for loc in locations:
            if loc.lower() in exhibition_text.lower():
                if tennis_data['detail']:
                    tennis_data['detail'] += f" ({loc})"
                else:
                    tennis_data['detail'] = loc
                break
        
        # 날짜 추출
        date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:-(\d{1,2}))?'
        date_match = re.search(date_pattern, exhibition_text, re.IGNORECASE)
        if date_match:
            month = date_match.group(1)[:3]
            day_start = date_match.group(2)
            day_end = date_match.group(3)
            if day_end:
                tennis_data['time'] = f"{month} {day_start}-{day_end}"
            else:
                tennis_data['time'] = f"{month} {day_start}"
        
        return tennis_data
    
    # 친선경기가 없으면 다음 공식 대회 검색
    tournament_query = "Carlos Alcaraz next tournament 2026 schedule"
    result = call_serper_api(tournament_query, serper_key)
    
    if not result:
        return None
    
    tennis_data = {
        'status': 'Off-Season',
        'info': 'TBD',
        'detail': '',
        'time': ''
    }
    
    text_to_search = ""
    
    if 'answerBox' in result:
        text_to_search += result['answerBox'].get('snippet', '') + " "
        text_to_search += result['answerBox'].get('answer', '') + " "
    
    for item in result.get('organic', [])[:3]:
        text_to_search += item.get('snippet', '') + " "
    
    # 대회 이름 추출
    tournaments = [
        'Australian Open', 'French Open', 'Roland Garros', 'Wimbledon', 'US Open',
        'ATP Finals', 'Indian Wells', 'Miami Open', 'Monte Carlo', 'Madrid Open',
        'Italian Open', 'Cincinnati', 'Shanghai Masters', 'Canada Masters'
    ]
    
    for tournament in tournaments:
        if tournament.lower() in text_to_search.lower():
            tennis_data['info'] = tournament
            tennis_data['status'] = 'Tournament'
            break
    
    # 날짜 패턴
    date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:-(\d{1,2}))?'
    date_match = re.search(date_pattern, text_to_search, re.IGNORECASE)
    if date_match:
        month = date_match.group(1)[:3]
        day_start = date_match.group(2)
        day_end = date_match.group(3)
        if day_end:
            tennis_data['time'] = f"{month} {day_start}-{day_end}"
        else:
            tennis_data['time'] = f"{month} {day_start}"
    
    # 장소 추출
    locations = ['Melbourne', 'Paris', 'London', 'New York', 'Indian Wells', 'Miami', 'Madrid', 'Rome']
    for loc in locations:
        if loc.lower() in text_to_search.lower():
            tennis_data['detail'] = loc
            break
    
    return tennis_data

# =============================================================================
# EPL 6가지 룰 검증 (순서 중요!)
# =============================================================================
def check_epl_rules(home, away, uk_day, uk_time, top_4, leader):
    """
    EPL 6가지 룰 검증하여 해당하는 룰 반환
    
    [룰 순서]
    1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
    2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
    3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6 - 서로 다른 조건)
    4. Prime Time: 일요일 16:30 UK
    5. Early KO: 토요일 12:30 UK
    6. Leader: 리그 1위 팀 포함
    """
    rules = []
    
    home_norm = normalize_team_name(home)
    away_norm = normalize_team_name(away)
    
    home_is_big6 = is_big_6(home_norm)
    away_is_big6 = is_big_6(away_norm)
    home_is_top4 = home_norm in top_4
    away_is_top4 = away_norm in top_4
    leader_norm = normalize_team_name(leader) if leader else ""
    
    # 1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
    if home_is_big6 and away_is_big6:
        rules.append("Big Match")
    
    # 2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
    if home_is_top4 and away_is_top4:
        rules.append("Top Tier")
    
    # 3. Challenger: Top 4 vs Big 6 (한쪽 Top 4이면서 Big 6 아님, 다른쪽 Big 6)
    # 조건: (홈이 Top4 & Big6 아님) AND (원정이 Big6) OR 그 반대
    if (home_is_top4 and not home_is_big6 and away_is_big6) or \
       (away_is_top4 and not away_is_big6 and home_is_big6):
        rules.append("Challenger")
    
    # 4. Prime Time: 일요일 16:30 UK
    if uk_day == "Sunday" and uk_time == "16:30":
        rules.append("Prime Time")
    
    # 5. Early KO: 토요일 12:30 UK
    if uk_day == "Saturday" and uk_time == "12:30":
        rules.append("Early KO")
    
    # 6. Leader: 1위 팀 포함
    if leader_norm:
        if leader_norm in home_norm or home_norm in leader_norm or \
           leader_norm in away_norm or away_norm in leader_norm:
            rules.append("Leader")
    
    return rules

def process_epl_matches(matches, top_4, leader, serper_key=None):
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
            home_norm = normalize_team_name(home_team)
            away_norm = normalize_team_name(away_team)
            
            # 중계 정보 검색 (Serper API 사용 시)
            channel = None
            if serper_key:
                channel = search_epl_broadcaster(
                    home_norm, 
                    away_norm, 
                    time_info['uk_date'],
                    serper_key
                )
            
            validated_matches.append({
                'home': home_norm,
                'away': away_norm,
                'kst_time': time_info['kst_full'],
                'uk_time': f"{time_info['uk_day']} {time_info['uk_time']} (UK)",
                'local': channel or '',  # 중계 정보
                'rules': rules,
                'rule_str': ', '.join(rules)
            })
    
    return validated_matches

# =============================================================================
# NBA 데이터 (Serper 검색)
# =============================================================================
def search_nba_warriors(serper_key):
    """
    Golden State Warriors 정보 검색
    
    [검색 항목]
    1. 시즌 전적 (W-L)
    2. 컨퍼런스 순위
    3. 최근 경기 결과
    4. 다음 일정 (상대, 날짜, 시간)
    """
    if not serper_key:
        return get_nba_default_data()
    
    nba_data = {
        "record": "-",
        "rank": "-",
        "last": {"opp": "-", "result": "-", "score": "-"},
        "schedule": []
    }
    
    # =========================================================================
    # 1. 전적 + 순위 + 최근 경기 검색
    # =========================================================================
    status_query = "Golden State Warriors record standings 2025-26 season"
    status_result = call_serper_api(status_query, serper_key)
    
    if status_result:
        status_text = ""
        
        if 'answerBox' in status_result:
            status_text += status_result['answerBox'].get('snippet', '') + " "
            status_text += status_result['answerBox'].get('answer', '') + " "
        
        # Knowledge Graph에서 정보 추출
        if 'knowledgeGraph' in status_result:
            kg = status_result['knowledgeGraph']
            status_text += kg.get('description', '') + " "
            for attr in kg.get('attributes', {}).values():
                status_text += str(attr) + " "
        
        for item in status_result.get('organic', [])[:5]:
            status_text += item.get('snippet', '') + " "
        
        # 전적 추출 (예: 18-16, 20-15 등)
        record_pattern = r'(\d{1,2})-(\d{1,2})'
        record_matches = re.findall(record_pattern, status_text)
        for wins, losses in record_matches:
            wins, losses = int(wins), int(losses)
            # 합리적인 범위의 전적만 (총 경기 10~82 사이)
            if 10 <= wins + losses <= 82:
                nba_data['record'] = f"{wins}-{losses}"
                break
        
        # 순위 추출
        rank_patterns = [
            r'(\d{1,2})(?:st|nd|rd|th)\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
            r'(?:Western|West)(?:ern)?\s+(?:Conference\s+)?(?:rank(?:ing)?|place|seed)[:\s]+(\d{1,2})',
            r'#(\d{1,2})\s+(?:in\s+)?(?:Western|West)',
        ]
        
        for pattern in rank_patterns:
            rank_match = re.search(pattern, status_text, re.IGNORECASE)
            if rank_match:
                rank_num = rank_match.group(1)
                nba_data['rank'] = f"#{rank_num} West"
                break
    
    # =========================================================================
    # 2. 최근 경기 결과 검색
    # =========================================================================
    last_game_query = "Golden State Warriors last game result score"
    last_result = call_serper_api(last_game_query, serper_key)
    
    if last_result:
        last_text = ""
        
        if 'answerBox' in last_result:
            last_text += last_result['answerBox'].get('snippet', '') + " "
            last_text += last_result['answerBox'].get('answer', '') + " "
        
        if 'sportsResults' in last_result:
            sports = last_result['sportsResults']
            last_text += str(sports) + " "
        
        for item in last_result.get('organic', [])[:3]:
            last_text += item.get('snippet', '') + " "
        
        # NBA 팀 목록
        nba_teams = [
            'Lakers', 'Clippers', 'Suns', 'Kings', 'Nuggets', 'Thunder', 'Mavericks',
            'Rockets', 'Spurs', 'Grizzlies', 'Pelicans', 'Timberwolves', 'Jazz', 'Trail Blazers',
            'Celtics', 'Nets', 'Knicks', '76ers', 'Raptors', 'Bulls', 'Cavaliers', 'Pistons',
            'Pacers', 'Bucks', 'Hawks', 'Heat', 'Hornets', 'Magic', 'Wizards'
        ]
        
        # 상대팀 추출
        for team in nba_teams:
            if team.lower() in last_text.lower():
                nba_data['last']['opp'] = team
                break
        
        # 승패 추출
        if 'warriors' in last_text.lower():
            if re.search(r'warriors?\s+(?:beat|defeated|won|victory)', last_text, re.IGNORECASE):
                nba_data['last']['result'] = 'W'
            elif re.search(r'warriors?\s+(?:lost?|fell|defeat)', last_text, re.IGNORECASE):
                nba_data['last']['result'] = 'L'
            elif re.search(r'(?:beat|defeated|over)\s+(?:the\s+)?warriors', last_text, re.IGNORECASE):
                nba_data['last']['result'] = 'L'
        
        # 스코어 추출 (예: 120-115, 108-102)
        score_pattern = r'(\d{2,3})-(\d{2,3})'
        score_matches = re.findall(score_pattern, last_text)
        for score1, score2 in score_matches:
            s1, s2 = int(score1), int(score2)
            # NBA 스코어 범위 (80-150)
            if 80 <= s1 <= 160 and 80 <= s2 <= 160:
                nba_data['last']['score'] = f"{score1}-{score2}"
                break
    
    # =========================================================================
    # 3. 다음 일정 검색
    # =========================================================================
    schedule_query = "Golden State Warriors next games schedule January 2026"
    schedule_result = call_serper_api(schedule_query, serper_key)
    
    if schedule_result:
        schedule_text = ""
        
        if 'answerBox' in schedule_result:
            schedule_text += schedule_result['answerBox'].get('snippet', '') + " "
        
        for item in schedule_result.get('organic', [])[:5]:
            schedule_text += item.get('snippet', '') + " "
            schedule_text += item.get('title', '') + " "
        
        # NBA 팀 목록 (위에서 정의)
        nba_teams = [
            'Lakers', 'Clippers', 'Suns', 'Kings', 'Nuggets', 'Thunder', 'Mavericks',
            'Rockets', 'Spurs', 'Grizzlies', 'Pelicans', 'Timberwolves', 'Jazz', 'Trail Blazers',
            'Celtics', 'Nets', 'Knicks', '76ers', 'Raptors', 'Bulls', 'Cavaliers', 'Pistons',
            'Pacers', 'Bucks', 'Hawks', 'Heat', 'Hornets', 'Magic', 'Wizards', 'Warriors'
        ]
        
        # 일정에서 팀과 날짜 추출 시도
        # 패턴: "Jan 5 vs Lakers" 또는 "@ Suns Jan 7"
        games_found = []
        
        # 날짜 패턴들
        date_patterns = [
            r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?)\s*\.?\s*(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})',  # 1/5 형식
        ]
        
        for team in nba_teams:
            if team.lower() == 'warriors':
                continue
            if team.lower() in schedule_text.lower():
                # 해당 팀 주변에서 날짜 찾기
                team_idx = schedule_text.lower().find(team.lower())
                context = schedule_text[max(0, team_idx-50):team_idx+50]
                
                for date_pattern in date_patterns:
                    date_match = re.search(date_pattern, context, re.IGNORECASE)
                    if date_match:
                        if '/' in date_pattern:
                            month, day = date_match.groups()
                            date_str = f"{int(month):02d}.{int(day):02d}"
                        else:
                            month_str, day = date_match.groups()
                            month_map = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
                                        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
                                        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
                            month_num = month_map.get(month_str[:3].lower(), '01')
                            date_str = f"{month_num}.{int(day):02d}"
                        
                        # 홈/어웨이 판단
                        location = 'home'
                        if '@' in context or 'at ' + team.lower() in context.lower():
                            location = 'away'
                        
                        games_found.append({
                            'opp': team,
                            'date': date_str,
                            'time': 'TBD',
                            'location': location,
                            'kst_time': 'TBD',
                            'local_time': 'TBD'
                        })
                        break
        
        # 중복 제거 및 정렬
        seen_teams = set()
        unique_games = []
        for game in games_found:
            if game['opp'] not in seen_teams:
                seen_teams.add(game['opp'])
                unique_games.append(game)
        
        nba_data['schedule'] = unique_games[:6]  # 최대 6경기
    
    return nba_data

def get_nba_default_data():
    """NBA 기본 데이터 (API 키 없을 때)"""
    return {
        "record": "-",
        "rank": "-",
        "last": {"opp": "-", "result": "-", "score": "-"},
        "schedule": []
    }

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    # API 키 확인
    football_api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    serper_api_key = os.environ.get("SERPER_API_KEY")
    
    if not football_api_key:
        log("❌ Error: FOOTBALL_DATA_API_KEY Missing")
        log("   Football-Data.org에서 무료 API 키를 발급받으세요:")
        log("   https://www.football-data.org/client/register")
        raise ValueError("FOOTBALL_DATA_API_KEY Missing")
    
    if not serper_api_key:
        log("⚠️ Warning: SERPER_API_KEY Missing")
        log("   중계/F1/Tennis 정보는 검색하지 않습니다.")
        log("   Serper API 키: https://serper.dev")
    
    kst_now = get_kst_now()
    
    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Data Sources:")
    log(f"   - EPL: Football-Data.org (Free Tier)")
    log(f"   - Search: Serper API {'✅' if serper_api_key else '❌'}")
    
    # =========================================================================
    # STEP 1: EPL 순위 가져오기
    # =========================================================================
    log("\n⚽ [Step 1/4] Premier League 순위...")
    
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
    log("\n⚽ [Step 2/4] Premier League 경기 일정 + 6가지 룰 적용...")
    log("   [룰 순서]")
    log("   1. Big Match: Big 6 vs Big 6")
    log("   2. Top Tier: Top 4 vs Top 4")
    log("   3. Challenger: Top 4 vs Big 6 (서로 다른 조건)")
    log("   4. Prime Time: 일요일 16:30 UK")
    log("   5. Early KO: 토요일 12:30 UK")
    log("   6. Leader: 1위 팀 포함")
    
    # 다음 매치데이 경기 가져오기
    if current_matchday:
        matches = get_epl_matches(football_api_key, matchday=current_matchday)
        if not matches:
            # 현재 매치데이에 경기가 없으면 다음 매치데이
            matches = get_epl_matches(football_api_key, matchday=current_matchday + 1)
    else:
        matches = get_epl_matches(football_api_key)
    
    log(f"\n   📋 총 {len(matches)}경기 조회됨")
    
    # 6가지 룰 적용 + 중계 정보 검색
    validated_epl = process_epl_matches(matches, top_4_teams, leader_team, serper_api_key)
    log(f"   ✅ 6가지 룰 적용 후: {len(validated_epl)}경기 선별")
    
    for match in validated_epl:
        channel_info = f" | {match['local']}" if match['local'] else ""
        log(f"      • {match['home']} vs {match['away']} [{match['rule_str']}]{channel_info}")
    
    # =========================================================================
    # STEP 3: NBA Warriors 검색 (Serper)
    # =========================================================================
    log("\n🏀 [Step 3/5] NBA Warriors 정보 검색...")
    
    if serper_api_key:
        nba_data = search_nba_warriors(serper_api_key)
        log(f"   ✅ 전적: {nba_data['record']} | 순위: {nba_data['rank']}")
        if nba_data['last']['opp'] != '-':
            log(f"   ✅ 최근 경기: vs {nba_data['last']['opp']} {nba_data['last']['result']} ({nba_data['last']['score']})")
        log(f"   ✅ 다음 일정: {len(nba_data['schedule'])}경기")
        for game in nba_data['schedule'][:3]:
            loc_icon = '🏠' if game.get('location') == 'home' else '✈️'
            log(f"      {loc_icon} {game['date']} vs {game['opp']}")
    else:
        nba_data = get_nba_default_data()
        log("   ⏭️ Serper API 키 없음, 기본값 사용")
    
    # =========================================================================
    # STEP 4: F1 일정 검색 (Serper)
    # =========================================================================
    log("\n🏎️ [Step 4/5] F1 일정 검색...")
    
    if serper_api_key:
        f1_data = search_f1_schedule(serper_api_key)
        if f1_data:
            log(f"   ✅ {f1_data['name']} | {f1_data['circuit']} | {f1_data['date']}")
        else:
            f1_data = {
                "status": "Off-Season",
                "name": "Australian Grand Prix",
                "circuit": "Albert Park, Melbourne",
                "date": "Mar 14-16"
            }
            log("   ⚠️ 검색 실패, 기본값 사용")
    else:
        f1_data = {
            "status": "Off-Season",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park, Melbourne",
            "date": "Mar 14-16"
        }
        log("   ⏭️ Serper API 키 없음, 기본값 사용")
    
    # =========================================================================
    # STEP 5: Tennis 일정 검색 (Serper)
    # =========================================================================
    log("\n🎾 [Step 5/5] Tennis (Alcaraz) 일정 검색...")
    
    if serper_api_key:
        tennis_data = search_tennis_schedule(serper_api_key)
        if tennis_data:
            log(f"   ✅ {tennis_data['status']} | {tennis_data['info']} | {tennis_data['detail']}")
        else:
            tennis_data = {
                "status": "Off-Season",
                "info": "Australian Open",
                "detail": "Melbourne, Australia",
                "time": "Jan 12-26"
            }
            log("   ⚠️ 검색 실패, 기본값 사용")
    else:
        tennis_data = {
            "status": "Off-Season",
            "info": "Australian Open",
            "detail": "Melbourne, Australia",
            "time": "Jan 12-26"
        }
        log("   ⏭️ Serper API 키 없음, 기본값 사용")
    
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
