from imgui_bundle import imgui

def set_item_tooltip_no_delay(fmt: str):
    """
    Set tooltip on an item that has no delay.
    """
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_none):
        imgui.set_tooltip(fmt)