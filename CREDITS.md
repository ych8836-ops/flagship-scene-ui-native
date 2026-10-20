# Sources and licenses

This is the native ComfyUI distribution of Flagship Scene UI. Installed native UI/assets and node implementations were preserved, with one publication portability correction: optional Spectrum VAE profiling writes its permission-error fallback report to the OS temporary directory instead of a developer-specific home path. Obsolete documentation was replaced with current manual links. File hashes are recorded in the package manifest. A clean startup workflow and installation tools are provided separately. The installed production ComfyUI was not modified.

## Flagship components

- Flagship Scene UI, project orchestration, sequence handling, camera adapters and restoration wrappers: ych8836-ops / Flagship. Project reference: <https://github.com/ych8836-ops/flagship-scene-ui-native>.
- The camera static-module URL correction from 2026-10-19 is included.
- The Git native tree excludes the protected image-upscaler binaries. The full native ZIP includes them as a separately disclosed optional component, not AGPL source.

## Community foundations bundled with their original notices

- Endless MiniMax H3 v1.5 workflow by u/embryo10: <https://www.reddit.com/r/comfyui/comments/1wt5oe9/endless_minimax_h3_with_endless_lipsync_v15_less/>
- Motion Context by NikoDemon80: <https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context>. The included Endless v1.5 registration wrapper assigns separate IDs; `UPSTREAM.md` and the original license are preserved.
- noEmbryo nodes, AV stitching and clip refiner: <https://github.com/noembryo/ComfyUI-noEmbryo>
- KJNodes by kijai: <https://github.com/kijai/ComfyUI-KJNodes>
- VideoHelperSuite by Kosinkadink: <https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite>
- H3-FaceRefine by Carasibana: <https://github.com/Carasibana/ComfyUI-H3-FaceRefine>. The bundled installed snapshot includes local compatibility/adaptor additions.
- Spectrum by xmarre: <https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3>. Included separately as an optional pack; not enabled by the startup workflow.
- CrossViewWarp by cseti007 and contributors: <https://github.com/cseti007/ComfyUI-CrossViewWarp>. The camera guide includes the upstream implementation under its adjacent Apache-2.0 LICENSE and NOTICE.
- Three.js: <https://github.com/mrdoob/three.js>. Local UI vendor assets retain their MIT notice.
- Noto Sans KR: <https://github.com/notofonts/noto-cjk>. Local font assets retain their OFL notice.

Optional additional helpers, when the selected restoration mode needs them:

- controlnet_aux by Fannovel16: <https://github.com/Fannovel16/comfyui_controlnet_aux>
- YCNodes by yichengup: <https://github.com/yichengup/ComfyUI-YCNodes-MiniMax-H3>

Every bundled third-party component retains its own license. The top-level AGPL-3.0 license for Flagship source does not relicense MIT/Apache/OFL/GPL components or NVIDIA proprietary runtimes. Models, LoRAs, NVIDIA runtime binaries, ComfyUI engine, user projects and personal media are not bundled. Refer to each model's own terms when installing weights.


Git 소스판은 기본 9개 팩과 선택 Spectrum을 포함합니다. 보호된 이미지 업스케일 바이너리는 제외합니다. 별도 전체 배포 ZIP에는 기존 바이너리가 고지되어 있습니다.
