수앤수 학생 온라인 버전 v2 (사용자 분리)

접속 주소
- /yeop : 제공한 academy_data.json을 변환한 초기 데이터
- /yeom : 별도 빈 데이터
- /yeong : 별도 빈 데이터

각 주소는 서로 다른 서버 JSON 파일에 저장되므로 데이터가 섞이지 않습니다.
기본 비밀번호: 1234 (Render 환경변수 APP_PASSWORD로 변경 가능)

Render Persistent Disk 사용 시 Mount Path를 /opt/render/project/src/data 로 설정하고
환경변수 DATA_DIR=/opt/render/project/src/data 를 지정하세요.


V3 수정: academy_data.json을 온라인 표시 구조로 변환. 기존 빈 yeop 데이터는 첫 실행 시 자동 교체됩니다.
