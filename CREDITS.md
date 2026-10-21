# 제작 코드와 외부 출처

## 이 저장소에서 배포하는 코드

Flagship Scene UI의 UI·프로젝트/씬/클립 관리, 카메라·시간축 연동, 업스케일 래퍼, 얼굴 유무 가드·분할 색상 처리와 외부 노드 등록 어댑터는 Flagship / ych8836-ops가 작성한 부분입니다. [저장소](https://github.com/ych8836-ops/flagship-scene-ui-native).

우리 어댑터를 원래 Motion Context·Endless·FaceRefine·CrossView 알고리즘 자체라고 주장하지 않습니다. 배포 팩별 구분은 BUNDLED_NODES.json에 있습니다. 보호 이미지 업스케일러는 Full ZIP의 기존 바이너리이며 공개 소스로 표시하지 않습니다.

## 외부 구현은 별도 설치

[EXTERNAL_NODES.md](EXTERNAL_NODES.md)에 저자·원저장소·설치 그룹이 있습니다. noEmbryo, KJNodes, VideoHelperSuite, H3-FaceRefine, Spectrum, Motion Context와 CrossView의 구현 소스를 이 배포에 넣지 않습니다. 외부 설치 도구는 사용자가 실행할 때 해당 출처에서 고정 버전을 가져옵니다.

- Endless MiniMax H3 v1.5 워크플로우: u/embryo10.
- Motion Context: NikoDemon80 및 기여자.
- Endless AV stitcher·clip refiner: noembryo 및 기여자.
- KJNodes: kijai 및 기여자.
- VideoHelperSuite: Kosinkadink 및 기여자.
- H3-FaceRefine: Carasibana 및 기여자.
- CrossViewWarp: cseti007 및 기여자.
- Spectrum: xmarre 및 기여자.

## UI 라이브러리·폰트

Three.js는 MIT, Noto Sans KR은 OFL 고지를 유지합니다. 이들은 UI 표시를 위한 라이브러리·폰트이며 다른 사람의 커스텀노드 팩을 동봉한 것이 아닙니다. 자체 코드는 루트 AGPL-3.0-only, 기존 비디오 복원 소스는 인접 Apache-2.0 LICENSE를 유지합니다. 외부 노드와 모델·NVIDIA 런타임은 각각 원저자의 조건을 따릅니다.

사용자 컴퓨터의 설치된 원본 ComfyUI와 대회용 앱을 이 배포 정리 과정에서 수정하지 않았습니다.
