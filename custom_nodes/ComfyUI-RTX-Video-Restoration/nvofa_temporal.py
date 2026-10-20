import ctypes
import logging
import os
import platform
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F


_LOG = logging.getLogger("ComfyUI-NVOFA-Temporal-Repair")
_ROOT = Path(__file__).resolve().parent


class TemporalRepairError(RuntimeError):
    pass


class _NV_OF_INIT_PARAMS(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("outGridSize", ctypes.c_int),
        ("hintGridSize", ctypes.c_int),
        ("mode", ctypes.c_int),
        ("perfLevel", ctypes.c_int),
        ("enableExternalHints", ctypes.c_int),
        ("enableOutputCost", ctypes.c_int),
        ("hPrivData", ctypes.c_void_p),
        ("disparityRange", ctypes.c_int),
        ("enableRoi", ctypes.c_int),
    ]


class _NV_OF_BUFFER_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("bufferUsage", ctypes.c_int),
        ("bufferFormat", ctypes.c_int),
    ]


class _NV_OF_EXECUTE_INPUT_PARAMS(ctypes.Structure):
    _fields_ = [
        ("inputFrame", ctypes.c_void_p),
        ("referenceFrame", ctypes.c_void_p),
        ("externalHints", ctypes.c_void_p),
        ("disableTemporalHints", ctypes.c_int),
        ("padding", ctypes.c_uint32),
        ("hPrivData", ctypes.c_void_p),
        ("padding2", ctypes.c_uint32),
        ("numRois", ctypes.c_uint32),
        ("roiData", ctypes.c_void_p),
    ]


class _NV_OF_EXECUTE_OUTPUT_PARAMS(ctypes.Structure):
    _fields_ = [
        ("outputBuffer", ctypes.c_void_p),
        ("outputCostBuffer", ctypes.c_void_p),
        ("hPrivData", ctypes.c_void_p),
    ]


class _NVOFA:
    """Small ctypes binding for the driver's public CUDA NVOF entry point."""

    API_VERSION = 0x20
    SUCCESS = 0
    MODE_OPTICAL_FLOW = 1
    PERF_FAST = 20
    PERF_MEDIUM = 10
    BUFFER_USAGE_INPUT = 1
    BUFFER_USAGE_OUTPUT = 2
    FORMAT_ABGR8 = 3
    FORMAT_SHORT2 = 5
    BUFFER_TYPE_CUDEVICEPTR = 2

    def __init__(self, width: int, height: int, grid: int, quality: str):
        if platform.system() != "Windows":
            raise TemporalRepairError("NVOFA is available only on Windows in this node.")
        dll = self._find_driver_dll()
        if dll is None:
            raise TemporalRepairError("NVIDIA Optical Flow driver DLL nvofapi64.dll was not found.")
        self.width = int(width)
        self.height = int(height)
        self.grid = int(grid)
        self._dll = ctypes.WinDLL(str(dll))
        self._cudart = self._load_cudart()
        self._handles = []
        self._load_api()
        self._create_session(quality)

    @staticmethod
    def _find_driver_dll() -> Optional[Path]:
        candidates = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvofapi64.dll",
            Path(__file__).resolve().parent / "nvofapi64.dll",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _load_cudart():
        candidates = [
            Path(torch.__file__).resolve().parent / "lib" / "cudart64_13.dll",
            Path(torch.__file__).resolve().parent / "lib" / "cudart64_12.dll",
        ]
        for candidate in candidates:
            if candidate.exists():
                lib = ctypes.WinDLL(str(candidate))
                lib.cudaMemcpyAsync.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                    ctypes.c_int, ctypes.c_void_p,
                ]
                lib.cudaMemcpyAsync.restype = ctypes.c_int
                return lib
        raise TemporalRepairError("PyTorch CUDA runtime cudart DLL was not found.")

    def _load_api(self):
        self._cu = ctypes.WinDLL("nvcuda.dll")
        self._cu.cuCtxGetCurrent.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._cu.cuCtxGetCurrent.restype = ctypes.c_int
        self._cu_context = ctypes.c_void_p()
        if self._cu.cuCtxGetCurrent(ctypes.byref(self._cu_context)) != 0 or not self._cu_context.value:
            raise TemporalRepairError("Could not obtain the active CUDA context.")

        functions = (ctypes.c_void_p * 12)()
        self._dll.NvOFAPICreateInstanceCuda.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        self._dll.NvOFAPICreateInstanceCuda.restype = ctypes.c_int
        status = self._dll.NvOFAPICreateInstanceCuda(self.API_VERSION, functions)
        if status != self.SUCCESS:
            raise TemporalRepairError(f"NvOFAPICreateInstanceCuda failed with status {status}.")
        self._fn = functions

        def winfun(restype, *args):
            return ctypes.WINFUNCTYPE(restype, *args)

        self._create = winfun(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(functions[0])
        self._init = winfun(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_NV_OF_INIT_PARAMS))(functions[1])
        self._create_buffer = winfun(
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_NV_OF_BUFFER_DESCRIPTOR),
            ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
        )(functions[2])
        self._get_device_ptr = winfun(ctypes.c_uint64, ctypes.c_void_p)(functions[4])
        self._set_streams = winfun(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64)(functions[6])
        self._execute = winfun(
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_NV_OF_EXECUTE_INPUT_PARAMS),
            ctypes.POINTER(_NV_OF_EXECUTE_OUTPUT_PARAMS),
        )(functions[7])
        self._destroy_buffer = winfun(ctypes.c_int, ctypes.c_void_p)(functions[8])
        self._destroy = winfun(ctypes.c_int, ctypes.c_void_p)(functions[9])

    def _create_session(self, quality: str):
        self._session = ctypes.c_void_p()
        status = self._create(self._cu_context, ctypes.byref(self._session))
        if status != self.SUCCESS:
            raise TemporalRepairError(f"nvCreateOpticalFlowCuda failed with status {status}.")
        perf = self.PERF_FAST if quality == "fast" else self.PERF_MEDIUM
        params = _NV_OF_INIT_PARAMS(
            self.width, self.height, self.grid, self.grid,
            self.MODE_OPTICAL_FLOW, perf, 0, 0, None, 0, 0,
        )
        status = self._init(self._session, ctypes.byref(params))
        if status != self.SUCCESS:
            self.close()
            raise TemporalRepairError(f"nvOFInit failed with status {status}.")

        input_desc = _NV_OF_BUFFER_DESCRIPTOR(self.width, self.height, self.BUFFER_USAGE_INPUT, self.FORMAT_ABGR8)
        output_desc = _NV_OF_BUFFER_DESCRIPTOR(
            (self.width + self.grid - 1) // self.grid,
            (self.height + self.grid - 1) // self.grid,
            self.BUFFER_USAGE_OUTPUT,
            self.FORMAT_SHORT2,
        )
        self._input_a = self._new_buffer(input_desc)
        self._input_b = self._new_buffer(input_desc)
        self._output = self._new_buffer(output_desc)
        self.out_width = int(output_desc.width)
        self.out_height = int(output_desc.height)

    def _new_buffer(self, desc):
        handle = ctypes.c_void_p()
        status = self._create_buffer(
            self._session, ctypes.byref(desc), self.BUFFER_TYPE_CUDEVICEPTR,
            ctypes.byref(handle),
        )
        if status != self.SUCCESS:
            self.close()
            raise TemporalRepairError(f"nvOFCreateGPUBufferCuda failed with status {status}.")
        self._handles.append(handle)
        return handle

    @staticmethod
    def _as_abgr(frame: torch.Tensor) -> torch.Tensor:
        rgb = frame[..., :3].clamp(0, 1)
        alpha = torch.ones((*rgb.shape[:-1], 1), device=rgb.device, dtype=rgb.dtype)
        rgba = torch.cat((alpha, rgb[..., 2:3], rgb[..., 1:2], rgb[..., 0:1]), dim=-1)
        return (rgba.mul(255).round().clamp(0, 255).to(torch.uint8).contiguous())

    def flow(self, input_frame: torch.Tensor, reference_frame: torch.Tensor) -> torch.Tensor:
        if input_frame.device.type != "cuda" or reference_frame.device.type != "cuda":
            raise TemporalRepairError("NVOFA requires CUDA input tensors.")
        a = self._as_abgr(input_frame)
        b = self._as_abgr(reference_frame)
        stream = int(torch.cuda.current_stream(input_frame.device).cuda_stream)
        memcpy_kind_device_to_device = 3
        for dst, src in ((self._get_device_ptr(self._input_a), a), (self._get_device_ptr(self._input_b), b)):
            status = self._cudart.cudaMemcpyAsync(
                ctypes.c_void_p(dst), ctypes.c_void_p(src.data_ptr()),
                ctypes.c_size_t(src.numel()), memcpy_kind_device_to_device,
                ctypes.c_void_p(stream),
            )
            if status != 0:
                raise TemporalRepairError(f"cudaMemcpyAsync failed with status {status}.")
        status = self._set_streams(self._session, stream, stream)
        if status != self.SUCCESS:
            raise TemporalRepairError(f"nvOFSetIOCudaStreams failed with status {status}.")
        execute_in = _NV_OF_EXECUTE_INPUT_PARAMS(
            self._input_a, self._input_b, None, 0, 0, None, 0, 0, None,
        )
        execute_out = _NV_OF_EXECUTE_OUTPUT_PARAMS(self._output, None, None)
        status = self._execute(self._session, ctypes.byref(execute_in), ctypes.byref(execute_out))
        if status != self.SUCCESS:
            raise TemporalRepairError(f"nvOFExecute failed with status {status}.")
        torch.cuda.synchronize(input_frame.device)
        result = torch.empty(
            (self.out_height, self.out_width, 2),
            device=input_frame.device, dtype=torch.int16,
        )
        status = self._cudart.cudaMemcpyAsync(
            ctypes.c_void_p(result.data_ptr()),
            ctypes.c_void_p(self._get_device_ptr(self._output)),
            ctypes.c_size_t(result.numel() * result.element_size()),
            memcpy_kind_device_to_device, ctypes.c_void_p(stream),
        )
        if status != 0:
            raise TemporalRepairError(f"cudaMemcpyAsync output failed with status {status}.")
        torch.cuda.synchronize(input_frame.device)
        return result.to(torch.float32).div_(32.0)

    def close(self):
        for handle in reversed(getattr(self, "_handles", [])):
            try:
                self._destroy_buffer(handle)
            except Exception:
                pass
        self._handles = []
        if getattr(self, "_session", None):
            try:
                self._destroy(self._session)
            except Exception:
                pass
            self._session = None

    def __del__(self):
        self.close()


_NVOFA_SESSIONS = {}


def _nvofa_flow(a, b, grid, quality):
    key = (a.device.index or 0, int(a.shape[-2]), int(a.shape[-3]), int(grid), quality)
    session = _NVOFA_SESSIONS.get(key)
    if session is None:
        session = _NVOFA(int(a.shape[-2]), int(a.shape[-3]), int(grid), quality)
        _NVOFA_SESSIONS[key] = session
    return session.flow(a, b)


def _gray(frame):
    return frame[..., :3].mul(torch.tensor([0.299, 0.587, 0.114], device=frame.device, dtype=frame.dtype)).sum(-1)


def _analysis_frames(frames, max_side=960):
    b, h, w, _ = frames.shape
    scale = min(1.0, float(max_side) / max(h, w))
    ah = max(32, int(round(h * scale / 8.0) * 8))
    aw = max(32, int(round(w * scale / 8.0) * 8))
    x = frames[..., :3].permute(0, 3, 1, 2)
    if (ah, aw) != (h, w):
        x = F.interpolate(x, size=(ah, aw), mode="bilinear", align_corners=False)
    return x.permute(0, 2, 3, 1).contiguous(), ah, aw


def _cpu_flow(a, b, quality):
    a_np = a.detach().float().cpu().numpy()
    b_np = b.detach().float().cpu().numpy()
    ga = cv2.cvtColor((a_np.clip(0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gb = cv2.cvtColor((b_np.clip(0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    if quality == "fast":
        flow = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 2, 13, 2, 5, 1.1, 0)
    elif hasattr(cv2, "DISOpticalFlow_create"):
        preset = cv2.DISOPTICAL_FLOW_PRESET_MEDIUM if quality == "balanced" else cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST
        dis = cv2.DISOpticalFlow_create(preset)
        dis.setVariationalRefinementIterations(1 if quality == "balanced" else 0)
        flow = dis.calc(ga, gb, None)
    else:
        flow = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 3, 21, 3, 7, 1.3, 0)
    return torch.from_numpy(flow).to(device=a.device, dtype=torch.float32)


def _flow_to_output(flow, out_h, out_w, analysis_h, analysis_w):
    x = flow.permute(2, 0, 1).unsqueeze(0)
    x = F.interpolate(x, size=(out_h, out_w), mode="bilinear", align_corners=True)[0].permute(1, 2, 0)
    x[..., 0].mul_(float(out_w) / float(analysis_w))
    x[..., 1].mul_(float(out_h) / float(analysis_h))
    return x


def _warp(frame, flow, return_valid=False):
    h, w = frame.shape[-3], frame.shape[-2]
    yy, xx = torch.meshgrid(
        torch.arange(h, device=frame.device, dtype=torch.float32),
        torch.arange(w, device=frame.device, dtype=torch.float32), indexing="ij",
    )
    gx = (xx + flow[..., 0]).mul(2.0 / max(1, w - 1)).sub(1.0)
    gy = (yy + flow[..., 1]).mul(2.0 / max(1, h - 1)).sub(1.0)
    grid = torch.stack((gx, gy), dim=-1).unsqueeze(0)
    src = frame[..., :3].permute(2, 0, 1).unsqueeze(0)
    warped = F.grid_sample(
        src, grid, mode="bilinear", padding_mode="border", align_corners=True
    )[0].permute(1, 2, 0)
    if not return_valid:
        return warped

    # Optical-flow samples outside the real neighbouring frame repeat border
    # pixels. Never blend those synthetic samples into the result: on moving
    # silhouettes they can appear as a one-frame black line.
    margin_x = 2.0 / max(1, w - 1)
    margin_y = 2.0 / max(1, h - 1)
    valid = (
        (gx >= -1.0 + margin_x)
        & (gx <= 1.0 - margin_x)
        & (gy >= -1.0 + margin_y)
        & (gy <= 1.0 - margin_y)
    )
    return warped, valid.to(dtype=frame.dtype)


def _edge_map(frame):
    x = frame[..., :3].mean(-1)
    dx = x[:, 1:] - x[:, :-1]
    dy = x[1:] - x[:-1]
    edge = torch.zeros_like(x)
    edge[:, 1:] += dx.abs()
    edge[1:] += dy.abs()
    return edge.clamp(0, 1)


def _flow_boundary_map(flow):
    """Return motion-vector discontinuities where foreground/background split."""
    dx = (flow[:, 1:] - flow[:, :-1]).square().sum(-1).sqrt()
    dy = (flow[1:] - flow[:-1]).square().sum(-1).sqrt()
    boundary = torch.zeros_like(flow[..., 0])
    boundary[:, 1:] = torch.maximum(boundary[:, 1:], dx)
    boundary[1:] = torch.maximum(boundary[1:], dy)
    return F.max_pool2d(boundary[None, None], kernel_size=5, stride=1, padding=2)[0, 0]


class NVOFATemporalArtifactRepair:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "enabled": ("BOOLEAN", {"default": True}),
                "backend": (["auto", "nvofa", "cpu"], {"default": "auto"}),
                "flow_quality": (["fast", "balanced", "quality"], {"default": "balanced"}),
                "flow_grid": (["4x4", "2x2"], {"default": "4x4"}),
                "repair_strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
                "artifact_sensitivity": ("FLOAT", {"default": 0.55, "min": 0.1, "max": 1.0, "step": 0.05}),
                "motion_guard": ("FLOAT", {"default": 0.75, "min": 0.1, "max": 1.0, "step": 0.05}),
                "scene_cut_threshold": ("FLOAT", {"default": 0.22, "min": 0.05, "max": 1.0, "step": 0.01}),
                "max_repair_ratio": ("FLOAT", {"default": 0.18, "min": 0.01, "max": 1.0, "step": 0.01}),
                "analysis_max_side": ("INT", {"default": 960, "min": 256, "max": 2048, "step": 64}),
            },
            "optional": {
                "source_images": ("IMAGE",),
                "candidate_images": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "status")
    FUNCTION = "repair"
    CATEGORY = "video/temporal restoration"
    DESCRIPTION = (
        "Uses a three-frame temporal window. NVOFA estimates motion between the "
        "current frame and its actual neighbors, then only blends small regions "
        "whose warped neighbors agree and whose current result disagrees. "
        "Scene cuts and unreliable high-motion regions are protected."
    )

    def repair(
        self, images, enabled=True, backend="auto", flow_quality="balanced",
        flow_grid="4x4", repair_strength=0.35, artifact_sensitivity=0.55,
        motion_guard=0.75, scene_cut_threshold=0.22, max_repair_ratio=0.18,
        analysis_max_side=960, source_images=None, candidate_images=None,
        region_prior=None,
    ):
        if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] < 3:
            raise TemporalRepairError("Expected IMAGE tensor with shape [frames, height, width, channels].")
        if not enabled or int(images.shape[0]) < 3:
            return (images, "disabled or fewer than 3 frames; no temporal repair applied")

        work = images[..., :3]
        source = source_images if isinstance(source_images, torch.Tensor) and source_images.ndim == 4 else work
        candidates = (
            candidate_images[..., :3]
            if isinstance(candidate_images, torch.Tensor) and candidate_images.ndim == 4
            else None
        )
        semantic_prior = None
        if isinstance(region_prior, torch.Tensor):
            semantic_prior = region_prior.to(device=work.device, dtype=work.dtype)
            if semantic_prior.ndim == 2:
                semantic_prior = semantic_prior.unsqueeze(0).expand(int(work.shape[0]), -1, -1)
            elif semantic_prior.ndim == 4 and semantic_prior.shape[-1] == 1:
                semantic_prior = semantic_prior[..., 0]
            if semantic_prior.ndim != 3:
                semantic_prior = None
        count = min(int(work.shape[0]), int(source.shape[0]))
        if candidates is not None:
            count = min(count, int(candidates.shape[0]))
        work = work[:count]
        source = source[:count]
        source_a, ah, aw = _analysis_frames(source, int(analysis_max_side))
        source_gray = _gray(source_a)
        out = work.clone()
        grid = int(str(flow_grid).split("x")[0])
        nvofa_errors = []
        use_nvofa = backend in ("auto", "nvofa")
        nvofa_used = False
        flow_cache = {}

        def get_flow(i, j):
            key = (i, j)
            if key in flow_cache:
                return flow_cache[key]
            a, b = source_a[i], source_a[j]
            flow = None
            if use_nvofa and a.device.type == "cuda":
                try:
                    flow = _nvofa_flow(a, b, grid, flow_quality)
                    nonlocal_nvofa[0] = True
                except Exception as exc:
                    nvofa_errors.append(str(exc))
                    if backend == "nvofa":
                        raise
            if flow is None:
                flow = _cpu_flow(a, b, flow_quality)
            flow_cache[key] = flow
            return flow

        nonlocal_nvofa = [False]
        for i in range(1, count - 1):
            prev_flow = get_flow(i, i - 1)
            next_flow = get_flow(i, i + 1)
            prev_flow = _flow_to_output(prev_flow, work.shape[1], work.shape[2], ah, aw).to(work.device)
            next_flow = _flow_to_output(next_flow, work.shape[1], work.shape[2], ah, aw).to(work.device)
            prev_warp, prev_valid = _warp(work[i - 1], prev_flow, return_valid=True)
            next_warp, next_valid = _warp(work[i + 1], next_flow, return_valid=True)
            current = work[i]
            neighbor_agreement = (prev_warp - next_warp).abs().mean(-1)
            current_disagreement = (current - (prev_warp + next_warp) * 0.5).abs().mean(-1)
            current_chroma = current - current.mean(-1, keepdim=True)
            neighbor_chroma = (prev_warp + next_warp) * 0.5
            neighbor_chroma = neighbor_chroma - neighbor_chroma.mean(-1, keepdim=True)
            chroma_disagreement = (current_chroma - neighbor_chroma).abs().mean(-1)
            motion = 0.5 * (prev_flow.square().sum(-1).sqrt() + next_flow.square().sum(-1).sqrt())
            flow_boundary = torch.maximum(
                _flow_boundary_map(prev_flow),
                _flow_boundary_map(next_flow),
            )
            motion_scale = max(2.0, min(work.shape[1], work.shape[2]) * 0.08)
            motion_conf = torch.exp(-((motion / (motion_scale * max(0.1, float(motion_guard)))) ** 2))
            # Optical-flow vectors split abruptly at moving silhouettes.  Those
            # pixels are disocclusions, not damaged detail, and borrowing either
            # neighbour creates black/white strokes around fast limbs.
            boundary_limit = 0.75 + motion * 0.035
            boundary_conf = torch.exp(-((flow_boundary / boundary_limit.clamp_min(0.75)) ** 2))
            cut_prev = (source_gray[i] - source_gray[i - 1]).abs().mean()
            cut_next = (source_gray[i] - source_gray[i + 1]).abs().mean()
            cut_guard = float(cut_prev <= scene_cut_threshold and cut_next <= scene_cut_threshold)
            if not cut_guard:
                continue
            # A local explosion or muzzle flash can occupy only a few percent
            # of the frame, so a scene-cut score alone does not catch it.  If a
            # sizeable bright region appears only in the current frame together
            # with a real exposure lift, preserve the complete action frame.
            # This keeps impact timing and avoids repairing unrelated faces or
            # limbs while the flash changes the optical-flow solution.
            current_luma = _gray(current)
            if candidates is not None:
                temporal_bright_reference = torch.maximum(
                    _gray(prev_warp), _gray(next_warp)
                )
                flash_area = (
                    (current_luma > 0.68)
                    & ((current_luma - temporal_bright_reference) > 0.12)
                ).float().mean()
                exposure_lift = current_luma.mean() - 0.5 * (
                    _gray(prev_warp).mean() + _gray(next_warp).mean()
                )
                if float(flash_area) > 0.035 and float(exposure_lift) > 0.008:
                    continue
            agreement = torch.exp(-neighbor_agreement / max(0.01, 0.08 * (1.0 - artifact_sensitivity + 0.25)))
            prior = None
            if semantic_prior is not None and i < semantic_prior.shape[0]:
                prior = semantic_prior[i]
                if prior.shape != current_luma.shape:
                    prior = F.interpolate(
                        prior[None, None], size=current_luma.shape,
                        mode="bilinear", align_corners=False,
                    )[0, 0]
            if candidates is not None:
                candidate = candidates[i].to(device=work.device, dtype=work.dtype)
                candidate_disagreement = (current - candidate).abs().mean(-1)
                candidate_chroma = candidate - candidate.mean(-1, keepdim=True)
                candidate_chroma_disagreement = (
                    current_chroma - candidate_chroma
                ).abs().mean(-1)
                edge_gain = (_edge_map(candidate) - _edge_map(current)).clamp_min(0)
                current_temporal_error = 0.5 * (
                    (current - prev_warp).abs().mean(-1)
                    + (current - next_warp).abs().mean(-1)
                )
                candidate_temporal_error = 0.5 * (
                    (candidate - prev_warp).abs().mean(-1)
                    + (candidate - next_warp).abs().mean(-1)
                )
                quality_gain = current_temporal_error - candidate_temporal_error
                quality_gain = F.avg_pool2d(
                    quality_gain[None, None], kernel_size=5, stride=1, padding=2
                )[0, 0]
                gain_scale = torch.quantile(quality_gain.abs().flatten(), 0.90).clamp_min(2.0 / 255.0)
                normalized_gain = (quality_gain / gain_scale).clamp(0, 1)
                quality_win = torch.where(
                    quality_gain > 0,
                    0.25 + 0.75 * normalized_gain,
                    torch.zeros_like(normalized_gain),
                )
                quality_win = F.max_pool2d(
                    quality_win[None, None], kernel_size=9, stride=1, padding=4
                )[0, 0]

                candidate_edge = _edge_map(candidate)
                temporal_edge = 0.5 * (_edge_map(prev_warp) + _edge_map(next_warp))
                edge_excess = (candidate_edge - temporal_edge - 0.08).clamp_min(0)
                structure_conf = torch.exp(-edge_excess / 0.06)
                reaction_support = None
                if prior is not None:
                    # DWPose/head boxes identify the person while NVOFA supplies
                    # the moving silhouette. Relax the generic high-motion and
                    # flow-boundary penalties only where the virtual midpoint is
                    # temporally better. This covers hair, cheeks, shoulders and
                    # folded limbs on the reacting/defending subject.
                    human_priority = ((prior - 0.45) / 0.55).clamp(0, 1)
                    reaction_support = human_priority * quality_win
                    structure_conf = torch.maximum(
                        structure_conf, reaction_support * 0.60
                    )
                signal = (
                    (candidate_disagreement - neighbor_agreement * 0.35).clamp_min(0)
                    + candidate_chroma_disagreement * 0.30
                    + edge_gain * 0.22
                )
                # NvOFFRUC performs its own forward/backward consistency test.
                # Retain a confidence floor so fast action is still eligible.
                motion_conf = 0.35 + 0.65 * motion_conf
                signal = signal * quality_win * structure_conf
            else:
                reaction_support = None
                candidate = (prev_warp + next_warp) * 0.5
                signal = (
                    (current_disagreement - neighbor_agreement * 0.55).clamp_min(0)
                    + chroma_disagreement * 0.35
                )
            if reaction_support is not None:
                agreement = torch.maximum(agreement, reaction_support * 0.42)
                motion_conf = torch.maximum(motion_conf, reaction_support * 0.55)
                boundary_conf = torch.maximum(boundary_conf, reaction_support * 0.55)
            signal = signal * agreement * motion_conf * boundary_conf
            if max_repair_ratio < 0.999:
                threshold = torch.quantile(signal.flatten(), 1.0 - float(max_repair_ratio))
                signal = torch.where(signal >= threshold, signal, torch.zeros_like(signal))
            mask = signal / (signal.amax() + 1e-6)
            mask = mask * prev_valid * next_valid
            mask = F.max_pool2d(mask[None, None], kernel_size=3, stride=1, padding=1)
            mask = F.avg_pool2d(mask, kernel_size=3, stride=1, padding=1)[0, 0]
            edge = _edge_map(current)
            mask = mask * (0.75 + 0.25 * edge).clamp(0, 1)
            if prior is not None:
                mask = mask * prior.clamp(0, 1)
            if reaction_support is not None:
                # Grow around a verified moving-human mask in proportion to the
                # subject's actual NVOFA speed. Fine hair needs only a few pixels;
                # Cover the immediate hair, face, and limb edge around a verified
                # reaction path without spreading repair into the other fighter.
                reactive_shell = F.max_pool2d(
                    (mask * reaction_support)[None, None],
                    kernel_size=7, stride=1, padding=3,
                )[0, 0]
                mask = torch.maximum(mask, reactive_shell * 0.70)
            blend = (mask * float(repair_strength)).unsqueeze(-1)
            proposed = current + blend * (candidate - current)

            # Never convert a rejected dark neighbour into a bright outline by
            # lifting it.  If the neighbour candidate is darker than the current
            # VFX pixel, keep the real current pixel.  At strong flow boundaries,
            # also keep the current pixel for either polarity.  Repair remains
            # active inside coherent moving regions where optical flow is valid.
            proposed = proposed.clamp(0, 1)
            candidate_luma = _gray(candidate)
            reject_dark = candidate_luma + (0.25 / 255.0) < current_luma
            reject_boundary = flow_boundary > boundary_limit
            # A coherent-looking but wrongly aligned neighbour can cover the
            # interior of a fast limb, so it may escape the vector-boundary map.
            # Reject any temporal candidate with a visible tonal jump.  The pass
            # remains useful for chroma bleed and sub-level local instability,
            # while neither white nor black contour strokes can be introduced.
            if candidates is not None:
                # FRUC candidates can legitimately move an edge and change its
                # luminance. Only reject extreme jumps and flow boundaries.
                reject_tonal_jump = (candidate_luma - current_luma).abs() > 0.24
                # Preserve intentional one-frame impact flashes. They resemble
                # temporal corruption numerically but are part of the action.
                reject_flash = (current_luma > 0.72) & (
                    candidate_luma + 0.10 < current_luma
                )
                if reaction_support is not None:
                    reject_boundary = reject_boundary & (reaction_support < 0.20)
                reject = reject_boundary | reject_tonal_jump | reject_flash
            else:
                reject_tonal_jump = (candidate_luma - current_luma).abs() > (3.0 / 255.0)
                reject = reject_dark | reject_boundary | reject_tonal_jump
            proposed = torch.where(reject.unsqueeze(-1), current, proposed)
            out[i] = proposed

        nvofa_used = nonlocal_nvofa[0]
        if nvofa_used and candidates is not None:
            status = "NVIDIA FRUC + NVOFA quality-win mask active; selective midpoint repair applied"
        elif nvofa_used:
            status = "NVOFA hardware optical flow active; 3-frame local repair applied"
        elif nvofa_errors:
            status = "CPU optical-flow fallback used; NVOFA unavailable: " + nvofa_errors[0]
        else:
            status = "CPU optical-flow backend used; 3-frame local repair applied"
        if status != getattr(self, "_last_logged_status", None):
            _LOG.info(status)
            self._last_logged_status = status
        result = out
        if images.shape[-1] > 3:
            result = torch.cat((out, images[:count, ..., 3:]), dim=-1)
        if count < images.shape[0]:
            result = torch.cat((result, images[count:]), dim=0)
        return (result.to(device=images.device, dtype=images.dtype).clamp(0, 1), status)


NODE_CLASS_MAPPINGS = {
    "NVOFATemporalArtifactRepair": NVOFATemporalArtifactRepair,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NVOFATemporalArtifactRepair": "NVOFA Temporal Artifact Repair",
}
