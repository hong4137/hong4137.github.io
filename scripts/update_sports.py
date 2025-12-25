import datetime  # (파일 맨 위에 import datetime이 없다면 추가)

# ... (기존 코드들) ...

def update_sports_data():
    # 1. 날짜 범위 계산 (오늘 ~ 7일 뒤)
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=7)
    
    # 날짜를 문자열로 변환 (예: "2025-12-25", "2026-01-01")
    date_range_str = f"from {today} to {next_week}"

    # 2. 프롬프트에 날짜를 명시적으로 박아넣기
    # "현재"가 아니라 "이 기간 동안의" 경기를 찾으라고 지시함
    prompt = f"""
    Search for the match schedules for the following sports {date_range_str}:
    
    1. **English Premier League (EPL)**: Find matches scheduled {date_range_str}. Focus on Round 18 or upcoming Boxing Day matches.
    2. **Golden State Warriors (NBA)**: Find upcoming games {date_range_str}.
    3. **Carlos Alcaraz (Tennis)**: Find upcoming matches {date_range_str}.
    4. **Formula 1**: Find the next Grand Prix schedule.

    (아래는 기존의 JSON 포맷 요청 부분 그대로 유지...)
    Return the result ONLY in the following JSON format:
    ...
    """
    
    # ... (이후 Gemini 호출 로직) ...
