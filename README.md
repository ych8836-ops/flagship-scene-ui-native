# Flagship Scene UI · 원본 커스텀노드판

기존 ComfyUI에서 사용하는 원본 스튜디오입니다. **이 저장소와 ZIP은 우리 UI·직접 작성한 노드·연결 어댑터만 배포합니다. 외부 커스텀노드는 동봉하지 않습니다.**

- [기능별 한글 이미지 27종·사용 설명서](docs/사용설명서_KO.md)
- [설치 방법](INSTALL_KO.md) · [외부 노드 설치·출처](EXTERNAL_NODES.md)
- [모델·LoRA 링크](MODELS_AND_LINKS.md) · [제작·라이선스 출처](CREDITS.md)
- [LLM용 계획 JSON 작성 요청](docs/LLM_JSON_작성요청_KO.md) · [전체 프롬프트 규칙](PROMPT_RULES_SEQUENCE_KO.md)
- [시작 워크플로우](workflows/Flagship_Scene_UI_Native.json) · [2씬 4클립 계획](examples/Two_Scenes_Four_Clips_Plan.json)

![일반 모드와 시퀀스 모드](docs/images/04-normal-sequence_ko.png)

## 포함하는 우리 코드

| 팩 | 역할 |
| --- | --- |
| ComfyUI-Endless-H3-AllInOne | UI·프로젝트·씬·클립 관리 |
| ComfyUI-Endless-H3-v15-Context | 별도 설치한 Motion Context에 연결하는 등록 어댑터만 |
| ComfyUI-H3-R2V-CameraLipLock | 카메라 타임라인·립싱크 연동 |
| ComfyUI-Flagship-Camera-Guide | 카메라·각도·기하 안내 어댑터 |
| ComfyUI-RTX-Video-Restoration | 비디오 복원·업스케일 래퍼 |
| ComfyUI-Flagship-Face-Adapters | 직접 작성한 얼굴 유무 가드·분할 색상 처리 |

Full ZIP은 여기에 기존 보호 이미지 업스케일러 바이너리만 추가합니다. 외부 노드를 더한 합본이 아닙니다. 보호 바이너리는 오픈소스 소스로 표시하지 않습니다.

## 설치 순서

1. H3를 지원하는 ComfyUI를 준비합니다.
2. 이 패키지의 Install.cmd를 실행하고 main.py가 있는 ComfyUI 폴더를 선택합니다. 우리 노드만 복사하며 기존 노드는 자동 덮어쓰지 않습니다.
3. 외부 노드는 아래 도구 또는 EXTERNAL_NODES.md의 출처에서 **별도 설치**합니다.
4. 해당 ComfyUI의 Python 의존성과 모델·LoRA를 준비하고 시작 워크플로우를 엽니다.

```powershell
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera --dry-run
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera
```

외부 설치 도구는 사용자가 실행할 때 공식 출처의 고정 버전을 다운로드·SHA256 검사합니다. 이 저장소에서 외부 구현을 다시 배포하는 방식이 아닙니다. 모델·Python 패키지는 자동 설치하지 않습니다. 이미 다른 외부 노드가 있으면 보존하고 수동 검토를 요청합니다.

시퀀스 모드는 씬 안 Endless → 씬 사이 FFmpeg, 일반 모드의 최종 합치기는 FFmpeg입니다. 영상은 스트림 복사, 오디오는 타이밍 보정 후 재인코딩될 수 있습니다.

ComfyUI·Python·모델·LoRA·NVIDIA 런타임·개인 미디어는 포함하지 않습니다. UI용 Three.js·Noto 폰트는 커스텀노드가 아닌 UI 의존성으로 기존 라이선스를 보존합니다. 자체 코드는 AGPL-3.0-only, 기존 복원 소스는 인접 Apache-2.0 고지를 유지합니다.
