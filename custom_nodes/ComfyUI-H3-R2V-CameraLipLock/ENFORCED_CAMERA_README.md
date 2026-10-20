# H3 R2V Camera — Enforced Camera v1

## 고친 문제

`source_audio_00005_.mp4`를 원본과 비교한 결과, H3가 영상 내용은 소폭 재생성했지만 3개 구간의 카메라 지시를 실제 구도에 반영하지 않았습니다. 프롬프트 지시만으로는 실패해도 감지하거나 보정하는 단계가 없었습니다.

새 워크플로우는 각 H3 구간의 디코드·트림 뒤에 `H3CameraReframe`을 연결합니다. 이 노드는 타임라인의 샷/이동/강도/중심값을 실제 픽셀 크롭 경로로 계산합니다. 세 구간은 강제 카메라 처리 후 조립되고, 기존 오디오와 SRFPTyp 2배 업스케일 단계는 그대로 유지됩니다.

## 보장되는 조작

- Wide / Medium / Medium Close-up / Close-up / Extreme Close-up
- Static / Zoom In / Zoom Out
- Pan Left / Pan Right
- Tilt Up / Tilt Down
- Smooth Tracking: 부드러운 좌우 슬라이더 이동
- `center_x`, `center_y`: 크롭 이동 범위 직접 지정

인물 세로 영상에서 중심값을 지정하지 않으면 Close-up 계열은 몸 중앙이 아니라 얼굴 쪽을 기본 중심으로 사용합니다.

## 정확한 한계

이 강제 단계는 원본에 없는 배경이나 얼굴의 뒷면을 생성하지 않습니다. 따라서 Orbit, 실제 High/Low angle, Rear/Top/Side novel view는 제공하지 않고 올인원 화면에서 숨깁니다. 이런 새 시점은 H3가 성공적으로 생성해야 하지만 현재 모델에서는 결과 보장이 되지 않습니다.

화면 안내가 `AI 생성 + 강제 카메라`로 표시되면 올바른 워크플로우입니다. H3 생성은 그대로 수행되며, 카메라만 후처리로 확실하게 반영됩니다.

## 파일

- `H3_R2V_Camera_Enforced_v1.json`: ComfyUI에서 불러올 워크플로우
- `Original_vs_Enforced_Camera.mp4`: 왼쪽 원본 / 오른쪽 실제 적용 결과
- `Camera_Control_Enforced_DEMO.mp4`: 적용 결과만 재생하는 736×1344 데모

검증 영상은 243프레임, 24fps, 10.125초이며 원본 오디오도 시작 0초·길이 10.125초로 유지했습니다.

## 실제 전체 워크플로우 검증

2026-09-05에 `H3_R2V_Camera_Enforced_v1.json`의 전체 경로를 ComfyUI에서 실행했습니다.

- H3 3구간 생성: 성공
- 강제 카메라 3구간: 각각 81프레임 처리 성공
- 구간 조립과 원본 오디오 연결: 성공
- SRFPTyp 2배 복원: 243/243프레임 성공
- 최종 저장: 1472×2688, 24fps, 243프레임, 10.125초
- 최종 오디오: AAC 32kHz, 시작 0초, 10.125초
- 전체 실행시간: 587.94초

카메라 로그 확인값:

- Close-up + Dolly In: 크롭 폭 `387.37 → 302.63`
- Medium + Tracking: 가로 시작점 `61.35 → 219.10`
- Wide + Tilt Up: 세로 시작점 `102.05 → 52.57`
