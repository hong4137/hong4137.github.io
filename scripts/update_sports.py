#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater v2.5
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

[v2.5 변경사항]
- Tennis: Web App 데이터 검증 + Serper/Gemini 보완 로직 추가
- Tennis: 대회 진행 중 next 경기 상대/라운드/시간 정확도 대폭 개선
- Tennis: 같은 대회 내 다음 경기 감지 (recent 대회 == 현재 진행 중)

[v2.4 변경사항]
- EPL: 기존 선정 라운드 경기를 별도 API 조회하여 정확한 상태 확인
- EPL: 경기 시간 3시간 경과 시 강제 FINISHED 처리 (API 미반영 방지)

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
import time
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
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
KOREAN_OVERSEAS_FILE = 'korean_overseas.json'
KOREAN_OVERSEAS_HISTORY_FILE = 'korean_overseas_history.json'
FOOTBALL_DATA_API_URL = "https://api.football-data.org/v4"
SERPER_API_URL = "https://google.serper.dev/search"
BALLDONTLIE_API_URL = "https://api.balldontlie.io/v1"
THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
OVERSEAS_REQUEST_DELAY_SEC = 2
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

LOG_MESSAGES = []

def log(message):
    """버퍼링 없이 즉시 출력 + LOG_MESSAGES에 누적"""
    print(message, flush=True)
    LOG_MESSAGES.append(str(message))

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
        else:
            body = response.text[:300]
            if response.status_code == 400 and "credit" in body.lower():
                log(f"   🚨 Serper API 크레딧 소진 — 검색 기반 데이터(LAFC 등 API 미지원 항목) 수집이 전면 중단됩니다. https://serper.dev 에서 크레딧 충전 필요. body={body}")
            else:
                log(f"   ⚠️ Serper API error: status={response.status_code}, body={body}")
    except Exception as e:
        log(f"   ⚠️ Serper API exception: {e}")
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
    if not api_key:
        return None, None, None

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
    if not api_key:
        return []

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

def load_json_safe(file_path, default=None):
    """JSON 파일을 안전하게 로드하고 파일 부재/파싱 실패 시 기본값을 반환한다."""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as ex:
        log(f"   ⚠️ JSON 로드 실패({file_path}): {ex}")
    return default

# =============================================================================
# v2.4 신규: 경기 시간 경과 확인
# =============================================================================
def is_match_past(kst_time_str):
    """
    v2.4: 경기 시간이 3시간 이상 지났는지 확인 (경기 종료 여유)
    kst_time_str 예: "02.23 01:30 (KST)"
    """
    try:
        kst_now = get_kst_now()
        clean = kst_time_str.replace(" (KST)", "").strip()
        year = kst_now.year
        match_dt = datetime.datetime.strptime(f"{year}.{clean}", "%Y.%m.%d %H:%M")
        match_dt = match_dt.replace(tzinfo=TZ_KST)
        return kst_now > match_dt + timedelta(hours=3)
    except:
        return False

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
    EPL 경기 처리 및 필터링 (v2.4 redesign)
    
    핵심 원칙:
    - matches는 항상 단일 라운드 경기만 전달받음
    - current_matchday는 선정 대상 라운드 (가장 가까운 미종료 라운드)
    - 기존 선정 라운드와 다르면 → 새로 선정
    - 기존 선정 라운드와 같으면 → 상태 업데이트, 모두 종료 시 새로 선정 불필요
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
    
    has_existing = bool(existing_selected)
    
    # =========================================================================
    # 기존 선정 라운드와 대상 라운드가 다르면 → 새로 선정
    # =========================================================================
    if has_existing and existing_round != current_matchday:
        # 기존 선정 경기가 진행 중인지 확인
        matches_by_id = {m.get('id'): m for m in matches if m.get('id')}
        
        # 기존 선정 라운드 경기 별도 조회
        existing_live = False
        if football_api_key and existing_round:
            round_matches = get_epl_matches(football_api_key, matchday=existing_round)
            for rm in round_matches:
                if rm.get('id') in {m.get('match_id') for m in existing_selected}:
                    if rm.get('status') == 'IN_PLAY':
                        existing_live = True
                        break
        
        if existing_live:
            log(f"   🔴 기존 R{existing_round} 경기 진행 중 → 유지")
            return existing_selected, existing_round, False
        
        log(f"   🔄 라운드 변경: R{existing_round} → R{current_matchday} (새로 선정)")
        # 아래 새 선정으로 진행
    
    # =========================================================================
    # 기존 선정 라운드와 같으면 → 상태 업데이트
    # =========================================================================
    elif has_existing and existing_round == current_matchday:
        # 기존 경기가 실제로 이 라운드에 속하는지 검증
        matches_by_id = {m.get('id'): m for m in matches if m.get('id')}
        
        mismatch = False
        for sel_match in existing_selected:
            mid = sel_match.get('match_id')
            api_match = matches_by_id.get(mid)
            if api_match:
                actual_rd = api_match.get('matchday')
                if actual_rd and actual_rd != current_matchday:
                    log(f"      ⚠️ {sel_match['home']} vs {sel_match['away']}: R{actual_rd} (선정 R{current_matchday}와 불일치)")
                    mismatch = True
            elif sel_match.get('status') != 'FINISHED':
                sel_md = sel_match.get('matchday')
                if sel_md and sel_md != current_matchday:
                    log(f"      ⚠️ {sel_match['home']} vs {sel_match['away']}: 저장된 R{sel_md} (불일치)")
                    mismatch = True
        
        if mismatch:
            log(f"   🔄 기존 선정에 다른 라운드 경기 혼입 → R{current_matchday}에서 새로 선정")
            # 아래 "새로운 경기 선정" 섹션으로 fall through
        else:
            # 상태 업데이트
            all_finished = True
            has_in_play = False
            updated_matches = []
            
            for sel_match in existing_selected:
                match_id = sel_match.get('match_id')
                current = matches_by_id.get(match_id)
                status = sel_match.get('status', 'SCHEDULED')
                score = sel_match.get('score', '-')
                
                if current:
                    status = current.get('status', 'SCHEDULED')
                    if status == 'FINISHED':
                        hs = current.get('score', {}).get('fullTime', {}).get('home', 0)
                        as_ = current.get('score', {}).get('fullTime', {}).get('away', 0)
                        score = f"{hs}-{as_}"
                    elif status == 'IN_PLAY':
                        hs = current.get('score', {}).get('fullTime', {}).get('home', 0)
                        as_ = current.get('score', {}).get('fullTime', {}).get('away', 0)
                        score = f"{hs}-{as_}"
                        has_in_play = True
                        all_finished = False
                    else:
                        if is_match_past(sel_match.get('kst_time', '')):
                            log(f"      ⏰ 강제 FINISHED: {sel_match['home']} vs {sel_match['away']}")
                            status = 'FINISHED'
                            score = 'N/A'
                        else:
                            all_finished = False
                else:
                    if is_match_past(sel_match.get('kst_time', '')):
                        status = 'FINISHED'
                        score = 'N/A'
                    elif status != 'FINISHED':
                        all_finished = False
                
                updated_matches.append({**sel_match, 'status': status, 'score': score})
            
            # v2.5: 기존 선정이 MAX보다 적으면, 더 높은 티어 경기가 있는지 확인 후 보충/교체
            existing_ids = {m.get('match_id') for m in updated_matches}
            existing_best_tier = min((get_best_tier(m.get('rules', [])) for m in updated_matches), default=99)
            
            if len(updated_matches) < MAX_EPL_MATCHES or True:
                # 현재 라운드에서 선정 가능한 모든 경기를 다시 계산
                all_candidates = select_matches_from_round(matches, top_4, leader, serper_key)
                
                # 기존에 없는 더 좋은 경기가 있는지 확인
                new_candidates = [c for c in all_candidates if c.get('match_id') not in existing_ids]
                better_candidates = [c for c in new_candidates if get_best_tier(c.get('rules', [])) < existing_best_tier]
                
                if better_candidates:
                    # 더 높은 티어 경기 발견 → 전체 재선정
                    log(f"   🔄 더 높은 티어 경기 발견 → 재선정")
                    for bc in better_candidates:
                        tier = get_best_tier(bc['rules'])
                        log(f"      ⬆️ [T{tier}] {bc['home']} vs {bc['away']} [{bc['rule_str']}]")
                    # fall through to 새 선정 (아래로)
                elif len(updated_matches) < MAX_EPL_MATCHES and new_candidates:
                    # 부족분 보충
                    slots = MAX_EPL_MATCHES - len(updated_matches)
                    for nc in new_candidates[:slots]:
                        updated_matches.append(nc)
                        log(f"      ➕ 보충: {nc['home']} vs {nc['away']} [{nc['rule_str']}]")
                    
                    if not all_finished:
                        log(f"   📌 기존 선정 + 보충 (R{existing_round}): {len(updated_matches)}경기")
                        return updated_matches, existing_round, False
                    else:
                        log(f"   🔄 R{existing_round} 경기 모두 종료")
                        return updated_matches, existing_round, False
                else:
                    # 변동 없음 → 기존 유지
                    if not all_finished:
                        log(f"   📌 기존 선정 유지 (R{existing_round})")
                        for m in updated_matches:
                            icon = '🔴' if m.get('status') == 'IN_PLAY' else ('✅' if m.get('status') == 'FINISHED' else '⏳')
                            log(f"      {icon} {m['home']} vs {m['away']} [{m.get('status')}] {m.get('score', '-')}")
                        return updated_matches, existing_round, False
                    else:
                        log(f"   🔄 R{existing_round} 경기 모두 종료 → 새로 선정 불필요")
                        return updated_matches, existing_round, False
    
    # =========================================================================
    # 새로운 경기 선정 (단일 라운드에서)
    # =========================================================================
    selected_matches = select_matches_from_round(matches, top_4, leader, serper_key)
    
    if selected_matches:
        log(f"   🏆 R{current_matchday}에서 {len(selected_matches)}경기 선정:")
        for m in selected_matches:
            tier = get_best_tier(m['rules'])
            log(f"      • [T{tier}] {m['home']} vs {m['away']} [{m['rule_str']}] {m['kst_time']}")
        return selected_matches, current_matchday, True
    
    log(f"   ⚠️ R{current_matchday}에 선정 가능한 경기 없음")
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
ALLSTAR_DATA = {
    "title": "NBA All-Star 2026",
    "dates": "Feb 13-15",
    "location": "Los Angeles (Intuit Dome)",
    "note": "Steph Curry selected as starter",
    "show_from": "2026-02-13",
    "show_until": "2026-02-17",
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
    """올스타 기간이면 nba_data에 allstar 필드를 추가."""
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
# Korean Players 함수 (TheSportsDB/Football-Data.org 우선 + Serper/Gemini 폴백)
# =============================================================================

# 코리안리거 추적 대상 (하이브리드 소스: API 우선 → 검색 폴백)
KOREAN_PLAYERS = [
    {"player": "이강인", "team_label": "ATM", "team_name": "Atletico Madrid",
     "team_id": 78, "competition_label": "La Liga", "thesportsdb_url": None},
    {"player": "김민재", "team_label": "Bayern", "team_name": "Bayern Munich",
     "team_id": 5, "competition_label": "Bundesliga", "thesportsdb_url": None},
    {"player": "손흥민", "team_label": "LAFC", "team_name": "LAFC",
     "team_id": None, "competition_label": "MLS",
     "thesportsdb_url": "https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=136050"},
]

# 해외파 코리안리거 돋보기 — 위 KOREAN_PLAYERS 3인은 별도 파이프라인으로 유지
# 팀 ID는 TheSportsDB searchplayers/searchteams, 슬러그는 ESPN 공식 선수 페이지로 재검증했다.
KOREAN_OVERSEAS_PLAYERS = [
    {"player": "황희찬", "team_label": "Wolverhampton Wanderers", "thesportsdb_team_id": 133599, "espn_player_id": 237224, "espn_slug": "hwang-hee-chan"},
    {"player": "이재성", "team_label": "Mainz", "thesportsdb_team_id": 133665, "espn_player_id": 134103, "espn_slug": "lee-jae-sung"},
    {"player": "황인범", "team_label": "Porto", "thesportsdb_team_id": 134114, "espn_player_id": 280061, "espn_slug": "hwang-in-beom"},
    {"player": "배준호", "team_label": "Stoke City", "thesportsdb_team_id": 133609, "espn_player_id": 362208, "espn_slug": "bae-jun-ho"},
    {"player": "오현규", "team_label": "Beşiktaş", "thesportsdb_team_id": 133794, "espn_player_id": 302434, "espn_slug": "oh-hyun-gyu"},
    {"player": "백승호", "team_label": "Birmingham City", "thesportsdb_team_id": 133597, "espn_player_id": 256598, "espn_slug": "paik-seung-ho"},
    {"player": "엄지성", "team_label": "Swansea City", "thesportsdb_team_id": 133614, "espn_player_id": 297791, "espn_slug": "eom-ji-sung"},
    {"player": "조규성", "team_label": "FC Midtjylland", "thesportsdb_team_id": 133891, "espn_player_id": 303464, "espn_slug": "cho-gue-sung"},
    {"player": "설영우", "team_label": "Crvena Zvezda", "thesportsdb_team_id": 133987, "espn_player_id": 302793, "espn_slug": "seol-young-woo"},
]

# 대회명 → 표시용 축약 라벨
COMPETITION_SHORT_LABELS = {
    "Primera Division": "La Liga",
    "Bundesliga": "Bundesliga",
    "Premier League": "Premier League",
    "Major League Soccer": "MLS",
    "DFB-Pokal": "DFB-Pokal",
    "Copa del Rey": "Copa del Rey",
    "UEFA Champions League": "UCL",
    "UEFA Europa League": "UEL",
}

# 컵대회 녹아웃 스테이지 → 한국어 라벨
STAGE_LABELS_KR = {
    "GROUP_STAGE": "조별리그",
    "LAST_16": "16강",
    "ROUND_OF_16": "16강",
    "QUARTER_FINALS": "8강",
    "SEMI_FINALS": "4강",
    "FINAL": "결승",
}

def format_match_round_label(match, fallback_label):
    """football-data.org 매치 정보 → 'La Liga R1' / 'DFB-Pokal 16강' / '친선전' 등 표시용 라벨"""
    comp = match.get("competition", {}) or {}
    comp_name = comp.get("name", "")

    if "friendl" in comp_name.lower():
        return "친선전"

    short = COMPETITION_SHORT_LABELS.get(comp_name, comp_name or fallback_label)
    stage = match.get("stage", "")
    matchday = match.get("matchday")

    if stage == "REGULAR_SEASON" and matchday:
        return f"{short} R{matchday}"
    if stage in STAGE_LABELS_KR:
        return f"{short} {STAGE_LABELS_KR[stage]}"
    if matchday:
        return f"{short} R{matchday}"
    return short

# 하드코딩 — F1_2026_CALENDAR와 동일한 관리 방식. API/검색 모두 실패 시 최종 폴백.
KOREAN_PLAYERS_DEFAULT_FALLBACK = {
    "이강인": {"opponent": "Málaga CF", "venue": "home", "kst_date": "08.20", "kst_time": "04:00", "competition": "La Liga R1"},
    "김민재": {"opponent": "VfB Stuttgart", "venue": "home", "kst_date": "08.29", "kst_time": "03:30", "competition": "Bundesliga R1"},
    "손흥민": {"opponent": "Portland Timbers", "venue": "home", "kst_date": "08.23", "kst_time": "11:30", "competition": "MLS"},
}

# =============================================================================
# F1 함수 - v2.5 (순위 + 세부 스케줄)
# =============================================================================

# 2026 F1 캘린더 (하드코딩 - 시즌 시작 전 업데이트)
F1_2026_CALENDAR = [
    {'round': 1, 'name': 'Australian Grand Prix', 'circuit': 'Albert Park, Melbourne', 'country': 'Australia',
     'date_from': '2026-03-06', 'date_to': '2026-03-08', 'local_tz': 'AEDT', 'utc_offset': 11, 'sprint': False},
    {'round': 2, 'name': 'Chinese Grand Prix', 'circuit': 'Shanghai International Circuit', 'country': 'China',
     'date_from': '2026-03-13', 'date_to': '2026-03-15', 'local_tz': 'CST', 'utc_offset': 8, 'sprint': True},
    {'round': 3, 'name': 'Japanese Grand Prix', 'circuit': 'Suzuka Circuit', 'country': 'Japan',
     'date_from': '2026-03-27', 'date_to': '2026-03-29', 'local_tz': 'JST', 'utc_offset': 9, 'sprint': False},
    # Round 4-5 (Bahrain, Saudi Arabia) CANCELLED due to Middle East situation
    {'round': 6, 'name': 'Miami Grand Prix', 'circuit': 'Miami International Autodrome', 'country': 'USA',
     'date_from': '2026-05-01', 'date_to': '2026-05-03', 'local_tz': 'EDT', 'utc_offset': -4, 'sprint': True},
    {'round': 7, 'name': 'Canadian Grand Prix', 'circuit': 'Circuit Gilles Villeneuve, Montreal', 'country': 'Canada',
     'date_from': '2026-05-15', 'date_to': '2026-05-17', 'local_tz': 'EDT', 'utc_offset': -4, 'sprint': True},
    {'round': 8, 'name': 'Monaco Grand Prix', 'circuit': 'Circuit de Monaco', 'country': 'Monaco',
     'date_from': '2026-05-22', 'date_to': '2026-05-24', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 9, 'name': 'Spanish Grand Prix', 'circuit': 'Circuit de Barcelona-Catalunya', 'country': 'Spain',
     'date_from': '2026-06-05', 'date_to': '2026-06-07', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 10, 'name': 'Austrian Grand Prix', 'circuit': 'Red Bull Ring, Spielberg', 'country': 'Austria',
     'date_from': '2026-06-26', 'date_to': '2026-06-28', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 11, 'name': 'British Grand Prix', 'circuit': 'Silverstone Circuit', 'country': 'UK',
     'date_from': '2026-07-03', 'date_to': '2026-07-05', 'local_tz': 'BST', 'utc_offset': 1, 'sprint': True},
    {'round': 12, 'name': 'Belgian Grand Prix', 'circuit': 'Circuit de Spa-Francorchamps', 'country': 'Belgium',
     'date_from': '2026-07-17', 'date_to': '2026-07-19', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 13, 'name': 'Hungarian Grand Prix', 'circuit': 'Hungaroring, Budapest', 'country': 'Hungary',
     'date_from': '2026-07-24', 'date_to': '2026-07-26', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 14, 'name': 'Dutch Grand Prix', 'circuit': 'Circuit Zandvoort', 'country': 'Netherlands',
     'date_from': '2026-08-21', 'date_to': '2026-08-23', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': True},
    {'round': 15, 'name': 'Italian Grand Prix', 'circuit': 'Autodromo di Monza', 'country': 'Italy',
     'date_from': '2026-09-04', 'date_to': '2026-09-06', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 16, 'name': 'Spanish Grand Prix (Madrid)', 'circuit': 'Circuito Urbano de Madrid', 'country': 'Spain',
     'date_from': '2026-09-11', 'date_to': '2026-09-13', 'local_tz': 'CEST', 'utc_offset': 2, 'sprint': False},
    {'round': 17, 'name': 'Azerbaijan Grand Prix', 'circuit': 'Baku City Circuit', 'country': 'Azerbaijan',
     'date_from': '2026-09-18', 'date_to': '2026-09-20', 'local_tz': 'AZT', 'utc_offset': 4, 'sprint': False},
    {'round': 18, 'name': 'Singapore Grand Prix', 'circuit': 'Marina Bay Street Circuit', 'country': 'Singapore',
     'date_from': '2026-10-02', 'date_to': '2026-10-04', 'local_tz': 'SGT', 'utc_offset': 8, 'sprint': True},
    {'round': 19, 'name': 'United States Grand Prix', 'circuit': 'COTA, Austin', 'country': 'USA',
     'date_from': '2026-10-16', 'date_to': '2026-10-18', 'local_tz': 'CDT', 'utc_offset': -5, 'sprint': False},
    {'round': 20, 'name': 'Mexico City Grand Prix', 'circuit': 'Autódromo Hermanos Rodríguez', 'country': 'Mexico',
     'date_from': '2026-10-23', 'date_to': '2026-10-25', 'local_tz': 'CDT', 'utc_offset': -5, 'sprint': False},
    {'round': 21, 'name': 'São Paulo Grand Prix', 'circuit': 'Interlagos, São Paulo', 'country': 'Brazil',
     'date_from': '2026-11-06', 'date_to': '2026-11-08', 'local_tz': 'BRT', 'utc_offset': -3, 'sprint': False},
    {'round': 22, 'name': 'Las Vegas Grand Prix', 'circuit': 'Las Vegas Strip Circuit', 'country': 'USA',
     'date_from': '2026-11-20', 'date_to': '2026-11-22', 'local_tz': 'PST', 'utc_offset': -8, 'sprint': False},
    {'round': 23, 'name': 'Qatar Grand Prix', 'circuit': 'Lusail International Circuit', 'country': 'Qatar',
     'date_from': '2026-11-27', 'date_to': '2026-11-29', 'local_tz': 'AST', 'utc_offset': 3, 'sprint': False},
    {'round': 24, 'name': 'Abu Dhabi Grand Prix', 'circuit': 'Yas Marina Circuit', 'country': 'UAE',
     'date_from': '2026-12-04', 'date_to': '2026-12-06', 'local_tz': 'GST', 'utc_offset': 4, 'sprint': False},
]

def get_f1_next_race():
    """캘린더에서 다음/현재 GP 찾기"""
    kst_now = get_kst_now()
    today = kst_now.date()
    
    for gp in F1_2026_CALENDAR:
        gp_end = datetime.date.fromisoformat(gp['date_to'])
        if today <= gp_end:
            gp_start = datetime.date.fromisoformat(gp['date_from'])
            if today >= gp_start:
                status = 'This Week'
            else:
                status = 'Next GP'
            return {**gp, 'status': status}
    
    # 시즌 종료
    return None

def get_f1_race_schedule(gp_info):
    """
    GP의 세부 세션 스케줄 생성 (KST 시간 포함)
    표준 스케줄 기반 + UTC offset으로 KST 변환
    """
    if not gp_info:
        return []
    
    date_from = datetime.date.fromisoformat(gp_info['date_from'])
    utc_offset = gp_info.get('utc_offset', 0)
    is_sprint = gp_info.get('sprint', False)
    
    friday = date_from
    saturday = date_from + timedelta(days=1)
    sunday = date_from + timedelta(days=2)
    
    sessions = []
    
    if is_sprint:
        # 스프린트 주말 포맷: FP1, SQ, Sprint, Qualifying, Race
        # 일반적 현지 시간대 (변동 가능하지만 대략적 기준)
        sprint_schedule = [
            (friday, 'FP1', 13, 30),
            (friday, 'Sprint Qualifying', 17, 30),
            (saturday, 'Sprint', 12, 0),
            (saturday, 'Qualifying', 16, 0),
            (sunday, 'Race', 15, 0),
        ]
        for day, name, local_h, local_m in sprint_schedule:
            utc_h = local_h - utc_offset
            kst_h = utc_h + 9
            # 날짜 보정
            kst_date = day
            if kst_h >= 24:
                kst_h -= 24
                kst_date = day + timedelta(days=1)
            elif kst_h < 0:
                kst_h += 24
                kst_date = day - timedelta(days=1)
            
            sessions.append({
                'name': name,
                'date': kst_date.strftime("%m.%d"),
                'day_local': day.strftime("%a"),
                'kst_time': f"{kst_h:02d}:{local_m:02d}",
                'local_time': f"{local_h:02d}:{local_m:02d}",
            })
    else:
        # 표준 주말 포맷: FP1, FP2, FP3, Qualifying, Race
        # 세션별 기본 현지 시간 (서킷마다 다를 수 있지만 일반적 기준)
        standard_schedule = [
            (friday, 'FP1', 13, 30),
            (friday, 'FP2', 17, 0),
            (saturday, 'FP3', 12, 30),
            (saturday, 'Qualifying', 16, 0),
            (sunday, 'Race', 15, 0),
        ]
        
        for day, name, local_h, local_m in standard_schedule:
            utc_h = local_h - utc_offset
            kst_h = utc_h + 9
            kst_date = day
            if kst_h >= 24:
                kst_h -= 24
                kst_date = day + timedelta(days=1)
            elif kst_h < 0:
                kst_h += 24
                kst_date = day - timedelta(days=1)
            
            sessions.append({
                'name': name,
                'date': kst_date.strftime("%m.%d"),
                'day_local': day.strftime("%a"),
                'kst_time': f"{kst_h:02d}:{local_m:02d}",
                'local_time': f"{local_h:02d}:{local_m:02d}",
            })
    
    return sessions

def get_f1_standings(serper_key, gemini_key):
    """
    F1 드라이버 순위 가져오기
    1차: 신뢰할 수 있는 페이지 직접 fetch + regex 파싱
    2차: Serper 검색 + Gemini 파싱 (fallback)
    """
    
    # =========================================================================
    # 1차: 웹페이지 직접 fetch (total-motorsport.com 테이블)
    # =========================================================================
    standings_urls = [
        "https://www.formula1.com/en/results/2026/drivers",
        "https://www.total-motorsport.com/f1-driver-standings-2026/",
        "https://racingnews365.com/f1/standings/2026/drivers",
        "https://www.motorsport.com/f1/standings/",
    ]
    
    for url in standings_urls:
        try:
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; DashboardBot/1.0)'
            })
            if resp.status_code != 200:
                continue
            
            page_text = resp.text
            standings = parse_f1_standings_from_html(page_text)
            if standings and len(standings) >= 5:
                log(f"      ✅ 순위 직접 파싱 성공 ({url.split('/')[2]}): {len(standings)}명")
                return standings[:10]
        except Exception as e:
            log(f"      ⚠️ fetch 실패 ({url.split('/')[2]}): {e}")
            continue
    
    # =========================================================================
    # 2차: Serper + Gemini fallback
    # =========================================================================
    if not serper_key:
        return None
    
    query = "F1 2026 driver championship standings points table"
    result = call_serper_api(query, serper_key)
    
    if not result:
        return None
    
    # 검색 결과 중 유용한 URL을 fetch 시도
    for item in result.get('organic', [])[:3]:
        item_url = item.get('link', '')
        if not item_url:
            continue
        if 'standings' in item_url.lower() or 'championship' in item_url.lower():
            try:
                resp = requests.get(item_url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; DashboardBot/1.0)'
                })
                if resp.status_code == 200:
                    standings = parse_f1_standings_from_html(resp.text)
                    if standings and len(standings) >= 5:
                        log(f"      ✅ Serper URL 파싱 성공: {len(standings)}명")
                        return standings[:10]
            except:
                continue
    
    # Serper snippet에서 직접 파싱
    text = ""
    if 'answerBox' in result:
        text += result['answerBox'].get('snippet', '') + " "
        text += result['answerBox'].get('answer', '') + " "
    if 'sportsResults' in result:
        text += json.dumps(result['sportsResults']) + " "
    for item in result.get('organic', [])[:5]:
        text += item.get('snippet', '') + " "
    
    # Gemini 파싱 시도
    if gemini_key and text.strip():
        kst_now = get_kst_now()
        today_str = kst_now.strftime("%B %d, %Y")
        
        prompt = f"""You are an F1 data extractor. Today is {today_str}.

Extract the current 2026 F1 World Championship Driver Standings (top 10) with ACCURATE points.
Points after each race: 1st=25, 2nd=18, 3rd=15, 4th=12, 5th=10, 6th=8, 7th=6, 8th=4, 9th=2, 10th=1.

Search results:
---
{text[:3000]}
---

CRITICAL: Each driver's points must be DIFFERENT (unless truly tied). Do NOT give everyone the same points.

Respond with ONLY a JSON array, no markdown:
[{{"pos": 1, "driver": "Full Name", "team": "Team Name", "points": 25}}, ...]

If unsure, respond: []"""
        
        gemini_response = call_gemini_api(prompt, gemini_key)
        
        if gemini_response:
            try:
                clean = gemini_response.strip()
                clean = re.sub(r'^```(?:json)?\s*', '', clean)
                clean = re.sub(r'\s*```$', '', clean)
                standings = json.loads(clean)
                if isinstance(standings, list) and len(standings) >= 5:
                    # 검증: 모든 포인트가 같으면 잘못된 파싱
                    points_set = set(s.get('points', 0) for s in standings[:5])
                    if len(points_set) >= 3:  # 최소 3종류 이상의 포인트
                        return standings[:10]
                    else:
                        log(f"      ⚠️ Gemini 결과 의심 (포인트 중복): {points_set}")
            except:
                log(f"      ⚠️ Gemini F1 standings 파싱 실패")
    
    return None

def parse_f1_standings_from_html(html_text):
    """
    HTML 페이지에서 F1 드라이버 순위 테이블 파싱
    다양한 형식의 테이블/리스트를 처리
    """
    known_drivers = {
        'Russell': ('George Russell', 'Mercedes'),
        'Antonelli': ('Kimi Antonelli', 'Mercedes'),
        'Leclerc': ('Charles Leclerc', 'Ferrari'),
        'Hamilton': ('Lewis Hamilton', 'Ferrari'),
        'Norris': ('Lando Norris', 'McLaren'),
        'Verstappen': ('Max Verstappen', 'Red Bull'),
        'Bearman': ('Oliver Bearman', 'Haas'),
        'Lindblad': ('Arvid Lindblad', 'Racing Bulls'),
        'Bortoleto': ('Gabriel Bortoleto', 'Audi'),
        'Gasly': ('Pierre Gasly', 'Alpine'),
        'Piastri': ('Oscar Piastri', 'McLaren'),
        'Sainz': ('Carlos Sainz', 'Williams'),
        'Albon': ('Alexander Albon', 'Williams'),
        'Stroll': ('Lance Stroll', 'Aston Martin'),
        'Alonso': ('Fernando Alonso', 'Aston Martin'),
        'Tsunoda': ('Yuki Tsunoda', 'Red Bull'),
        'Hulkenberg': ('Nico Hülkenberg', 'Audi'),
        'Hülkenberg': ('Nico Hülkenberg', 'Audi'),
        'Ocon': ('Esteban Ocon', 'Haas'),
        'Doohan': ('Jack Doohan', 'Alpine'),
        'Colapinto': ('Franco Colapinto', 'Alpine'),
        'Lawson': ('Liam Lawson', 'Red Bull'),
        'Hadjar': ('Isack Hadjar', 'Racing Bulls'),
        'Bottas': ('Valtteri Bottas', 'Cadillac'),
        'Perez': ('Sergio Perez', 'Cadillac'),
        'Pérez': ('Sergio Perez', 'Cadillac'),
    }
    
    standings = []
    
    # 패턴 1: HTML 테이블 행 (<td> 기반)
    # "Position | Driver | Team | Points" 형태
    row_pattern = r'<tr[^>]*>\s*<td[^>]*>\s*(\d{1,2})\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*(\d{1,3})\s*</td>'
    rows = re.findall(row_pattern, html_text, re.DOTALL | re.IGNORECASE)
    
    if rows:
        for pos_str, driver_cell, team_cell, pts_str in rows:
            pos = int(pos_str)
            pts = int(pts_str)
            
            # driver_cell에서 이름 추출 (HTML 태그 제거)
            driver_name = re.sub(r'<[^>]+>', '', driver_cell).strip()
            team_name = re.sub(r'<[^>]+>', '', team_cell).strip()
            
            if driver_name and pts >= 0 and pos <= 22:
                # known_drivers로 이름/팀 정리 (3글자 코드 등 제거)
                clean_driver = driver_name
                clean_team = team_name
                for surname, (full, t) in known_drivers.items():
                    if surname in driver_name:
                        clean_driver = full
                        clean_team = t
                        break
                standings.append({
                    'pos': pos,
                    'driver': clean_driver,
                    'team': clean_team,
                    'points': pts
                })
        
        if len(standings) >= 5:
            standings.sort(key=lambda x: x['pos'])
            return standings
    
    # 패턴 2: 텍스트에서 known_drivers 기반 포인트 추출
    text = re.sub(r'<[^>]+>', ' ', html_text)  # 모든 태그 제거
    text = re.sub(r'\s+', ' ', text)
    
    for surname, (full_name, team) in known_drivers.items():
        # "surname ... NN" (포인트가 이름 근처에 있는 패턴)
        patterns = [
            rf'{surname}\s+{re.escape(team)}\s+(\d{{1,3}})',
            rf'{surname}[^0-9]{{0,30}}(\d{{1,3}})\s',
            rf'(\d{{1,3}})\s+{surname}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                pts = int(match.group(1))
                if 0 <= pts <= 500:  # 합리적 범위
                    standings.append({
                        'driver': full_name,
                        'team': team,
                        'points': pts
                    })
                    break
    
    if standings:
        standings.sort(key=lambda x: x['points'], reverse=True)
        # 중복 제거
        seen = set()
        unique = []
        for s in standings:
            if s['driver'] not in seen:
                seen.add(s['driver'])
                s['pos'] = len(unique) + 1
                unique.append(s)
        return unique if len(unique) >= 3 else None
    
    return None

def get_f1_standings_regex(text):
    """Regex fallback으로 F1 순위 추출"""
    # 일반적인 순위 패턴: "1. Russell (Mercedes) 25" 등
    known_drivers = {
        'Russell': ('George Russell', 'Mercedes'),
        'Antonelli': ('Kimi Antonelli', 'Mercedes'),
        'Leclerc': ('Charles Leclerc', 'Ferrari'),
        'Hamilton': ('Lewis Hamilton', 'Ferrari'),
        'Norris': ('Lando Norris', 'McLaren'),
        'Verstappen': ('Max Verstappen', 'Red Bull'),
        'Bearman': ('Oliver Bearman', 'Haas'),
        'Lindblad': ('Arvid Lindblad', 'Racing Bulls'),
        'Bortoleto': ('Gabriel Bortoleto', 'Audi'),
        'Gasly': ('Pierre Gasly', 'Alpine'),
        'Piastri': ('Oscar Piastri', 'McLaren'),
        'Sainz': ('Carlos Sainz', 'Williams'),
        'Albon': ('Alexander Albon', 'Williams'),
        'Stroll': ('Lance Stroll', 'Aston Martin'),
        'Alonso': ('Fernando Alonso', 'Aston Martin'),
        'Tsunoda': ('Yuki Tsunoda', 'Red Bull'),
        'Hulkenberg': ('Nico Hülkenberg', 'Audi'),
        'Ocon': ('Esteban Ocon', 'Haas'),
        'Doohan': ('Jack Doohan', 'Alpine'),
        'Colapinto': ('Franco Colapinto', 'Alpine'),
        'Lawson': ('Liam Lawson', 'Red Bull'),
        'Hadjar': ('Isack Hadjar', 'Racing Bulls'),
        'Bottas': ('Valtteri Bottas', 'Cadillac'),
        'Perez': ('Sergio Perez', 'Cadillac'),
    }
    
    standings = []
    for surname, (full_name, team) in known_drivers.items():
        # "surname ... XX points" 또는 "surname XX pts"
        pattern = rf'{surname}\s+.*?(\d{{1,3}})\s*(?:pts?|points?)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            pts = int(match.group(1))
            if pts > 0:
                standings.append({
                    'driver': full_name,
                    'team': team,
                    'points': pts
                })
    
    if standings:
        standings.sort(key=lambda x: x['points'], reverse=True)
        for i, s in enumerate(standings):
            s['pos'] = i + 1
        return standings[:10]
    
    return None

def get_f1_schedule_from_search(gp_info, serper_key, gemini_key):
    """
    Serper + Gemini로 정확한 세션 시간 가져오기 (선택적 보완)
    캘린더 기반 기본 스케줄이 있으므로, 검색으로 정확한 시간만 보완
    """
    if not serper_key or not gemini_key or not gp_info:
        return None
    
    gp_name = gp_info.get('name', '')
    year = 2026
    
    query = f"F1 {year} {gp_name} schedule practice qualifying race start times"
    result = call_serper_api(query, serper_key)
    
    if not result:
        return None
    
    text = ""
    if 'answerBox' in result:
        text += result['answerBox'].get('snippet', '') + " "
    for item in result.get('organic', [])[:5]:
        text += item.get('snippet', '') + " "
    
    kst_now = get_kst_now()
    today_str = kst_now.strftime("%B %d, %Y")
    
    is_sprint = gp_info.get('sprint', False)
    
    if is_sprint:
        format_hint = "This is a SPRINT weekend. Sessions are: FP1 (Friday), Sprint Qualifying (Friday), Sprint (Saturday), Qualifying (Saturday), Race (Sunday)."
    else:
        format_hint = "This is a STANDARD weekend. Sessions are: FP1 (Friday), FP2 (Friday), FP3 (Saturday), Qualifying (Saturday), Race (Sunday)."
    
    prompt = f"""You are an F1 schedule extractor. Today is {today_str}.
Extract the 2026 {gp_name} session schedule with LOCAL times.
{format_hint}

Search results:
---
{text[:3000]}
---

Respond with ONLY a JSON array, no markdown. Each element:
{{
  "name": "session name (FP1/FP2/FP3/Sprint Qualifying/Sprint/Qualifying/Race)",
  "date": "YYYY-MM-DD",
  "local_time": "HH:MM (24h format, local circuit time)"
}}

If you cannot determine, respond with: []"""
    
    gemini_response = call_gemini_api(prompt, gemini_key)
    if not gemini_response:
        return None
    
    try:
        clean = gemini_response.strip()
        clean = re.sub(r'^```(?:json)?\s*', '', clean)
        clean = re.sub(r'\s*```$', '', clean)
        sessions_raw = json.loads(clean)
        
        if not isinstance(sessions_raw, list) or len(sessions_raw) == 0:
            return None
        
        utc_offset = gp_info.get('utc_offset', 0)
        sessions = []
        
        for s in sessions_raw:
            local_time = s.get('local_time', '')
            session_date_str = s.get('date', '')
            name = s.get('name', '')
            
            if not local_time or not name:
                continue
            
            try:
                local_h, local_m = map(int, local_time.split(':'))
                utc_h = local_h - utc_offset
                kst_h = utc_h + 9
                
                if session_date_str:
                    session_date = datetime.date.fromisoformat(session_date_str)
                else:
                    session_date = datetime.date.today()
                
                kst_date = session_date
                if kst_h >= 24:
                    kst_h -= 24
                    kst_date = session_date + timedelta(days=1)
                elif kst_h < 0:
                    kst_h += 24
                    kst_date = session_date - timedelta(days=1)
                
                sessions.append({
                    'name': name,
                    'date': kst_date.strftime("%m.%d"),
                    'day_local': session_date.strftime("%a"),
                    'kst_time': f"{kst_h:02d}:{local_m:02d}",
                    'local_time': local_time,
                })
            except:
                continue
        
        if len(sessions) >= 3:
            return sessions
    except:
        pass
    
    return None

def search_f1_data(serper_key, gemini_key=None):
    """
    v2.5: F1 데이터 통합 수집
    Returns: {
        'next_race': {...},      # 다음/현재 GP 정보
        'schedule': [...],        # 세부 세션 스케줄 (KST)
        'standings': [...],       # 드라이버 순위 Top 10
    }
    """
    kst_now = get_kst_now()
    
    f1_data = {
        'next_race': None,
        'schedule': [],
        'standings': [],
    }
    
    # =========================================================================
    # 시즌 전 (1~2월): 프리시즌 테스트
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
            f1_data['next_race'] = {'status': 'Pre-Season', 'name': 'Test 1 (Private)', 'circuit': 'Barcelona-Catalunya', 'date': 'Jan 26-30'}
        elif today <= test1_end:
            f1_data['next_race'] = {'status': 'Testing', 'name': 'Test 1 (Private)', 'circuit': 'Barcelona-Catalunya', 'date': 'Jan 26-30'}
        elif today < test2_start:
            f1_data['next_race'] = {'status': 'Pre-Season', 'name': 'Test 2', 'circuit': 'Bahrain International', 'date': 'Feb 11-13'}
        elif today <= test2_end:
            f1_data['next_race'] = {'status': 'Testing', 'name': 'Test 2', 'circuit': 'Bahrain International', 'date': 'Feb 11-13'}
        elif today < test3_start:
            f1_data['next_race'] = {'status': 'Pre-Season', 'name': 'Test 3', 'circuit': 'Bahrain International', 'date': 'Feb 18-20'}
        elif today <= test3_end:
            f1_data['next_race'] = {'status': 'Testing', 'name': 'Test 3', 'circuit': 'Bahrain International', 'date': 'Feb 18-20'}
        else:
            f1_data['next_race'] = {'status': 'Pre-Season', 'name': 'Australian Grand Prix', 'circuit': 'Albert Park, Melbourne', 'date': 'Mar 06-08'}
        
        return f1_data
    
    # =========================================================================
    # 시즌 중 (3월~): 캘린더 기반 + 검색 보완
    # =========================================================================
    
    # 1. 다음/현재 GP 찾기
    gp_info = get_f1_next_race()
    if gp_info:
        gp_start = datetime.date.fromisoformat(gp_info['date_from'])
        gp_end = datetime.date.fromisoformat(gp_info['date_to'])
        
        f1_data['next_race'] = {
            'round': gp_info['round'],
            'name': gp_info['name'],
            'circuit': gp_info['circuit'],
            'country': gp_info['country'],
            'date': f"{gp_start.strftime('%b %d')}-{gp_end.strftime('%d')}",
            'date_from': gp_info['date_from'],
            'date_to': gp_info['date_to'],
            'status': gp_info['status'],
            'sprint': gp_info.get('sprint', False),
        }
        
        # 2. 세부 스케줄: 먼저 Serper+Gemini로 시도, 실패 시 캘린더 기반
        log("   [F1] 세부 스케줄 조회...")
        search_schedule = get_f1_schedule_from_search(gp_info, serper_key, gemini_key)
        
        if search_schedule:
            f1_data['schedule'] = search_schedule
            log(f"   ✅ Serper+Gemini 스케줄: {len(search_schedule)}세션")
        else:
            f1_data['schedule'] = get_f1_race_schedule(gp_info)
            log(f"   ℹ️ 캘린더 기반 스케줄 (기본값): {len(f1_data['schedule'])}세션")
    else:
        f1_data['next_race'] = {
            'status': 'Off-Season',
            'name': 'Season Complete',
            'circuit': '-',
            'date': '-'
        }
    
    # 3. 드라이버 순위
    log("   [F1] 드라이버 순위 조회...")
    standings = get_f1_standings(serper_key, gemini_key)
    if standings:
        f1_data['standings'] = standings
        log(f"   ✅ 순위: {len(standings)}명")
        for s in standings[:5]:
            log(f"      {s.get('pos', '-')}. {s.get('driver', '-')} ({s.get('team', '-')}) {s.get('points', 0)}pts")
    else:
        log("   ⚠️ 순위 조회 실패")
    
    return f1_data

# =============================================================================
# Korean Players 데이터 수집 함수
# =============================================================================
def get_korean_player_match_from_thesportsdb(event_url, team_name):
    """TheSportsDB 무료 API로 다음 경기 조회 (Serper 크레딧 소진과 무관하게 항상 사용 가능)"""
    try:
        r = requests.get(event_url, timeout=10)
        if r.status_code != 200:
            log(f"   ⚠️ TheSportsDB API error: {r.status_code}")
            return None
        events = r.json().get("events") or []
        if not events:
            return None
        e = events[0]
        home = e.get("strHomeTeam", "") or ""
        away = e.get("strAwayTeam", "") or ""
        date_event = e.get("dateEvent", "")
        str_time = e.get("strTime", "")
        if not date_event or not str_time:
            # 시간 미확정 경기는 KST 변환이 부정확해질 수 있어 다음 소스(Serper)로 넘김
            return None
        utc_iso = f"{date_event}T{str_time}Z"
        time_info = convert_utc_to_kst(utc_iso)
        if not time_info:
            return None
        # TheSportsDB는 LAFC를 "Los Angeles FC"로 반환하므로 홈 경기 판정에도 별칭을 적용한다.
        team_aliases = {team_name.lower()}
        if team_name.lower() == "lafc":
            team_aliases.add("los angeles fc")
        is_home = any(alias in home.lower() for alias in team_aliases)
        is_away = any(alias in away.lower() for alias in team_aliases)
        if not is_home and not is_away:
            return None
        opponent = away if is_home else home
        if not opponent:
            return None
        round_num = e.get("intRound")
        league = e.get("strLeague") or "MLS"
        competition = f"{league} R{round_num}" if round_num else league
        return {
            "opponent": opponent,
            "venue": "home" if is_home else "away",
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "competition": competition,
            "status": "SCHEDULED",
        }
    except Exception as ex:
        log(f"   ⚠️ TheSportsDB exception: {ex}")
        return None


def get_korean_player_match_from_api(team_id, football_key, fallback_label):
    """football-data.org 팀 다음 경기 조회 (이강인·김민재 전용, MLS 미지원)"""
    if not team_id or not football_key:
        return None
    url = f"{FOOTBALL_DATA_API_URL}/teams/{team_id}/matches"
    headers = {"X-Auth-Token": football_key}
    params = {"status": "SCHEDULED", "limit": 1}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code != 200:
            log(f"   ⚠️ team {team_id} matches API error: {r.status_code}")
            return None
        matches = r.json().get("matches", [])
        if not matches:
            return None
        m = matches[0]
        time_info = convert_utc_to_kst(m.get("utcDate", ""))
        if not time_info:
            return None
        home = m.get("homeTeam", {})
        away = m.get("awayTeam", {})
        is_home = str(home.get("id")) == str(team_id)
        opponent = away.get("name", "-") if is_home else home.get("name", "-")
        return {
            "opponent": opponent,
            "venue": "home" if is_home else "away",
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "competition": format_match_round_label(m, fallback_label),
            "status": "SCHEDULED",
        }
    except Exception as e:
        log(f"   ⚠️ team {team_id} matches exception: {e}")
        return None


def get_korean_player_match_from_search(team_name, serper_key, gemini_key, fallback_label):
    """Serper 검색 + Gemini 파싱 (MLS 등 API 미지원 리그 / API 실패 폴백)"""
    if not serper_key or not gemini_key:
        return None
    search_result = call_serper_api(
        f"{team_name} next match schedule official fixture 2026 date time kickoff",
        serper_key,
    )
    if not search_result:
        return None
    snippet_text = json.dumps(search_result.get("organic", [])[:5])
    kst_today = get_kst_now().strftime("%Y-%m-%d")
    prompt = (
        f"다음 검색결과에서 {team_name}의 다음(향후) 예정 경기 정보를 JSON으로만 추출해줘 (설명 없이 JSON만). "
        f"오늘은 {kst_today}(KST)이며, 오늘 날짜 이후에 열리는 가장 가까운 경기만 추출해줘. "
        f"이미 종료되었거나 오늘 이전 날짜의 경기는 절대 반환하지 마. "
        f'형식: {{"opponent": str, "venue": "home 또는 away", "date_utc": "YYYY-MM-DDTHH:MM:SSZ", '
        f'"competition": str}}. "competition"은 "La Liga R1", "DFB-Pokal 16강", "친선전"처럼 '
        f"대회명과 라운드/스테이지를 구체적으로 조합해서 작성해줘. "
        f"정보를 찾을 수 없거나 확실하지 않으면 null만 반환.\n\n검색결과: {snippet_text}"
    )
    parsed = call_gemini_api(prompt, gemini_key)
    if not parsed:
        return None
    try:
        data = json.loads(parsed.strip().strip('```json').strip('```'))
        if not data:
            return None
        time_info = convert_utc_to_kst(data.get("date_utc", ""))
        if not time_info:
            return None
        return {
            "opponent": data.get("opponent", "-"),
            "venue": data.get("venue", "-"),
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "competition": data.get("competition") or fallback_label,
            "status": "SCHEDULED",
        }
    except Exception:
        return None


def is_future_match(entry):
    """분리 저장된 KST 날짜와 시간으로 아직 지나지 않은 경기인지 확인한다."""
    kst_date = entry.get("kst_date", "-")
    kst_time = entry.get("kst_time", "-")
    if kst_date in ("-", None) or kst_time in ("-", None):
        return False
    combined = f"{kst_date} {kst_time} (KST)"
    return not is_match_past(combined)


def get_korean_players_data(football_key, serper_key, gemini_key, existing_data=None):
    """코리안리거 3인 다음 경기 데이터 수집
    우선순위: TheSportsDB → API 조회 → 검색 폴백 → 기존 sports.json 데이터 유지 → 기본 예상 매치업
    """
    existing_list = (existing_data or {}).get("korean_players") or []
    existing_by_player = {e.get("player"): e for e in existing_list if e.get("player")}

    results = []
    for p in KOREAN_PLAYERS:
        match_info = None
        if p.get("thesportsdb_url"):
            match_info = get_korean_player_match_from_thesportsdb(p["thesportsdb_url"], p["team_name"])
        if not match_info and p["team_id"]:
            match_info = get_korean_player_match_from_api(p["team_id"], football_key, p["competition_label"])
        if not match_info:
            match_info = get_korean_player_match_from_search(p["team_name"], serper_key, gemini_key, p["competition_label"])

        if match_info and not is_future_match(match_info):
            log(f"   ⚠️ {p['player']} 검색 결과가 과거 날짜({match_info.get('kst_date', '-')}) → 폐기")
            match_info = None

        if match_info:
            entry = {
                "player": p["player"],
                "team": p["team_label"],
                "opponent": match_info["opponent"],
                "venue": match_info["venue"],
                "kst_date": match_info["kst_date"],
                "kst_time": match_info["kst_time"],
                "competition": match_info["competition"],
                "status": match_info["status"],
            }
            log(f"   ✅ {p['player']} ({p['team_label']}): vs {entry['opponent']} | {entry['kst_date']} {entry['kst_time']} KST")
        else:
            existing_entry = existing_by_player.get(p["player"])
            existing_has_schedule = (
                existing_entry
                and existing_entry.get("opponent", "-") not in ("-", None)
                and existing_entry.get("kst_date", "-") not in ("-", None)
                and existing_entry.get("kst_time", "-") not in ("-", None)
                and existing_entry.get("competition", "-") not in ("-", None)
                and is_future_match(existing_entry)
            )
            if existing_has_schedule:
                entry = existing_entry
                log(f"   ⚠️ {p['player']} 수집 실패 → 기존 데이터 유지 (vs {entry.get('opponent', '-')})")
            else:
                if existing_entry and not is_future_match(existing_entry):
                    log(f"   ⚠️ {p['player']} 기존 데이터 만료(과거 경기: {existing_entry.get('kst_date', '-')}) → 폴백으로 대체")
                fb = KOREAN_PLAYERS_DEFAULT_FALLBACK.get(p["player"], {})
                entry = {
                    "player": p["player"],
                    "team": p["team_label"],
                    "opponent": fb.get("opponent", "-"),
                    "venue": fb.get("venue", "-"),
                    "kst_date": fb.get("kst_date", "-"),
                    "kst_time": fb.get("kst_time", "-"),
                    "competition": fb.get("competition", p["competition_label"]),
                    "status": "ESTIMATED",
                }
                if not is_future_match(entry):
                    log(f"   🚨 {p['player']} 폴백 데이터도 만료됨(과거: {entry['kst_date']} {entry['kst_time']}) — KOREAN_PLAYERS_DEFAULT_FALLBACK 수동 갱신 필요! (vs {entry['opponent']})")
                else:
                    log(f"   ⚠️ {p['player']} 수집 실패, 기존 데이터 없음 → 기본 예상 일정 사용 (vs {entry['opponent']})")
        results.append(entry)
    return results

# =============================================================================
# 해외파 코리안리거 돋보기 (TheSportsDB 일정/결과 + ESPN 개인 스탯)
# =============================================================================
def _sportsdb_event_time(event):
    """TheSportsDB 이벤트의 UTC timestamp를 KST 표시값으로 변환한다."""
    timestamp = event.get("strTimestamp")
    if not timestamp:
        date_event = event.get("dateEvent")
        str_time = event.get("strTime")
        if not date_event or not str_time:
            return None
        timestamp = f"{date_event}T{str_time}"
    if not re.search(r'(?:Z|[+-]\d{2}:\d{2})$', timestamp):
        timestamp += "Z"
    return convert_utc_to_kst(timestamp)


def get_overseas_team_next_match(team_id, team_label):
    """TheSportsDB에서 팀의 가장 가까운 다음 경기를 조회한다."""
    if not team_id:
        return None
    try:
        response = requests.get(
            f"{THESPORTSDB_BASE}/eventsnext.php",
            params={"id": team_id},
            timeout=10,
        )
        if response.status_code != 200:
            log(f"   ⚠️ TheSportsDB eventsnext 실패({team_label}): {response.status_code}")
            return None

        for event in response.json().get("events") or []:
            time_info = _sportsdb_event_time(event)
            if not time_info:
                continue
            if time_info["datetime_kst"] <= get_kst_now():
                continue
            is_home = str(event.get("idHomeTeam")) == str(team_id)
            opponent = event.get("strAwayTeam") if is_home else event.get("strHomeTeam")
            if not opponent:
                continue
            round_num = event.get("intRound")
            league = event.get("strLeague") or "-"
            competition = f"{league} R{round_num}" if round_num else league
            return {
                "opponent": opponent,
                "venue": "home" if is_home else "away",
                "kst_date": time_info["kst_date"],
                "kst_time": time_info["kst_time"],
                "competition": competition,
                "status": "SCHEDULED",
            }
    except Exception as ex:
        log(f"   ⚠️ TheSportsDB eventsnext 예외({team_label}): {ex}")
    return None


def get_overseas_team_last_match(team_id, team_label):
    """TheSportsDB에서 팀의 가장 최근 완료 경기 결과를 조회한다."""
    if not team_id:
        return None
    try:
        response = requests.get(
            f"{THESPORTSDB_BASE}/eventslast.php",
            params={"id": team_id},
            timeout=10,
        )
        if response.status_code != 200:
            log(f"   ⚠️ TheSportsDB eventslast 실패({team_label}): {response.status_code}")
            return None

        for event in response.json().get("results") or []:
            time_info = _sportsdb_event_time(event)
            if not time_info:
                continue
            try:
                home_score = int(event.get("intHomeScore"))
                away_score = int(event.get("intAwayScore"))
            except (TypeError, ValueError):
                continue

            is_home = str(event.get("idHomeTeam")) == str(team_id)
            opponent = event.get("strAwayTeam") if is_home else event.get("strHomeTeam")
            if not opponent:
                continue
            goals_for = home_score if is_home else away_score
            goals_against = away_score if is_home else home_score
            result = "W" if goals_for > goals_against else ("L" if goals_for < goals_against else "D")
            round_num = event.get("intRound")
            league = event.get("strLeague") or "-"
            competition = f"{league} R{round_num}" if round_num else league
            return {
                "id_event": event.get("idEvent"),
                "opponent": opponent,
                "venue": "home" if is_home else "away",
                "kst_date": time_info["kst_date"],
                "kst_time": time_info["kst_time"],
                "competition": competition,
                "result": result,
                "goals_for": goals_for,
                "goals_against": goals_against,
            }
    except Exception as ex:
        log(f"   ⚠️ TheSportsDB eventslast 예외({team_label}): {ex}")
    return None


def _espn_parse_player_block(html, espn_slug, espn_player_id=None):
    """ESPN 경기 HTML의 선수별 구조화 JSON 블록을 파싱한다."""
    player_path = (
        rf'/soccer/player/_/id/{re.escape(str(espn_player_id))}/[^"?]+'
        if espn_player_id
        else rf'/soccer/player/_/id/\d+/{re.escape(espn_slug)}'
    )
    pattern = (
        rf'"lnk":"{player_path}"'
        rf'[^{{}}]*"stats":\{{([^}}]*)\}}'
    )
    match = re.search(pattern, html, re.IGNORECASE)
    if not match:
        return None, None

    stats = json.loads("{" + match.group(1) + "}")
    # 빈 stats 객체는 명단에는 있었지만 실제 출전하지 않은 선수다.
    appearances = int(stats.get("appearances", 0) or 0)
    if appearances <= 0:
        return None, {"played": False, "started": False}

    started = stats.get("subIns") == "0"
    goals = int(stats.get("totalGoals", 0) or 0)
    assists = int(stats.get("goalAssists", 0) or 0)

    # 현재 선수 블록 안의 subIn/subOut 이벤트로 출전시간을 계산한다.
    # 예: 76분 교체 투입은 76분이 아니라 약 14분 출전이다.
    next_player = html.find('"lnk":"/soccer/player/_/id/', match.end())
    segment_end = next_player if next_player != -1 else min(len(html), match.end() + 5000)
    player_segment = html[match.start():segment_end]
    substitution_events = re.findall(
        r'"minute":"(\d+)(?:\+\d+)?\'"[^{}]{0,160}?"iconType":"(subIn|subOut)"',
        player_segment,
        re.IGNORECASE,
    )
    minutes = None
    if started:
        sub_out = next((int(minute) for minute, kind in substitution_events if kind.lower() == "subout"), None)
        minutes = sub_out if sub_out is not None else 90
    else:
        sub_in = next((int(minute) for minute, kind in substitution_events if kind.lower() == "subin"), None)
        minutes = max(0, 90 - sub_in) if sub_in is not None else None

    return {
        "started": started,
        "minutes": minutes,
        "goals": goals,
        "assists": assists,
    }, {"played": True, "started": started}


def get_overseas_player_stat_from_espn(
    espn_slug,
    team_label,
    opponent,
    serper_key,
    espn_player_id=None,
    match_context=None,
    include_involvement=False,
):
    """Serper로 ESPN 경기 페이지를 찾아 구조화 JSON에서 개인 스탯을 추출한다.

    기본 반환값은 player_stat 또는 None이다. 내부 조립 단계에서는
    include_involvement=True로 호출해 확인 가능한 결장 상태도 함께 받는다.
    """
    def result(player_stat=None, involvement=None):
        return (player_stat, involvement) if include_involvement else player_stat

    if not serper_key or not espn_slug or not opponent:
        return result()
    try:
        query_context = f" {match_context}" if match_context else ""
        search_result = call_serper_api(
            f"{team_label} vs {opponent}{query_context} site:espn.com/soccer/match/_/gameId/",
            serper_key,
        )
        if not search_result:
            return result()
        espn_url = next(
            (
                item.get("link")
                for item in search_result.get("organic", [])
                if "espn.com/soccer/match" in (item.get("link") or "")
            ),
            None,
        )
        if not espn_url:
            log(f"   ⚠️ ESPN 경기 페이지 검색 실패({team_label} vs {opponent})")
            return result()

        page = requests.get(
            espn_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if page.status_code != 200:
            log(f"   ⚠️ ESPN 페이지 접근 실패({team_label}): {page.status_code}")
            return result()

        player_stat, involvement = _espn_parse_player_block(page.text, espn_slug, espn_player_id)
        if player_stat or involvement:
            return result(player_stat, involvement)

        # 다른 선수들의 stats 블록은 있는데 대상 선수만 없으면 스쿼드 제외로 확정한다.
        lineup_stats_count = len(re.findall(
            r'"lnk":"/soccer/player/_/id/\d+/[^"?]+"[^{{}}]*"stats":\{',
            page.text,
            re.IGNORECASE,
        ))
        if lineup_stats_count >= 2:
            log(f"   ℹ️ ESPN 라인업에 '{espn_slug}' 없음 — 결장/스쿼드 제외")
            return result(None, {"played": False, "started": False})

        log(f"   ℹ️ ESPN 페이지에 라인업 데이터 없음({team_label} vs {opponent})")
    except Exception as ex:
        log(f"   ⚠️ ESPN 개인 스탯 추출 예외({team_label}): {ex}")
    return result()


def append_history(history, player, new_record, cap=10):
    """선수별 경기 이력을 최신순으로 저장하고 최대 cap개로 제한한다."""
    records = history.get(player, [])
    event_id = new_record.get("id_event")
    if event_id:
        records = [r for r in records if str(r.get("id_event")) != str(event_id)]
    else:
        records = [r for r in records if r.get("kst_date") != new_record.get("kst_date")]
    records.insert(0, new_record)
    history[player] = records[:cap]
    return history


def _same_overseas_match(cached, latest):
    if not cached or not latest:
        return False
    if cached.get("id_event") and latest.get("id_event"):
        return str(cached["id_event"]) == str(latest["id_event"])
    return cached.get("kst_date") == latest.get("kst_date")


def get_korean_overseas_data(serper_key, existing_history=None, existing_data=None):
    """9명 해외파의 다음 경기, 최근 팀 결과, ESPN 개인 스탯과 이력을 조립한다."""
    history = existing_history if isinstance(existing_history, dict) else {}
    existing_players = (existing_data or {}).get("players") or []
    existing_by_player = {
        entry.get("player"): entry
        for entry in existing_players
        if entry.get("player")
    }
    players_out = []

    for player in KOREAN_OVERSEAS_PLAYERS:
        player_name = player["player"]
        team_label = player["team_label"]
        schedule_info = get_overseas_team_next_match(player["thesportsdb_team_id"], team_label)
        team_result = get_overseas_team_last_match(player["thesportsdb_team_id"], team_label)
        existing_entry = existing_by_player.get(player_name)
        if not schedule_info and existing_entry and is_future_match(existing_entry):
            schedule_info = {
                "opponent": existing_entry.get("opponent", "-"),
                "venue": existing_entry.get("venue", "-"),
                "kst_date": existing_entry.get("kst_date", "-"),
                "kst_time": existing_entry.get("kst_time", "-"),
                "competition": existing_entry.get("competition", "-"),
                "status": existing_entry.get("status", "SCHEDULED"),
            }
            log(f"   ♻️ {player_name}: 다음 일정 API 실패 → 기존 일정 유지")
        cached = (history.get(player_name) or [{}])[0]
        already_covered = (
            _same_overseas_match(cached, team_result)
            and (cached.get("player_stat") is not None or cached.get("involvement") is not None)
        )

        player_stat = None
        involvement = None
        if already_covered:
            player_stat = cached.get("player_stat")
            involvement = cached.get("involvement")
            log(f"   ⏭️ {player_name}: 동일 경기({team_result.get('kst_date')}) 이미 확인됨 — ESPN 재조회 생략")
        elif team_result and player.get("espn_slug") and serper_key:
            player_stat, involvement = get_overseas_player_stat_from_espn(
                player["espn_slug"],
                team_label,
                team_result.get("opponent"),
                serper_key,
                espn_player_id=player.get("espn_player_id"),
                match_context=(
                    f"{get_kst_now().year} {team_result.get('kst_date')} "
                    f"{team_result.get('goals_for')}-{team_result.get('goals_against')}"
                ),
                include_involvement=True,
            )
            # 실제 Serper/ESPN 경로를 시도한 경우에만 다음 선수 호출 전 페이싱한다.
            time.sleep(OVERSEAS_REQUEST_DELAY_SEC)

        if team_result:
            history_record = {
                **team_result,
                "involvement": involvement,
                "player_stat": player_stat,
            }
            history = append_history(history, player_name, history_record)
        elif cached:
            team_result = {
                key: value
                for key, value in cached.items()
                if key not in ("involvement", "player_stat")
            }
            involvement = cached.get("involvement")
            player_stat = cached.get("player_stat")

        entry = {
            "player": player_name,
            "team": team_label,
            "competition": (schedule_info or {}).get("competition", "-"),
            "opponent": (schedule_info or {}).get("opponent", "-"),
            "venue": (schedule_info or {}).get("venue", "-"),
            "kst_date": (schedule_info or {}).get("kst_date", "-"),
            "kst_time": (schedule_info or {}).get("kst_time", "-"),
            "status": (schedule_info or {}).get("status", "UNKNOWN"),
            "team_result": team_result,
            "involvement": involvement,
            "player_stat": player_stat,
        }
        players_out.append(entry)
        recent_label = "-"
        if team_result:
            recent_label = f"{team_result['result']} {team_result['goals_for']}-{team_result['goals_against']}"
        log(f"   {'✅' if schedule_info else '⚠️'} {player_name} ({team_label}): 다음 vs {entry['opponent']} | 최근 {recent_label}")

    return players_out, history


def _fallback_overseas_hot_issues(players_out):
    """Gemini가 없거나 실패해도 팀 결과 기반의 중립적 핫이슈를 제공한다."""
    candidates = [p for p in players_out if p.get("team_result")]
    candidates.sort(
        key=lambda p: (
            (p.get("player_stat") or {}).get("goals", 0) * 2
            + (p.get("player_stat") or {}).get("assists", 0),
            {"W": 2, "D": 1, "L": 0}.get(p["team_result"].get("result"), 0),
            p["team_result"].get("goals_for", 0) - p["team_result"].get("goals_against", 0),
            p["team_result"].get("goals_for", 0),
        ),
        reverse=True,
    )
    issues = []
    for player in candidates[:4]:
        team_result = player["team_result"]
        result_word = {"W": "승리", "D": "무승부", "L": "패배"}.get(team_result.get("result"), "경기")
        headline = f"{player['team']} {team_result['goals_for']}-{team_result['goals_against']} {result_word}"
        involvement = player.get("involvement")
        player_stat = player.get("player_stat")
        if player_stat:
            start_label = "선발" if player_stat.get("started") else "교체 출전"
            detail = f"{player['player']} {start_label}, {player_stat.get('goals', 0)}골 {player_stat.get('assists', 0)}도움"
        elif involvement and involvement.get("played") is False:
            detail = f"{team_result.get('competition', '-')} · {player['player']} 결장"
        else:
            detail = f"{team_result.get('competition', '-')} · {player['player']} 출전 여부 미확인"
        issues.append({"headline": headline, "detail": detail, "player": player["player"]})
    return issues


def summarize_overseas_hot_issues(players_out, gemini_key):
    """전체 해외파 데이터를 한 번에 요약하며 실패 시 중립적 로컬 요약으로 폴백한다."""
    fallback = _fallback_overseas_hot_issues(players_out)
    if not gemini_key:
        return fallback
    brief_data = [
        {
            "player": player["player"],
            "team": player["team"],
            "team_result": player.get("team_result"),
            "involvement": player.get("involvement"),
            "player_stat": player.get("player_stat"),
        }
        for player in players_out
        if player.get("team_result")
    ]
    if not brief_data:
        return []
    prompt = (
        "다음은 해외파 한국 축구선수 소속팀의 최근 결과와 확인된 개인 출전 정보다. "
        "involvement가 null이거나 played가 false이면 팀 승리를 선수 개인의 기여나 활약으로 표현하지 마라. "
        "개인 기여는 involvement.played=true 또는 player_stat이 있는 경우에만 언급하라. "
        "눈에 띄는 항목 3~4개를 JSON 배열로만 답하라. "
        '형식: [{"headline": str, "detail": str, "player": str}].\n\n'
        + json.dumps(brief_data, ensure_ascii=False)
    )
    parsed = call_gemini_api(prompt, gemini_key)
    if not parsed:
        return fallback
    try:
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', parsed.strip(), flags=re.IGNORECASE)
        issues = json.loads(cleaned)
        valid_players = {p["player"] for p in players_out}
        if not isinstance(issues, list):
            return fallback
        player_lookup = {p["player"]: p for p in players_out}
        fallback_lookup = {issue["player"]: issue for issue in fallback}
        validated = []
        seen_players = set()
        for issue in issues:
            if (
                not isinstance(issue, dict)
                or issue.get("player") not in valid_players
                or not isinstance(issue.get("headline"), str)
                or not isinstance(issue.get("detail"), str)
            ):
                continue
            player_name = issue["player"]
            if player_name in seen_players:
                continue
            source = player_lookup[player_name]
            involvement = source.get("involvement")
            if not source.get("player_stat") and not (involvement and involvement.get("played") is True):
                issue = fallback_lookup.get(player_name, issue)
            validated.append(issue)
            seen_players.add(player_name)

        for issue in fallback:
            if len(validated) >= 4:
                break
            if issue["player"] not in seen_players:
                validated.append(issue)
                seen_players.add(issue["player"])
        return validated[:4] or fallback
    except Exception as ex:
        log(f"   ⚠️ 해외파 핫이슈 JSON 파싱 실패: {ex}")
        return fallback

# =============================================================================
# 테니스 함수 - v2.5 (Apps Script Web App + Serper/Gemini 보완)
# =============================================================================
TENNIS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbyl0S8XLRt4F9NYjO95ZYKOaPwppsI7v1xra-fuCIQZvNptFsDerXqq_peHtTn-Rt2qJw/exec"

# 대회명 정규화 매핑 (같은 대회의 다른 이름들)
TOURNAMENT_ALIASES = {
    'bnp paribas open': 'Indian Wells',
    'indian wells open': 'Indian Wells',
    'indian wells masters': 'Indian Wells',
    'indian wells': 'Indian Wells',
    'miami open': 'Miami Open',
    'miami masters': 'Miami Open',
    'monte carlo masters': 'Monte Carlo Masters',
    'monte-carlo masters': 'Monte Carlo Masters',
    'mutua madrid open': 'Madrid Open',
    'madrid open': 'Madrid Open',
    'internazionali d\'italia': 'Italian Open',
    'italian open': 'Italian Open',
    'rome masters': 'Italian Open',
    'roland garros': 'Roland Garros',
    'french open': 'Roland Garros',
    'wimbledon': 'Wimbledon',
    'us open': 'US Open',
    'australian open': 'Australian Open',
    'canadian open': 'Canadian Open',
    'national bank open': 'Canadian Open',
    'cincinnati open': 'Cincinnati Masters',
    'western & southern open': 'Cincinnati Masters',
    'shanghai masters': 'Shanghai Masters',
    'paris masters': 'Paris Masters',
    'rolex paris masters': 'Paris Masters',
    'atp finals': 'ATP Finals',
    'nitto atp finals': 'ATP Finals',
}

def normalize_tournament_name(name):
    """대회명 정규화"""
    if not name or name == '-':
        return name
    name_lower = name.lower().strip()
    for alias, standard in TOURNAMENT_ALIASES.items():
        if alias in name_lower:
            return standard
    return name

def is_same_tournament(name1, name2):
    """두 대회명이 같은 대회인지 확인"""
    if not name1 or not name2 or name1 == '-' or name2 == '-':
        return False
    norm1 = normalize_tournament_name(name1)
    norm2 = normalize_tournament_name(name2)
    return norm1 == norm2

def is_tennis_data_incomplete(webapp_data):
    """
    v2.5: Web App 데이터가 불완전한지 검증
    
    불완전 판정 기준:
    1. next 상대가 '-' 또는 빈 값
    2. next 대회가 recent 대회와 같은 대회인데 라운드/상대 정보 없음
    3. next 날짜가 비어있거나 '-'
    """
    recent = webapp_data.get('recent', {})
    next_data = webapp_data.get('next', {})
    
    next_event = next_data.get('event', '-')
    next_opponent = next_data.get('opponent', '-')
    next_round = next_data.get('round', '-')
    next_date = next_data.get('date', '-')
    recent_event = recent.get('event', '-')
    
    reasons = []
    
    # 1. 상대 정보 없음
    if next_opponent in ('-', '', None):
        reasons.append('no_opponent')
    
    # 2. 같은 대회 진행 중인데 라운드 정보 없음 (대회 아직 끝나지 않음)
    if is_same_tournament(recent_event, next_event):
        if next_round in ('-', '', None):
            reasons.append('same_tournament_no_round')
    
    # 3. 다른 대회로 넘어갔는데 상대/라운드 모두 없음 (너무 이른 정보)
    if not is_same_tournament(recent_event, next_event):
        if next_opponent in ('-', '', None) and next_round in ('-', '', None):
            reasons.append('future_tournament_no_detail')
    
    # 4. 날짜 없음
    if next_date in ('-', '', None):
        reasons.append('no_date')
    
    # 5. 현재 대회가 아직 진행 중인데 다른 대회로 넘어간 경우
    #    (recent 대회 종료일이 아직 지나지 않았는데 next가 다른 대회)
    if not is_same_tournament(recent_event, next_event) and recent_event != '-':
        tournament_end_dates = {
            'Indian Wells': (3, 16),  # Mar 16
            'Miami Open': (3, 30),
            'Monte Carlo Masters': (4, 13),
            'Madrid Open': (5, 4),
            'Italian Open': (5, 18),
            'Roland Garros': (6, 8),
            'Wimbledon': (7, 13),
            'Canadian Open': (8, 10),
            'Cincinnati Masters': (8, 17),
            'US Open': (9, 7),
            'Shanghai Masters': (10, 12),
            'Paris Masters': (11, 2),
            'ATP Finals': (11, 16),
            'Australian Open': (2, 2),
        }
        recent_norm = normalize_tournament_name(recent_event)
        end_date = tournament_end_dates.get(recent_norm)
        if end_date:
            kst_now = get_kst_now()
            tournament_end = datetime.date(kst_now.year, end_date[0], end_date[1])
            if kst_now.date() <= tournament_end:
                reasons.append('recent_tournament_still_ongoing')
    
    return reasons

def enrich_tennis_with_search(webapp_data, serper_key, gemini_key):
    """
    v2.5: Serper 검색 + Gemini 파싱으로 Web App 데이터 보완
    
    흐름:
    1. Serper로 "Alcaraz next match" 검색 (2회)
    2. 검색 결과를 Gemini에게 JSON 파싱 요청
    3. 파싱 결과로 Web App 데이터 보완/교체
    
    Returns: 보완된 webapp_data (원본 구조 유지)
    """
    if not serper_key:
        log("      ⚠️ Serper API 키 없음 → 보완 불가")
        return webapp_data
    
    recent = webapp_data.get('recent', {})
    next_data = webapp_data.get('next', {})
    recent_event = recent.get('event', '-')
    
    # =========================================================================
    # Step 1: Serper 검색 (2개 쿼리)
    # =========================================================================
    kst_now = get_kst_now()
    today_str = kst_now.strftime("%B %d, %Y")
    
    search_texts = []
    
    # 쿼리 1: 다음 경기 상대 (가장 직접적)
    q1 = "Alcaraz next match vs opponent today tomorrow"
    result1 = call_serper_api(q1, serper_key)
    if result1:
        text = ""
        if 'answerBox' in result1:
            text += result1['answerBox'].get('snippet', '') + " "
            text += result1['answerBox'].get('answer', '') + " "
        if 'sportsResults' in result1:
            text += json.dumps(result1['sportsResults']) + " "
        for item in result1.get('organic', [])[:5]:
            text += item.get('snippet', '') + " "
            text += item.get('title', '') + " "
        search_texts.append(text)
    
    # 쿼리 2: 현재 대회 쿼터파이널/다음 라운드 (상대 이름이 나올 확률 높음)
    recent_norm = normalize_tournament_name(recent_event)
    q2 = f"Alcaraz {recent_norm} 2026 quarterfinal semifinal preview prediction"
    result2 = call_serper_api(q2, serper_key)
    if result2:
        text = ""
        if 'answerBox' in result2:
            text += result2['answerBox'].get('snippet', '') + " "
        for item in result2.get('organic', [])[:5]:
            text += item.get('snippet', '') + " "
            text += item.get('title', '') + " "
        search_texts.append(text)
    
    if not search_texts:
        log("      ⚠️ Serper 검색 결과 없음")
        return webapp_data
    
    combined_search = "\n\n".join(search_texts)
    
    # =========================================================================
    # Step 2: Gemini로 구조화 파싱
    # =========================================================================
    if not gemini_key:
        # Gemini 없으면 regex fallback
        log("      ℹ️ Gemini 키 없음 → regex fallback")
        return enrich_tennis_regex_fallback(webapp_data, combined_search)
    
    prompt = f"""You are a tennis data extractor. Today is {today_str}.

From the search results below, extract Carlos Alcaraz's NEXT upcoming match information.
Important: Focus on his NEXT match that has NOT been played yet. Ignore completed matches.
If a tournament is currently ongoing, the next match is within that same tournament.

Search results:
---
{combined_search[:3000]}
---

Web App current data (may be inaccurate):
- Recent match: {recent.get('event', '-')} vs {recent.get('opponent', '-')} ({recent.get('result', '-')}) on {recent.get('date', '-')}
- Next shown: {next_data.get('event', '-')} vs {next_data.get('opponent', '-')} on {next_data.get('date', '-')}

Respond with ONLY a JSON object, no markdown, no explanation:
{{
  "tournament": "tournament name",
  "opponent": "opponent full name or TBD if unknown",
  "round": "round name (e.g. QF, SF, F, R16, R32, R64, R128) or - if unknown",
  "date": "match date in Mon DD format (e.g. Mar 14) or - if unknown",
  "time_kst": "match time in KST HH:MM format or - if unknown",
  "status": "tournament category: Grand Slam, Masters, ATP 500, ATP 250, or -",
  "confidence": "high, medium, or low"
}}"""

    gemini_response = call_gemini_api(prompt, gemini_key)
    
    if not gemini_response:
        log("      ⚠️ Gemini 응답 없음 → regex fallback")
        return enrich_tennis_regex_fallback(webapp_data, combined_search)
    
    # JSON 파싱
    try:
        # ```json ... ``` 제거
        clean = gemini_response.strip()
        clean = re.sub(r'^```(?:json)?\s*', '', clean)
        clean = re.sub(r'\s*```$', '', clean)
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        log(f"      ⚠️ Gemini JSON 파싱 실패: {gemini_response[:100]}")
        return enrich_tennis_regex_fallback(webapp_data, combined_search)
    
    confidence = parsed.get('confidence', 'low')
    log(f"      🤖 Gemini 파싱 결과 (confidence: {confidence}):")
    log(f"         대회: {parsed.get('tournament', '-')}")
    log(f"         상대: {parsed.get('opponent', '-')}")
    log(f"         라운드: {parsed.get('round', '-')}")
    log(f"         날짜: {parsed.get('date', '-')}")
    log(f"         시간(KST): {parsed.get('time_kst', '-')}")
    
    # =========================================================================
    # Step 3: Web App 데이터 보완
    # =========================================================================
    enriched = json.loads(json.dumps(webapp_data))  # deep copy
    
    gem_tournament = parsed.get('tournament', '-')
    gem_opponent = parsed.get('opponent', '-')
    gem_round = parsed.get('round', '-')
    gem_date = parsed.get('date', '-')
    gem_time_kst = parsed.get('time_kst', '-')
    gem_status = parsed.get('status', '-')
    
    # confidence가 low면 보완하지 않음
    if confidence == 'low':
        log("      ⚠️ Low confidence → regex fallback 시도")
        return enrich_tennis_regex_fallback(webapp_data, combined_search)
    
    # next 데이터 보완
    if gem_tournament and gem_tournament != '-':
        enriched['next']['event'] = gem_tournament
    
    if gem_opponent and gem_opponent not in ('-', 'TBD', ''):
        enriched['next']['opponent'] = gem_opponent
    
    if gem_round and gem_round != '-':
        enriched['next']['round'] = gem_round
    
    if gem_date and gem_date != '-':
        enriched['next']['date'] = gem_date
    
    if gem_time_kst and gem_time_kst != '-':
        enriched['next']['time_kst'] = gem_time_kst
    
    # Gemini가 상대를 못 찾았으면 (TBD 또는 -) regex로 추가 시도
    if enriched['next'].get('opponent', '-') in ('-', '', None, 'TBD'):
        log("      ℹ️ Gemini 상대 미확인 → regex 추가 시도")
        regex_result = enrich_tennis_regex_fallback(enriched, combined_search)
        if regex_result.get('next', {}).get('opponent', '-') not in ('-', '', None, 'TBD'):
            enriched['next']['opponent'] = regex_result['next']['opponent']
            log(f"      📎 Regex로 상대 보완: {enriched['next']['opponent']}")
    
    # enriched에 source 표시
    enriched['_enriched'] = True
    enriched['_enriched_confidence'] = confidence
    
    return enriched

def enrich_tennis_regex_fallback(webapp_data, search_text):
    """
    Gemini 없을 때 regex로 최소한의 보완 시도
    주로 상대 이름과 라운드 추출
    """
    enriched = json.loads(json.dumps(webapp_data))
    
    text = search_text.lower()
    
    # 라운드 감지
    round_patterns = [
        (r'alcaraz.*?quarter[\s-]?final', 'QF'),
        (r'quarter[\s-]?final.*?alcaraz', 'QF'),
        (r'alcaraz.*?semi[\s-]?final', 'SF'),
        (r'semi[\s-]?final.*?alcaraz', 'SF'),
        (r'alcaraz.*?\bfinal\b', 'F'),
        (r'alcaraz.*?round of 16', 'R16'),
        (r'alcaraz.*?fourth round', 'R16'),
        (r'alcaraz.*?third round', 'R32'),
        (r'alcaraz.*?second round', 'R64'),
    ]
    
    detected_round = None
    for pattern, round_name in round_patterns:
        if re.search(pattern, text):
            detected_round = round_name
            break
    
    if detected_round and enriched.get('next', {}).get('round', '-') in ('-', '', None):
        enriched['next']['round'] = detected_round
        log(f"      📎 Regex fallback: round={detected_round}")
    
    # 상대 감지: 다양한 패턴으로 상대 이름 추출
    opponent_patterns = [
        # "Alcaraz vs Cameron Norrie", "Alcaraz will face Cameron Norrie"
        r'[Aa]lcaraz\s+(?:vs\.?|faces?|plays?|takes?\s+on|meets?|against|will\s+face)\s+(?:\(\d+\)\s*)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        # "Alcaraz vs [27] Cameron Norrie" (시드 포함)
        r'[Aa]lcaraz\s+(?:vs\.?|faces?)\s+\[?\d*\]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        # "[1] Carlos Alcaraz (ESP) vs [27] Cameron Norrie (GBR)"
        r'Alcaraz\s+\([A-Z]{3}\)\s+(?:vs?\.?\s+|d\.?\s+)\[?\d*\]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        # "Cameron Norrie vs Alcaraz" / "Cameron Norrie vs Carlos Alcaraz"
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+vs\.?\s+(?:Carlos\s+)?[Aa]lcaraz',
        # "quarterfinal against Cameron Norrie" / "faces Cameron Norrie in the quarterfinals"
        r'(?:quarter|semi|final|round)[\w\s]*(?:against|vs\.?|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        # "Next: vs Cameron Norrie"
        r'[Nn]ext:?\s+(?:vs\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
    ]
    
    detected_opponent = None
    skip_words = {'The', 'And', 'For', 'His', 'This', 'That', 'Next', 'Match', 
                 'Round', 'Final', 'Open', 'Masters', 'Grand', 'Slam', 'Indian Wells',
                 'Carlos Alcaraz', 'Stadium Court', 'Not Before', 'BNP Paribas'}
    
    for pattern in opponent_patterns:
        matches = re.findall(pattern, search_text)
        for candidate in matches:
            candidate = candidate.strip()
            if candidate in skip_words or len(candidate) < 4:
                continue
            # 알카라스 본인 이름 제외
            if 'alcaraz' in candidate.lower() or 'carlos' in candidate.lower():
                continue
            # 후행 불필요 단어 제거 (Preview, Prediction 등)
            candidate = re.sub(r'\s+(Preview|Prediction|Highlights?|Schedule|Results?|Head|Match|Live|ATP|WTA).*$', '', candidate, flags=re.IGNORECASE).strip()
            if len(candidate) < 4:
                continue
            detected_opponent = candidate
            break
        if detected_opponent:
            break
    
    if detected_opponent and enriched.get('next', {}).get('opponent', '-') in ('-', '', None):
        enriched['next']['opponent'] = detected_opponent
        log(f"      📎 Regex fallback: opponent={detected_opponent}")
    
    if detected_round or detected_opponent:
        enriched['_enriched'] = True
        enriched['_enriched_confidence'] = 'regex'
    
    return enriched

def get_tennis_data_from_webapp():
    """Tennis (Alcaraz) - Apps Script Web App에서 데이터 가져오기"""
    
    default_data = {
        'recent': {'event': '-', 'opponent': '-', 'result': '-', 'score': '-', 'date': '-'},
        'next': {'event': '-', 'detail': '-', 'match_time': 'TBD', 'tournament_dates': '', 'status': '-'}
    }
    
    try:
        response = requests.get(TENNIS_WEBAPP_URL, timeout=30)
        if response.status_code != 200:
            log(f"   ⚠️ Web App 호출 실패: {response.status_code}")
            return None  # v2.5: None 반환하여 호출측에서 fallback 가능
        
        data = response.json()
        
        if 'error' in data:
            log(f"   ⚠️ Web App 에러: {data['error']}")
            return None
        
        # v2.5: raw 데이터 반환 (후처리는 format_tennis_data에서)
        return data
        
    except requests.exceptions.Timeout:
        log(f"   ⚠️ Web App 타임아웃")
        return None
    except Exception as e:
        log(f"   ⚠️ Web App 예외: {e}")
        return None

def format_tennis_data(raw_data):
    """
    v2.5: raw 데이터를 대시보드 표시용 포맷으로 변환
    Web App 원본이든 enriched 데이터든 동일하게 처리
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
    
    status_map = {
        'australian open': 'Grand Slam', 'french open': 'Grand Slam',
        'roland garros': 'Grand Slam', 'wimbledon': 'Grand Slam',
        'us open': 'Grand Slam', 'indian wells': 'Masters',
        'miami': 'Masters', 'monte carlo': 'Masters',
        'madrid': 'Masters', 'rome': 'Masters', 'italian': 'Masters',
        'cincinnati': 'Masters', 'shanghai': 'Masters',
        'paris masters': 'Masters', 'atp finals': 'Finals'
    }
    
    if not raw_data:
        return {
            'recent': {'event': '-', 'opponent': '-', 'result': '-', 'score': '-', 'date': '-'},
            'next': {'event': '-', 'detail': '-', 'match_time': 'TBD', 'tournament_dates': '', 'status': '-'}
        }
    
    recent = raw_data.get('recent', {})
    next_data = raw_data.get('next', {})

    # v2.6: 스코어 없는 미경기가 'recent'(완료 경기)로 잘못 분류되는 Web App 버그 방어
    recent_score = recent.get('score', '-')
    recent_has_event = recent.get('event', '-') not in ('-', '', None)
    if recent_score in ('-', '', None) and recent_has_event:
        log(f"   ⚠️ Tennis: 'recent'에 스코어 없는 미경기 감지(vs {recent.get('opponent', '-')}) → next로 재분류")
        if next_data.get('event', '-') in ('-', '', None):
            next_data = {
                'event': recent.get('event', '-'),
                'opponent': recent.get('opponent', '-'),
                'round': recent.get('round', '-'),
                'date': recent.get('date', '-'),
                'time_kst': recent.get('time_kst', '-'),
            }
        recent = {}
    
    next_event = next_data.get('event', '-')
    next_opponent = next_data.get('opponent', '-')
    next_round = next_data.get('round', '-')
    next_date = next_data.get('date', '-')
    time_kst = next_data.get('time_kst', '-')
    
    # detail 구성
    if next_round not in ('-', '', None) and next_opponent not in ('-', '', None, 'TBD'):
        next_detail = f"{next_round} vs {next_opponent}"
    elif next_round not in ('-', '', None):
        next_detail = next_round
    elif next_opponent not in ('-', '', None, 'TBD'):
        next_detail = f"vs {next_opponent}"
    else:
        next_detail = '-'
    
    # match_time 구성
    if time_kst not in ('-', '', None):
        match_time = f"{next_date} {time_kst} KST"
    elif next_date not in ('-', '', None):
        match_time = next_date
    else:
        match_time = 'TBD'
    
    # tournament_dates
    tournament_dates = ''
    for keyword, dates in tournament_schedule.items():
        if keyword in next_event.lower():
            tournament_dates = dates
            break
    
    # status (대회 등급)
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
    
    # enriched 메타데이터 전달
    if raw_data.get('_enriched'):
        tennis_data['_enriched'] = True
        tennis_data['_enriched_confidence'] = raw_data.get('_enriched_confidence', '-')
    
    return tennis_data

# =============================================================================
# World Cup 함수 (Football-Data.org API — competition code: WC)
# =============================================================================
def get_worldcup_data(football_key):
    """
    2026 FIFA World Cup 오늘/내일 경기 수집 (Football-Data.org API v4)
    Endpoint: /v4/competitions/WC/matches

    Returns:
        dict: {"phase": str, "matches": list}
    """
    if not football_key:
        log("   ⚠️ FOOTBALL_DATA_API_KEY 없음 → World Cup 데이터 수집 불가")
        return {"phase": "Group Stage", "matches": []}

    kst_now = get_kst_now()
    today_kst_str    = kst_now.strftime("%m.%d")
    tomorrow_kst_str = (kst_now + timedelta(days=1)).strftime("%m.%d")

    date_from = (kst_now.date() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_to   = (kst_now.date() + timedelta(days=1)).strftime("%Y-%m-%d")

    url     = f"{FOOTBALL_DATA_API_URL}/competitions/WC/matches"
    headers = {"X-Auth-Token": football_key}
    params  = {"dateFrom": date_from, "dateTo": date_to}

    STAGE_TO_PHASE = {
        "GROUP_STAGE":    "Group Stage",
        "LAST_16":        "Round of 16",
        "ROUND_OF_16":    "Round of 16",
        "QUARTER_FINALS": "Quarter-Finals",
        "SEMI_FINALS":    "Semi-Finals",
        "THIRD_PLACE":    "Third Place",
        "FINAL":          "Final",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            log(f"   ⚠️ Football-Data WC API error: status={response.status_code}, body={response.text[:300]}")
            return {"phase": "Group Stage", "matches": []}
        all_matches = response.json().get("matches", [])
        log(f"   [WorldCup] API 응답: {len(all_matches)}경기 (UTC {date_from}~{date_to})")
    except Exception as e:
        log(f"   ⚠️ Football-Data WC API exception: {e}")
        return {"phase": "Group Stage", "matches": []}

    phase = "Group Stage"
    output_matches = []

    for match in all_matches:
        utc_date  = match.get("utcDate", "")
        time_info = convert_utc_to_kst(utc_date)
        if not time_info:
            continue

        kst_date = time_info["kst_date"]
        if kst_date not in (today_kst_str, tomorrow_kst_str):
            continue

        raw_status = match.get("status", "")
        if raw_status in ("IN_PLAY", "PAUSED"):
            status = "LIVE"
        elif raw_status in ("FINISHED", "AWARDED"):
            status = "FINISHED"
        else:
            status = "SCHEDULED"

        if status in ("LIVE", "FINISHED"):
            ft = match.get("score", {}).get("fullTime", {})
            h, a = ft.get("home"), ft.get("away")
            score = f"{h}-{a}" if h is not None and a is not None else ""
        else:
            score = ""

        stage = match.get("stage", "")
        phase_label = STAGE_TO_PHASE.get(stage)
        if phase_label:
            phase = phase_label

        group_raw = match.get("group") or ""
        if group_raw.startswith("GROUP_"):
            group = "Group " + group_raw[6:]
        elif group_raw:
            group = group_raw.replace("_", " ").title()
        else:
            group = ""

        home = match.get("homeTeam", {}).get("name", "").strip()
        away = match.get("awayTeam", {}).get("name", "").strip()
        if not home or not away:
            continue

        output_matches.append({
            "home":     home,
            "away":     away,
            "kst_date": time_info["kst_date"],
            "kst_time": time_info["kst_time"],
            "score":    score,
            "status":   status,
            "group":    group
        })

    log(f"   ✅ World Cup 데이터: {len(output_matches)}경기 ({phase})")
    for m in output_matches:
        icon = "🔴" if m["status"] == "LIVE" else ("✅" if m["status"] == "FINISHED" else "📅")
        log(f"      {icon} {m['kst_date']} {m['kst_time']} KST | {m['home']} vs {m['away']} [{m['status']}] {m['score']} {m['group']}")

    return {"phase": phase, "matches": output_matches}

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    football_api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    serper_api_key = os.environ.get("SERPER_API_KEY")
    balldontlie_api_key = os.environ.get("BALLDONTLIE_API_KEY")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

    if not football_api_key:
        log("⚠️ FOOTBALL_DATA_API_KEY 없음 → EPL은 기존 데이터 유지, Korean Players는 폴백/안전값 사용")

    kst_now = get_kst_now()

    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Data Sources:")
    log(f"   - EPL: Football-Data.org {'✅' if football_api_key else '❌'}")
    log(f"   - NBA: balldontlie.io {'✅' if balldontlie_api_key else '❌'}")
    log(f"   - Search: Serper API {'✅' if serper_api_key else '❌'}")
    log(f"   - AI Parse: Gemini API {'✅' if gemini_api_key else '❌'}")

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
        existing_epl = existing_data.get("epl", {}) if existing_data else {}
        if existing_epl:
            log("   ⚠️ 순위 정보 가져오기 실패, 기존 EPL 데이터 사용")
            leader_team = existing_epl.get("leader") or "Arsenal"
            top_4_teams = existing_epl.get("top4") or ["Arsenal", "Manchester City", "Liverpool", "Chelsea"]
            current_matchday = existing_epl.get("matchday") or existing_epl.get("selected_round")
        else:
            log("   ⚠️ 순위 정보 가져오기 실패, 기본값 사용")
            leader_team = "Arsenal"
            top_4_teams = ["Arsenal", "Manchester City", "Liverpool", "Chelsea"]
            current_matchday = None

    # =========================================================================
    # STEP 2: EPL 경기 일정 + 6가지 룰 + 티어 우선순위
    # =========================================================================
    log("\n⚽ [Step 2/5] Premier League 경기 선정 (v2.4)...")
    log("   [티어 우선순위]")
    log("   T1. Big Match: Big 6 vs Big 6")
    log("   T2. Top Tier: Top 4 vs Top 4")
    log("   T3. Challenger: Top 4 vs Big 6")
    log("   T4. Prime Time: 일요일 16:30 UK")
    log("   T5. Early KO: 토요일 12:30 UK")
    log("   T6. Leader: 1위 팀 포함")
    log(f"   [최대 선정: {MAX_EPL_MATCHES}경기]")

    matches = get_epl_matches(football_api_key, current_matchday)
    
    # v2.4: 날짜 기반 7일 조회도 추가 (API currentMatchday가 실제보다 앞서는 경우 대비)
    date_matches = get_epl_matches(football_api_key, matchday=None)  # 7일간 경기
    
    # 두 소스 합치기 (중복 제거)
    seen_ids = {m.get('id') for m in matches if m.get('id')}
    for dm in date_matches:
        if dm.get('id') and dm['id'] not in seen_ids:
            matches.append(dm)
            seen_ids.add(dm['id'])
    
    # 라운드별 그룹핑
    rounds = {}
    for m in matches:
        rd = m.get('matchday')
        if rd:
            if rd not in rounds:
                rounds[rd] = []
            rounds[rd].append(m)
    
    # 가장 가까운 미종료 라운드 찾기 (라운드 번호 오름차순)
    target_round = None
    target_matches = []
    for rd in sorted(rounds.keys()):
        rd_matches = rounds[rd]
        has_unfinished = any(m.get('status') not in ('FINISHED',) for m in rd_matches)
        if has_unfinished:
            target_round = rd
            target_matches = rd_matches
            break
    
    # 모든 라운드가 종료된 경우 → 가장 높은 라운드 사용
    if target_round is None and rounds:
        target_round = max(rounds.keys())
        target_matches = rounds[target_round]
    
    # 상태별 로그
    status_count = {}
    for m in target_matches:
        s = m.get('status', 'UNKNOWN')
        status_count[s] = status_count.get(s, 0) + 1
    log(f"   📋 전체: {len(matches)}경기 (라운드: {sorted(rounds.keys())})")
    log(f"   🎯 선정 대상: R{target_round} ({len(target_matches)}경기)")
    log(f"   📊 상태별: {status_count}")

    existing_epl = existing_data.get("epl", {}) if existing_data else {}
    if not football_api_key and existing_epl:
        validated_epl = existing_epl.get("selected_matches") or existing_epl.get("matches") or []
        selected_round = existing_epl.get("selected_round") or current_matchday
        is_new_selection = False
        log(f"   ⚠️ FOOTBALL_DATA_API_KEY 없음 → 기존 EPL 경기 유지: {len(validated_epl)}경기 (R{selected_round})")
    else:
        # v2.4: 단일 라운드(target_matches)만 전달
        validated_epl, selected_round, is_new_selection = process_epl_matches(
            target_matches, top_4_teams, leader_team, serper_api_key, existing_data,
            football_api_key=football_api_key,
            current_matchday=target_round
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
        existing_nba = existing_data.get("nba") if existing_data else None
        if existing_nba:
            nba_data = existing_nba
            log("   ⚠️ BALLDONTLIE_API_KEY 없음, 기존 NBA 데이터 유지")
        else:
            nba_data = get_nba_default_data()
            log("   ⚠️ BALLDONTLIE_API_KEY 없음, 기본값 사용")

    # =========================================================================
    # STEP 4: F1 (v2.5: 순위 + 세부 스케줄)
    # =========================================================================
    log("\n🏎️ [Step 4/5] F1 (v2.5: 순위 + 세부 스케줄)...")

    f1_data = search_f1_data(serper_api_key, gemini_api_key)
    next_race = f1_data.get('next_race', {})
    log(f"   ✅ {next_race.get('name', '-')} | {next_race.get('circuit', '-')} | {next_race.get('date', '-')} [{next_race.get('status', '-')}]")
    if f1_data.get('schedule'):
        for s in f1_data['schedule']:
            log(f"      📅 {s['date']} {s['kst_time']} KST | {s['name']}")
    if f1_data.get('standings'):
        log(f"   ✅ 순위: {len(f1_data['standings'])}명 로드")

    # =========================================================================
    # STEP 5a: Korean Players (하이브리드: Football-Data.org + Serper/Gemini)
    # =========================================================================
    log("\n🇰🇷 [Step 5a] Korean Players (이강인·김민재·손흥민)...")

    korean_players_data = get_korean_players_data(football_api_key, serper_api_key, gemini_api_key, existing_data)

    # @disabled:worldcup — 월드컵 종료로 데이터 수집 중단. 다음 대회 시 주석 해제.
    # worldcup_data = get_worldcup_data(football_api_key)
    # log(f"   ✅ Phase: {worldcup_data['phase']} | Matches: {len(worldcup_data['matches'])}경기")

    # =========================================================================
    # STEP 5: Tennis (v6: Sofascore Web App — Gemini 없음)
    # =========================================================================
    log("\n🎾 [Step 5/5] Tennis (Alcaraz) - v6 (Sofascore)...")

    raw_tennis = get_tennis_data_from_webapp()
    
    if raw_tennis:
        recent = raw_tennis.get('recent', {})
        next_raw = raw_tennis.get('next', {})
        log(f"   ✅ Web App 응답:")
        log(f"      Recent: {recent.get('event', '-')} vs {recent.get('opponent', '-')} {recent.get('result', '-')} ({recent.get('score', '-')})")
        log(f"      Next: {next_raw.get('event', '-')} | {next_raw.get('date', '-')}")
        tennis_data = format_tennis_data(raw_tennis)
    else:
        log("   ⚠️ Web App 실패 → 기본값")
        tennis_data = format_tennis_data(None)
    
    # 최종 결과 로그
    final_recent = tennis_data.get('recent', {})
    final_next = tennis_data.get('next', {})
    log(f"   📊 최종:")
    log(f"      Recent: {final_recent.get('event', '-')} vs {final_recent.get('opponent', '-')} {final_recent.get('result', '-')} ({final_recent.get('score', '-')}) | {final_recent.get('date', '-')}")
    log(f"      Next: {final_next.get('event', '-')} | {final_next.get('detail', '-')} | {final_next.get('match_time', '-')}")

    # =========================================================================
    # STEP 6: 해외파 코리안리거 돋보기
    # =========================================================================
    log("\n🌍 [Step 6] 해외파 코리안리거 돋보기...")

    existing_overseas_data = load_json_safe(KOREAN_OVERSEAS_FILE, {})
    existing_overseas_history = load_json_safe(KOREAN_OVERSEAS_HISTORY_FILE, {})
    overseas_players, overseas_history = get_korean_overseas_data(
        serper_api_key,
        existing_overseas_history,
        existing_overseas_data,
    )
    overseas_hot_issues = summarize_overseas_hot_issues(overseas_players, gemini_api_key)
    log(f"   ✅ 해외파 {len(overseas_players)}명 수집, 핫이슈 {len(overseas_hot_issues)}건")

    # =========================================================================
    # NBA All-Star Week 데이터 삽입 (기간 내 자동 표시/숨김)
    # =========================================================================
    nba_data = inject_allstar_data(nba_data, kst_now)

    # =========================================================================
    # 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")

    # EPL 표시용 라운드
    display_matchday = f"R{selected_round}" if selected_round else f"R{current_matchday}"
    
    clean_tennis = tennis_data

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
        "tennis": clean_tennis,
        "korean_players": korean_players_data,
        # "worldcup": worldcup_data,  # @disabled:worldcup — 데이터 자체 중단
        "debug": {
            "has_football_key": bool(football_api_key),
            "has_serper_key": bool(serper_api_key),
            "has_gemini_key": bool(gemini_api_key),
            "has_balldontlie_key": bool(balldontlie_api_key),
            "logs": LOG_MESSAGES
        }
    }

    with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sports_data, f, ensure_ascii=False, indent=2)

    with open(KOREAN_OVERSEAS_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(overseas_history, f, ensure_ascii=False, indent=2)

    with open(KOREAN_OVERSEAS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "updated": kst_now.strftime("%Y-%m-%d %H:%M:%S KST"),
            "hot_issues": overseas_hot_issues,
            "players": overseas_players,
        }, f, ensure_ascii=False, indent=2)

    log(f"✅ [Complete]")
    log(f"   EPL: {len(validated_epl)}경기 ({display_matchday})")
    log(f"   NBA: {len(nba_data['schedule'])}경기")
    log(f"   F1: {next_race.get('name', '-')} | {len(f1_data.get('schedule', []))}세션 | {len(f1_data.get('standings', []))}명 순위")
    log(f"   Tennis: {final_next.get('event', '-')} | {final_next.get('detail', '-')}")
    log(f"   Korean Players: {len(korean_players_data)}명")
    log(f"   Korean Overseas: {len(overseas_players)}명 | 핫이슈 {len(overseas_hot_issues)}건")
    log(f"   파일: {SPORTS_FILE}, {KOREAN_OVERSEAS_FILE}, {KOREAN_OVERSEAS_HISTORY_FILE}")

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
