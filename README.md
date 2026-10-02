# TokenTV

Mini 데몬 스캐폴드와 구현 계획은 [PLAN.md](PLAN.md)에 있다. 현재 응답은 **mock 데이터**이며 실제 계정 사용량을 조회하지 않는다.

Python 3.10+에서 실행:

```bash
python3 -m token_tv.app
curl http://127.0.0.1:8787/snapshot
curl http://127.0.0.1:8787/snapshot/claude_work
python3 -m unittest discover -s tests
```

기기에서 접근할 때는 Mini의 실제 LAN 인터페이스 주소로 바인드해야 한다. 확인한 주소를 `--host`에 넣어 실행한다. 기기 IP와 보드 모델 확인 전까지 테마 설치와 통신 검증은 보류한다.

```bash
python3 -m token_tv.app --host <mini-lan-ip> --port 8787
```

응답의 `status: "mock"`은 예시 수치임을 뜻한다. `/snapshot/<key>`는 smalltv-mod 테마 JSON source용이며, `/snapshot`은 전체 계정 점검용이다. 데몬에 자격 증명을 등록하거나 기기에 전송하는 기능은 아직 없다.

`/snapshot/claude_work` 응답 예시:

```json
{"alias":"Claude work","provider":"claude","status":"mock","session_percent":61,"session_reset_minutes":80,"weekly_percent":22,"weekly_reset_minutes":2400}
```
