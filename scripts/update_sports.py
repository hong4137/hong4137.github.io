import os
import json
import datetime
import traceback
import re
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 설정값
# ---------------------------------------------------------
SPORTS_FILE = 'sports.json'
MODEL_NAME = 'gemini-1.5-flash-latest'

def extract_json_content(text):
    """
    [복원된 핵심 기능]
    AI가 검색 과정을 거치며 잡담(텍스트)을 섞어서 답변하더라도,
    가장 바깥쪽 중괄호 {}를 찾아 순수 JSON 데이터만 도려냅니다.
    """
    text = text.strip()
    # 마크다운 코드블록 제거
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            # 잡담을 잘라내고 JSON 구간만 취함
            json_str = text[start_idx : end_idx + 1]
            return json.loads(json_str)
        else:
            return json.loads(text)
    except json.JSONDecodeError:
        # 파싱 실패 시 로그 확인을 위해 에러 던짐
        print(f"❌ JSON 추출 실패. 원본 텍스트 일부: {text[:200]}...")
        raise

def normalize_data(data):
    """
    [데이터 정규화]
    1. 검색된 데이터의 키(Key)를 대시보드 호환용으로 강제 통일
    2. 과거 스크린샷의 'NBA vs undefined' 오류 수정 포함
    """
    print("🔧 [Processing] 검색된 데이터 규격화(Normalization) 수행 중...")

    # 1. EPL 데이터 보정
    if 'epl' in data and isinstance(data['epl'], list):
        data['epl'] = data['epl'][:5] # 최대 5개

        for item in data['epl']:
            # match, teams, game, fixture 등 AI가 뭘 가져와도 다 잡음
            main_text = item.get('match') or item.get('teams') or item.get('game') or "Match Info"
            
            # 대시보드 호환성을 위해 양쪽 키 생성
            item['teams'] = main_text
            item['match'] = main_text
            item['time'] = item.get('time') or item.get('score') or "Scheduled"
            
            # 로고 표시용 (Home/Away 분리)
            if 'vs' in main_text and (not item.get('home') or not item.get('away')):
                try:
                    parts = main_text.split('vs')
                    item['home'] = parts[0].strip()
                    item['away'] = parts[1].strip()
                except: pass

    # 2. NBA 데이터 보정
    if 'nba' not in data: data['nba'] = {}
    nba = data['nba']
    nba['ranking'] = nba.get('ranking') or nba.get('rank') or "-"
    nba['record'] = nba.get('record') or "-"
    
    if 'schedule' in nba:
        # 문자열로 오면 리스트로 변환
        if isinstance(nba['schedule'], str):
            nba['schedule'] = [{"match": nba['schedule'], "time": ""}]
        
        if isinstance(nba['schedule'], list):
            nba['schedule'] = nba['schedule'][:4]
            for item in nba['schedule']:
                if isinstance(item, str): item = {"match": item, "time": ""}
                
                # [수정] 과거 'vs undefined' 원인 해결
                # AI가 'opponent'나 'team'으로 줄 경우를 대비해 모든 가능성 체크
                m_text = (item.get('match') or item.get('teams') or 
                          item.get('opponent') or "vs Opponent")
                
                # vs가 없으면 붙여줌 (가독성)
                if 'vs' not in m_text and '@' not in m_text:
                    m_text = f"vs {m_text}"

                item['match'] = m_text
                item['teams'] = m_text # 중요: 대시보드가 이 키를 참조함
                item['time'] = item.get('time') or item.get('date') or "TBD"

    # 3. 테니스/F1 보정 (데이터 증발 방지)
    if 'tennis' not in data: data['tennis'] = {}
    t = data['tennis']
    t['match'] = t.get('match') or t.get('tournament') or "No Match Found"
    t['time'] = t.get('time') or ""

    if 'f1' not in data: data['f1'] = {}
    f = data['f1']
    f['grand_prix'] = f.get('grand_prix') or "Next GP"
    f['time'] = f.get('time') or ""
    f['circuit'] = f.get('circuit') or ""

    return data

def update_sports_data():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ Error: GEMINI_API_KEY 환경 변수가 없습니다!")

    # [핵심 1] 구글 검색 도구 정의
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    print(f"🚀 [Start] Gemini API({MODEL_NAME}) + Google Search 호출...")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=1)
    end_date = today + datetime.timedelta(days=7)
    date_range_str = f"from {start_date} to {end_date}"
    
    print(f"📅 검색 기간: {date_range_str} (실제 웹 검색 수행)")

    prompt = f"""
    Current Date: {today}
    
    TASK: Use Google Search to find the OFFICIAL match schedules for the following sports between {date_range_str}.
    Do NOT use your internal knowledge cutoff. SEARCH for the real-time schedule.

    1. **EPL (Premier League)**: Find fixtures for this week (Round dates).
    2. **NBA**: Find Golden State Warriors schedule.
    3. **Tennis**: Find Carlos Alcaraz's next match or current tournament status.
    4. **F1**: Find the next scheduled Grand Prix date and location (2026 Season).

    Output Format:
    Return a valid JSON object.
    {{
        "epl": [ {{ "teams": "Home vs Away", "time": "MM.DD HH:MM" }} ],
        "nba": {{ "team": "GS Warriors", "record": "W-L", "ranking": "Rank", "schedule": [ {{ "teams": "vs Team", "time": "MM.DD HH:MM" }} ] }},
        "tennis": {{ "player": "Carlos Alcaraz", "match": "vs Opponent", "time": "MM.DD HH:MM" }},
        "f1": {{ "grand_prix": "Race Name", "time": "MM.DD HH:MM", "circuit": "Location" }}
    }}
    """

    client = genai.Client(api_key=api_key)
    
    try:
        # [핵심 2] JSON 강제 모드 해제 + 검색 도구 장착
        # response_mime_type을 뺐기 때문에 AI가 자유롭게 검색(Thinking)을 수행합니다.
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool], 
            )
        )
    except Exception as api_error:
        print(f"❌ API 호출 중 에러 발생: {api_error}")
        raise api_error

    if not response.text:
        raise ValueError("❌ API 응답이 비어있습니다!")

    try:
        # 1. 텍스트(잡담+JSON)에서 JSON만 추출
        data = extract_json_content(response.text)
        
        # 2. 데이터 규격화 (undefined 방지)
        data = normalize_data(data)
        
        # 3. 파일 저장
        with open(SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Success] {SPORTS_FILE} 업데이트 완료!")
        print(f"EPL Items: {len(data.get('epl', []))}")
        print(f"NBA Schedule: {len(data.get('nba', {}).get('schedule', []))}")

    except Exception as e:
        print("❌ 처리 중 에러 발생")
        # 디버깅을 위해 응답 내용 일부 출력
        # print(f"Raw Response: {response.text}") 
        traceback.print_exc()
        raise e

if __name__ == "__main__":
    try:
        update_sports_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        # GitHub Actions에서 실패로 처리되도록 exit code 1 반환
        exit(1)
