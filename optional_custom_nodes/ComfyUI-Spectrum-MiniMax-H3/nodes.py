if __package__:
    from .comfyui_spectrum_h3.nodes import (
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
        SpectrumApplyMiniMaxH3,
    )
else:
    from comfyui_spectrum_h3.nodes import (
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
        SpectrumApplyMiniMaxH3,
    )

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "SpectrumApplyMiniMaxH3",
]
