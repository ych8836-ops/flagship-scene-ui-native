from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import torch


class NvFRUCError(RuntimeError):
    pass


_STATUS = {
    0: "success",
    1: "hardware optical flow is not supported",
    2: "invalid pointer",
    3: "invalid parameter",
    4: "invalid handle",
    5: "out of system memory",
    6: "out of video memory",
    7: "OpenCV is unavailable",
    8: "unimplemented",
    9: "optical-flow generation failed",
    10: "duplicate resource",
    11: "unregistered resource",
    12: "incorrect API sequence",
    13: "write failed",
    14: "pipeline execution failed",
    15: "synchronization failed",
    16: "generic failure",
}


class _CreateParams(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("device", ctypes.c_void_p),
        ("resource_type", ctypes.c_int),
        ("surface_format", ctypes.c_int),
        ("cuda_resource_type", ctypes.c_int),
        ("reserved", ctypes.c_uint32 * 32),
    ]


class _FrameData(ctypes.Structure):
    _fields_ = [
        ("frame", ctypes.c_void_p),
        ("timestamp", ctypes.c_double),
        ("pitch", ctypes.c_size_t),
        ("repeated", ctypes.POINTER(ctypes.c_bool)),
        ("reserved", ctypes.c_uint32 * 32),
    ]


class _SyncWait(ctypes.Union):
    _fields_ = [("values", ctypes.c_uint64 * 2)]


class _SyncSignal(ctypes.Union):
    _fields_ = [("values", ctypes.c_uint64 * 2)]


class _ProcessIn(ctypes.Structure):
    _fields_ = [
        ("frame_data", _FrameData),
        ("skip_warp", ctypes.c_uint32),
        ("sync_wait", _SyncWait),
        ("reserved", ctypes.c_uint32 * 32),
    ]


class _ProcessOut(ctypes.Structure):
    _fields_ = [
        ("frame_data", _FrameData),
        ("sync_signal", _SyncSignal),
        ("reserved", ctypes.c_uint32 * 32),
    ]


class _RegisterParams(ctypes.Structure):
    _fields_ = [
        ("resources", ctypes.c_void_p * 10),
        ("fence", ctypes.c_void_p),
        ("count", ctypes.c_uint32),
    ]


class _UnregisterParams(ctypes.Structure):
    _fields_ = [
        ("resources", ctypes.c_void_p * 10),
        ("count", ctypes.c_uint32),
    ]


def _check(status: int, operation: str) -> None:
    if int(status) != 0:
        detail = _STATUS.get(int(status), f"unknown status {int(status)}")
        raise NvFRUCError(f"{operation} failed: {detail}")


def find_nvfruc_dll(node_root: Path | None = None) -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("NVOFFRUC_DLL", "").strip()
    if configured:
        candidates.append(Path(configured))
    if node_root is not None:
        candidates.extend(
            [
                node_root / "runtime" / "NvOFFRUC.dll",
                node_root / "NvOFFRUC.dll",
            ]
        )
    candidates.append(
        Path.home()
        / "Documents"
        / "New project"
        / "Optical_Flow_SDK_5.0.7"
        / "Optical_Flow_SDK_5.0.7"
        / "NvOFFRUC"
        / "NvOFFRUCSample"
        / "bin"
        / "win64"
        / "NvOFFRUC.dll"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "NvOFFRUC.dll을 찾을 수 없습니다. 노드의 runtime 폴더에 NVIDIA Optical "
        "Flow SDK 5.x win64 DLL을 두거나 NVOFFRUC_DLL 환경변수를 지정하세요."
    )


class NvFRUCStream:
    """Stateful midpoint interpolation over one monotonic frame sequence."""

    def __init__(self, width: int, height: int, dll_path: Path):
        if os.name != "nt":
            raise NvFRUCError("이 NvOFFRUC 런타임은 Windows에서만 지원됩니다.")
        if not torch.cuda.is_available():
            raise NvFRUCError("CUDA GPU를 사용할 수 없습니다.")
        self.width = int(width)
        self.height = int(height)
        self.pitch = self.width * 4
        self._dll_dir = os.add_dll_directory(str(dll_path.parent))
        self._dll = ctypes.WinDLL(str(dll_path))
        self._create = self._dll.NvOFFRUCCreate
        self._register = self._dll.NvOFFRUCRegisterResource
        self._unregister = self._dll.NvOFFRUCUnregisterResource
        self._process = self._dll.NvOFFRUCProcess
        self._destroy = self._dll.NvOFFRUCDestroy
        self._create.argtypes = [ctypes.POINTER(_CreateParams), ctypes.POINTER(ctypes.c_void_p)]
        self._register.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RegisterParams)]
        self._unregister.argtypes = [ctypes.c_void_p, ctypes.POINTER(_UnregisterParams)]
        self._process.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessIn), ctypes.POINTER(_ProcessOut)]
        self._destroy.argtypes = [ctypes.c_void_p]
        for function in (self._create, self._register, self._unregister, self._process, self._destroy):
            function.restype = ctypes.c_int

        # FRUC expects CUDA device pointers passed by address. Torch allocations
        # provide a stable, tightly packed RGBA surface for the lifetime here.
        torch.empty(1, device="cuda")
        self._surfaces = [
            torch.empty((self.height, self.width, 4), dtype=torch.uint8, device="cuda")
            for _ in range(3)
        ]
        self._device_ptrs = [ctypes.c_uint64(surface.data_ptr()) for surface in self._surfaces]
        self._resource_handles = [
            ctypes.cast(ctypes.pointer(ptr), ctypes.c_void_p) for ptr in self._device_ptrs
        ]
        self._handle = ctypes.c_void_p()
        self._registered = False
        self._closed = False
        self._input_slot = 0
        self._calls = 0

        params = _CreateParams()
        params.width = self.width
        params.height = self.height
        params.device = None
        params.resource_type = 0       # CudaResource
        params.surface_format = 1      # ARGBSurface (RGBA byte layout in sample)
        params.cuda_resource_type = 0  # CudaResourceCuDevicePtr
        _check(self._create(ctypes.byref(params), ctypes.byref(self._handle)), "NvOFFRUCCreate")

        register = _RegisterParams()
        register.count = len(self._resource_handles)
        for index, resource in enumerate(self._resource_handles):
            register.resources[index] = resource
        try:
            _check(self._register(self._handle, ctypes.byref(register)), "NvOFFRUCRegisterResource")
            self._registered = True
        except Exception:
            self.close()
            raise

    def process_cuda(
        self, rgba: torch.Tensor, timestamp: float
    ) -> tuple[torch.Tensor | None, bool]:
        """Run FRUC from a CUDA frame and keep its midpoint on CUDA.

        The result aliases this stream's output surface and must be consumed
        before the same stream advances again.
        """
        if self._closed:
            raise NvFRUCError("NvFRUC stream is already closed")
        if (
            not isinstance(rgba, torch.Tensor)
            or rgba.device.type != "cuda"
            or tuple(rgba.shape) != (self.height, self.width, 4)
            or rgba.dtype != torch.uint8
        ):
            raise ValueError("NvFRUC input must be a CUDA uint8 RGBA [height,width,4] tensor")

        input_index = self._input_slot
        output_index = 2
        self._surfaces[input_index].copy_(rgba.contiguous(), non_blocking=True)
        repeated = ctypes.c_bool(False)

        in_params = _ProcessIn()
        in_params.frame_data.frame = self._resource_handles[input_index]
        in_params.frame_data.timestamp = float(timestamp)
        in_params.frame_data.pitch = self.pitch

        out_params = _ProcessOut()
        out_params.frame_data.frame = self._resource_handles[output_index]
        out_params.frame_data.timestamp = float(timestamp) - 1.0
        out_params.frame_data.pitch = self.pitch
        out_params.frame_data.repeated = ctypes.pointer(repeated)

        _check(self._process(self._handle, ctypes.byref(in_params), ctypes.byref(out_params)), "NvOFFRUCProcess")
        torch.cuda.synchronize()
        self._calls += 1
        self._input_slot = 1 - self._input_slot
        if self._calls < 2:
            return None, bool(repeated.value)
        return self._surfaces[output_index], bool(repeated.value)

    def process(self, rgba: np.ndarray, timestamp: float) -> tuple[np.ndarray | None, bool]:
        """Compatibility path for existing host-memory callers."""
        if rgba.shape != (self.height, self.width, 4) or rgba.dtype != np.uint8:
            raise ValueError("NvFRUC input must be contiguous uint8 RGBA [height,width,4]")
        upload = np.ascontiguousarray(rgba)
        device_frame = torch.from_numpy(upload).to(device="cuda", non_blocking=False)
        candidate, repeated = self.process_cuda(device_frame, timestamp)
        if candidate is None:
            return None, repeated
        return candidate.cpu().numpy().copy(), repeated

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if getattr(self, "_handle", None) and self._handle.value:
            if self._registered:
                unregister = _UnregisterParams()
                unregister.count = len(self._resource_handles)
                for index, resource in enumerate(self._resource_handles):
                    unregister.resources[index] = resource
                self._unregister(self._handle, ctypes.byref(unregister))
            self._destroy(self._handle)
        if getattr(self, "_dll_dir", None) is not None:
            self._dll_dir.close()

    def __enter__(self) -> "NvFRUCStream":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def generate_midpoint_candidates(
    frames: Iterable[np.ndarray], width: int, height: int, dll_path: Path
) -> Iterable[tuple[int, np.ndarray, bool]]:
    """Yield candidates for every interior index while preserving source timing."""
    streams: list[NvFRUCStream] = []
    parity_counts = [0, 0]
    try:
        streams.append(NvFRUCStream(width, height, dll_path))
        streams.append(NvFRUCStream(width, height, dll_path))
        for index, frame in enumerate(frames):
            parity = index & 1
            parity_counts[parity] += 1
            # Positive, monotonic timestamps with a two-frame interval make the
            # requested output timestamp exactly the missing source-frame time.
            timestamp = float(parity_counts[parity] * 2)
            candidate, repeated = streams[parity].process(frame, timestamp)
            if candidate is not None:
                yield index - 1, candidate, repeated
    finally:
        for stream in streams:
            stream.close()


def generate_midpoint_candidates_cuda(
    frames: Iterable[torch.Tensor], width: int, height: int, dll_path: Path
) -> Iterable[tuple[int, torch.Tensor, bool]]:
    """Yield CUDA midpoint candidates with no intermediate host copy."""
    streams: list[NvFRUCStream] = []
    parity_counts = [0, 0]
    try:
        streams.append(NvFRUCStream(width, height, dll_path))
        streams.append(NvFRUCStream(width, height, dll_path))
        for index, frame in enumerate(frames):
            parity = index & 1
            parity_counts[parity] += 1
            timestamp = float(parity_counts[parity] * 2)
            candidate, repeated = streams[parity].process_cuda(frame, timestamp)
            if candidate is not None:
                yield index - 1, candidate, repeated
    finally:
        for stream in streams:
            stream.close()
