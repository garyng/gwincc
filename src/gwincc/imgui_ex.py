from imgui_bundle import imgui
import ctypes

def set_item_tooltip_no_delay(fmt: str):
    """
    Set tooltip on an item that has no delay.
    """
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_none):
        imgui.set_tooltip(fmt)


# get the name of the pycapsule object
platform_handle_raw_GetName = ctypes.pythonapi.PyCapsule_GetName
platform_handle_raw_GetName.restype = ctypes.c_char_p
platform_handle_raw_GetName.argtypes = [ctypes.py_object]

# unwrap the value of void* pointer
platform_handle_raw_GetPointer = ctypes.pythonapi.PyCapsule_GetPointer
platform_handle_raw_GetPointer.restype = ctypes.c_void_p
platform_handle_raw_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]

def get_window_viewport_platform_hwnd() -> int | None:
    vp = imgui.get_window_viewport()
    if not vp.platform_window_created:
        return None
    return platform_handle_raw_GetPointer(vp.platform_handle_raw, platform_handle_raw_GetName(vp.platform_handle_raw))