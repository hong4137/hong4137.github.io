#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater
=================================================
EPL 경기 선별 시 6가지 룰을 "검색 후 검증" 방식으로 적용

[핵심 교훈]
- 추측하지 말고 검색으로 확인할 것
- Big 6는 고정값이지만, Top 4와 1위는 매번 검색 필요
- 킥오프 시간도 반드시 검색으로 확인
- 타임존 변환은 Gemini에게 맡기지 말고 Python에서 직접 처리

[6가지 룰]
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함 경기

[타임존]
- UK (GMT/BST) → KST: +9시간 (겨울), +8시간 (여름 BST)
- PST → KST: +17시간
- EST → KST: +14시간
- GitHub Actions 서버는 UTC → KST 표시를 위해 +9시간
"""

import os
import json
import datetime
import traceback
import re
import sys

# ---------------------------------------------------------
# [Configuration]
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json' 
MODEL_NAME = 'gemini-flash-latest' 
# =============================================================================
# 타임존 설정
# =============================================================================
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo

# 타임존 정의
TZ_KST = ZoneInfo("Asia/Seoul")
TZ_UTC = ZoneInfo("UTC")
TZ_UK = ZoneInfo("Europe/London")  # GMT/BST 자동 처리
TZ_PST = ZoneInfo("America/Los_Angeles")
TZ_EST = ZoneInfo("America/New_York")

# =============================================================================
# 설정
# =============================================================================
SPORTS_FILE = 'sports.json'
MODEL_NAME = 'gemini-flash-latest'

# Big 6는 고정값 (검색 불필요)
BIG_6 = ["Manchester City", "Manchester United", "Liverpool", "Arsenal", "Chelsea", "Tottenham"]
BIG_6_ALIASES = {
    "Man City": "Manchester City",
    "Man Utd": "Manchester United", 
    "Spurs": "Tottenham",
    "Tottenham Hotspur": "Tottenham"
}

def log(message):
    """버퍼링 없이 즉시 출력"""
    print(message, flush=True)

# =============================================================================
# 라이브러리 임포트
# =============================================================================
try:
    from google import genai
    from google.genai import types
except ImportError:
    log("❌ Critical Error: 'google-genai' library not found.")
    sys.exit(1)

# =============================================================================
# 타임존 변환 함수
# =============================================================================
def get_kst_now():
    """현재 한국 시간 반환"""
    return datetime.datetime.now(TZ_KST)

def convert_uk_to_kst(date_str, time_str):
    """
    UK 시간을 KST로 변환
    
    Args:
        date_str: "01.04" 또는 "2026-01-04" 형식
        time_str: "12:30" 또는 "17:30" 형식
    
    Returns:
        tuple: (kst_date_str, kst_time_str, kst_full_str)
        예: ("01.04", "21:30", "01.04 21:30 (KST)")
    """
    try:
        # 날짜 파싱
        if '.' in date_str and len(date_str) <= 5:
            # "01.04" 형식
            month, day = map(int, date_str.split('.'))
            year = get_kst_now().year
            if month < get_kst_now().month - 6:
                year += 1  # 다음 해로 추정
        elif '-' in date_str:
            # "2026-01-04" 형식
            parts = date_str.split('-')
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return date_str, time_str, f"{date_str} {time_str}"
        
        # 시간 파싱
        time_str_clean = time_str.replace(' ', '').split('(')[0]  # "(UK)" 등 제거
        if ':' in time_str_clean:
            hour, minute = map(int, time_str_clean.split(':'))
        else:
            return date_str, time_str, f"{date_str} {time_str}"
        
        # UK 시간으로 datetime 생성
        uk_dt = datetime.datetime(year, month, day, hour, minute, tzinfo=TZ_UK)
        
        # KST로 변환
        kst_dt = uk_dt.astimezone(TZ_KST)
        
        kst_date_str = kst_dt.strftime("%m.%d")
        kst_time_str = kst_dt.strftime("%H:%M")
        kst_full_str = f"{kst_date_str} {kst_time_str} (KST)"
        
        return kst_date_str, kst_time_str, kst_full_str
        
    except Exception as e:
        log(f"   ⚠️ UK→KST 변환 실패: {date_str} {time_str} - {e}")
        return date_str, time_str, f"{date_str} {time_str}"

def convert_pst_to_kst(date_str, time_str):
    """
    PST(미국 서부) 시간을 KST로 변환
    
    Args:
        date_str: "01.02" 형식
        time_str: "19:00" 또는 "7:00 PM" 형식
    
    Returns:
        tuple: (kst_date_str, kst_time_str, kst_full_str)
    """
    try:
        # 날짜 파싱
        if '.' in date_str and len(date_str) <= 5:
            month, day = map(int, date_str.split('.'))
            year = get_kst_now().year
            if month < get_kst_now().month - 6:
                year += 1
        else:
            return date_str, time_str, f"{date_str} {time_str} (PST)"
        
        # 시간 파싱 (PM/AM 처리)
        time_str_clean = time_str.upper().replace(' ', '')
        time_str_clean = re.sub(r'\(.*\)', '', time_str_clean)  # (PST) 등 제거
        
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
            return date_str, time_str, f"{date_str} {time_str} (PST)"
        
        # PST 시간으로 datetime 생성
        pst_dt = datetime.datetime(year, month, day, hour, minute, tzinfo=TZ_PST)
        
        # KST로 변환
        kst_dt = pst_dt.astimezone(TZ_KST)
        
        kst_date_str = kst_dt.strftime("%m.%d")
        kst_time_str = kst_dt.strftime("%H:%M")
        kst_full_str = f"{kst_date_str} {kst_time_str} (KST)"
        
        return kst_date_str, kst_time_str, kst_full_str
        
    except Exception as e:
        log(f"   ⚠️ PST→KST 변환 실패: {date_str} {time_str} - {e}")
        return date_str, time_str, f"{date_str} {time_str} (PST)"

def convert_est_to_kst(date_str, time_str):
    """
    EST(미국 동부) 시간을 KST로 변환
    """
    try:
        if '.' in date_str and len(date_str) <= 5:
            month, day = map(int, date_str.split('.'))
            year = get_kst_now().year
            if month < get_kst_now().month - 6:
                year += 1
        else:
            return date_str, time_str, f"{date_str} {time_str} (EST)"
        
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
            return date_str, time_str, f"{date_str} {time_str} (EST)"
        
        est_dt = datetime.datetime(year, month, day, hour, minute, tzinfo=TZ_EST)
        kst_dt = est_dt.astimezone(TZ_KST)
        
        kst_date_str = kst_dt.strftime("%m.%d")
        kst_time_str = kst_dt.strftime("%H:%M")
        kst_full_str = f"{kst_date_str} {kst_time_str} (KST)"
        
        return kst_date_str, kst_time_str, kst_full_str
        
    except Exception as e:
        log(f"   ⚠️ EST→KST 변환 실패: {date_str} {time_str} - {e}")
        return date_str, time_str, f"{date_str} {time_str} (EST)"

# =============================================================================
# 유틸리티 함수
# =============================================================================
def extract_json_content(text):
    """텍스트에서 JSON 부분만 추출"""
    text = text.strip()
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    try:
@@ -31,204 +248,505 @@
            return json.loads(text[start_idx : end_idx + 1])
        return json.loads(text)
    except json.JSONDecodeError:
        log(f"⚠️ JSON Parsing Failed. Text start: {text[:50]}...")
        log(f"⚠️ JSON Parsing Failed. Text start: {text[:100]}...")
        return {}

def normalize_data(data):
    log("🔧 [Processing] Robust Normalization...")
def normalize_team_name(name):
    """팀 이름 정규화 (별칭 처리)"""
    name = name.strip()
    return BIG_6_ALIASES.get(name, name)

    # 1. EPL
    if 'epl_round' not in data:
        data['epl_round'] = "R--"
    else:
        raw_round = str(data['epl_round'])
        nums = re.findall(r'\d+', raw_round)
        if nums:
            data['epl_round'] = f"R{nums[0]}"
        elif not raw_round.startswith('R'):
             data['epl_round'] = f"R{raw_round}"

    if 'epl' in data and isinstance(data['epl'], list):
        for item in data['epl']:
            # [핵심 수정] 파이썬 분기 로직 강화
            # AI가 home/away를 안 줬을 경우를 대비해 'v', 'vs', '-' 모두 체크
            if not item.get('home') or not item.get('away'):
                raw_teams = item.get('teams') or item.get('match') or ""
                
                # 영국식(v), 일반(vs), 하이픈(-) 순차 체크
                if ' vs ' in raw_teams:
                    h, a = raw_teams.split(' vs ')
                elif ' v ' in raw_teams:
                    h, a = raw_teams.split(' v ')
                elif ' - ' in raw_teams:
                    h, a = raw_teams.split(' - ')
                else:
                    # 분리 실패 시 통째로라도 넣어서 undefined 방지
                    h, a = raw_teams, ""
                
                item['home'] = h.strip()
                item['away'] = a.strip()

            # 부가 정보 보정
            if not item.get('channel') or item.get('channel') == "TBD": 
                pass # 프론트엔드가 처리하게 둠
def is_big_6(team_name):
    """Big 6 팀인지 확인"""
    normalized = normalize_team_name(team_name)
    return any(big in normalized for big in BIG_6)

# =============================================================================
# EPL 데이터 정규화
# =============================================================================
def normalize_epl_data(epl_list, top_4_teams, leader_team):
    """
    EPL 경기 데이터 정규화 및 룰 검증
    
    Args:
        epl_list: Gemini가 반환한 EPL 경기 목록
        top_4_teams: 검색으로 확인한 현재 Top 4 팀 목록
        leader_team: 검색으로 확인한 현재 1위 팀
    """
    if not epl_list or not isinstance(epl_list, list):
        return []
    
    validated_matches = []
    
    for match in epl_list:
        # 홈/어웨이 팀 추출
        home = match.get('home', '')
        away = match.get('away', '')
        
        # teams 필드에서 추출 시도
        if not home or not away:
            teams_str = match.get('teams') or match.get('match') or ''
            if ' vs ' in teams_str:
                parts = teams_str.split(' vs ')
                home = parts[0].strip()
                away = parts[1].strip() if len(parts) > 1 else ''
            elif ' v ' in teams_str:
                parts = teams_str.split(' v ')
                home = parts[0].strip()
                away = parts[1].strip() if len(parts) > 1 else ''
        
        if not home or not away:
            continue
        
        # 팀 이름 정규화
        home = normalize_team_name(home)
        away = normalize_team_name(away)
        
        # 킥오프 정보
        kickoff_day = match.get('kickoff_day', '')  # Saturday, Sunday, etc.
        kickoff_time_uk = match.get('kickoff_time_uk', '')  # 12:30, 16:30, etc.
        match_date = match.get('date', '')  # 01.04
        
        # 6가지 룰 체크
        matched_rules = []
        
        # 룰 1: Big Match (Big 6 vs Big 6)
        if is_big_6(home) and is_big_6(away):
            matched_rules.append("Rule1:Big6vsBig6")
        
        # 룰 2: Top Tier (Top 4 vs Top 4)
        home_in_top4 = any(home in t or t in home for t in top_4_teams)
        away_in_top4 = any(away in t or t in away for t in top_4_teams)
        if home_in_top4 and away_in_top4:
            matched_rules.append("Rule2:Top4vsTop4")
        
        # 룰 3: Challenger (Top 4 vs Big 6, 서로 다른 조건)
        home_is_big6 = is_big_6(home)
        away_is_big6 = is_big_6(away)
        if (home_in_top4 and away_is_big6 and not home_is_big6) or \
           (away_in_top4 and home_is_big6 and not away_is_big6):
            matched_rules.append("Rule3:Top4vsBig6")
        
        # 룰 4: Prime Time (일요일 16:30 UK)
        if 'sunday' in kickoff_day.lower() and '16:30' in kickoff_time_uk:
            matched_rules.append("Rule4:Sunday16:30")
        
        # 룰 5: Early KO (토요일 12:30 UK)
        if 'saturday' in kickoff_day.lower() and '12:30' in kickoff_time_uk:
            matched_rules.append("Rule5:Saturday12:30")
        
        # 룰 6: Leader (1위 팀 포함)
        if leader_team:
            if leader_team in home or home in leader_team or \
               leader_team in away or away in leader_team:
                matched_rules.append("Rule6:Leader")
        
        # 최소 1개 룰에 해당하면 선택
        if matched_rules:
            match['home'] = home
            match['away'] = away
            match['matched_rules'] = matched_rules
            
            # UK → KST 시간 변환 (Python에서 직접 처리)
            if match_date and kickoff_time_uk:
                kst_date, kst_time, kst_full = convert_uk_to_kst(match_date, kickoff_time_uk)
                match['kst_time'] = kst_full
                match['local_time'] = f"{match_date} {kickoff_time_uk} (UK)"
            else:
                match['kst_time'] = match.get('time', 'TBD')
                match['local_time'] = f"{kickoff_day} {kickoff_time_uk}".strip() or ''

            if not item.get('kst_time'): item['kst_time'] = item.get('time', 'TBD')
            if not item.get('local_time'): item['local_time'] = ""
            if not item.get('status'): item['status'] = "Scheduled"

    # 2. NBA
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    nba['record'] = nba.get('record') or "-"
    nba['rank'] = nba.get('ranking') or nba.get('rank') or "-"
    if 'last' not in nba: nba['last'] = {"opp": "-", "result": "-", "score": "-"}

    if 'schedule' in nba and isinstance(nba['schedule'], list):
        nba['schedule'] = nba['schedule'][:4] 
        for item in nba['schedule']:
            if 'opp' not in item:
                raw = item.get('teams') or item.get('match') or ""
                if 'vs' in raw:
                    item['opp'] = raw.split('vs')[-1].strip()
            match['channel'] = match.get('broadcaster') or match.get('channel') or 'UK TV'
            match['status'] = match.get('status') or 'Scheduled'
            
            validated_matches.append(match)
            log(f"   ✅ {home} vs {away} → {', '.join(matched_rules)}")
        else:
            log(f"   ❌ {home} vs {away} → 어떤 룰에도 해당 안 됨 (day={kickoff_day}, time={kickoff_time_uk})")
    
    return validated_matches[:7]  # 최대 7경기

# =============================================================================
# NBA 데이터 정규화
# =============================================================================
def normalize_nba_data(nba_data):
    """NBA 데이터 정규화 - undefined 방지, PST→KST 변환"""
    if not nba_data:
        nba_data = {}
    
    nba_data['record'] = nba_data.get('record') or '-'
    nba_data['rank'] = nba_data.get('ranking') or nba_data.get('rank') or '-'
    
    # last game 정보
    if 'last' not in nba_data:
        nba_data['last'] = {'opp': '-', 'result': '-', 'score': '-'}
    else:
        last = nba_data['last']
        last['opp'] = last.get('opp') or last.get('opponent') or '-'
        last['result'] = last.get('result') or '-'
        last['score'] = last.get('score') or '-'
    
    # schedule 정규화 + PST→KST 변환
    if 'schedule' in nba_data and isinstance(nba_data['schedule'], list):
        nba_data['schedule'] = nba_data['schedule'][:4]
        for game in nba_data['schedule']:
            # opp 필드 확보
            if 'opp' not in game or not game['opp']:
                raw = game.get('teams') or game.get('match') or game.get('opponent') or ''
                if 'vs' in raw.lower():
                    game['opp'] = raw.lower().split('vs')[-1].strip().title()
                elif '@' in raw:
                    item['opp'] = raw.split('@')[-1].strip()
                    game['opp'] = raw.split('@')[-1].strip()
                else:
                    item['opp'] = raw.replace("GS Warriors", "").strip() or "TBD"
                    game['opp'] = raw.replace('Warriors', '').replace('Golden State', '').strip() or 'TBD'
            
            # 시간 추출 및 PST→KST 변환
            date_str = game.get('date', '')
            time_str = game.get('time', '')

            if 'time' in item and not item.get('date'):
                parts = item['time'].split(' ')
            # time 필드에 날짜+시간이 합쳐져 있는 경우 분리
            if not date_str and time_str:
                parts = time_str.split(' ', 1)
                if len(parts) >= 1:
                    date_str = parts[0]
                if len(parts) >= 2:
                    item['date'] = parts[0]
                    item['time'] = " ".join(parts[1:])
                else:
                    item['date'] = item['time']

    # 3. Tennis
    if 'tennis' not in data: data['tennis'] = {}
    t = data['tennis']
    if not t.get('info'): t['info'] = "No Match"
    if not t.get('detail'): t['detail'] = "Check Schedule"
    if not t.get('status'): t['status'] = "Season 2026"
    if not t.get('time'): t['time'] = ""

    # 4. F1
    if 'f1' not in data: data['f1'] = {}
    f = data['f1']
    if not f.get('name'): f['name'] = "Next GP"
    if not f.get('circuit'): f['circuit'] = "Circuit TBD"
    if not f.get('status'): f['status'] = "Upcoming"
    if not f.get('date'): f['date'] = f.get('time', '')

    data['updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return data
                    time_str = parts[1]
            
            # PST → KST 변환
            if date_str and time_str:
                kst_date, kst_time, kst_full = convert_pst_to_kst(date_str, time_str)
                game['date'] = kst_date
                game['time'] = kst_time
                game['time_kst'] = kst_full
                game['time_pst'] = f"{date_str} {time_str} (PST)"
            elif date_str:
                game['date'] = date_str
    else:
        nba_data['schedule'] = []
    
    return nba_data

# =============================================================================
# Tennis 데이터 정규화
# =============================================================================
def normalize_tennis_data(tennis_data):
    """Tennis 데이터 정규화"""
    if not tennis_data:
        tennis_data = {}
    
    tennis_data['status'] = tennis_data.get('status') or tennis_data.get('tournament_status') or 'Off-Season'
    tennis_data['info'] = tennis_data.get('info') or tennis_data.get('tournament') or tennis_data.get('match') or 'Next Tournament TBD'
    tennis_data['detail'] = tennis_data.get('detail') or tennis_data.get('round') or 'Check Schedule'
    tennis_data['time'] = tennis_data.get('time') or tennis_data.get('date') or ''
    
    return tennis_data

# =============================================================================
# F1 데이터 정규화
# =============================================================================
def normalize_f1_data(f1_data):
    """F1 데이터 정규화"""
    if not f1_data:
        f1_data = {}
    
    f1_data['status'] = f1_data.get('status') or 'Season 2026'
    f1_data['name'] = f1_data.get('name') or f1_data.get('grand_prix') or 'Next GP'
    f1_data['circuit'] = f1_data.get('circuit') or f1_data.get('location') or 'Circuit TBD'
    f1_data['date'] = f1_data.get('date') or f1_data.get('time') or ''
    
    return f1_data

# =============================================================================
# 메인 업데이트 함수
# =============================================================================
def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("❌ Error: GEMINI_API_KEY Missing")
        raise ValueError("API Key Missing")

    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    log(f"🚀 [Start] Gemini API({MODEL_NAME}) initialized.")
    today = datetime.date.today()
    client = genai.Client(api_key=api_key)

    # [Prompt] home, away 분리 요청 + v/vs 이슈 원천 차단
    prompt = f"""
    # 현재 시간 (KST)
    kst_now = get_kst_now()
    today = kst_now.date()
    
    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Model: {MODEL_NAME}")
    
    # =========================================================================
    # STEP 1: 현재 프리미어리그 순위 검색 (Top 4, 1위 확인)
    # =========================================================================
    log("\n📊 [Step 1] Premier League 순위 검색...")
    
    standings_prompt = f"""
    Current Date: {today}
    TASK: Search for OFFICIAL 2026 schedules.
    
    *** STRICT EPL MATCH SELECTION (NO FILLERS) ***
    Filter the upcoming fixtures and return matches that meet AT LEAST ONE of the following 6 Criteria.
    If 0 matches meet criteria, return []. If 10 matches meet criteria, return all 10.

    [Context] Big 6: Man City, Man Utd, Liverpool, Arsenal, Chelsea, Tottenham.
    Search for the CURRENT Premier League 2025-26 season standings table.
    
    [Selection Criteria]
    1. **Big Match:** Big 6 vs Big 6.
    2. **Top Tier:** Current Top 4 vs Current Top 4.
    3. **Challenger:** Current Top 4 vs Big 6.
    4. **Prime Time:** Sunday 16:30 (UK Time).
    5. **Early KO:** Saturday 12:30 (UK Time).
    6. **Leader:** Match featuring League Leader.
    I need to know:
    1. Which team is currently in 1st place (Leader)?
    2. Which 4 teams are currently in Top 4 positions?
    
    *** OTHER TASKS ***
    1. **EPL Info**: Find specific UK Broadcaster (Sky/TNT/Amazon).
    2. **Tennis (Alcaraz)**: Check for EXHIBITION matches (e.g. Kooyong) or Tournaments.
    3. **NBA**: Next 4 games (Find Opponent Name).
    4. **F1**: Next 2026 GP.

    TARGET JSON STRUCTURE (Must separate Home/Away):
    Return JSON only:
    {{
        "leader": "Team name in 1st place",
        "top_4": ["1st place team", "2nd place team", "3rd place team", "4th place team"]
    }}
    """
    
    try:
        standings_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=standings_prompt,
            config=types.GenerateContentConfig(tools=[google_search_tool])
        )
        standings_data = extract_json_content(standings_response.text)
        leader_team = standings_data.get('leader', '')
        top_4_teams = standings_data.get('top_4', [])
        log(f"   ✅ Leader: {leader_team}")
        log(f"   ✅ Top 4: {top_4_teams}")
    except Exception as e:
        log(f"   ⚠️ 순위 검색 실패: {e}")
        leader_team = 'Arsenal'  # fallback
        top_4_teams = ['Arsenal', 'Manchester City', 'Liverpool', 'Chelsea']
    
    # =========================================================================
    # STEP 2: EPL 경기 일정 + 킥오프 시간 검색 (UK 시간으로만 요청)
    # =========================================================================
    log("\n⚽ [Step 2] EPL 경기 일정 검색 (UK 시간)...")
    
    epl_prompt = f"""
    Current Date: {today}
    
    Search for Premier League fixtures for the NEXT matchweek (upcoming games).
    
    IMPORTANT: 
    - Provide kickoff times in UK time ONLY (I will convert to KST myself)
    - Include the day of week for each match
    
    For each match, provide:
    - home: Home team name
    - away: Away team name  
    - kickoff_day: Day of week in English (Saturday, Sunday, Monday, etc.)
    - kickoff_time_uk: Kickoff time in UK, 24-hour format (e.g., "12:30", "15:00", "16:30", "17:30", "20:00")
    - date: Match date in MM.DD format (e.g., "01.04")
    - broadcaster: UK TV channel (Sky Sports, TNT Sports, Amazon Prime, etc.)
    
    Return JSON only:
    {{
        "epl_round": "Current Matchweek Number (e.g. 20)",
        "epl_round": "Matchweek number (e.g., 20)",
        "epl": [
            {{ 
              "home": "Home Team Name",
              "away": "Away Team Name",
              "kst_time": "MM.DD HH:MM (KST)", 
              "local_time": "MM.DD HH:MM (Local)",
              "channel": "UK TV Channel", 
              "status": "Scheduled"
            {{
                "home": "Home Team",
                "away": "Away Team",
                "kickoff_day": "Saturday",
                "kickoff_time_uk": "12:30",
                "date": "01.04",
                "broadcaster": "Sky Sports"
            }}
        ],
        ]
    }}
    
    Include ALL matches in the matchweek, not just selected ones.
    """
    
    try:
        epl_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=epl_prompt,
            config=types.GenerateContentConfig(tools=[google_search_tool])
        )
        epl_data = extract_json_content(epl_response.text)
        epl_round = epl_data.get('epl_round', 'R--')
        epl_matches = epl_data.get('epl', [])
        log(f"   검색된 경기 수: {len(epl_matches)}")
    except Exception as e:
        log(f"   ⚠️ EPL 검색 실패: {e}")
        traceback.print_exc()
        epl_round = 'R--'
        epl_matches = []
    
    # =========================================================================
    # STEP 3: 6가지 룰로 EPL 경기 필터링
    # =========================================================================
    log("\n🎯 [Step 3] 6가지 룰 적용하여 경기 선별...")
    log(f"   Big 6: {BIG_6}")
    log(f"   Top 4: {top_4_teams}")
    log(f"   Leader: {leader_team}")
    
    validated_epl = normalize_epl_data(epl_matches, top_4_teams, leader_team)
    log(f"   선별된 경기 수: {len(validated_epl)}")
    
    # =========================================================================
    # STEP 4: NBA 데이터 검색 (PST 시간으로 요청, Python에서 KST 변환)
    # =========================================================================
    log("\n🏀 [Step 4] NBA Warriors 일정 검색 (PST)...")
    
    nba_prompt = f"""
    Current Date: {today}
    
    Search for Golden State Warriors:
    1. Current season record (W-L)
    2. Current Western Conference ranking
    3. Last game result (opponent, W/L, score)
    4. Next 4 scheduled games
    
    IMPORTANT: Provide game times in PST (Pacific Standard Time) only.
    
    Return JSON only:
    {{
        "nba": {{
            "record": "W-L",
            "rank": "Conf. Rank",
            "last": {{ "opp": "Name", "result": "W/L", "score": "100-90" }},
            "schedule": [ {{ "opp": "Name", "date": "MM.DD", "time": "HH:MM (PST)" }} ]
        }},
            "record": "17-16",
            "rank": "8th West",
            "last": {{
                "opp": "Opponent Name",
                "result": "W",
                "score": "107-104"
            }},
            "schedule": [
                {{ "opp": "Hornets", "date": "01.02", "time": "19:00" }}
            ]
        }}
    }}
    """
    
    try:
        nba_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=nba_prompt,
            config=types.GenerateContentConfig(tools=[google_search_tool])
        )
        nba_data = extract_json_content(nba_response.text).get('nba', {})
        log(f"   ✅ Record: {nba_data.get('record', 'N/A')}")
    except Exception as e:
        log(f"   ⚠️ NBA 검색 실패: {e}")
        nba_data = {}
    
    nba_data = normalize_nba_data(nba_data)
    
    # =========================================================================
    # STEP 5: Tennis 데이터 검색
    # =========================================================================
    log("\n🎾 [Step 5] Carlos Alcaraz 일정 검색...")
    
    tennis_prompt = f"""
    Current Date: {today}
    
    Search for Carlos Alcaraz's next tennis match or tournament:
    1. Is he currently playing in a tournament?
    2. What is his next scheduled match/tournament?
    3. Include exhibition matches like Kooyong Classic if applicable.
    
    Return JSON only:
    {{
        "tennis": {{
            "status": "Exhibition / Tournament Name",
            "info": "Event Name",
            "detail": "Round info",
            "time": "MM.DD HH:MM"
        }},
        "f1": {{
            "status": "Season 2026",
            "name": "Grand Prix Name",
            "circuit": "Circuit Name",
            "date": "MM.DD - MM.DD"
            "status": "Playing / Off-Season / Exhibition",
            "info": "Tournament Name",
            "detail": "Round or Match info (e.g., Final vs Sinner)",
            "time": "01.12 or date range"
        }}
    }}
    """

    Return ONLY the JSON object.
    try:
        tennis_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=tennis_prompt,
            config=types.GenerateContentConfig(tools=[google_search_tool])
        )
        tennis_data = extract_json_content(tennis_response.text).get('tennis', {})
        log(f"   ✅ Status: {tennis_data.get('status', 'N/A')}")
    except Exception as e:
        log(f"   ⚠️ Tennis 검색 실패: {e}")
        tennis_data = {}
    
    tennis_data = normalize_tennis_data(tennis_data)
    
    # =========================================================================
    # STEP 6: F1 데이터 검색
    # =========================================================================
    log("\n🏎️ [Step 6] F1 2026 시즌 검색...")
    
    f1_prompt = f"""
    Current Date: {today}
    
    Search for the next Formula 1 Grand Prix in 2026 season:
    1. Grand Prix name
    2. Circuit name and location
    3. Race date
    
    Return JSON only:
    {{
        "f1": {{
            "status": "Off-Season / Race Week",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park Circuit, Melbourne",
            "date": "03.14-03.16"
        }}
    }}
    """

    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
        f1_response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool]
            )
            contents=f1_prompt,
            config=types.GenerateContentConfig(tools=[google_search_tool])
        )
        
        if not response.text:
            log("⚠️ Warning: Empty response.")
            return

        data = extract_json_content(response.text)
        data = normalize_data(data)
        
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        log(f"✅ [Success] Data updated (v/vs Safe Mode).")
        log(f"   - EPL Matches Selected: {len(data.get('epl', []))}")
        
        # 로그 확인용 (첫 번째 경기의 홈팀이 잘 들어갔는지)
        if data.get('epl'):
            log(f"   - Sample: {data['epl'][0].get('home')} vs {data['epl'][0].get('away')}")
        f1_data = extract_json_content(f1_response.text).get('f1', {})
        log(f"   ✅ Next GP: {f1_data.get('name', 'N/A')}")
    except Exception as e:
        log(f"   ⚠️ F1 검색 실패: {e}")
        f1_data = {}
    
    f1_data = normalize_f1_data(f1_data)
    
    # =========================================================================
    # STEP 7: 최종 데이터 저장
    # =========================================================================
    log("\n💾 [Step 7] 데이터 저장...")
    
    # epl_round 정규화
    if epl_round:
        nums = re.findall(r'\d+', str(epl_round))
        if nums:
            epl_round = f"R{nums[0]}"
        elif not str(epl_round).startswith('R'):
            epl_round = f"R{epl_round}"
    
    final_data = {
        "updated": get_kst_now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "epl_round": epl_round,
        "standings": {
            "leader": leader_team,
            "top_4": top_4_teams
        },
        "epl": validated_epl,
        "nba": nba_data,
        "tennis": tennis_data,
        "f1": f1_data
    }
    
    with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    log(f"\n✅ [Complete] 데이터 업데이트 완료!")
    log(f"   - EPL 선별 경기: {len(validated_epl)}개")
    log(f"   - NBA 일정: {len(nba_data.get('schedule', []))}경기")
    log(f"   - 저장 시간: {get_kst_now().strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   - 파일: {SPORTS_FILE}")

# =============================================================================
# 엔트리 포인트
# =============================================================================
if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        log(f"❌ API Call Failed: {e}")
        log(f"\n❌ [Fatal Error] {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    update_sports_data()
