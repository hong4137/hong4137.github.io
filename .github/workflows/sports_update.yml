name: Update Sports Data

on:
  schedule:
    - cron: '0 */6 * * *' # 6시간마다 실행
  workflow_dispatch: # 수동 실행 버튼

# [핵심] 권한 설정: 이 부분이 없어서 에러가 났던 것입니다.
permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install -r scripts/requirements.txt

    - name: Run update script
      run: |
        python scripts/update_sports.py

    - name: Commit and Push changes
      run: |
        git config --global user.name "GitHub Action Bot"
        git config --global user.email "action@github.com"
        git add sports.json
        # 변경사항이 없으면 에러 내지 않고 넘어감
        git diff --quiet && git diff --staged --quiet || (git commit -m "Auto-update sports data" && git push)
