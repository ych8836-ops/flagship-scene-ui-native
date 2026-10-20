"""Read-only node/asset check. Does not submit a prompt or download a model."""
import argparse
import json
from urllib.request import urlopen
from urllib.error import URLError

FEATURES = {
    'studio': ['EndlessH3AllInOne', 'EndlessH3ProjectCommit', 'EndlessH3StitchScene', 'EndlessH3ConcatScenes'],
    'generation': ['MiniMaxH3ImageToVideo', 'MiniMaxH3ReferenceToVideo', 'SamplerCustomAdvanced',
                   'MiniMaxChunkFeedForward', 'EndlessV15MiniMaxH3MotionContext',
                   'EndlessV15MiniMaxH3MotionContextTrim', 'EndlessV15MiniMaxH3MotionContextLoadLatent',
                   'EndlessV15MiniMaxH3MotionContextSaveLatent'],
    'assembly': ['H3MotionContextClipStitcher -noEmbryo', 'H3ClipRefiner -noEmbryo'],
    'camera': ['H3R2VCameraTimeline', 'H3CameraExactAudioLock', 'H3CameraSegmentPreview',
               'H3FaceTrackCrop', 'H3InjectVideoLatent', 'H3FaceStitch', 'VHS_LoadVideoFFmpeg',
               'FlagshipPrepareCameraGeometry', 'FlagshipGeometryCamera', 'FlagshipMultiAngle',
               'FlagshipCameraLipRepairGuard', 'FlagshipCrossViewGuide', 'LoadMoGeModel',
               'MoGeInference', 'MiniMaxH3FunControlNetApply'],
    'video_upscale': ['RTXVideoVSRRestore'],
    'image_upscale': ['SRFPTypImageUpscaler'],
    'spectrum': ['SpectrumApplyMiniMaxH3'],
}


def check(base, features):
    base = base.rstrip('/')
    with urlopen(base + '/object_info', timeout=30) as response:
        registered = json.load(response)
    report = {'scope': 'node registration and frontend routes only; not GPU/model/quality verification',
              'features': {name: {'missing': sorted(set(FEATURES[name]) - set(registered))} for name in features},
              'assets': []}
    paths = ['/extensions/ComfyUI-Endless-H3-AllInOne/studio.js',
             '/extensions/ComfyUI-Endless-H3-AllInOne/camera_window.js',
             '/extensions/ComfyUI-H3-R2V-CameraLipLock/camera_dynamic_graph.js',
             '/extensions/ComfyUI-Endless-H3-AllInOne/fonts/NotoSansKR-variable.woff2',
             '/extensions/ComfyUI-Endless-H3-AllInOne/vendor/build/three.module.js',
             '/extensions/ComfyUI-Endless-H3-AllInOne/vendor/examples/jsm/environments/RoomEnvironment.js',
             '/h3r2v_camera_lip_lock/runtime_template']
    for path in paths:
        with urlopen(base + path, timeout=15) as response:
            body = response.read()
            assert response.status == 200 and body
            if path.endswith('camera_window.js'):
                assert b'import(cameraEngineURL())' in body and b"api.apiURL('/extensions/" not in body
            report['assets'].append({'path': path, 'status': response.status, 'bytes': len(body)})
    report['ready'] = not any(value['missing'] for value in report['features'].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    parser.add_argument('--features', nargs='+', choices=list(FEATURES), default=[name for name in FEATURES if name not in {'spectrum', 'image_upscale'}])
    args = parser.parse_args()
    try:
        result = check(args.url, args.features)
    except (OSError, ValueError, AssertionError, URLError) as error:
        result = {'ready': False, 'error': str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
