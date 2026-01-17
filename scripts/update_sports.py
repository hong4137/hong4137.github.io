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
from datetime import timedelta, date

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
    """Football-Data.org에서 EPL 경기 일정 가져오기 (현재 + 다음 라운드)"""
    url = f"{FOOTBALL_DATA_API_URL}/competitions/PL/matches"
    headers = {"X-Auth-Token": api_key}
    
    all_matches = []
    
    # 방법 1: matchday 지정 시 해당 라운드 + 다음 라운드 조회
    if matchday:
        for md in [matchday, matchday + 1]:
            try:
                params = {"status": "SCHEDULED", "matchday": md}
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    matches = data.get('matches', [])
                    all_matches.extend(matches)
            except:
                pass
    
    # 방법 2: matchday 없으면 앞으로 14일간 SCHEDULED 경기 조회
    if not all_matches:
        try:
            kst_now = get_kst_now()
            date_from = kst_now.strftime("%Y-%m-%d")
            date_to = (kst_now + timedelta(days=14)).strftime("%Y-%m-%d")
            
            params = {
                "status": "SCHEDULED",
                "dateFrom": date_from,
                "dateTo": date_to
            }
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                all_matches = data.get('matches', [])
        except:
            pass
    
    # 중복 제거 (경기 ID 기준)
    seen_ids = set()
    unique_matches = []
    for m in all_matches:
        match_id = m.get('id')
        if match_id and match_id not in seen_ids:
            seen_ids.add(match_id)
            unique_matches.append(m)
    
    return unique_matches

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
        matchday = match.get('matchday', 0)
        
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
                'rule_str': ', '.join(rules),
                'matchday': matchday
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
    wins = 0
    losses = 0
    
    if past_games and 'data' in past_games:
        completed_games = [g for g in past_games['data'] if g.get('status') == 'Final']
        
        if completed_games:
            completed_games.sort(key=lambda x: x.get('date', ''), reverse=True)
            last_game = completed_games[0]
    
    # =========================================================================
    # 1-1. 시즌 전체 경기로 전적 계산 (balldontlie API)
    # =========================================================================
    # 2025-26 시즌은 2025년 10월부터 시작
    season_start = "2025-10-01"
    
    season_games = call_balldontlie_api(
        "games",
        params={
            "team_ids[]": WARRIORS_TEAM_ID,
            "start_date": season_start,
            "end_date": today_str,
            "per_page": 100
        },
        api_key=balldontlie_key
    )
    
    if season_games and 'data' in season_games:
        for game in season_games['data']:
            if game.get('status') != 'Final':
                continue
            
            home_team = game.get('home_team', {})
            visitor_team = game.get('visitor_team', {})
            home_score = game.get('home_team_score', 0)
            visitor_score = game.get('visitor_team_score', 0)
            
            if home_team.get('id') == WARRIORS_TEAM_ID:
                if home_score > visitor_score:
                    wins += 1
                else:
                    losses += 1
            elif visitor_team.get('id') == WARRIORS_TEAM_ID:
                if visitor_score > home_score:
                    wins += 1
                else:
                    losses += 1
        
        if wins + losses > 0:
            nba_data['record'] = f"{wins}-{losses}"
    
    # 순위는 Serper로 검색 (무료 API에서 standings 미지원)
    if serper_key:
        rank_query = "Golden State Warriors Western Conference rank standings 2026"
        rank_result = call_serper_api(rank_query, serper_key)
        if rank_result:
            rank_text = ""
            if 'answerBox' in rank_result:
                rank_text += rank_result['answerBox'].get('snippet', '') + " "
                rank_text += rank_result['answerBox'].get('answer', '') + " "
            if 'knowledgeGraph' in rank_result:
                kg = rank_result['knowledgeGraph']
                rank_text += str(kg.get('attributes', {})) + " "
            if 'sportsResults' in rank_result:
                rank_text += str(rank_result['sportsResults']) + " "
            for item in rank_result.get('organic', [])[:5]:
                rank_text += item.get('snippet', '') + " "
            
            # 순위 패턴
            rank_patterns = [
                r'#(\d{1,2})\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
                r'(\d{1,2})(?:st|nd|rd|th)\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
                r'(?:Western|West)(?:ern)?\s+(?:Conference\s+)?(?:rank(?:ing)?s?)?\s*[:#]?\s*(\d{1,2})',
                r'(?:ranked?|seeded?|place|position|No\.?)\s*#?(\d{1,2})\s+(?:in\s+)?(?:the\s+)?(?:Western|West)',
                r'(\d{1,2})(?:st|nd|rd|th)\s+(?:place|seed|in the West)',
                r'West(?:ern)?\s+#?(\d{1,2})(?:st|nd|rd|th)?',
            ]
            for pattern in rank_patterns:
                rank_match = re.search(pattern, rank_text, re.IGNORECASE)
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
    """F1 다음 그랑프리 또는 프리시즌 테스트 검색"""
    kst_now = get_kst_now()
    
    f1_data = {
        'status': 'Off-Season',
        'name': 'TBD',
        'circuit': 'TBD',
        'date': ''
    }
    
    # =========================================================================
    # 시즌 전 (1~2월): 프리시즌 테스트 일정 표시
    # =========================================================================
    if kst_now.month <= 2:
        # 2026 프리시즌 테스트 일정 (고정값)
        # Test 1: Jan 26-30 Barcelona (Private)
        # Test 2: Feb 11-13 Bahrain
        # Test 3: Feb 18-20 Bahrain
        # Season Start: Mar 6-8 Australia
        
        today = kst_now.date()
        
        # 날짜 기준으로 다음 이벤트 결정
        test1_start = date(2026, 1, 26)
        test1_end = date(2026, 1, 30)
        test2_start = date(2026, 2, 11)
        test2_end = date(2026, 2, 13)
        test3_start = date(2026, 2, 18)
        test3_end = date(2026, 2, 20)
        season_start = date(2026, 3, 6)
        
        if today < test1_start:
            # Test 1 전
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 1 (Private)',
                'circuit': 'Barcelona-Catalunya',
                'date': 'Jan 26-30'
            }
        elif today <= test1_end:
            # Test 1 진행 중
            f1_data = {
                'status': 'Testing',
                'name': 'Test 1 (Private)',
                'circuit': 'Barcelona-Catalunya',
                'date': 'Jan 26-30'
            }
        elif today < test2_start:
            # Test 1 끝, Test 2 전
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 2',
                'circuit': 'Bahrain International',
                'date': 'Feb 11-13'
            }
        elif today <= test2_end:
            # Test 2 진행 중
            f1_data = {
                'status': 'Testing',
                'name': 'Test 2',
                'circuit': 'Bahrain International',
                'date': 'Feb 11-13'
            }
        elif today < test3_start:
            # Test 2 끝, Test 3 전
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 3',
                'circuit': 'Bahrain International',
                'date': 'Feb 18-20'
            }
        elif today <= test3_end:
            # Test 3 진행 중
            f1_data = {
                'status': 'Testing',
                'name': 'Test 3',
                'circuit': 'Bahrain International',
                'date': 'Feb 18-20'
            }
        else:
            # 모든 테스트 끝, 시즌 개막 전
            f1_data = {
                'status': 'Off-Season',
                'name': 'AUSTRALIAN Grand Prix',
                'circuit': 'Albert Park, Melbourne',
                'date': 'Mar 06-08'
            }
        
        return f1_data
    
    # =========================================================================
    # 시즌 중 (3월~): 다음 GP 검색
    # =========================================================================
    query = "F1 2026 next Grand Prix race schedule"
    result = call_serper_api(query, serper_key)
    
    if not result:
        return {
            "status": "Off-Season",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park, Melbourne",
            "date": "Mar 2026"
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
            f1_data['status'] = 'Next GP'
            break
    
    # 날짜 추출
    date_pattern = r'(March|April|May|June|July|August|September|October|November)\s+(\d{1,2})(?:-(\d{1,2}))?'
    date_match = re.search(date_pattern, text, re.IGNORECASE)
    if date_match:
        month = date_match.group(1)[:3]
        day_start = date_match.group(2)
        day_end = date_match.group(3) or str(int(day_start) + 2)
        f1_data['date'] = f"{month} {day_start}-{day_end}"
    
    return f1_data

# =============================================================================
# 테니스 함수 - Recent + Next 구조
# =============================================================================
def search_tennis_schedule(serper_key):
    """
    Tennis (Alcaraz) - Recent 경기 결과 + Next 일정
    
    반환 구조:
    {
        'recent': {'event': '', 'opponent': '', 'result': '', 'score': '', 'date': ''},
        'next': {'event': '', 'detail': '', 'date': '', 'status': ''}
    }
    """
    
    default_data = {
        'recent': {'event': '-', 'opponent': '-', 'result': '-', 'score': '-', 'date': '-'},
        'next': {'event': '-', 'detail': '-', 'date': '-', 'status': '-'}
    }
    
    if not serper_key:
        return default_data
    
    kst_now = get_kst_now()
    
    top_players = [
        'Sinner', 'Djokovic', 'Zverev', 'Medvedev', 'Rune', 'Fritz',
        'Tsitsipas', 'Ruud', 'Nadal', 'Federer', 'Murray', 'Draper', 'Fonseca'
    ]
    
    tennis_data = {
        'recent': {'event': '-', 'opponent': '-', 'result': '-', 'score': '-', 'date': '-'},
        'next': {'event': '-', 'detail': '-', 'date': '-', 'status': '-'}
    }
    
    # =========================================================================
    # 1. 최근 경기 결과 검색
    # =========================================================================
    recent_query = "Carlos Alcaraz latest match result score 2026"
    recent_result = call_serper_api(recent_query, serper_key)
    
    recent_text = ""
    if recent_result:
        if 'answerBox' in recent_result:
            recent_text += recent_result['answerBox'].get('snippet', '') + " "
            recent_text += recent_result['answerBox'].get('answer', '') + " "
        if 'sportsResults' in recent_result:
            recent_text += str(recent_result['sportsResults']) + " "
        for item in recent_result.get('organic', [])[:5]:
            recent_text += item.get('snippet', '') + " "
            recent_text += item.get('title', '') + " "
    
    recent_lower = recent_text.lower()
    
    # 최근 경기 이벤트명 감지
    events = {
        'hyundai card': 'Hyundai Card',
        'super match': 'Hyundai Card',
        'australian open': 'Australian Open',
        'six kings slam': 'Six Kings Slam',
        'atp finals': 'ATP Finals',
    }
    
    recent_event = '-'
    for keyword, name in events.items():
        if keyword in recent_lower:
            recent_event = name
            break
    
    # 상대 선수
    recent_opponent = '-'
    for player in top_players:
        if player.lower() in recent_lower:
            recent_opponent = player
            break
    
    # 승패 결과
    recent_result_str = '-'
    if 'alcaraz' in recent_lower:
        win_patterns = ['alcaraz won', 'alcaraz beat', 'alcaraz defeated', 'alcaraz advances', 'alcaraz wins', 'victory for alcaraz']
        lose_patterns = ['alcaraz lost', 'alcaraz fell', 'alcaraz eliminated', 'alcaraz out', 'defeat for alcaraz']
        
        for wp in win_patterns:
            if wp in recent_lower:
                recent_result_str = 'W'
                break
        if recent_result_str == '-':
            for lp in lose_patterns:
                if lp in recent_lower:
                    recent_result_str = 'L'
                    break
    
    # 스코어 추출 (예: 6-4, 7-5 또는 6-4 6-3)
    score_pattern = r'\b([0-7]-[0-7](?:\s*,?\s*[0-7]-[0-7])*)\b'
    score_match = re.search(score_pattern, recent_text)
    recent_score = score_match.group(1) if score_match else '-'
    
    # 날짜 추출
    date_pattern = r'(Jan(?:uary)?|Feb(?:ruary)?|Dec(?:ember)?)\s+(\d{1,2})'
    date_match = re.search(date_pattern, recent_text, re.IGNORECASE)
    recent_date = f"{date_match.group(1)[:3]} {date_match.group(2)}" if date_match else '-'
    
    tennis_data['recent'] = {
        'event': recent_event,
        'opponent': recent_opponent,
        'result': recent_result_str,
        'score': recent_score,
        'date': recent_date
    }
    
    # =========================================================================
    # 2. 다음 경기 일정 검색 (1R 상대 우선)
    # =========================================================================
    # 더 정확한 쿼리: "first round opponent" 또는 "next opponent"
    next_query = "Carlos Alcaraz Australian Open 2026 first round opponent draw"
    next_result = call_serper_api(next_query, serper_key)
    
    next_text = ""
    if next_result:
        if 'answerBox' in next_result:
            next_text += next_result['answerBox'].get('snippet', '') + " "
        for item in next_result.get('organic', [])[:5]:
            next_text += item.get('snippet', '') + " "
            next_text += item.get('title', '') + " "
    
    next_lower = next_text.lower()
    
    # 다음 이벤트 감지
    tournaments = {
        'australian open': ('Australian Open', 'Grand Slam'),
        'french open': ('Roland Garros', 'Grand Slam'),
        'roland garros': ('Roland Garros', 'Grand Slam'),
        'wimbledon': ('Wimbledon', 'Grand Slam'),
        'us open': ('US Open', 'Grand Slam'),
        'indian wells': ('Indian Wells', 'Masters'),
        'miami open': ('Miami Open', 'Masters'),
        'rotterdam': ('Rotterdam', 'ATP 500'),
        'hyundai card': ('Hyundai Card', 'Exhibition'),
        'six kings': ('Six Kings Slam', 'Exhibition'),
    }
    
    next_event = '-'
    next_status = '-'
    for keyword, (name, status) in tournaments.items():
        if keyword in next_lower:
            next_event = name
            next_status = status
            break
    
    # 1R 상대 추출 - "begins against", "opens against", "faces", "will play" 패턴
    next_detail = '-'
    
    # 1라운드 상대 패턴 (더 구체적인 패턴 우선)
    first_round_patterns = [
        r'(?:begins|opens|starts|kicks off).*?(?:against|versus|vs\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'first[- ]?round.*?(?:against|versus|vs\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        r'(?:will|to)\s+(?:play|face|meet)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+in\s+(?:the\s+)?(?:first|opening)',
        r'(?:against|versus|vs\.?)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+in\s+(?:the\s+)?first',
    ]
    
    first_round_opponent = None
    for pattern in first_round_patterns:
        match = re.search(pattern, next_text, re.IGNORECASE)
        if match:
            first_round_opponent = match.group(1).strip()
            # "Adam Walton" 같은 이름 추출
            break
    
    # "projected" 또는 "could meet" 같은 예상 경로는 제외
    projected_keywords = ['projected', 'could meet', 'could face', 'potential', 'hypothetical', 'semi-final', 'semifinal', 'quarter-final', 'quarterfinal']
    
    if first_round_opponent:
        # 예상 경로가 아닌 실제 1R 상대만 사용
        next_detail = f"R1 vs {first_round_opponent}"
    else:
        # 1R 상대를 못 찾으면 라운드 패턴 검색
        round_patterns = {
            'final': 'Final', 'semifinal': 'SF', 'semi-final': 'SF',
            'quarterfinal': 'QF', 'quarter-final': 'QF',
            'round of 16': 'R16', '4th round': 'R16',
            '3rd round': '3R', 'third round': '3R',
            '2nd round': '2R', 'second round': '2R',
            '1st round': '1R', 'first round': '1R',
        }
        
        for pattern, round_name in round_patterns.items():
            if pattern in next_lower:
                # 예상 경로 키워드가 있으면 스킵
                is_projected = any(pk in next_lower for pk in projected_keywords)
                if not is_projected or round_name == '1R':
                    next_detail = round_name
                    break
        
        # 상대 선수 추가 (top players에서만, projected가 아닌 경우)
        if not any(pk in next_lower for pk in projected_keywords):
            for player in top_players:
                if player.lower() in next_lower:
                    if next_detail != '-':
                        next_detail = f"{next_detail} vs {player}"
                    else:
                        next_detail = f"vs {player}"
                    break
    
    # 장소 (detail이 없으면)
    if next_detail == '-':
        locations = {
            'Australian Open': 'Melbourne',
            'Roland Garros': 'Paris',
            'Wimbledon': 'London',
            'US Open': 'New York',
            'Rotterdam': 'Netherlands',
        }
        next_detail = locations.get(next_event, '-')
    
    # 날짜 추출
    next_date_pattern = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?'
    next_date_match = re.search(next_date_pattern, next_text, re.IGNORECASE)
    if next_date_match:
        month = next_date_match.group(1)[:3]
        day_start = next_date_match.group(2)
        day_end = next_date_match.group(3)
        if day_end:
            next_date = f"{month} {day_start}-{day_end}"
        else:
            next_date = f"{month} {day_start}"
    else:
        next_date = '-'
    
    tennis_data['next'] = {
        'event': next_event,
        'detail': next_detail,
        'date': next_date,
        'status': next_status
    }
    
    return tennis_data

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
    log(f"   📋 총 {len(matches)}경기 조회됨 (R{current_matchday} + R{current_matchday + 1 if current_matchday else '?'})")
    
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
    recent = tennis_data.get('recent', {})
    next_match = tennis_data.get('next', {})
    log(f"   ✅ Recent: {recent.get('event', '-')} vs {recent.get('opponent', '-')} {recent.get('result', '-')} ({recent.get('score', '-')}) | {recent.get('date', '-')}")
    log(f"   ✅ Next: {next_match.get('event', '-')} | {next_match.get('detail', '-')} | {next_match.get('date', '-')} [{next_match.get('status', '-')}]")
    
    # =========================================================================
    # 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")
    
    # EPL 실제 라운드 범위 계산
    if validated_epl:
        matchdays = [m.get('matchday', 0) for m in validated_epl if m.get('matchday')]
        if matchdays:
            min_md = min(matchdays)
            max_md = max(matchdays)
            if min_md == max_md:
                display_matchday = f"R{min_md}"
            else:
                display_matchday = f"R{min_md}-{max_md}"
        else:
            display_matchday = f"R{current_matchday}" if current_matchday else "R?"
    else:
        display_matchday = f"R{current_matchday}" if current_matchday else "R?"
    
    sports_data = {
        "updated": kst_now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "epl": {
            "matchday": current_matchday,
            "display_matchday": display_matchday,
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
    log(f"   EPL: {len(validated_epl)}경기 ({display_matchday})")
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
