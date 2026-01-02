#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sports.py - Sports Dashboard Data Updater
=================================================
EPL 경기 선별 시 6가지 룰을 "검색 후 검증" 방식으로 적용

[Rate Limit 대응]
- Gemini Free Tier: 분당 5회, 일일 1500회 제한
- API 호출 통합: 6회 → 3회로 줄임
- 호출 사이 15초 딜레이
- 429 에러 시 재시도 로직

[6가지 룰]
1. Big Match: Big 6 vs Big 6 (양쪽 모두 Big 6)
2. Top Tier: Top 4 vs Top 4 (양쪽 모두 Top 4)
3. Challenger: Top 4 vs Big 6 (한쪽 Top 4, 한쪽 Big 6)
4. Prime Time: 일요일 16:30 UK
5. Early KO: 토요일 12:30 UK
6. Leader: 리그 1위 팀 포함 경기

[타임존]
- UK (GMT/BST) → KST: +9시간 (겨울), +8시간 (여름 BST)
- PT → KST: +17시간
"""

import os
import json
import datetime
import traceback
import re
import sys
import time  # Rate Limit 대응용

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
MODEL_NAME = 'gemini-2.0-flash'  # Free Tier: 10 RPM, 1500 RPD (2.5-flash보다 훨씬 여유)

# Gemini Free Tier Rate Limit 대응
# gemini-2.0-flash: 10 RPM = 6초마다 1회 가능, 여유있게 8초
API_CALL_DELAY = 8

# Big 6는 고정값
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
# Rate Limit 대응 API 호출 래퍼
# =============================================================================
class RateLimitExceeded(Exception):
    """Rate Limit 초과 시 발생하는 예외 - 조용히 종료용"""
    pass

def call_gemini_api(client, prompt, tools):
    """
    Gemini API 호출 - Rate Limit 시 재시도 없이 바로 예외 발생
    (할당량 소진 시 다음 실행까지 기다림)
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(tools=tools)
        )
        return response
    except Exception as e:
        error_str = str(e)
        if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str:
            log(f"   ⚠️ Rate Limit 도달 - 다음 실행까지 대기합니다.")
            raise RateLimitExceeded("API 할당량 소진")
        else:
            raise e

# =============================================================================
# 타임존 변환 함수
# =============================================================================
def get_kst_now():
    """현재 한국 시간 반환"""
    return datetime.datetime.now(TZ_KST)

def convert_uk_to_kst(date_str, time_str):
    """UK 시간을 KST로 변환"""
    try:
        if '.' in date_str and len(date_str) <= 5:
            month, day = map(int, date_str.split('.'))
            year = get_kst_now().year
            if month < get_kst_now().month - 6:
                year += 1
        elif '-' in date_str:
            parts = date_str.split('-')
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return date_str, time_str, f"{date_str} {time_str}"
        
        time_str_clean = time_str.replace(' ', '').split('(')[0]
        if ':' in time_str_clean:
            hour, minute = map(int, time_str_clean.split(':'))
        else:
            return date_str, time_str, f"{date_str} {time_str}"
        
        uk_dt = datetime.datetime(year, month, day, hour, minute, tzinfo=TZ_UK)
        kst_dt = uk_dt.astimezone(TZ_KST)
        
        kst_date_str = kst_dt.strftime("%m.%d")
        kst_time_str = kst_dt.strftime("%H:%M")
        kst_full_str = f"{kst_date_str} {kst_time_str} (KST)"
        
        return kst_date_str, kst_time_str, kst_full_str
        
    except Exception as e:
        log(f"   ⚠️ UK→KST 변환 실패: {date_str} {time_str} - {e}")
        return date_str, time_str, f"{date_str} {time_str}"

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
def extract_json_content(text):
    """텍스트에서 JSON 부분만 추출"""
    text = text.strip()
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            return json.loads(text[start_idx : end_idx + 1])
        return json.loads(text)
    except json.JSONDecodeError:
        log(f"⚠️ JSON Parsing Failed. Text start: {text[:100]}...")
        return {}

def normalize_team_name(name):
    """팀 이름 정규화"""
    name = name.strip()
    return BIG_6_ALIASES.get(name, name)

def is_big_6(team_name):
    """Big 6 팀인지 확인"""
    normalized = normalize_team_name(team_name)
    return any(big in normalized for big in BIG_6)

# =============================================================================
# EPL 데이터 정규화
# =============================================================================
def normalize_epl_data(epl_list, top_4_teams, leader_team):
    """EPL 경기 데이터 정규화 및 룰 검증"""
    if not epl_list or not isinstance(epl_list, list):
        return []
    
    validated_matches = []
    
    for match in epl_list:
        home = match.get('home', '')
        away = match.get('away', '')
        
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
        
        home = normalize_team_name(home)
        away = normalize_team_name(away)
        
        kickoff_day = match.get('kickoff_day', '')
        kickoff_time_uk = match.get('kickoff_time_uk', '')
        match_date = match.get('date', '')
        
        matched_rules = []
        
        # 룰 1: Big Match (Big 6 vs Big 6)
        if is_big_6(home) and is_big_6(away):
            matched_rules.append("Rule1:Big6vsBig6")
        
        # 룰 2: Top Tier (Top 4 vs Top 4)
        home_in_top4 = any(home in t or t in home for t in top_4_teams)
        away_in_top4 = any(away in t or t in away for t in top_4_teams)
        if home_in_top4 and away_in_top4:
            matched_rules.append("Rule2:Top4vsTop4")
        
        # 룰 3: Challenger (Top 4 vs Big 6)
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
        
        if matched_rules:
            match['home'] = home
            match['away'] = away
            match['matched_rules'] = matched_rules
            
            if match_date and kickoff_time_uk:
                kst_date, kst_time, kst_full = convert_uk_to_kst(match_date, kickoff_time_uk)
                match['kst_time'] = kst_full
                match['local_time'] = f"{match_date} {kickoff_time_uk} (UK)"
            else:
                match['kst_time'] = match.get('time', 'TBD')
                match['local_time'] = f"{kickoff_day} {kickoff_time_uk}".strip() or ''
            
            match['channel'] = match.get('broadcaster') or match.get('channel') or 'UK TV'
            match['status'] = match.get('status') or 'Scheduled'
            
            validated_matches.append(match)
            log(f"   ✅ {home} vs {away} → {', '.join(matched_rules)}")
        else:
            log(f"   ❌ {home} vs {away} → 룰 미해당 (day={kickoff_day}, time={kickoff_time_uk})")
    
    return validated_matches[:7]

# =============================================================================
# NBA 데이터 정규화
# =============================================================================
NBA_OTT_CHANNELS = [
    'prime video', 'amazon prime', 'peacock', 'nba tv', 'nbatv', 
    'nba league pass', 'league pass', 'espn+', 'paramount+'
]
NBA_NATIONAL_TV = ['espn', 'abc', 'nbc', 'tnt']

def is_national_tv_broadcast(channel):
    """전국 TV 중계인지 확인"""
    if not channel:
        return False, None
    
    channel_lower = channel.lower()
    
    for ott in NBA_OTT_CHANNELS:
        if ott in channel_lower:
            return False, None
    
    for tv in NBA_NATIONAL_TV:
        if tv in channel_lower:
            if 'espn' in channel_lower and 'espn+' not in channel_lower:
                return True, 'ESPN'
            elif 'abc' in channel_lower:
                return True, 'ABC'
            elif 'nbc' in channel_lower and 'peacock' not in channel_lower:
                return True, 'NBC'
            elif 'tnt' in channel_lower:
                return True, 'TNT'
    
    return False, None

def normalize_nba_data(nba_data):
    """NBA 데이터 정규화"""
    if not nba_data:
        nba_data = {}
    
    nba_data['record'] = nba_data.get('record') or '-'
    nba_data['rank'] = nba_data.get('ranking') or nba_data.get('rank') or '-'
    
    if 'last' not in nba_data:
        nba_data['last'] = {'opp': '-', 'result': '-', 'score': '-'}
    else:
        last = nba_data['last']
        last['opp'] = last.get('opp') or last.get('opponent') or '-'
        last['result'] = last.get('result') or '-'
        last['score'] = last.get('score') or '-'
    
    if 'schedule' in nba_data and isinstance(nba_data['schedule'], list):
        normalized_schedule = []
        
        for game in nba_data['schedule']:
            opp = game.get('opp') or game.get('opponent') or 'TBD'
            location = game.get('location', 'home')
            if '@' in str(game.get('opp', '')) or '@' in str(game.get('teams', '')):
                location = 'away'
            
            date_str = game.get('date', '')
            time_str = game.get('time_pt', '') or game.get('time', '')
            
            if date_str and time_str:
                kst_date, kst_time, kst_full = convert_pst_to_kst(date_str, time_str)
                local_time = f"{date_str} {time_str} (PT)"
            else:
                kst_full = 'TBD'
                local_time = date_str or 'TBD'
            
            raw_channel = game.get('channel', '') or game.get('tv', '') or ''
            is_national, normalized_channel = is_national_tv_broadcast(raw_channel)
            
            normalized_game = {
                'opp': opp.replace('@', '').strip(),
                'location': location,
                'kst_time': kst_full,
                'local_time': local_time,
                'channel': normalized_channel if is_national else None,
                'raw_channel': raw_channel,
                'is_national_tv': is_national
            }
            
            normalized_schedule.append(normalized_game)
        
        nba_data['schedule'] = normalized_schedule[:6]
    else:
        nba_data['schedule'] = []
    
    return nba_data

# =============================================================================
# Tennis/F1 데이터 정규화
# =============================================================================
def normalize_tennis_data(tennis_data):
    if not tennis_data:
        tennis_data = {}
    
    tennis_data['status'] = tennis_data.get('status') or 'Off-Season'
    tennis_data['info'] = tennis_data.get('info') or tennis_data.get('tournament') or 'Next Tournament TBD'
    tennis_data['detail'] = tennis_data.get('detail') or tennis_data.get('round') or 'Check Schedule'
    tennis_data['time'] = tennis_data.get('time') or tennis_data.get('date') or ''
    
    return tennis_data

def normalize_f1_data(f1_data):
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

    client = genai.Client(api_key=api_key)
    
    kst_now = get_kst_now()
    today = kst_now.date()
    
    log(f"🚀 [Start] {kst_now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
    log(f"   Model: {MODEL_NAME}")
    log(f"   API Delay: {API_CALL_DELAY}s")
    
    # =========================================================================
    # STEP 1: EPL 순위 + 경기 일정 통합 검색
    # =========================================================================
    log("\n⚽ [Step 1/3] Premier League 순위 + 경기 일정...")
    
    epl_prompt = f"""
    Current Date: {today}
    
    Search for Premier League 2025-26 season:
    
    1. STANDINGS: Current 1st place team and Top 4 teams
    2. NEXT MATCHWEEK: All fixtures with UK kickoff times
    
    Return JSON:
    {{
        "leader": "1st place team",
        "top_4": ["1st", "2nd", "3rd", "4th"],
        "epl_round": "20",
        "epl": [
            {{
                "home": "Home Team",
                "away": "Away Team",
                "kickoff_day": "Saturday",
                "kickoff_time_uk": "12:30",
                "date": "01.04",
                "broadcaster": "Sky Sports"
            }}
        ]
    }}
    """
    
    try:
        epl_response = call_gemini_api(client, epl_prompt, [google_search_tool])
        epl_data = extract_json_content(epl_response.text)
        
        leader_team = epl_data.get('leader', 'Arsenal')
        top_4_teams = epl_data.get('top_4', ['Arsenal', 'Manchester City', 'Liverpool', 'Chelsea'])
        epl_round = epl_data.get('epl_round', 'R--')
        epl_matches = epl_data.get('epl', [])
        
        log(f"   ✅ Leader: {leader_team}, Top 4: {top_4_teams}")
        log(f"   ✅ Round: {epl_round}, 경기: {len(epl_matches)}개")
    except RateLimitExceeded:
        log("\n⏸️ [중단] Rate Limit - 기존 데이터 유지, 다음 실행 대기")
        return  # 조용히 종료
    except Exception as e:
        log(f"   ⚠️ EPL 검색 실패: {e}")
        leader_team = 'Arsenal'
        top_4_teams = ['Arsenal', 'Manchester City', 'Liverpool', 'Chelsea']
        epl_round = 'R--'
        epl_matches = []
    
    # 6가지 룰 적용
    log("\n   🎯 6가지 룰 적용...")
    validated_epl = normalize_epl_data(epl_matches, top_4_teams, leader_team)
    log(f"   ✅ 선별 경기: {len(validated_epl)}개")
    
    # Rate Limit 대기
    log(f"\n   ⏳ API 대기 ({API_CALL_DELAY}초)...")
    time.sleep(API_CALL_DELAY)
    
    # =========================================================================
    # STEP 2: NBA 통합 검색
    # =========================================================================
    log("\n🏀 [Step 2/3] NBA Warriors 전적 + 일정 + TV...")
    
    nba_prompt = f"""
    Current Date: {today}
    
    Search for Golden State Warriors:
    
    1. STATUS: Record (W-L), Conference ranking, last game result
    2. SCHEDULE: Next 6 games with date, time (PT), home/away, TV channel
    
    Return JSON:
    {{
        "record": "18-16",
        "rank": "8th West",
        "last": {{"opp": "Hornets", "result": "W", "score": "132-125"}},
        "schedule": [
            {{"opp": "Thunder", "date": "01.03", "time_pt": "19:30", "location": "home", "channel": "ESPN"}}
        ]
    }}
    """
    
    try:
        nba_response = call_gemini_api(client, nba_prompt, [google_search_tool])
        nba_data = extract_json_content(nba_response.text)
        log(f"   ✅ {nba_data.get('record', '-')} | {nba_data.get('rank', '-')}")
        log(f"   ✅ 일정: {len(nba_data.get('schedule', []))}경기")
    except RateLimitExceeded:
        log("\n⏸️ [중단] Rate Limit - 기존 데이터 유지, 다음 실행 대기")
        return  # 조용히 종료
    except Exception as e:
        log(f"   ⚠️ NBA 검색 실패: {e}")
        nba_data = {}
    
    nba_data = normalize_nba_data(nba_data)
    
    # TV 중계 필터링 로그
    if nba_data.get('schedule'):
        log("\n   📺 TV 필터링:")
        for g in nba_data['schedule']:
            icon = '✅' if g.get('is_national_tv') else '❌'
            ch = g.get('channel') or 'No National TV'
            log(f"      {icon} vs {g['opp']}: {ch} (원본: {g.get('raw_channel', '-')})")
    
    # Rate Limit 대기
    log(f"\n   ⏳ API 대기 ({API_CALL_DELAY}초)...")
    time.sleep(API_CALL_DELAY)
    
    # =========================================================================
    # STEP 3: Tennis + F1 통합 검색
    # =========================================================================
    log("\n🎾🏎️ [Step 3/3] Tennis + F1...")
    
    other_prompt = f"""
    Current Date: {today}
    
    Search for:
    1. CARLOS ALCARAZ: Current status, next tournament/match, date
    2. F1 2026: Next Grand Prix name, circuit, date
    
    Return JSON:
    {{
        "tennis": {{
            "status": "Exhibition",
            "info": "Exhibition Match vs Sinner",
            "detail": "Incheon, South Korea",
            "time": "01.10"
        }},
        "f1": {{
            "status": "Off-Season",
            "name": "Australian Grand Prix",
            "circuit": "Albert Park, Melbourne",
            "date": "03.14-03.16"
        }}
    }}
    """
    
    try:
        other_response = call_gemini_api(client, other_prompt, [google_search_tool])
        other_data = extract_json_content(other_response.text)
        
        tennis_data = other_data.get('tennis', {})
        f1_data = other_data.get('f1', {})
        
        log(f"   ✅ Tennis: {tennis_data.get('status', '-')} - {tennis_data.get('info', '-')}")
        log(f"   ✅ F1: {f1_data.get('name', '-')}")
    except RateLimitExceeded:
        log("\n⏸️ [중단] Rate Limit - 기존 데이터 유지, 다음 실행 대기")
        return  # 조용히 종료
    except Exception as e:
        log(f"   ⚠️ Tennis/F1 검색 실패: {e}")
        tennis_data = {}
        f1_data = {}
    
    tennis_data = normalize_tennis_data(tennis_data)
    f1_data = normalize_f1_data(f1_data)
    
    # =========================================================================
    # 최종 데이터 저장
    # =========================================================================
    log("\n💾 [Save] 데이터 저장...")
    
    if epl_round:
        nums = re.findall(r'\d+', str(epl_round))
        if nums:
            epl_round = f"R{nums[0]}"
    
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
    
    log(f"\n✅ [Complete]")
    log(f"   EPL: {len(validated_epl)}경기 | NBA: {len(nba_data.get('schedule', []))}경기")
    log(f"   파일: {SPORTS_FILE}")

# =============================================================================
# 엔트리 포인트
# =============================================================================
if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        log(f"\n❌ [Fatal Error] {e}")
        traceback.print_exc()
        sys.exit(1)
