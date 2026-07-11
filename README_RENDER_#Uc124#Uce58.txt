Render 배포 설정값

Repository 예시: sandsu-online
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: python app.py

수정 반영 내용:
- /yeop, /yeom, /yeong 주소별로 저장파일이 정확히 분리되도록 수정했습니다.
- 기존 HTML이 XMLHttpRequest로 /api/load, /api/save를 호출해도 자동으로 /api/선생/load, /api/선생/save로 변환됩니다.
- 저장 직전 기존 JSON을 backups/선생명 폴더에 백업하도록 보강했습니다.
- __pycache__ 제거, .gitignore 추가, Render Blueprint용 render.yaml 추가.

필수 설정 1: 비밀번호
Render Dashboard > Environment 에 아래 값을 추가하세요.

SANDSU_PASSWORD=원하는접속비밀번호
SANDSU_SECRET=아무거나긴문자열_예_32자이상

비밀번호를 안 넣으면 기본값은 1234입니다. 실제 운영 전에는 반드시 바꾸세요.

필수 설정 2: 데이터 유지용 Persistent Disk
Render Dashboard > Disks 에서 디스크를 추가하세요.

Mount Path 권장: /var/data

그리고 Environment 에 아래 값을 추가하세요.

SANDSU_DATA_DIR=/var/data

이 설정을 해야 재배포/재시작 후에도 yeop.json, yeom.json, yeong.json, backups 데이터가 유지됩니다.

접속 주소 예시:
https://서비스주소.onrender.com/yeop
https://서비스주소.onrender.com/yeom
https://서비스주소.onrender.com/yeong

로그인:
처음 접속하면 /login 으로 이동합니다.
Render 환경변수 SANDSU_PASSWORD 값으로 로그인합니다.

API:
GET  /api/yeop/load
POST /api/yeop/save
GET  /api/yeom/load
POST /api/yeom/save
GET  /api/yeong/load
POST /api/yeong/save

보안 적용 내용:
- /yeop, /yeom, /yeong 접속 전 로그인 필요
- 저장/불러오기 API 로그인 필요
- /api/shutdown 원격 비활성화 유지

주의:
- 같은 선생님 주소에 여러 명이 동시에 저장하면 마지막 저장이 덮어쓸 수 있습니다.
- Render 무료 인스턴스는 일정 시간 미사용 시 sleep 될 수 있습니다.
- 기존 PC 프로그램 자동 업로드/다운로드 연동은 다음 단계에서 별도 수정해야 합니다.
