#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater v2
====================================================
EPL: Football-Data.org 무료 API (순위, 일정)
NBA: balldontlie.io 무료 API (일정, 결과)
EPL 중계/F1/Tennis: Serper API 검색 (월 2,500회 무료)

[EPL 6가지 룰] - 순서 중요!
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6 - 서로 다른 조건)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함 경기
"""

import os
import json
import datetime
import re
import sys
import requests
from datetime import timedelta

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
BALLDONTLIE_API_URL = "https://api.balldontlie.io/v1"
WARRIORS_TEAM_ID = 10  # Golden State Warriors

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
        utc_dt = datetime.datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        kst_dt = utc_dt.astimezone(TZ_KST)
        uk_dt = utc_dt.astimezone(TZ_UK)
        
        return {
            'kst_date': kst_dt.strftime("%m.%d"),
            'kst_time': kst_dt.strftime("%H:%M"),
            'kst_full': kst_dt.strftime("%m.%d %H:%M (KST)"),
            'uk_time': uk_dt.strftime("%H:%M"),
            'uk_day': uk_dt.strftime("%A"),
            'uk_date': uk_dt.strftime("%m.%d"),
            'datetime_kst': kst_dt,
            'datetime_uk': uk_dt
        }
    except:
        return None

# =============================================================================
# API 호출 함수들
# =============================================================================
def call_serper_api(query, api_key):
    """Serper API 호출"""
    if not api_key:
        return None
    
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "gl": "uk", "hl": "en"}
    
    try:
        response = requests.post(SERPER_API_URL, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

def call_balldontlie_api(endpoint, params=None, api_key=None):
    """balldontlie.io API 호출"""
    if not api_key:
        return None
    
    url = f"{BALLDONTLIE_API_URL}/{endpoint}"
    headers = {"Authorization": api_key}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            log(f"   ⚠️ balldontlie API error: {response.status_code}")
    except Exception as e:
        log(f"   ⚠️ balldontlie API exception: {e}")
    return None

# =============================================================================
# EPL 함수들 (기존 유지)
# =============================================================================
def normalize_team_name(name):
    """팀 이름 정규화"""
    if name in BIG_6_ALIASES:
        return BIG_6_ALIASES[name]
    for alias, standard in BIG_6_ALIASES.items():
        if alias.lower() in name.lower():
            return standard
    return name.replace(" FC", "").strip()

def is_big_6(team_name):
    """Big 6 팀인지 확인"""
    norm = normalize_team_name(team_name)
    return any(b6.lower() in norm.lower() or norm.lower() in b6.lower() for b6 in BIG_6)

def get_epl_standings(api_key):
    """Football-Data.org에서 EPL 순위 가져오기"""
    url = f"{FOOTBALL_DATA_API_URL}/competitions/PL/standings"
    headers = {"X-Auth-Token": api_key}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            standings = data.get('standings', [])
            
            if standings:
                table = standings[0].get('table', [])
                if table:
                    leader = normalize_team_name(table[0].get('team', {}).get('name', ''))
                    top_4 = [normalize_team_name(t.get('team', {}).get('name', '')) for t in table[:4]]
                    matchday = data.get('season', {}).get('currentMatchday', 0)
                    return leader, top_4, matchday
    except:
        pass
    return None, None, None

def get_epl_matches(api_key, matchday=None):
    """Football-Data.org에서 EPL 경기 일정 가져오기"""
    url = f"{FOOTBALL_DATA_API_URL}/competitions/PL/matches"
    headers = {"X-Auth-Token": api_key}
    params = {"status": "SCHEDULED"}
    if matchday:
        params["matchday"] = matchday
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('matches', [])
    except:
        pass
    return []

def check_epl_rules(home, away, uk_day, uk_time, top_4, leader):
    """EPL 6가지 룰 검증"""
    rules = []
    
    home_norm = normalize_team_name(home)
    away_norm = normalize_team_name(away)
    
    home_is_big6 = is_big_6(home_norm)
    away_is_big6 = is_big_6(away_norm)
    home_is_top4 = home_norm in top_4
    away_is_top4 = away_norm in top_4
    leader_norm = normalize_team_name(leader) if leader else ""
    
    if home_is_big6 and away_is_big6:
        rules.append("Big Match")
    if home_is_top4 and away_is_top4:
        rules.append("Top Tier")
    if (home_is_top4 and not home_is_big6 and away_is_big6) or \
       (away_is_top4 and not away_is_big6 and home_is_big6):
        rules.append("Challenger")
    if uk_day == "Sunday" and uk_time == "16:30":
        rules.append("Prime Time")
    if uk_day == "Saturday" and uk_time == "12:30":
        rules.append("Early KO")
    if leader_norm and (leader_norm in home_norm or home_norm in leader_norm or 
                       leader_norm in away_norm or away_norm in leader_norm):
        rules.append("Leader")
    
    return rules

def search_epl_broadcaster(home, away, match_date, serper_key):
    """EPL 경기 중계 정보 검색 - 개선된 버전"""
    if not serper_key:
        return None
    
    # 더 구체적인 검색어 사용
    queries = [
        f"{home} vs {away} TV channel Sky TNT BBC",
        f"Premier League {home} {away} live TV UK"
    ]
    
    broadcasters = {
        'sky sports': 'Sky Sports',
        'sky': 'Sky Sports',
        'tnt sports': 'TNT Sports',
        'tnt': 'TNT Sports',
        'bt sport': 'TNT Sports',
        'bbc': 'BBC',
        'amazon prime': 'Amazon Prime',
        'amazon': 'Amazon Prime'
    }
    
    for query in queries:
        result = call_serper_api(query, serper_key)
        if result:
            text = ""
            if 'answerBox' in result:
                text += result['answerBox'].get('snippet', '') + " "
            for item in result.get('organic', [])[:3]:
                text += item.get('snippet', '') + " "
                text += item.get('title', '') + " "
            
            text_lower = text.lower()
            for keyword, channel in broadcasters.items():
                if keyword in text_lower:
                    return channel
    
    return None

def process_epl_matches(matches, top_4, leader, serper_key=None):
    """EPL 경기 처리 및 필터링"""
    validated_matches = []
    
    for match in matches:
        home_team = match.get('homeTeam', {}).get('name', '')
        away_team = match.get('awayTeam', {}).get('name', '')
        utc_date = match.get('utcDate', '')
        
        if not home_team or not away_team or not utc_date:
            continue
        
        time_info = convert_utc_to_kst(utc_date)
        if not time_info:
            continue
        
        rules = check_epl_rules(home_team, away_team, time_info['uk_day'], 
                               time_info['uk_time'], top_4, leader)
        
        if rules:
            home_norm = normalize_team_name(home_team)
            away_norm = normalize_team_name(away_team)
            
            channel = None
            if serper_key:
                channel = search_epl_broadcaster(home_norm, away_norm, 
                                                time_info['uk_date'], serper_key)
            
            validated_matches.append({
                'home': home_norm,
                'away': away_norm,
                'kst_time': time_info['kst_full'],
                'uk_time': f"{time_info['uk_day']} {time_info['uk_time']} (UK)",
                'local': channel or '',
                'rules': rules,
                'rule_str': ', '.join(rules)
            })
    
    return validated_matches

# =============================================================================
# NBA 함수 (balldontlie.io API)
# =============================================================================
def get_nba_warriors_data(balldontlie_key, serper_key=None):
    """Golden State Warriors 정보 - balldontlie.io API 사용"""
    if not balldontlie_key:
        return get_nba_default_data()
    
    nba_data = {
        "record": "-",
        "rank": "-",
        "last": {"opp": "-", "result": "-", "score": "-"},
        "schedule": []
    }
    
    kst_now = get_kst_now()
    today_str = kst_now.strftime("%Y-%m-%d")
    
    # =========================================================================
    # 1. 최근 경기 가져오기 (지난 30일)
    # =========================================================================
    start_date = (kst_now - timedelta(days=30)).strftime("%Y-%m-%d")
    
    past_games = call_balldontlie_api(
        "games",
        params={
            "team_ids[]": WARRIORS_TEAM_ID,
            "start_date": start_date,
            "end_date": today_str,
            "per_page": 50
        },
        api_key=balldontlie_key
    )
    
    last_game = None
    
    if past_games and 'data' in past_games:
        completed_games = [g for g in past_games['data'] if g.get('status') == 'Final']
        
        if completed_games:
            completed_games.sort(key=lambda x: x.get('date', ''), reverse=True)
            last_game = completed_games[0]
    
    # 전적 + 순위는 Serper로 검색 (무료 API에서 standings 미지원)
    if serper_key:
        record_query = "Golden State Warriors standings Western Conference 2025-26"
        record_result = call_serper_api(record_query, serper_key)
        if record_result:
            record_text = ""
            if 'answerBox' in record_result:
                record_text += record_result['answerBox'].get('snippet', '') + " "
                record_text += record_result['answerBox'].get('answer', '') + " "
            if 'knowledgeGraph' in record_result:
                kg = record_result['knowledgeGraph']
                record_text += str(kg.get('attributes', {})) + " "
            for item in record_result.get('organic', [])[:5]:
                record_text += item.get('snippet', '') + " "
            
            # 전적 패턴
            record_match = re.search(r'(\d{1,2})-(\d{1,2})', record_text)
            if record_match:
                w, l = int(record_match.group(1)), int(record_match.group(2))
                if 10 <= w + l <= 82:
                    nba_data['record'] = f"{w}-{l}"
            
            # 순위 패턴 - 더 많은 패턴 추가
            rank_patterns = [
                r'#(\d{1,2})\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
                r'(\d{1,2})(?:st|nd|rd|th)\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
                r'(?:Western|West)(?:ern)?\s+(?:Conference\s+)?#?(\d{1,2})',
                r'(?:ranked?|seed(?:ed)?|place|position)\s*#?(\d{1,2})',
                r'(\d{1,2})(?:st|nd|rd|th)\s+(?:place|seed)',
            ]
            for pattern in rank_patterns:
                rank_match = re.search(pattern, record_text, re.IGNORECASE)
                if rank_match:
                    rank_num = int(rank_match.group(1))
                    if 1 <= rank_num <= 15:
                        nba_data['rank'] = f"#{rank_num} West"
                        break
    
    # 최근 경기 결과
    if last_game:
        home_team = last_game.get('home_team', {})
        visitor_team = last_game.get('visitor_team', {})
        home_score = last_game.get('home_team_score', 0)
        visitor_score = last_game.get('visitor_team_score', 0)
        
        if home_team.get('id') == WARRIORS_TEAM_ID:
            opp_name = visitor_team.get('name', '-')
            warriors_score = home_score
            opp_score = visitor_score
        else:
            opp_name = home_team.get('name', '-')
            warriors_score = visitor_score
            opp_score = home_score
        
        result = 'W' if warriors_score > opp_score else 'L'
        nba_data['last'] = {
            'opp': opp_name,
            'result': result,
            'score': f"{warriors_score}-{opp_score}"
        }
    
    # =========================================================================
    # 2. 다음 일정 가져오기 (앞으로 14일)
    # =========================================================================
    future_end = (kst_now + timedelta(days=14)).strftime("%Y-%m-%d")
    
    future_games = call_balldontlie_api(
        "games",
        params={
            "team_ids[]": WARRIORS_TEAM_ID,
            "start_date": today_str,
            "end_date": future_end,
            "per_page": 20
        },
        api_key=balldontlie_key
    )
    
    if future_games and 'data' in future_games:
        upcoming = [g for g in future_games['data'] if g.get('status') != 'Final']
        upcoming.sort(key=lambda x: x.get('datetime', ''))
        
        for game in upcoming[:4]:
            home_team = game.get('home_team', {})
            visitor_team = game.get('visitor_team', {})
            game_datetime = game.get('datetime', '')
            
            if home_team.get('id') == WARRIORS_TEAM_ID:
                opp_name = visitor_team.get('name', 'TBD')
                location = 'home'
                venue = 'Chase Center'
            else:
                opp_name = home_team.get('name', 'TBD')
                location = 'away'
                venue = f"@ {home_team.get('city', '')}"
            
            kst_time = ''
            local_time = ''
            date_str = ''
            
            if game_datetime:
                try:
                    utc_dt = datetime.datetime.fromisoformat(game_datetime.replace('Z', '+00:00'))
                    kst_dt = utc_dt.astimezone(TZ_KST)
                    pst_dt = utc_dt.astimezone(TZ_PST)
                    
                    date_str = kst_dt.strftime("%m.%d")
                    kst_time = kst_dt.strftime("%H:%M")
                    local_time = pst_dt.strftime("%I:%M %p PT").lstrip('0')
                except:
                    date_str = game.get('date', '')[:10].replace('-', '.')
            
            nba_data['schedule'].append({
                'opp': opp_name,
                'date': date_str,
                'kst_time': kst_time,
                'local_time': local_time,
                'location': location,
                'venue': venue,
                'channel': ''
            })
    
    return nba_data

def get_nba_default_data():
    """NBA 기본 데이터"""
    return {
        "record": "-",
        "rank": "-",
        "last": {"opp": "-", "result": "-", "score": "-"},
        "schedule": []
    }

# =============================================================================
# F1 함수
# =============================================================================
def search_f1_schedule(serper_key):
    """F1 다음 그랑프리 검색"""
    kst_now = get_kst_now()
    
    if kst_now.month <= 2:
        query = "F1 2026 season first race Australian Grand Prix March"
    else:
        query = "F1 2026 next Grand Prix race schedule"
    
    result = call_serper_api(query, serper_key)
    if not result:
        return {
            "status": "Off-Season",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park, Melbourne",
            "date": "Mar 2026"
        }
    
    f1_data = {
        'status': 'Off-Season',
        'name': 'TBD',
        'circuit': 'TBD',
        'date': ''
    }
    
    text = ""
    if 'answerBox' in result:
        text += result['answerBox'].get('snippet', '') + " "
    for item in result.get('organic', [])[:5]:
        text += item.get('snippet', '') + " "
        text += item.get('title', '') + " "
    
    gp_circuit_map = {
        'Australian': 'Albert Park, Melbourne',
        'Bahrain': 'Sakhir',
        'Saudi Arabian': 'Jeddah',
        'Japanese': 'Suzuka',
        'Chinese': 'Shanghai',
        'Miami': 'Miami',
        'Monaco': 'Monaco',
        'Canadian': 'Montreal',
        'Spanish': 'Barcelona',
        'Austrian': 'Red Bull Ring',
        'British': 'Silverstone',
    }
    
    for gp_name, circuit in gp_circuit_map.items():
        if gp_name.lower() in text.lower():
            f1_data['name'] = f"{gp_name.upper()} Grand Prix"
            f1_data['circuit'] = circuit
            break
    
    if f1_data['name'] == 'TBD' and kst_now.month <= 2:
        f1_data['name'] = 'AUSTRALIAN Grand Prix'
        f1_data['circuit'] = 'Albert Park, Melbourne'
    
    # 날짜 추출
    date_pattern = r'(March|April|May|June)\s+(\d{1,2})(?:-(\d{1,2}))?'
    date_match = re.search(date_pattern, text, re.IGNORECASE)
    if date_match:
        month = date_match.group(1)[:3]
        day_start = date_match.group(2)
        day_end = date_match.group(3) or str(int(day_start) + 2)
        f1_data['date'] = f"{month} {day_start}-{day_end}"
    elif kst_now.month <= 2:
        f1_data['date'] = 'Mar 2026'
    
    return f1_data

# =============================================================================
# 테니스 함수 - 실시간 검색 기반
# =============================================================================
def search_tennis_schedule(serper_key):
    """
    Tennis (Alcaraz) 일정 - 실시간 검색
    
    [우선순위]
    1. 최근 경기 결과/진행 중 대회 감지
    2. 친선경기 감지
    3. 다음 대회 일정
    """
    
    if not serper_key:
        return {
            'status': '-',
            'info': 'No API Key',
            'detail': '-',
            'time': '-'
        }
    
    # =========================================================================
    # 1. 최근 경기/현재 상태 검색
    # =========================================================================
    latest_query = "Carlos Alcaraz latest match result today 2026"
    latest_result = call_serper_api(latest_query, serper_key)
    
    latest_text = ""
    if latest_result:
        if 'answerBox' in latest_result:
            latest_text += latest_result['answerBox'].get('snippet', '') + " "
            latest_text += latest_result['answerBox'].get('answer', '') + " "
        if 'sportsResults' in latest_result:
            latest_text += str(latest_result['sportsResults']) + " "
        for item in latest_result.get('organic', [])[:5]:
            latest_text += item.get('snippet', '') + " "
            latest_text += item.get('title', '') + " "
    
    # =========================================================================
    # 2. 그랜드슬램/대회 진행 중 감지
    # =========================================================================
    tournaments = {
        'australian open': ('Australian Open', 'Grand Slam'),
        'french open': ('French Open', 'Grand Slam'),
        'roland garros': ('Roland Garros', 'Grand Slam'),
        'wimbledon': ('Wimbledon', 'Grand Slam'),
        'us open': ('US Open', 'Grand Slam'),
        'indian wells': ('Indian Wells', 'Masters'),
        'miami open': ('Miami Open', 'Masters'),
        'monte carlo': ('Monte Carlo', 'Masters'),
        'madrid open': ('Madrid Open', 'Masters'),
        'italian open': ('Italian Open', 'Masters'),
        'rome': ('Italian Open', 'Masters'),
        'cincinnati': ('Cincinnati', 'Masters'),
        'shanghai': ('Shanghai', 'Masters'),
        'paris masters': ('Paris Masters', 'Masters'),
        'atp finals': ('ATP Finals', 'Finals'),
        'rotterdam': ('Rotterdam', 'ATP 500'),
        'barcelona': ('Barcelona Open', 'ATP 500'),
        'queen': ('Queen\'s Club', 'ATP 500'),
        'halle': ('Halle Open', 'ATP 500'),
        'beijing': ('Beijing', 'ATP 500'),
        'basel': ('Basel', 'ATP 500'),
        'vienna': ('Vienna', 'ATP 500'),
    }
    
    # 라운드 패턴
    round_patterns = {
        'final': 'Final',
        'finals': 'Final',
        'f ': 'Final',
        'semifinal': 'SF',
        'semi-final': 'SF',
        'sf': 'SF',
        'quarterfinal': 'QF',
        'quarter-final': 'QF',
        'qf': 'QF',
        'round of 16': 'R16',
        'r16': 'R16',
        '4r': 'R16',
        '4th round': 'R16',
        'fourth round': 'R16',
        '3r': '3R',
        '3rd round': '3R',
        'third round': '3R',
        '2r': '2R',
        '2nd round': '2R',
        'second round': '2R',
        '1r': '1R',
        '1st round': '1R',
        'first round': '1R',
    }
    
    latest_lower = latest_text.lower()
    
    # 대회 감지
    detected_tournament = None
    detected_status = None
    for keyword, (name, status) in tournaments.items():
        if keyword in latest_lower:
            detected_tournament = name
            detected_status = status
            break
    
    # 라운드 감지
    detected_round = None
    for pattern, round_name in round_patterns.items():
        if pattern in latest_lower:
            detected_round = round_name
            break
    
    # 상대 선수 추출
    top_players = [
        'Sinner', 'Djokovic', 'Zverev', 'Medvedev', 'Rune', 'Fritz',
        'Tsitsipas', 'Ruud', 'Hurkacz', 'De Minaur', 'Shelton', 'Draper',
        'Musetti', 'Dimitrov', 'Tiafoe', 'Paul', 'Fonseca', 'Fils',
        'Nadal', 'Federer', 'Murray'
    ]
    
    opponent = None
    for player in top_players:
        if player.lower() in latest_lower:
            # "Alcaraz vs Sinner" 또는 "Sinner vs Alcaraz" 형태 확인
            opponent = player
            break
    
    # 승패 결과 감지
    result = None
    if 'alcaraz' in latest_lower:
        win_patterns = ['alcaraz won', 'alcaraz beat', 'alcaraz defeated', 'alcaraz advances', 'alcaraz wins']
        lose_patterns = ['alcaraz lost', 'alcaraz fell', 'alcaraz eliminated', 'alcaraz out']
        
        for wp in win_patterns:
            if wp in latest_lower:
                result = 'W'
                break
        if not result:
            for lp in lose_patterns:
                if lp in latest_lower:
                    result = 'L'
                    break
    
    # =========================================================================
    # 3. 대회 진행 중이면 해당 정보 반환
    # =========================================================================
    if detected_tournament and detected_round:
        detail = detected_round
        if opponent:
            detail = f"{detected_round} vs {opponent}"
        if result:
            result_str = "Win ✓" if result == 'W' else "Lost"
            detail = f"{detected_round} {result_str}"
            if opponent:
                detail = f"{detected_round} vs {opponent} ({result_str})"
        
        return {
            'status': detected_status or 'Tournament',
            'info': detected_tournament,
            'detail': detail,
            'time': ''
        }
    
    # =========================================================================
    # 4. 친선경기 감지
    # =========================================================================
    exhibition_keywords = [
        ('hyundai card super match', 'Hyundai Card Super Match'),
        ('hyundai card', 'Hyundai Card Super Match'),
        ('super match', 'Hyundai Card Super Match'),
        ('six kings slam', 'Six Kings Slam'),
        ('netflix slam', 'Netflix Slam'),
        ('riyadh season', 'Riyadh Season'),
        ('world tennis league', 'World Tennis League'),
        ('laver cup', 'Laver Cup'),
        ('mubadala', 'Mubadala WTC'),
        ('exhibition', 'Exhibition Match'),
    ]
    
    for keyword, event_name in exhibition_keywords:
        if keyword in latest_lower:
            # 친선경기 상세 정보 검색
            exhibition_query = f"Carlos Alcaraz {event_name} 2026 date location opponent"
            exh_result = call_serper_api(exhibition_query, serper_key)
            
            exh_text = ""
            if exh_result:
                if 'answerBox' in exh_result:
                    exh_text += exh_result['answerBox'].get('snippet', '') + " "
                for item in exh_result.get('organic', [])[:3]:
                    exh_text += item.get('snippet', '') + " "
            
            exh_lower = exh_text.lower()
            
            # 상대 선수
            exh_opponent = None
            for player in top_players:
                if player.lower() in exh_lower:
                    exh_opponent = player
                    break
            
            # 장소
            locations = [
                ('incheon', 'Incheon'), ('seoul', 'Seoul'), ('inspire arena', 'Incheon'),
                ('korea', 'Korea'), ('riyadh', 'Riyadh'), ('saudi', 'Saudi Arabia'),
                ('dubai', 'Dubai'), ('abu dhabi', 'Abu Dhabi'),
            ]
            exh_location = None
            for loc_key, loc_name in locations:
                if loc_key in exh_lower:
                    exh_location = loc_name
                    break
            
            # 날짜
            date_pattern = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Dec(?:ember)?)\s+(\d{1,2})'
            date_match = re.search(date_pattern, exh_text, re.IGNORECASE)
            exh_date = ""
            if date_match:
                month = date_match.group(1)[:3]
                day = date_match.group(2)
                exh_date = f"{month} {day}"
            
            # detail 구성
            detail_parts = []
            if exh_opponent:
                detail_parts.append(f"vs {exh_opponent}")
            if exh_location:
                detail_parts.append(f"({exh_location})")
            
            return {
                'status': 'Exhibition',
                'info': event_name,
                'detail': ' '.join(detail_parts) if detail_parts else '',
                'time': exh_date
            }
    
    # =========================================================================
    # 5. 대회 진행 중 아니면 다음 일정 검색
    # =========================================================================
    next_query = "Carlos Alcaraz next tournament schedule 2026"
    next_result = call_serper_api(next_query, serper_key)
    
    next_text = ""
    if next_result:
        if 'answerBox' in next_result:
            next_text += next_result['answerBox'].get('snippet', '') + " "
        for item in next_result.get('organic', [])[:5]:
            next_text += item.get('snippet', '') + " "
    
    next_lower = next_text.lower()
    
    # 다음 대회 감지
    next_tournament = None
    next_status = None
    for keyword, (name, status) in tournaments.items():
        if keyword in next_lower:
            next_tournament = name
            next_status = status
            break
    
    # 날짜 추출
    date_range_pattern = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:\s*[-–]\s*(?:(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+)?(\d{1,2}))?'
    date_match = re.search(date_range_pattern, next_text, re.IGNORECASE)
    
    next_date = ""
    if date_match:
        start_month = date_match.group(1)[:3]
        start_day = date_match.group(2)
        end_month = date_match.group(3)
        end_day = date_match.group(4)
        
        if end_day:
            if end_month:
                next_date = f"{start_month} {start_day} - {end_month[:3]} {end_day}"
            else:
                next_date = f"{start_month} {start_day}-{end_day}"
        else:
            next_date = f"{start_month} {start_day}"
    
    # 장소 추출
    tournament_locations = {
        'Australian Open': 'Melbourne',
        'French Open': 'Paris',
        'Roland Garros': 'Paris',
        'Wimbledon': 'London',
        'US Open': 'New York',
        'Indian Wells': 'California',
        'Miami Open': 'Miami',
        'Monte Carlo': 'Monaco',
        'Madrid Open': 'Madrid',
        'Italian Open': 'Rome',
        'Rotterdam': 'Netherlands',
        'Barcelona Open': 'Barcelona',
        'ATP Finals': 'Turin',
    }
    
    location = tournament_locations.get(next_tournament, '')
    
    if next_tournament:
        return {
            'status': next_status or 'Tournament',
            'info': next_tournament,
            'detail': location,
            'time': next_date
        }
    
    # 기본값
    return {
        'status': 'Tournament',
        'info': 'Next Event',
        'detail': 'TBD',
        'time': '-'
    }

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    football_api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    serper_api_key = os.environ.get("SERPER_API_KEY")
    balldontlie_api_key = os.environ.get("BALLDONTLIE_API_KEY")
    
    if not football_api_key:
        log("❌ Error: FOOTBALL_DATA_API_KEY Missing")
        raise ValueError("FOOTBALL_DATA_API_KEY Missing")
    
    kst_now = get_kst_now()
    
    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Data Sources:")
    log(f"   - EPL: Football-Data.org ✅")
    log(f"   - NBA: balldontlie.io {'✅' if balldontlie_api_key else '❌'}")
    log(f"   - Search: Serper API {'✅' if serper_api_key else '❌'}")
    
    # =========================================================================
    # STEP 1: EPL 순위
    # =========================================================================
    log("\n⚽ [Step 1/5] Premier League 순위...")
    
    leader_team, top_4_teams, current_matchday = get_epl_standings(football_api_key)
    
    if leader_team and top_4_teams:
        log(f"   ✅ 1위: {leader_team}")
        log(f"   ✅ Top 4: {', '.join(top_4_teams)}")
        log(f"   ✅ 현재 라운드: R{current_matchday}")
    else:
        log("   ⚠️ 순위 정보 가져오기 실패, 기본값 사용")
        leader_team = "Arsenal"
        top_4_teams = ["Arsenal", "Manchester City", "Liverpool", "Chelsea"]
        current_matchday = None
    
    # =========================================================================
    # STEP 2: EPL 경기 일정 + 6가지 룰
    # =========================================================================
    log("\n⚽ [Step 2/5] Premier League 경기 일정 + 6가지 룰...")
    log("   [룰 순서]")
    log("   1. Big Match: Big 6 vs Big 6")
    log("   2. Top Tier: Top 4 vs Top 4")
    log("   3. Challenger: Top 4 vs Big 6 (서로 다른 조건)")
    log("   4. Prime Time: 일요일 16:30 UK")
    log("   5. Early KO: 토요일 12:30 UK")
    log("   6. Leader: 1위 팀 포함")
    
    matches = get_epl_matches(football_api_key, current_matchday)
    log(f"   📋 총 {len(matches)}경기 조회됨")
    
    validated_epl = process_epl_matches(matches, top_4_teams, leader_team, serper_api_key)
    log(f"   ✅ 6가지 룰 적용 후: {len(validated_epl)}경기 선별")
    
    for match in validated_epl:
        channel_info = f" | {match['local']}" if match['local'] else ""
        log(f"      • {match['home']} vs {match['away']} [{match['rule_str']}]{channel_info}")
    
    # =========================================================================
    # STEP 3: NBA Warriors
    # =========================================================================
    log("\n🏀 [Step 3/5] NBA Warriors (balldontlie.io API)...")
    
    if balldontlie_api_key:
        nba_data = get_nba_warriors_data(balldontlie_api_key, serper_api_key)
        log(f"   ✅ 전적: {nba_data['record']} | 순위: {nba_data['rank']}")
        if nba_data['last']['opp'] != '-':
            log(f"   ✅ 최근 경기: vs {nba_data['last']['opp']} {nba_data['last']['result']} ({nba_data['last']['score']})")
        log(f"   ✅ 다음 일정: {len(nba_data['schedule'])}경기")
        for game in nba_data['schedule'][:4]:
            loc_icon = '🏠' if game.get('location') == 'home' else '✈️'
            venue = game.get('venue', '')
            time_info = f"{game.get('kst_time', '')} KST" if game.get('kst_time') else 'TBD'
            log(f"      {loc_icon} {game['date']} vs {game['opp']} | {time_info} | {venue}")
    else:
        nba_data = get_nba_default_data()
        log("   ⚠️ BALLDONTLIE_API_KEY 없음, 기본값 사용")
    
    # =========================================================================
    # STEP 4: F1
    # =========================================================================
    log("\n🏎️ [Step 4/5] F1 일정...")
    
    if serper_api_key:
        f1_data = search_f1_schedule(serper_api_key)
        log(f"   ✅ {f1_data['name']} | {f1_data['circuit']} | {f1_data['date']}")
    else:
        f1_data = {
            "status": "Off-Season",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park, Melbourne",
            "date": "Mar 2026"
        }
    
    # =========================================================================
    # STEP 5: Tennis
    # =========================================================================
    log("\n🎾 [Step 5/5] Tennis (Alcaraz)...")
    
    tennis_data = search_tennis_schedule(serper_api_key)
    log(f"   ✅ {tennis_data['status']} | {tennis_data['info']} | {tennis_data['detail']} | {tennis_data['time']}")
    
    # =========================================================================
    # 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")
    
    sports_data = {
        "updated": kst_now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "epl": {
            "matchday": current_matchday,
            "leader": leader_team,
            "top4": top_4_teams,
            "matches": validated_epl
        },
        "nba": nba_data,
        "f1": f1_data,
        "tennis": tennis_data
    }
    
    with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sports_data, f, ensure_ascii=False, indent=2)
    
    log(f"✅ [Complete]")
    log(f"   EPL: {len(validated_epl)}경기")
    log(f"   NBA: {len(nba_data['schedule'])}경기")
    log(f"   파일: {SPORTS_FILE}")
    
    return sports_data

# =============================================================================
# 메인 실행
# =============================================================================
if __name__ == "__main__":
    try:
        update_sports_data()
        sys.exit(0)
    except Exception as e:
        log(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
