# Flagship Scene UI · 원본 커스텀노드판

**씬을 나누고, 클립을 만들고, 원하는 부분만 다시 생성하는 ComfyUI 영상 작업 UI입니다.**

이미지·비디오·오디오 참고와 클립별 프롬프트를 한 화면에서 관리합니다. LLM으로 작성한 계획 JSON을 불러오거나 직접 편집하고, 생성 결과를 미리보기·갤러리·씬 지도로 확인할 수 있습니다.

이 저장소는 **기존 ComfyUI 안에서 사용하는 원본 커스텀노드판**입니다. 대회용 SDK판은 별도 저장소에서 관리합니다.

## 다운로드와 시작 안내

- [최신 배포 파일](https://github.com/ych8836-ops/flagship-scene-ui-native/releases/latest): Source ZIP 또는 Full ZIP을 받습니다.
- Source에는 UI와 자체 작성 노드·어댑터가 있습니다. Full은 여기에 보호된 이미지 업스케일러 바이너리를 추가합니다.
- 두 패키지 모두 외부 커스텀노드·모델·LoRA·ComfyUI 본체는 별도 설치합니다.

- [기능별 한글 이미지 27종·사용 설명서](docs/사용설명서_KO.md)
- [설치 방법](INSTALL_KO.md) · [외부 노드 설치·출처](EXTERNAL_NODES.md)
- [모델·LoRA 링크](MODELS_AND_LINKS.md) · [제작·라이선스 출처](CREDITS.md)
- [LLM용 계획 JSON 작성 요청](docs/LLM_JSON_작성요청_KO.md) · [전체 프롬프트 규칙](PROMPT_RULES_SEQUENCE_KO.md)
- [시작 워크플로우](workflows/Flagship_Scene_UI_Native.json) · [2씬 4클립 계획](examples/Two_Scenes_Four_Clips_Plan.json)

## 작업 화면

상단은 참고 입력, 왼쪽은 프로젝트·생성 설정, 가운데는 미리보기·아웃풋, 오른쪽은 씬·클립 지도입니다. 지도에서 생성 상태와 이전 결과·재생성 결과를 확인합니다. 실제 실행 그래프는 **노드 보기**로 열 수 있습니다.

아래 그림은 기능을 설명하는 **한글 안내 도식**이며 실제 UI 스크린샷이나 생성 품질 비교 영상은 아닙니다.

![작업 공간과 패널](docs/images/01-workspace_ko.png)

## 계획 JSON으로 시작하기

1. [프롬프트 규칙](PROMPT_RULES_SEQUENCE_KO.md)과 [LLM 작성 요청](docs/LLM_JSON_작성요청_KO.md)을 작성 채팅에 전달합니다.
2. 이야기·등장인물·참고 파일 순서를 정하고 씬·클립별 프롬프트와 설정을 담은 계획 JSON을 만듭니다.
3. 스튜디오에서 **새 작업 → JSON 불러오기**를 선택합니다.
4. 실제 참고 파일과 모델을 연결하고 각 클립의 설정을 확인한 뒤 생성합니다.

**계획 JSON과 ComfyUI 워크플로우 JSON은 다릅니다.** 시작 워크플로우는 ComfyUI에 불러오고, 계획 JSON은 스튜디오 안에서 불러옵니다. 계획에는 미디어나 모델 파일이 내장되지 않습니다.

![계획 JSON 작성과 불러오기](docs/images/03-json-import_ko.png)

## 일반 모드와 시퀀스 모드

| 모드 | 계획 방식 | 사용 예 |
| --- | --- | --- |
| 일반 | 전체 클립을 하나의 연속 흐름으로 구성 | 한 장소에서 이어지는 대화·롱테이크 |
| 시퀀스 | 씬을 나누고 각 씬 안에 연결할 클립을 구성 | 장소·시간·카메라 구도가 바뀌는 이야기 |

시퀀스 모드에서는 새 씬이 기본적으로 새로 시작하고, 필요한 곳에서 앞 씬 연결을 선택합니다. 같은 동작이 이어지는 클립은 한 씬에 두고, 크게 바뀌는 장면은 새 씬으로 나눕니다.

![일반 모드와 시퀀스 모드](docs/images/04-normal-sequence_ko.png)

## 원하는 클립만 다시 생성

원래 프로젝트에서 클립 번호를 선택하고 프롬프트·참고·설정을 수정한 뒤 **클립 생성**을 실행합니다. 이전 결과는 이력으로 남으며 씬 지도와 갤러리에서 비교할 수 있습니다. **이 클립부터 재생성**은 선택한 번호 이후를 예약하는 별도 동작입니다.

한 클립을 수정한 결과가 뒤 클립과 자동으로 완벽하게 맞는 것은 아닙니다. 연결 상태를 확인하고 필요한 구간만 다시 생성합니다. 재생성 시에는 새 배경 이미지나 프로젝트 첫 클립을 배경 참고로 사용하는 옵션도 있습니다.

![선택 클립 재생성과 이전 결과](docs/images/15-regenerate_ko.png)

## 미리보기·갤러리·합치기·업스케일

갤러리에서 전체 프로젝트 또는 현재 프로젝트의 결과를 찾고, 즐겨찾기·다중 선택 삭제·저장소 열기를 사용할 수 있습니다. 대상 조건에 맞는 합본 영상은 **선택 영상 업스케일**로 따로 처리합니다.

시퀀스 모드의 합치기는 **씬 내부 Endless AV 연결 → 완성된 씬 사이 FFmpeg 연결** 순서입니다. 이 원본판의 일반 모드 최종 합치기는 FFmpeg이며, 생성 단계의 AV 컨텍스트 연결과 최종 파일 합치기는 구분합니다. FFmpeg 영상 연결은 스트림 복사를 사용하고, 오디오는 시간 정렬 과정에서 재인코딩될 수 있습니다.

업스케일 배율·색상·저장 품질과 모션 리페어·가변 프레임 보간은 해당 설정에서 선택합니다. NVIDIA 기능은 지원 환경과 별도 런타임이 필요합니다.

![업스케일과 저장 설정](docs/images/19-upscaling_ko.png)

## 카메라 디렉팅

R2V에서 참고 비디오를 넣고 **카메라 디렉팅**을 열어 샷·앵글·무빙·렌즈·포커스를 선택합니다. 비디오 구간별로 각도·줌·이동·속도를 설정하고 본 UI의 Generate로 실행합니다. 마우스 오버 애니메이션은 각 컨트롤의 의미를 설명합니다.

모드별로 생성·크롭·깊이 안내·선택 어댑터 경로가 다릅니다. 입력 영상에 따라 결과가 달라지며 큰 회전이나 립싱크 유지가 항상 보장되지는 않습니다.

![카메라 디렉팅](docs/images/23-camera-directing_ko.png)

## 기능별 한글 설명서

[27개 기능의 이미지와 사용법 전체 보기](docs/사용설명서_KO.md). 압축을 푼 뒤 `docs/안내이미지_모아보기.html`을 열면 안내 이미지를 모아 볼 수 있습니다.

| 작업 | 안내 |
| --- | --- |
| 프로젝트·계획 | [새 프로젝트](docs/사용설명서_KO.md#02-new-project) · [씬 구성](docs/사용설명서_KO.md#05-scene-plan) · [클립 편집·다중 선택](docs/사용설명서_KO.md#06-clip-editor) |
| 참고 입력 | [이미지와 @picture 규칙](docs/사용설명서_KO.md#07-image-routing) · [비디오·오디오](docs/사용설명서_KO.md#08-media-references) · [I2V 시작·끝 이미지](docs/사용설명서_KO.md#09-i2v-keyframes) |
| 생성 설정 | [립싱크](docs/사용설명서_KO.md#10-lipsync) · [해상도](docs/사용설명서_KO.md#11-resolution) · [모델·LoRA](docs/사용설명서_KO.md#12-models-loras) · [옵티마이저](docs/사용설명서_KO.md#13-optimizers) |
| 실행·검토 | [생성·예약](docs/사용설명서_KO.md#14-generate) · [씬 지도](docs/사용설명서_KO.md#16-scene-map) · [갤러리](docs/사용설명서_KO.md#17-gallery) · [합치기](docs/사용설명서_KO.md#18-assembly) |
| 보정·후처리 | [모션 리페어·보간](docs/사용설명서_KO.md#20-motion-repair) · [배경 참고 갱신](docs/사용설명서_KO.md#21-background-refresh) · [클립 리파이너](docs/사용설명서_KO.md#22-clip-refiner) |
| 카메라·UI | [구간별 카메라 설정](docs/사용설명서_KO.md#24-camera-segments) · [폰트·VRAM 리셋](docs/사용설명서_KO.md#25-settings-vram) · [노드 보기](docs/사용설명서_KO.md#26-view-nodes) |

## 배포 코드와 외부 의존성

**이 저장소와 ZIP은 우리 UI·직접 작성한 노드·연결 어댑터를 배포합니다.** 외부 커스텀노드의 원 구현은 별도 설치하며 저자와 설치 링크는 [외부 노드 안내](EXTERNAL_NODES.md)에 있습니다.

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

ComfyUI·Python·모델·LoRA·NVIDIA 런타임·개인 미디어는 포함하지 않습니다. UI용 Three.js·Noto 폰트는 커스텀노드가 아닌 UI 의존성으로 기존 라이선스를 보존합니다. 자체 코드는 AGPL-3.0-only, 기존 복원 소스는 인접 Apache-2.0 고지를 유지합니다.

## 검증 범위

설치 파일 무결성과 별도 의존성 어댑터 불러오기를 확인했습니다. 격리 환경의 전체 CPU 서버 시작 검사는 시간 초과되어 완료하지 못했으며, 이번 배포 정리로 모든 카메라·생성 모드의 GPU 출력 품질이 검증된 것은 아닙니다. 세부 기록은 [배포 검사](docs/DEPENDENCY_SEPARATION_CHECKS.json)와 [어댑터 검사](docs/ADAPTER_IMPORT_CHECKS.json)를 참고하세요.
