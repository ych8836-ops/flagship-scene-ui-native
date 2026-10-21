# 원본판 설치 방법

## 1. 대상 ComfyUI 확인

H3를 지원하는 ComfyUI와 동작하는 Python/torch/CUDA를 먼저 준비합니다. 설치 도구는 main.py가 있는 폴더 또는 포터블 상위 폴더를 물어봅니다. 기존 설치를 무조건 덮어쓰지 않습니다.

## 2. 우리 노드 설치

Install.cmd를 실행하거나 아래 명령을 사용합니다. 기본 소스판은 우리 코드 6개 팩과 시작 워크플로우만 복사합니다.

```powershell
python install.py --comfy "D:\ComfyUI_portable\ComfyUI" --dry-run
python install.py --comfy "D:\ComfyUI_portable\ComfyUI"
```

Full ZIP의 이미지 업스케일러는 기존 보호 Windows Python 3.12/3.13 바이너리입니다. Full에도 외부 커스텀노드는 없습니다.

## 3. 외부 의존성 별도 설치

[EXTERNAL_NODES.md](EXTERNAL_NODES.md)의 출처를 확인합니다. 기본 생성·합치기는 core, 카메라/얼굴 보조는 camera를 사용합니다.

```powershell
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera --dry-run
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera
# Spectrum을 사용할 경우에만 별도 실행
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features spectrum
```

외부 소스는 사용자 실행 시 원저장소에서 받습니다. 고정 버전·다운로드 SHA256은 external_dependencies.lock.json에 있습니다. 대상에 다른 버전이 있으면 덮어쓰지 않습니다. --dry-run은 다운로드·파일 복사를 하지 않습니다. 이 단계는 원본 저장소 안에 외부 코드를 넣지 않고 선택한 ComfyUI에만 설치합니다.

Motion Context의 nodes/layout과 CrossView 계산 파일은 ComfyUI/flagship_dependencies에 별도 설치합니다. 전체 Motion Context 초기화 패치를 자동으로 실행하는 방식이 아니라 어댑터가 필요한 구현을 불러옵니다. noEmbryo·KJNodes·VideoHelperSuite·FaceRefine·선택 Spectrum은 선택 ComfyUI/custom_nodes에 원래 이름으로 설치됩니다.

## 4. Python·모델·런타임

선택한 ComfyUI가 실제 사용하는 Python으로 requirements-studio.txt와 설치한 외부 노드의 requirements를 확인·설치합니다. torch/CUDA를 이 설치 도구가 교체하지 않습니다.

```powershell
& "D:\ComfyUI_portable\python_embeded\python.exe" -m pip install -r requirements-studio.txt
```

[모델·LoRA 링크](MODELS_AND_LINKS.md)에서 가중치를 별도로 받아 실제 파일명을 UI에서 선택합니다. NVIDIA VFX/FRUC는 지원 기능에서만 별도 설치합니다. 새 시작 워크플로우는 캐시·업스케일·모션 리페어 OFF입니다.

## 5. 시작

ComfyUI를 시작하고 workflows/Flagship_Scene_UI_Native.json을 불러옵니다. 모델·인코더·비디오/오디오 VAE·Turbo 파일명을 확인합니다. 계획 예제는 UI 안의 JSON 불러오기로 가져옵니다. 자세한 설명은 [한글 사용 설명서](docs/사용설명서_KO.md)를 확인하세요.

설치 과정은 기존 생성 중인 ComfyUI를 자동 중단·재시작하지 않습니다. 사용자 실행 후 노드를 반영하려면 작업이 끝난 뒤 재시작합니다.
