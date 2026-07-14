수앤수 학생 온라인 버전 V4

/yeop : 제공된 academy_data.json 기반 데이터(반 8개, 재원생 61명)
/yeom, /yeong : 사용자별 별도 데이터

수정 사항
- Render 저장 경로 권한/마운트 문제 자동 우회
- 기존 빈 yeop 파일 자동 판별 및 초기 데이터 강제 복구
- 브라우저가 빈 데이터를 받으면 자동 reset 후 재조회
- 화면 상단에 실제 동기화된 반/학생 수 표시
- /yeop/health에서 서버가 읽은 반/학생 수 확인 가능

GitHub 저장소 루트에 ZIP 내용을 전부 덮어쓴 뒤 Render에서 Manual Deploy > Clear build cache & deploy를 실행하세요.
기본 비밀번호: 1234
