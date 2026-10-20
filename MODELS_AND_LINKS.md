# 모델·LoRA·추가 의존성 링크

파일은 직접 받아 선택한 ComfyUI의 `models` 아래에 넣습니다. 이름과 양자화 변형을 실제 UI에서 선택합니다. 기본 설치 도구는 가중치나 런타임을 다운로드하지 않습니다.

| 용도 | 파일/폴더 | 출처 |
| --- | --- | --- |
| H3 기본 모델 | `diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors` | [공식 모델 저장소](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models) |
| 인코더 | `text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | [공식 인코더](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders) |
| 비디오 VAE | `vae/minimax_h3_video_vae_fp16.safetensors` | [공식 VAE](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae) |
| 오디오 VAE | `vae/minimax_h3_audio_vae_fp32.safetensors` | [공식 VAE](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae) |
| 8-step Turbo | `loras/minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | [공식 LoRA](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/loras) |
| FL2VA 참고 적응 LoRA | `loras/minimax/minimax_h3_ref_lora_layer20-49adaln_proj_rank_256_bf16.safetensors` | [morisoba](https://huggingface.co/morisoba/ComfyUI_extracted_lora/tree/main/minimax-h3) |

공식 Turbo는 동봉 시작 워크플로우가 선택한 파일입니다. 원본 Python에는 다른 rank 변형을 기본 이름으로 둔 부분이 있으므로, 파일을 이름만 바꿔 대체하지 말고 실제 설치한 변형을 UI에서 선택합니다. 카메라 독립 예제 일부는 nvfp4_awq 인코더 이름을 가지고 있으므로 그 경우에도 실제 설치한 인코더를 직접 지정합니다. 참고 적응 LoRA는 음성 LoRA가 아닙니다.

## 카메라 기능별 선택 모델

- MoGe 깊이 추정: <https://huggingface.co/Comfy-Org/MoGe> → `models/geometry_estimation`의 호환 파일.
- H3 Fun ControlNet: <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fun-controlnet> → 안내된 호환 `model_patches` 파일.
- CrossView adapter: <https://huggingface.co/Cseti/MiniMax-H3_Ref2VA-LoRA-CrossView-Warp_v1> → 현재 카메라 코드의 경로 `loras/minimax/flagship_camera/MiniMax-H3_Ref2VA-LoRA-CrossView-Warp_v1_3500.safetensors`.
- 지원 모션 adapter: <https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora> → 코드/파일 선택기에 맞는 `loras` 경로.
- 얼굴 검출 `face_yolov8m.pt`: <https://huggingface.co/Bingsu/adetailer> → `models/ultralytics/bbox`.
- 포즈/분할 `yolo11n-pose.pt`, `yolo11n-seg.pt`: <https://github.com/ultralytics/assets/releases/tag/v8.3.0> → `models/flagship_segmenters`.
- 선택 음성 분석: <https://huggingface.co/Systran/faster-whisper-small> → 저장소 파일 전체를 `models/whisper/faster-whisper-small`에 보관.

인물별 음성 LoRA는 필수 파일이 아니며 포함하지 않습니다. 세그먼트별 카메라 모드가 다르게 동작하므로 모든 모델이 모든 실행에서 사용된다고 설명하지 않습니다.

## NVIDIA 업스케일·모션 리페어 런타임

- NVIDIA VFX Python: <https://docs.nvidia.com/maxine/vfx-python/latest/index.html>
- 테스트에 사용된 Windows ABI3 휠: <https://pypi.nvidia.com/nvidia-vfx/nvidia_vfx-0.1.0.1-cp312-abi3-win_amd64.whl>
- Optical Flow / FRUC SDK: <https://developer.nvidia.com/opticalflow/download>

NVIDIA 배포 조건과 GPU/드라이버 요구사항을 확인하고 별도로 설치합니다. 바인딩은 선택한 Comfy Python에서 import 가능해야 합니다. FRUC 모드는 `NvOFFRUC.dll`을 따로 필요로 합니다. 패키지에는 NVIDIA SDK나 DLL이 포함되지 않습니다.

## 외부 노드 링크

핵심 외부 노드는 소스 스냅샷을 함께 포함하지만, 누락·재설치·출처 확인용 링크를 남깁니다.

- <https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context>
- <https://github.com/noembryo/ComfyUI-noEmbryo>
- <https://github.com/kijai/ComfyUI-KJNodes>
- <https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite>
- <https://github.com/Carasibana/ComfyUI-H3-FaceRefine>
- <https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3>
- <https://github.com/cseti007/ComfyUI-CrossViewWarp>
- 선택 복원 보조: <https://github.com/Fannovel16/comfyui_controlnet_aux>
- 선택 추가 H3 도구: <https://github.com/yichengup/ComfyUI-YCNodes-MiniMax-H3>

동봉 컨텍스트 어댑터의 `EndlessV15...` 노드명은 일반 Motion Context만 새로 설치했다고 생기는 이름이 아닙니다. 함께 제공된 어댑터를 유지합니다. 외부 저장소 최신본을 무조건 덮어쓰면 현재 스냅샷과 API가 달라질 수 있습니다.


Git 소스판은 기본 9개 팩과 선택 Spectrum을 포함합니다. 보호된 이미지 업스케일 바이너리는 제외합니다. 별도 전체 배포 ZIP에는 기존 바이너리가 고지되어 있습니다.
