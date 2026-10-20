# Flagship Scene UI · 원본 커스텀노드판 · 2026-10-21

기존 ComfyUI 안에서 사용하는 원본 스튜디오입니다. 설치된 원본 실행 소스를 보존하는 독립 저장소입니다.

- **[기능별 한글 안내 이미지 27종 + 사용 설명서](docs/사용설명서_KO.md)**
- [이미지 모아보기 HTML](docs/안내이미지_모아보기.html) — 내려받은 뒤 브라우저에서 열기
- [English text manual](docs/MANUAL_EN.md)
- [설치](INSTALL_KO.md) · [모델·LoRA 링크](MODELS_AND_LINKS.md) · [출처](CREDITS.md)
- [LLM용 JSON 작성 요청](docs/LLM_JSON_작성요청_KO.md) · [상세 작성 규칙](PROMPT_RULES_SEQUENCE_KO.md)

![일반 모드와 시퀀스 모드](docs/images/04-normal-sequence_ko.png)

Git 소스판은 기본 9개 팩과 선택 Spectrum을 포함합니다. 보호된 이미지 업스케일러 바이너리는 제외합니다. 별도 전체 배포 ZIP에는 기존 Windows Python 3.12/3.13 바이너리가 고지되어 있으며 이를 오픈소스로 표시하지 않습니다.

| 모드 | 합치기 처리 |
| --- | --- |
| 원본 시퀀스 | 씬 안 Endless → 완성 씬 사이 FFmpeg |
| 원본 일반 | 생성은 컨텍스트 연속, 최종 MP4는 FFmpeg 연결 |

최종 FFmpeg 연결은 영상 스트림 복사이며 오디오는 길이 보정 후 재인코딩될 수 있습니다. Endless 조립에는 AV 아카이브가 필요합니다. 그림은 설명용 도식이며 모든 기능의 추론 성공 증거가 아닙니다. 이 문서 배포를 위해 설치된 원본 ComfyUI를 수정하지 않았습니다.

## Installation overview

Complete native custom-node installation package for an existing **H3-capable ComfyUI**. No previous Flagship installation or UI patch is required.

**Start with [INSTALL_KO.md](INSTALL_KO.md).** Run `Install.cmd` on Windows or `python install.py` and select your ComfyUI folder. The installer refuses to overwrite existing node folders. It does not install Python requirements or download weights.

- Original native UI/assets copied unchanged, including the camera module-path fix.
- 9 source node packs, with Spectrum available separately as an optional pack. Protected image-upscaler binaries are excluded from Git source.
- Clean startup workflow: `workflows/Flagship_Scene_UI_Native.json`.
- Scene-plan example: `examples/Two_Scenes_Four_Clips_Plan.json`.
- Prompt instructions: `PROMPT_RULES_SEQUENCE_KO.md`.
- Model/runtime prerequisites and download sources: `MODELS_AND_LINKS.md`.
- Upstream attribution and licensing: `CREDITS.md` and each node pack's notices.
- Read-only runtime check: `python check_installation.py --url http://127.0.0.1:8188`.

This package does **not** include ComfyUI itself, model weights, Python/torch, or NVIDIA proprietary runtimes. NVIDIA upscaling requires separate runtime installation. The native implementation and UI are preserved in this independent custom-node repository.

See `VALIDATION.json` for verification scope. Node registration and asset loading were checked in a separate CPU-started ComfyUI 0.38.1 / Python 3.13.9 environment; no new video inference or GPU upscaling benchmark was performed for this archive.
