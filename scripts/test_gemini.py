from google import genai
import os

print("📡 Gemini 연결 테스트 시작 (New SDK)...")

# 1. 키 확인
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("❌ 에러: GEMINI_API_KEY가 없습니다.")
    exit(1)

print("🔑 API Key 확인됨.")

# 2. 모델 연결 및 대화 시도 (새로운 방식)
try:
    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model="gemini-1.5-flash", 
        contents="Hello! Are you working?"
    )
    
    print(f"✅ 성공! Gemini 응답: {response.text}")
    print("🚀 모델명(gemini-1.5-flash) 설정 완료.")

except Exception as e:
    print(f"❌ 연결 실패: {e}")
    exit(1)
