# Flagship Scene UI · 원본 신규 설치본 · 2026-10-19

## 이 패키지의 범위

기존 Flagship 올인원 노드가 없는 ComfyUI에 설치하는 **원본 방식의 전체 노드 패키지**입니다. 기존 ComfyUI에 설치하는 전체 커스텀노드 패키지입니다. 기본 ComfyUI 엔진 자체, Python, torch/CUDA, 모델·LoRA, NVIDIA 런타임은 별도로 준비합니다.

현재 원본의 UI 파일을 수정 없이 복사했습니다. 브라운/그레이/민트 테마, 입력 레일, 설정·미리보기/아웃풋·씬 패널, 생성 컨트롤, 카메라 창, 폰트, 호버 애니메이션이 포함됩니다. 카메라 모듈 경로 오류 수정도 포함됩니다. 새 PC에 예전 올인원 파일을 먼저 설치하거나 부분 패치를 따로 적용할 필요가 없습니다.

## 1. 설치할 ComfyUI 폴더 선택

먼저 **어느 ComfyUI 폴더에 설치할지 확인**합니다. `main.py`와 `custom_nodes`가 있는 폴더입니다. 설치 도구가 위치를 물어보며 특정 드라이브를 가정하지 않습니다. 기존에 사용 중인 ComfyUI가 있다면 새 테스트 ComfyUI를 따로 준비해 설치하는 것을 권장합니다.

- MiniMax H3와 최신 VIDEO/ComfyExtension 노드를 지원하는 ComfyUI가 필요합니다.
- 현재 원본과 대조한 엔진은 ComfyUI 0.38.1 계열의 H3 지원 환경, Windows, Python 3.13입니다.
- 별도 전체 배포 ZIP의 이미지 업스케일러 바이너리는 Windows x64 Python 3.12/3.13용입니다. 전체 패키지의 실제 시작 검수 환경은 검증 보고서를 확인합니다. 다른 OS/Python에서 검증됐다는 의미가 아닙니다.

## 2. 노드 설치

압축을 작업 폴더에 풉니다. `Install.cmd`를 실행하고 설치할 ComfyUI 경로를 입력합니다. 또는 아래 명령을 사용합니다.

```powershell
python install.py --comfy "D:\ComfyUI_portable\ComfyUI"
```

`python`이 없는 포터블 환경에서는 그 포터블의 Python을 지정합니다.

```powershell
& "D:\ComfyUI_portable\python_embeded\python.exe" -B install.py --comfy "D:\ComfyUI_portable\ComfyUI"
```

- 설치 전 확인만 하려면 `--dry-run`을 추가합니다.
- 기본 설치는 `custom_nodes`의 9개 팩과 시작 워크플로우를 복사합니다.
- Spectrum도 설치하려면 `--with-spectrum`을 추가합니다. 기본 UI에서 캐시는 OFF인 상태로 시작합니다.
- 대상 노드 폴더가 이미 하나라도 있으면 사전 확인 단계에서 멈춥니다. 기존 설치본을 자동 덮어쓰거나 삭제하지 않습니다. 기존 노드가 있는 설치에는 직접 버전과 변경사항을 검토해 병합하거나 새로운 ComfyUI를 사용합니다.
- 설치 도구는 모델 다운로드, pip 설치, 서버 시작/중단, GPU 작업을 하지 않습니다.
- 수동 설치도 가능합니다. ComfyUI 종료 상태에서 이 패키지의 `custom_nodes` 안 폴더들을 해당 `ComfyUI/custom_nodes`로 복사합니다. 기존 폴더를 무조건 합쳐 덮어쓰지는 않습니다.

## 3. Python 의존성

**설치 대상 ComfyUI가 실제로 사용하는 Python**으로 실행합니다. 시스템 Python에 설치하고 Comfy Python에 설치됐다고 간주하지 않습니다.

```powershell
& "D:\ComfyUI_portable\python_embeded\python.exe" -m pip install -r requirements-studio.txt
```

torch와 CUDA는 정상 작동하는 ComfyUI 환경의 것을 사용합니다. 설치 도구는 이들을 교체하지 않습니다. 번들된 외부 노드의 자체 requirements도 함께 확인합니다.

- 기본 UI·일반 생성·합치기: ComfyUI/H3, PyAV, imageio-ffmpeg, KJNodes 관련 일반 의존성.
- 카메라 보조 처리: OpenCV, numpy, scipy, ultralytics.
- 일부 신원 매칭: InsightFace가 필요한 기능에서 별도로 설치. 단순 UI 표시를 위해 무조건 설치할 필요는 없습니다.
- SageAttention: 해당 GPU/torch/Python에 맞는 빌드가 있을 때 설치하고 켭니다. 시작 워크플로우는 별도 커널이 없는 새 환경을 고려해 Attention OFF입니다. 버튼과 원본 UI는 그대로 있습니다.
- 선택 음성 분석/립 복원: ctranslate2, tokenizers, openai-whisper와 로컬 faster-whisper-small 모델. 없을 때의 분기와 실제 립싱크 품질 검수는 구분합니다.

## 4. 모델과 NVIDIA 업스케일링

`MODELS_AND_LINKS.md`의 모델·LoRA를 해당 폴더에 직접 넣습니다. UI에서 설치된 실제 파일명을 선택합니다. 모델 파일을 예제 이름에 맞춰 임의로 바꾸지 않습니다.

비디오 업스케일 UI와 노드 구현은 포함되지만 NVIDIA VFX/FRUC 바이너리는 포함하지 않습니다. **노드가 목록에 보이는 것과 NVIDIA 런타임이 설치된 것은 별개**입니다.

NVIDIA VFX가 필요하면 공식 문서와 휠 링크를 확인한 뒤, 설치 대상 Comfy Python에 호환 런타임을 별도로 설치합니다. 원본 worker는 설치된 `nvvfx` 바인딩을 사용합니다. FRUC 모드를 쓸 때는 호환 `NvOFFRUC.dll`을 비디오 업스케일러 노드의 `runtime/NvOFFRUC.dll`에 직접 넣거나 `NVOFFRUC_DLL` 환경변수에 파일 경로를 설정합니다.

신규 시작 워크플로우는 업스케일 OFF, 모션 리페어 OFF입니다. 필요한 런타임을 설치한 뒤 켭니다. 이 파일의 초기 선택값은 기존 사용자의 프로젝트나 원본 Python 기본 설정을 바꾸지 않습니다.

## 5. 첫 실행

1. 선택한 ComfyUI를 시작합니다.
2. `workflows/Flagship_Scene_UI_Native.json`을 불러옵니다. 자동 설치했다면 사용자 워크플로우의 `FlagshipSceneUI` 폴더에도 있습니다.
3. 공통 설정에서 모델, 인코더, 두 VAE, Turbo LoRA의 실제 파일명을 선택합니다. 예제는 공식 일반 8-step Turbo 파일명을 사용하므로 다른 변형을 설치했다면 직접 맞춥니다.
4. 새 프로젝트를 만들고 I2V 시작 이미지/프롬프트 또는 R2V 참고 자료를 등록합니다. 프로젝트 ID와 참고 사진이 들어 있지 않은 깨끗한 시작 파일입니다.
5. 씬 구조를 익히려면 `examples/Two_Scenes_Four_Clips_Plan.json`을 계획 JSON으로 가져옵니다. 사람·음성·개인 참고가 없는 T2V 큐브 예제입니다. 이 파일은 Comfy 노드 워크플로우가 아니라 UI 안에서 불러오는 계획입니다.
6. 단계별로 클립 생성, 전체 생성, 합치기, 개별 재생성을 사용합니다. 시퀀스 모드에서는 씬 안 클립을 Endless로 처리하고 완성 씬을 FFmpeg로 연결합니다.
7. 자세한 프롬프트 형식은 `PROMPT_RULES_SEQUENCE_KO.md`를 작성 채팅에 제공하고 현재 계획 설정을 함께 전달합니다.

## 구성

| 구분 | 포함 팩 |
| --- | --- |
| 원본 UI와 프로젝트 관리 | ComfyUI-Endless-H3-AllInOne |
| Endless 연결 어댑터 | ComfyUI-Endless-H3-v15-Context |
| 카메라 타임라인 | ComfyUI-H3-R2V-CameraLipLock |
| 카메라 보조 처리 | ComfyUI-Flagship-Camera-Guide |
| 합치기·클립 리파이너 | ComfyUI-noEmbryo |
| H3 옵티마이저·유틸리티 | comfyui-kjnodes |
| 영상 로딩 | comfyui-videohelpersuite |
| 얼굴 처리 보조 | ComfyUI-H3-FaceRefine |
| 비디오 업스케일 | ComfyUI-RTX-Video-Restoration |
| 선택 이미지 업스케일 | Git 소스판 제외; 전체 ZIP의 기존 보호 바이너리 |
| 선택 캐시 | optional_custom_nodes/ComfyUI-Spectrum-MiniMax-H3 |

모든 카메라 모드에 모든 선택 모델이 필요한 것은 아닙니다. 추가 모드별 모델과 외부 노드 출처는 `MODELS_AND_LINKS.md`, `CREDITS.md`에서 확인합니다. ComfyUI를 통째로 다시 배포하거나 런타임·가중치까지 포함한 오프라인 완제품으로 설명하지 않습니다.


Git 소스판은 기본 9개 팩과 선택 Spectrum을 포함합니다. 보호된 이미지 업스케일 바이너리는 제외합니다. 별도 전체 배포 ZIP에는 기존 바이너리가 고지되어 있습니다.
