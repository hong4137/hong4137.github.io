from google import genai
import os

print("📡 Gemini 2.5 Flash 연결 테스트...")

# 1. API 키 확인
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("❌ API Key가 없습니다.")
    exit(1)

# 2. 클라이언트 생성
try:
    client = genai.Client(api_key=api_key)
    print("✅ 클라이언트 생성 완료")
except Exception as e:
    print(f"❌ 클라이언트 생성 실패: {e}")
    exit(1)

# 3. 모델 호출 (gemini-2.5-flash)
target_model = "gemini-2.5-flash"

print(f"🚀 모델({target_model})에게 인사하는 중...")

try:
    response = client.models.generate_content(
        model=target_model, 
        contents="Hello! If you see this, just say 'Gemini 2.5 is Ready'."
    )
    
    print("-" * 30)
    print(f"🤖 응답: {response.text}")
    print("-" * 30)
    print("🎉 테스트 성공! 이 모델을 사용해도 안전합니다.")

except Exception as e:
    print("-" * 30)
    print(f"❌ 호출 실패: {e}")
    print("모델명이 리스트에는 있지만, 실제 호출 권한이나 파라미터가 다를 수 있습니다.")
    exit(1)
