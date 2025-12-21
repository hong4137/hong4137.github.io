from google import genai
import os

print("📋 사용 가능한 모델 목록 조회 중...")

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("❌ API Key가 없습니다.")
    exit(1)

client = genai.Client(api_key=api_key)

try:
    # API에게 "내가 쓸 수 있는 모델 리스트 줘"라고 요청
    # pager를 통해 모든 모델을 순회
    pager = client.models.list()
    
    print("\n✅ [사용 가능한 모델 ID 목록]")
    print("=" * 40)
    
    count = 0
    for model in pager:
        # 우리가 필요한 건 '채팅/텍스트 생성'이 가능한 모델
        # 모델 이름(ID)과 설명 출력
        print(f"🔹 {model.name}") 
        # (참고: model.name은 보통 'models/gemini-1.5-flash' 형태로 나옵니다)
        count += 1

    print("=" * 40)
    print(f"총 {count}개의 모델이 감지되었습니다.")
    print("위 목록에 있는 이름(models/ 부분 제외)을 코드에 넣으면 100% 작동합니다.")

except Exception as e:
    print(f"❌ 조회 실패: {e}")
    # 혹시 라이브러리 호환성 문제일 경우를 대비한 추가 정보
    print("\n[Tip] SDK 버전에 따라 'models/list' 메서드 위치가 다를 수 있습니다.")
