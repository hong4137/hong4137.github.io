import google.generativeai as genai
import os

print("📡 Gemini 연결 테스트 시작...")

# 1. 키 확인
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("❌ 에러: GEMINI_API_KEY가 없습니다. GitHub Secrets를 확인하세요.")
    exit(1)

print("🔑 API Key 확인됨.")

# 2. 모델 연결 및 대화 시도
try:
    genai.configure(api_key=api_key)
    # 구글이 권장하는 최신 경량 모델
    model = genai.GenerativeModel('gemini-1.5-flash') 
    
    response = model.generate_content("Hello! Are you working?")
    
    print(f"✅ 성공! Gemini 응답: {response.text}")
    print("🚀 모델명(gemini-1.5-flash) 설정에 문제 없습니다.")

except Exception as e:
    print(f"❌ 연결 실패: {e}")
    exit(1)
