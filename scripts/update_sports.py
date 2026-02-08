#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater v2.3
======================================================
EPL: Football-Data.org 무료 API (순위, 일정)
NBA: balldontlie.io 무료 API (일정, 결과)
EPL 중계/F1/Tennis: Serper API 검색 (월 2,500회 무료)

[EPL 6가지 룰] - 티어 우선순위!
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6 - 서로 다른 조건)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함

[v2.3 변경사항]
- EPL: 선정 경기 모두 종료 + 현재 라운드에 선정 가능 경기 없음 → 다음 라운드 자동 전환
- EPL: process_epl_matches에 football_api_key 파라미터 추가

[v2.2 변경사항]
- EPL: 티어 우선순위로 정렬 후 상위 3경기만 선정
- EPL: 선정된 경기 ID 저장 → 상태 업데이트 시 재사용
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

# =============================================================================
# EPL 티어 우선순위 설정
# =============================================================================
TIER_PRIORITY = {
    'Big Match': 1,      # 티어 1: Big 6 vs Big 6
    'Top Tier': 2,       # 티어 2: Top 4 vs Top 4
    'Challenger': 3,     # 티어 3: Top 4 vs Big 6
    'Prime Time': 4,     # 티어 4: 일요일 16:30 UK
    'Early KO': 5,       # 티어 5: 토요일 12:30 UK
    'Leader': 6          # 티어 6: 1위 팀 포함
}
MAX_EPL_MATCHES = 3  # 최대 선정 경기 수

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

def call_gemini_api(prompt, api_key):
    """Gemini API 호출"""
    if not api_key:
        return None
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return text
        elif response.status_code == 429:
            log(f"   ⚠️ Gemini API rate limit (429)")
        elif response.status_code == 404:
            log(f"   ⚠️ Gemini API model not found (404)")
        else:
            log(f"   ⚠️ Gemini API error: {response.status_code}")
    except Exception as e:
        log(f"   ⚠️ Gemini API exception: {e}")
    return None

# =============================================================================
# EPL 함수들
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

    all_matches = []

    # 특정 라운드 조회
    if matchday:
        try:
            params = {"matchday": matchday}
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                matches = data.get('matches', [])
                all_matches.extend(matches)
        except:
            pass

    # matchday 없으면 앞으로 7일간 경기 조회
    if not all_matches:
        try:
            kst_now = get_kst_now()
            date_from = kst_now.strftime("%Y-%m-%d")
            date_to = (kst_now + timedelta(days=7)).strftime("%Y-%m-%d")

            params = {
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
    """EPL 6가지 룰 검증 - 최고 티어 반환"""
    home_norm = normalize_team_name(home)
    away_norm = normalize_team_name(away)

    home_is_big6 = is_big_6(home_norm)
    away_is_big6 = is_big_6(away_norm)
    home_is_top4 = home_norm in top_4
    away_is_top4 = away_norm in top_4
    leader_norm = normalize_team_name(leader) if leader else ""

    rules = []
    
    # 티어 1: Big Match
    if home_is_big6 and away_is_big6:
        rules.append("Big Match")
    
    # 티어 2: Top Tier
    if home_is_top4 and away_is_top4:
        rules.append("Top Tier")
    
    # 티어 3: Challenger
    if (home_is_top4 and not home_is_big6 and away_is_big6) or \
       (away_is_top4 and not away_is_big6 and home_is_big6):
        rules.append("Challenger")
    
    # 티어 4: Prime Time
    if uk_day == "Sunday" and uk_time == "16:30":
        rules.append("Prime Time")
    
    # 티어 5: Early KO
    if uk_day == "Saturday" and uk_time == "12:30":
        rules.append("Early KO")
    
    # 티어 6: Leader
    if leader_norm and (leader_norm in home_norm or home_norm in leader_norm or
                       leader_norm in away_norm or away_norm in leader_norm):
        rules.append("Leader")

    return rules

def get_best_tier(rules):
    """룰 목록에서 가장 높은 티어(낮은 숫자) 반환"""
    if not rules:
        return 99
    return min(TIER_PRIORITY.get(r, 99) for r in rules)

def search_epl_broadcaster(home, away, match_date, serper_key):
    """EPL 경기 중계 정보 검색 (구체적인 채널명)"""
    if not serper_key:
        return None

    queries = [
        f"{home} vs {away} TV channel UK",
        f"{home} {away} Sky Sports TNT Amazon live TV"
    ]

    broadcasters = [
        ('sky sports main event', 'Sky Sports Main Event'),
        ('sky sports premier league', 'Sky Sports Premier League'),
        ('sky sports football', 'Sky Sports Football'),
        ('sky sports ultra', 'Sky Sports Ultra HD'),
        ('sky sports+', 'Sky Sports+'),
        ('sky sports', 'Sky Sports'),
        ('tnt sports 1', 'TNT Sports 1'),
        ('tnt sports 2', 'TNT Sports 2'),
        ('tnt sports 3', 'TNT Sports 3'),
        ('tnt sports 4', 'TNT Sports 4'),
        ('tnt sports', 'TNT Sports'),
        ('bt sport', 'TNT Sports'),
        ('amazon prime video', 'Amazon Prime'),
        ('amazon prime', 'Amazon Prime'),
        ('prime video', 'Amazon Prime'),
        ('bbc one', 'BBC One'),
        ('bbc two', 'BBC Two'),
        ('bbc', 'BBC'),
    ]

    for query in queries:
        result = call_serper_api(query, serper_key)
        if result:
            text = ""
            if 'answerBox' in result:
                text += result['answerBox'].get('snippet', '') + " "
                text += result['answerBox'].get('answer', '') + " "
            for item in result.get('organic', [])[:3]:
                text += item.get('snippet', '') + " "
                text += item.get('title', '') + " "

            text_lower = text.lower()
            
            for keyword, channel in broadcasters:
                if keyword in text_lower:
                    return channel

    return None

def load_existing_sports_data():
    """기존 sports.json 로드"""
    try:
        if os.path.exists(SPORTS_FILE):
            with open(SPORTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return None

def select_matches_from_round(matches, top_4, leader, serper_key=None):
    """
    특정 라운드 경기에서 룰에 맞는 경기 선정 (내부 헬퍼 함수)
    FINISHED 경기 제외, 티어 우선순위 정렬 후 상위 N개 반환
    """
    validated_matches = []

    for match in matches:
        status = match.get('status', '')
        
        # FINISHED 경기는 새 선정에서 제외
        if status == 'FINISHED':
            continue
            
        home_team = match.get('homeTeam', {}).get('name', '')
        away_team = match.get('awayTeam', {}).get('name', '')
        utc_date = match.get('utcDate', '')
        matchday = match.get('matchday', 0)
        match_id = match.get('id')

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
                'match_id': match_id,
                'home': home_norm,
                'away': away_norm,
                'kst_time': time_info['kst_full'],
                'uk_time': f"{time_info['uk_day']} {time_info['uk_time']} (UK)",
                'local': channel or '',
                'rules': rules,
                'rule_str': ', '.join(rules),
                'matchday': matchday,
                'status': 'SCHEDULED',
                'score': '-',
                'datetime_kst': time_info['datetime_kst']
            })

    # 티어 우선순위 정렬 + 상위 N개 선정
    if validated_matches:
        validated_matches.sort(key=lambda m: (
            get_best_tier(m['rules']),
            m['datetime_kst']
        ))
        
        selected_matches = validated_matches[:MAX_EPL_MATCHES]
        
        # datetime 객체 제거 (JSON 직렬화 불가)
        for m in selected_matches:
            if 'datetime_kst' in m:
                del m['datetime_kst']
        
        return selected_matches
    
    return []

def process_epl_matches(matches, top_4, leader, serper_key=None, existing_data=None, 
                        football_api_key=None, current_matchday=None):
    """
    EPL 경기 처리 및 필터링 (v2.3 개선)
    
    1. 기존에 선정된 경기가 있고, 아직 모두 종료되지 않았으면 → 상태만 업데이트
    2. 기존 선정 경기가 모두 종료됨 → 현재 라운드에서 새로 선정 시도
    3. 현재 라운드에 선정 가능 경기 없음 → 다음 라운드 자동 조회 (v2.3 추가)
    """
    
    # =========================================================================
    # 기존 선정 경기 확인
    # =========================================================================
    existing_selected = []
    existing_round = None
    
    if existing_data and 'epl' in existing_data:
        existing_epl = existing_data['epl']
        existing_selected = existing_epl.get('selected_matches', [])
        existing_round = existing_epl.get('selected_round')
    
    # 기존 선정 경기의 ID 목록
    existing_ids = {m.get('match_id') for m in existing_selected if m.get('match_id')}
    
    # =========================================================================
    # 현재 라운드 경기 상태 확인
    # =========================================================================
    current_matches_by_id = {}
    for match in matches:
        match_id = match.get('id')
        if match_id:
            current_matches_by_id[match_id] = match
    
    # =========================================================================
    # 기존 선정 경기 상태 업데이트 체크
    # =========================================================================
    if existing_selected and existing_ids:
        all_finished = True
        updated_matches = []
        
        for sel_match in existing_selected:
            match_id = sel_match.get('match_id')
            current = current_matches_by_id.get(match_id)
            
            if current:
                status = current.get('status', 'SCHEDULED')
                score = '-'
                
                if status == 'FINISHED':
                    home_score = current.get('score', {}).get('fullTime', {}).get('home', 0)
                    away_score = current.get('score', {}).get('fullTime', {}).get('away', 0)
                    score = f"{home_score}-{away_score}"
                elif status == 'IN_PLAY':
                    home_score = current.get('score', {}).get('fullTime', {}).get('home', 0)
                    away_score = current.get('score', {}).get('fullTime', {}).get('away', 0)
                    score = f"{home_score}-{away_score}"
                    all_finished = False
                else:
                    all_finished = False
                
                updated_matches.append({
                    **sel_match,
                    'status': status,
                    'score': score
                })
            else:
                updated_matches.append(sel_match)
                if sel_match.get('status') != 'FINISHED':
                    all_finished = False
        
        # 모두 종료되지 않았으면 기존 선정 유지 + 상태만 업데이트
        if not all_finished:
            log(f"   📌 기존 선정 경기 유지 (R{existing_round})")
            for m in updated_matches:
                status_icon = '✅' if m.get('status') == 'FINISHED' else '⏳'
                log(f"      {status_icon} {m['home']} vs {m['away']} [{m.get('status', 'SCHEDULED')}] {m.get('score', '-')}")
            return updated_matches, existing_round, False  # 새 선정 아님
        else:
            log(f"   🔄 기존 선정 경기 모두 종료 → 새로 선정")
    
    # =========================================================================
    # 새로운 경기 선정 (현재 라운드)
    # =========================================================================
    selected_matches = select_matches_from_round(matches, top_4, leader, serper_key)
    
    if selected_matches:
        log(f"   🏆 현재 라운드에서 {len(selected_matches)}경기 선정:")
        for m in selected_matches:
            tier = get_best_tier(m['rules'])
            log(f"      • [T{tier}] {m['home']} vs {m['away']} [{m['rule_str']}]")
        
        selected_round = selected_matches[0]['matchday'] if selected_matches else None
        return selected_matches, selected_round, True
    
    # =========================================================================
    # v2.3: 현재 라운드에 선정 가능 경기 없음 → 다음 라운드 조회
    # =========================================================================
    if football_api_key and current_matchday:
        next_matchday = current_matchday + 1
        log(f"   ⚠️ R{current_matchday}에 선정 가능 경기 없음 → R{next_matchday} 조회")
        
        next_round_matches = get_epl_matches(football_api_key, matchday=next_matchday)
        
        if next_round_matches:
            # 상태별 로그
            status_count = {}
            for m in next_round_matches:
                s = m.get('status', 'UNKNOWN')
                status_count[s] = status_count.get(s, 0) + 1
            log(f"   📋 R{next_matchday} 전체: {len(next_round_matches)}경기")
            log(f"   📊 상태별: {status_count}")
            
            selected_matches = select_matches_from_round(next_round_matches, top_4, leader, serper_key)
            
            if selected_matches:
                log(f"   🏆 다음 라운드(R{next_matchday})에서 {len(selected_matches)}경기 선정:")
                for m in selected_matches:
                    tier = get_best_tier(m['rules'])
                    log(f"      • [T{tier}] {m['home']} vs {m['away']} [{m['rule_str']}]")
                
                return selected_matches, next_matchday, True
            else:
                log(f"   ⚠️ R{next_matchday}에도 선정 가능 경기 없음")
    
    # 선정 가능한 경기 없음
    log(f"   ⚠️ 선정 가능한 경기 없음")
    return [], current_matchday, True

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
    # 1-1. 시즌 전체 경기로 전적 계산
    # =========================================================================
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

    # 순위는 Serper로 검색
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

        for game in upcoming[:2]:
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
# NBA All-Star Week (기간 내 자동 표시)
# =============================================================================
# 올스타 일정을 여기에 정의해두면, 해당 기간에만 자동으로 표시됩니다.
# 올스타가 끝나면 자동으로 사라집니다. 매년 새 일정으로 교체하면 됩니다.
#
# 2026 NBA All-Star Weekend: Feb 13-15, Los Angeles (Intuit Dome)
# KST 변환: ET + 14시간

ALLSTAR_DATA = {
    "title": "NBA All-Star 2026",
    "dates": "Feb 13-15",
    "location": "Los Angeles (Intuit Dome)",
    "note": "Steph Curry selected as starter",
    # 표시 기간: 이 날짜 범위 안에서만 대시보드에 노출
    "show_from": "2026-02-08",   # 올스타 1주 전부터 표시
    "show_until": "2026-02-17",  # 올스타 다음날까지 표시
    "events": [
        {
            "name": "Celebrity Game",
            "date": "02.14 (토)",
            "kst_time": "09:00",
            "et_time": "7:00 PM ET",
            "channel": "ESPN",
            "venue": "Kia Forum"
        },
        {
            "name": "Rising Stars",
            "date": "02.14 (토)",
            "kst_time": "11:00",
            "et_time": "9:00 PM ET",
            "channel": "Peacock",
            "venue": "Intuit Dome"
        },
        {
            "name": "Shooting Stars",
            "date": "02.15 (일)",
            "kst_time": "07:00",
            "et_time": "5:00 PM ET",
            "channel": "NBC",
            "venue": "Intuit Dome"
        },
        {
            "name": "3-Point Contest",
            "date": "02.15 (일)",
            "kst_time": "~08:00",
            "et_time": "~6:00 PM ET",
            "channel": "NBC",
            "venue": "Intuit Dome"
        },
        {
            "name": "Slam Dunk",
            "date": "02.15 (일)",
            "kst_time": "~09:00",
            "et_time": "~7:00 PM ET",
            "channel": "NBC",
            "venue": "Intuit Dome"
        },
        {
            "name": "75th All-Star Game",
            "date": "02.16 (월)",
            "kst_time": "07:00",
            "et_time": "5:00 PM ET",
            "channel": "NBC",
            "venue": "Intuit Dome"
        }
    ]
}

def inject_allstar_data(nba_data, kst_now):
    """
    올스타 기간이면 nba_data에 allstar 필드를 추가.
    기간 밖이면 아무것도 하지 않음.
    """
    try:
        show_from = datetime.date.fromisoformat(ALLSTAR_DATA["show_from"])
        show_until = datetime.date.fromisoformat(ALLSTAR_DATA["show_until"])
        today = kst_now.date()

        if show_from <= today <= show_until:
            allstar_output = {
                "title": ALLSTAR_DATA["title"],
                "dates": ALLSTAR_DATA["dates"],
                "location": ALLSTAR_DATA["location"],
                "note": ALLSTAR_DATA["note"],
                "events": ALLSTAR_DATA["events"]
            }
            nba_data["allstar"] = allstar_output
            log(f"   ⭐ All-Star Week 데이터 삽입 ({ALLSTAR_DATA['dates']})")
        else:
            log(f"   ℹ️ All-Star 표시 기간 아님 (표시: {ALLSTAR_DATA['show_from']} ~ {ALLSTAR_DATA['show_until']})")
    except Exception as e:
        log(f"   ⚠️ All-Star 데이터 처리 오류: {e}")

    return nba_data

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
        today = kst_now.date()

        test1_start = date(2026, 1, 26)
        test1_end = date(2026, 1, 30)
        test2_start = date(2026, 2, 11)
        test2_end = date(2026, 2, 13)
        test3_start = date(2026, 2, 18)
        test3_end = date(2026, 2, 20)

        if today < test1_start:
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 1 (Private)',
                'circuit': 'Barcelona-Catalunya',
                'date': 'Jan 26-30'
            }
        elif today <= test1_end:
            f1_data = {
                'status': 'Testing',
                'name': 'Test 1 (Private)',
                'circuit': 'Barcelona-Catalunya',
                'date': 'Jan 26-30'
            }
        elif today < test2_start:
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 2',
                'circuit': 'Bahrain International',
                'date': 'Feb 11-13'
            }
        elif today <= test2_end:
            f1_data = {
                'status': 'Testing',
                'name': 'Test 2',
                'circuit': 'Bahrain International',
                'date': 'Feb 11-13'
            }
        elif today < test3_start:
            f1_data = {
                'status': 'Pre-Season',
                'name': 'Test 3',
                'circuit': 'Bahrain International',
                'date': 'Feb 18-20'
            }
        elif today <= test3_end:
            f1_data = {
                'status': 'Testing',
                'name': 'Test 3',
                'circuit': 'Bahrain International',
                'date': 'Feb 18-20'
            }
        else:
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

    date_pattern = r'(March|April|May|June|July|August|September|October|November)\s+(\d{1,2})(?:-(\d{1,2}))?'
    date_match = re.search(date_pattern, text, re.IGNORECASE)
    if date_match:
        month = date_match.group(1)[:3]
        day_start = date_match.group(2)
        day_end = date_match.group(3) or str(int(day_start) + 2)
        f1_data['date'] = f"{month} {day_start}-{day_end}"

    return f1_data

# =============================================================================
# 테니스 함수 - v2.5 (Apps Script Web App 호출)
# =============================================================================
TENNIS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbxtXuoeprkGMGbLBIOoxtYK47lU4rQ4faJHAnW6clP1Exi8EO0eAqj-NM6efl9aSMbxSQ/exec"

def get_tennis_data_from_webapp():
    """
    Tennis (Alcaraz) - Apps Script Web App에서 데이터 가져오기
    """
    
    tournament_schedule = {
        'australian open': 'Jan 12 - Feb 2',
        'roland garros': 'May 25 - Jun 8',
        'french open': 'May 25 - Jun 8',
        'wimbledon': 'Jun 30 - Jul 13',
        'us open': 'Aug 25 - Sep 7',
        'indian wells': 'Mar 5 - 16',
        'miami open': 'Mar 19 - 30',
        'monte carlo': 'Apr 6 - 13',
        'madrid open': 'Apr 27 - May 4',
        'italian open': 'May 11 - 18',
        'canadian open': 'Aug 4 - 10',
        'cincinnati': 'Aug 11 - 17',
        'shanghai': 'Oct 5 - 12',
        'paris masters': 'Oct 27 - Nov 2',
        'atp finals': 'Nov 9 - 16',
    }
    
    default_data = {
        'recent': {'event': '-', 'opponent': '-', 'result': '-', 'score': '-', 'date': '-'},
        'next': {'event': '-', 'detail': '-', 'match_time': 'TBD', 'tournament_dates': '', 'status': '-'}
    }
    
    try:
        response = requests.get(TENNIS_WEBAPP_URL, timeout=30)
        if response.status_code != 200:
            log(f"   ⚠️ Web App 호출 실패: {response.status_code}")
            return default_data
        
        data = response.json()
        
        if 'error' in data:
            log(f"   ⚠️ Web App 에러: {data['error']}")
            return default_data
        
        recent = data.get('recent', {})
        next_data = data.get('next', {})
        next_event = next_data.get('event', '-')
        next_opponent = next_data.get('opponent', '-')
        next_round = next_data.get('round', '-')
        next_date = next_data.get('date', '-')
        time_kst = next_data.get('time_kst', '-')
        
        if next_round != '-' and next_opponent != '-':
            next_detail = f"{next_round} vs {next_opponent}"
        elif next_round != '-':
            next_detail = next_round
        elif next_opponent != '-':
            next_detail = f"vs {next_opponent}"
        else:
            next_detail = '-'
        
        if time_kst != '-':
            match_time = f"{next_date} {time_kst} KST"
        else:
            match_time = next_date
        
        tournament_dates = ''
        for keyword, dates in tournament_schedule.items():
            if keyword in next_event.lower():
                tournament_dates = dates
                break
        
        status_map = {
            'australian open': 'Grand Slam', 'french open': 'Grand Slam', 
            'roland garros': 'Grand Slam', 'wimbledon': 'Grand Slam', 
            'us open': 'Grand Slam', 'indian wells': 'Masters', 
            'miami': 'Masters', 'monte carlo': 'Masters', 
            'madrid': 'Masters', 'rome': 'Masters', 'italian': 'Masters',
            'cincinnati': 'Masters', 'shanghai': 'Masters', 
            'paris masters': 'Masters', 'atp finals': 'Finals'
        }
        next_status = '-'
        for keyword, status in status_map.items():
            if keyword in next_event.lower():
                next_status = status
                break
        
        tennis_data = {
            'recent': {
                'event': recent.get('event', '-'),
                'opponent': recent.get('opponent', '-'),
                'result': recent.get('result', '-'),
                'score': recent.get('score', '-'),
                'date': recent.get('date', '-')
            },
            'next': {
                'event': next_event,
                'detail': next_detail,
                'match_time': match_time,
                'tournament_dates': tournament_dates,
                'status': next_status
            }
        }
        
        return tennis_data
        
    except requests.exceptions.Timeout:
        log(f"   ⚠️ Web App 타임아웃")
        return default_data
    except Exception as e:
        log(f"   ⚠️ Web App 예외: {e}")
        return default_data

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    football_api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    serper_api_key = os.environ.get("SERPER_API_KEY")
    balldontlie_api_key = os.environ.get("BALLDONTLIE_API_KEY")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

    if not football_api_key:
        log("❌ Error: FOOTBALL_DATA_API_KEY Missing")
        raise ValueError("FOOTBALL_DATA_API_KEY Missing")

    kst_now = get_kst_now()

    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Data Sources:")
    log(f"   - EPL: Football-Data.org ✅")
    log(f"   - NBA: balldontlie.io {'✅' if balldontlie_api_key else '❌'}")
    log(f"   - Search: Serper API {'✅' if serper_api_key else '❌'}")

    # 기존 데이터 로드
    existing_data = load_existing_sports_data()

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
    # STEP 2: EPL 경기 일정 + 6가지 룰 + 티어 우선순위
    # =========================================================================
    log("\n⚽ [Step 2/5] Premier League 경기 선정 (v2.3)...")
    log("   [티어 우선순위]")
    log("   T1. Big Match: Big 6 vs Big 6")
    log("   T2. Top Tier: Top 4 vs Top 4")
    log("   T3. Challenger: Top 4 vs Big 6")
    log("   T4. Prime Time: 일요일 16:30 UK")
    log("   T5. Early KO: 토요일 12:30 UK")
    log("   T6. Leader: 1위 팀 포함")
    log(f"   [최대 선정: {MAX_EPL_MATCHES}경기]")

    matches = get_epl_matches(football_api_key, current_matchday)
    
    # 상태별 경기 수 로그 (디버깅용)
    status_count = {}
    for m in matches:
        s = m.get('status', 'UNKNOWN')
        status_count[s] = status_count.get(s, 0) + 1
    log(f"   📋 R{current_matchday} 전체: {len(matches)}경기")
    log(f"   📊 상태별: {status_count}")

    # v2.3: football_api_key와 current_matchday 전달하여 다음 라운드 조회 가능하게
    validated_epl, selected_round, is_new_selection = process_epl_matches(
        matches, top_4_teams, leader_team, serper_api_key, existing_data,
        football_api_key=football_api_key,  # v2.3 추가
        current_matchday=current_matchday    # v2.3 추가
    )
    
    if is_new_selection:
        log(f"   ✅ 새로 선정됨: {len(validated_epl)}경기 (R{selected_round})")
    else:
        log(f"   ✅ 기존 선정 유지: {len(validated_epl)}경기 (R{selected_round})")

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
    # STEP 5: Tennis (Apps Script Web App)
    # =========================================================================
    log("\n🎾 [Step 5/5] Tennis (Alcaraz) - Web App...")

    tennis_data = get_tennis_data_from_webapp()
    recent = tennis_data.get('recent', {})
    next_match = tennis_data.get('next', {})
    log(f"   ✅ Recent: {recent.get('event', '-')} vs {recent.get('opponent', '-')} {recent.get('result', '-')} ({recent.get('score', '-')}) | {recent.get('date', '-')}")
    log(f"   ✅ Next: {next_match.get('event', '-')} | {next_match.get('detail', '-')} | {next_match.get('match_time', '-')} [{next_match.get('status', '-')}]")

    # =========================================================================
    # NBA All-Star Week 데이터 삽입 (기간 내 자동 표시/숨김)
    # =========================================================================
    nba_data = inject_allstar_data(nba_data, kst_now)

    # =========================================================================
    # 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")

    # EPL 표시용 라운드: 선정된 라운드가 있으면 그것 사용, 없으면 현재 라운드
    display_matchday = f"R{selected_round}" if selected_round else f"R{current_matchday}"

    sports_data = {
        "updated": kst_now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "epl": {
            "matchday": current_matchday,
            "selected_round": selected_round,
            "display_matchday": display_matchday,
            "leader": leader_team,
            "top4": top_4_teams,
            "matches": validated_epl,
            "selected_matches": validated_epl
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
