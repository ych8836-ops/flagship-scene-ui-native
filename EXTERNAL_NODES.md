# 외부 커스텀노드 · 별도 설치

아래 프로젝트의 구현은 이 저장소나 배포 ZIP에 **동봉하지 않습니다**. 원저장소의 출처와 라이선스를 따르며 사용자가 별도 설치합니다. 우리 코드는 해당 노드의 연결·UI·상태 관리를 담당합니다.

## 설치 링크와 용도

| 외부 프로젝트 | 설치 링크 | 사용하는 기능 | 설치 위치·방식 |
| --- | --- | --- | --- |
| noEmbryo | [원저장소·설치 안내](https://github.com/noembryo/ComfyUI-noEmbryo#readme) | Endless 합치기·클립 리파이너 | `ComfyUI/custom_nodes/ComfyUI-noEmbryo` |
| KJNodes | [원저장소·설치 안내](https://github.com/kijai/ComfyUI-KJNodes#readme) | Attention·메모리 분할 등 선택 최적화 | `ComfyUI/custom_nodes/comfyui-kjnodes` |
| VideoHelperSuite | [원저장소·설치 안내](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite#readme) | 참고 영상 로딩 | `ComfyUI/custom_nodes/comfyui-videohelpersuite` |
| H3-FaceRefine | [원저장소·설치 안내](https://github.com/Carasibana/ComfyUI-H3-FaceRefine#readme) | 선택 얼굴 추적·크롭·스티치 | `ComfyUI/custom_nodes/ComfyUI-H3-FaceRefine` |
| Spectrum | [원저장소·설치 안내](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3#readme) | Spectrum을 켤 때만 필요 | `ComfyUI/custom_nodes/ComfyUI-Spectrum-MiniMax-H3` |
| H3 Motion Context | [원저장소·설치 안내](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context#readme) | 앞 클립 AV 컨텍스트·저장/불러오기 | 이 배포의 어댑터용 파일은 아래 설치 도구로 `ComfyUI/flagship_dependencies/motion_context`에 배치 |
| CrossViewWarp | [원저장소·설치 안내](https://github.com/cseti007/ComfyUI-CrossViewWarp#readme) | 해당 카메라 모드의 깊이 기반 참고 생성 | 이 배포의 어댑터용 파일은 아래 설치 도구로 `ComfyUI/flagship_dependencies/crossview`에 배치 |

ComfyUI-Manager로 일반 팩을 설치하거나 각 원저장소의 설치 안내를 따릅니다. Motion Context·CrossView는 **전체 팩을 설치하는 것과 우리 어댑터가 읽는 연결 파일을 배치하는 것이 다릅니다.** 아래 도구를 쓰면 이 배포에 필요한 파일을 지정 경로에 배치합니다. 전체 원팩의 초기화 코드를 우리 배포에 복사하지 않습니다.

## 이 배포와 맞는 버전으로 별도 설치

원본 배포 패키지의 루트에서 실행합니다. ComfyUI 경로는 사용자 환경에 맞게 바꿉니다. `--comfy`를 생략하면 위치를 물어봅니다.

```powershell
# 먼저 설치 대상과 다운로드 출처만 확인
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera --dry-run

# 기본 연결·합치기와 카메라 의존성 설치
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features core camera

# Spectrum을 사용할 때만 별도 설치
python tools/install_external_nodes.py --comfy "D:\ComfyUI_portable\ComfyUI" --features spectrum
```

사용자가 실행할 때 원 출처에서 다운로드하고 SHA256을 확인합니다. 기존 다른 버전은 자동 덮어쓰지 않습니다. Python 패키지·모델은 이 도구가 설치하지 않으므로 각 외부 노드의 requirements와 모델 안내도 확인합니다. 모든 작업이 끝난 후 ComfyUI를 재시작합니다.

자세한 전체 순서는 [원본판 설치 안내](https://github.com/ych8836-ops/flagship-scene-ui-native/blob/main/INSTALL_KO.md)를 확인하세요.

## 고정 버전 출처

| 설치 그룹 | 프로젝트 | 원 출처 |
| --- | --- | --- |
| core | ComfyUI-noEmbryo | [원저장소](https://github.com/noembryo/ComfyUI-noEmbryo) · [고정 버전](https://github.com/noembryo/ComfyUI-noEmbryo/tree/4289beac758c836138d3eab560cefaa5dc0f6057) |
| core | comfyui-kjnodes | [원저장소](https://github.com/kijai/ComfyUI-KJNodes) · [고정 버전](https://github.com/kijai/ComfyUI-KJNodes/tree/3f20054214fec9f9234fd3841ae6f1e4287948f6) |
| core | comfyui-videohelpersuite | [원저장소](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) · [고정 버전](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite/tree/4d907bee61e92c2e65af3bd6383a4e4d356126d1) |
| camera | ComfyUI-H3-FaceRefine | [원저장소](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) · [고정 버전](https://github.com/Carasibana/ComfyUI-H3-FaceRefine/tree/79a97ce5ee4b393ce26313bd1280b706fe8b4f2c) |
| spectrum | ComfyUI-Spectrum-MiniMax-H3 | [원저장소](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3) · [고정 버전](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3/tree/9dc51b7fbb6e1c5208701ed3c8494801b4754097) |
| extra | ComfyUI-YCNodes-MiniMax-H3 | [원저장소](https://github.com/yichengup/ComfyUI-YCNodes-MiniMax-H3) · [고정 버전](https://github.com/yichengup/ComfyUI-YCNodes-MiniMax-H3/tree/efbe83f69ffa97a251a575ce42edc7bf8005da0c) |
| repair | comfyui_controlnet_aux | [원저장소](https://github.com/Fannovel16/comfyui_controlnet_aux) · [고정 버전](https://github.com/Fannovel16/comfyui_controlnet_aux/tree/a587a4c1594524c1d2de5cd1a86cd868ff448e1c) |

- Motion Context: [NikoDemon80](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context), 원 계산 구현은 별도 다운로드, 우리 팩에는 등록 어댑터만 있습니다.
- CrossViewWarp: [cseti007](https://github.com/cseti007/ComfyUI-CrossViewWarp), 해당 카메라 모드에서 필요한 원 구현을 별도 다운로드합니다.
- Endless v1.5 워크플로우 기반: [u/embryo10](https://www.reddit.com/r/comfyui/comments/1wt5oe9/endless_minimax_h3_with_endless_lipsync_v15_less/).

설치 명령은 INSTALL_KO.md를 확인합니다. 기존 외부 팩을 이미 설치했다면 중복 설치·무조건 덮어쓰기를 하지 않습니다. 해당 버전이 제공하는 노드 ID를 확인합니다. 외부 소스의 저자를 우리 것으로 표시하지 않습니다.

## FaceRefine 연동

ComfyUI-H3-FaceRefine의 얼굴 추적/크롭/스티치는 원저자의 구현입니다. 우리 ComfyUI-Flagship-Face-Adapters는 H3FacePresence와 ColorMatchLABChunked만 추가합니다. 외부 FaceRefine 파일을 바꿔 넣지 않습니다.

integrations/face_refine/compatibility.patch는 필요한 환경에서 InsightFace의 CPU 실행 공급자로 바꾸는 **우리 변경분**입니다. 원저자의 전체 소스가 아닙니다. 문제가 있는 환경에서 외부 노드 버전을 확인하고 백업 후 선택 적용합니다.
