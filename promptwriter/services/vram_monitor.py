import threading

try:
    import pynvml
except ImportError:
    pynvml = None


DEFAULT_DEVICE_INDEX = 0
BYTES_PER_GB = 1024**3
VRAM_ERROR_LABEL = "VRAM: N/A"
VRAM_UNSUPPORTED_LABEL = "VRAM: Not supported"
VRAM_COLOR_GREEN = "#2e9e5b"
VRAM_COLOR_ORANGE = "#e08a1e"
VRAM_COLOR_RED = "#e04b4b"
VRAM_COLOR_NEUTRAL = "gray"

_STATE_UNINITIALIZED = "uninitialized"
_STATE_READY = "ready"
_STATE_UNAVAILABLE = "unavailable"

_nvml_lock = threading.Lock()
_nvml_state = _STATE_UNINITIALIZED
_nvml_device_supported = True


def init_nvml():
    """Initialize NVML once. Returns False when no NVIDIA GPU is available."""
    global _nvml_state
    with _nvml_lock:
        if _nvml_state == _STATE_READY:
            return True
        if _nvml_state == _STATE_UNAVAILABLE:
            return False
        if pynvml is None:
            _nvml_state = _STATE_UNAVAILABLE
            return False
        try:
            pynvml.nvmlInit()
        except Exception:
            _nvml_state = _STATE_UNAVAILABLE
            return False
        _nvml_state = _STATE_READY
        return True


def shutdown_nvml():
    global _nvml_state, _nvml_device_supported
    with _nvml_lock:
        _nvml_device_supported = True
        if _nvml_state != _STATE_READY:
            _nvml_state = _STATE_UNINITIALIZED
            return
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
        _nvml_state = _STATE_UNINITIALIZED


def is_vram_supported():
    """Return True when NVIDIA VRAM can be queried.

    A failed device query (for example on a non-NVIDIA GPU) is cached until
    shutdown_nvml() so polling never repeats the failing call.
    """
    if not init_nvml():
        return False
    with _nvml_lock:
        return _nvml_device_supported


def get_gpu_memory_usage(device_index=DEFAULT_DEVICE_INDEX):
    """Return used/total GPU memory in GB and percent, or None when unavailable."""
    global _nvml_device_supported
    if not init_nvml():
        return None
    with _nvml_lock:
        if not _nvml_device_supported:
            return None
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        total_bytes = float(memory.total)
        used_bytes = float(memory.used)
    except Exception:
        with _nvml_lock:
            _nvml_device_supported = False
        return None
    if total_bytes <= 0:
        return None
    return {
        "used_gb": used_bytes / BYTES_PER_GB,
        "total_gb": total_bytes / BYTES_PER_GB,
        "percent": used_bytes / total_bytes * 100.0,
    }


def format_vram_usage(memory):
    if not memory:
        return VRAM_ERROR_LABEL
    try:
        used_gb = float(memory["used_gb"])
        total_gb = float(memory["total_gb"])
        percent = float(memory["percent"])
    except (KeyError, TypeError, ValueError):
        return VRAM_ERROR_LABEL
    return f"VRAM: {used_gb:.1f} / {total_gb:.1f} GB ({percent:.0f}%)"


def vram_label_text(memory):
    """Header label text: usage, 'Not supported', or 'N/A'."""
    if memory:
        return format_vram_usage(memory)
    if not is_vram_supported():
        return VRAM_UNSUPPORTED_LABEL
    return VRAM_ERROR_LABEL


def vram_usage_color(percent):
    if not isinstance(percent, (int, float)) or isinstance(percent, bool):
        return VRAM_COLOR_NEUTRAL
    if percent < 70:
        return VRAM_COLOR_GREEN
    if percent <= 85:
        return VRAM_COLOR_ORANGE
    return VRAM_COLOR_RED
