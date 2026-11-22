"""QPhoneMirror 可愛清新多主題配色、高對比開關與教學卡色票規範。"""

from typing import Dict, Any

FONT_FAMILY = "Microsoft JhengHei UI"
CORNER_CARD = 18
CORNER_BTN = 16
CORNER_INPUT = 12
CORNER_BADGE = 12

THEMES: Dict[str, Dict[str, Any]] = {
    "pastel_cute": {
        "id": "pastel_cute",
        "display_name": "櫻花薄荷・可愛清新",
        "appearance_mode": "light",
        "bg_main": "#FFFDF9",
        "bg_sidebar": "#EDF7F2",
        "bg_card": "#FFFFFF",
        "bg_card_alt": "#FFF4F6",
        "bg_input": "#F7FBF9",
        "bg_badge": "#E8F6EF",
        "bg_log": "#F9FCFA",
        "border": "#D5EDE2",
        "border_pink": "#FAD4DC",
        "text_primary": "#3D405B",
        "text_secondary": "#646985",
        "text_on_accent": "#FFFFFF",
        "accent_primary": "#1B825B",
        "accent_primary_hover": "#156B4A",
        "accent_secondary": "#C93B62",
        "accent_secondary_hover": "#AE2E52",
        "accent_info": "#256CC2",
        "accent_info_hover": "#1D59A3",
        "accent_warn": "#A85A08",
        "accent_warn_hover": "#8F4B06",
        "switch_track_off": "#CFE0D8",
        "switch_track_on": "#7AD4AE",
        "switch_thumb": "#1A543E",
        "switch_thumb_hover": "#123D2D",
        "status_ok": "#1E7E4E",
        "status_warn": "#A85C0B",
        "status_err": "#C2354B",
        "nav_active": "#D9F2E6",
        "nav_hover": "#E4F5EC",
        "guide_cards": [
            ("#FFF4F6", "#FAD4DC"),  # 柔櫻粉
            ("#F1FAF5", "#CBEAD9"),  # 柔薄荷
            ("#F2F8FF", "#CBE0FA"),  # 柔天藍
            ("#FFFBF0", "#F5E2B3"),  # 柔奶油黃
            ("#F7F3FF", "#DFD3FA"),  # 柔薰衣草
            ("#FFF6F0", "#FAD8C3"),  # 柔蜜桃橘
        ],
    },
    "nordic_fresh": {
        "id": "nordic_fresh",
        "display_name": "森林燕麥・北歐清新",
        "appearance_mode": "light",
        "bg_main": "#F7F6F2",
        "bg_sidebar": "#EAECE5",
        "bg_card": "#FFFFFF",
        "bg_card_alt": "#F2F6F3",
        "bg_input": "#F4F6F3",
        "bg_badge": "#E3ECE6",
        "bg_log": "#F7F8F6",
        "border": "#CFDCD3",
        "border_pink": "#D9D2C5",
        "text_primary": "#2F3E46",
        "text_secondary": "#56685E",
        "text_on_accent": "#FFFFFF",
        "accent_primary": "#3D6E59",
        "accent_primary_hover": "#305947",
        "accent_secondary": "#8F4D5B",
        "accent_secondary_hover": "#783E4A",
        "accent_info": "#3A6F73",
        "accent_info_hover": "#2E5B5E",
        "accent_warn": "#9A6024",
        "accent_warn_hover": "#804F1C",
        "switch_track_off": "#CED9D2",
        "switch_track_on": "#94B7A6",
        "switch_thumb": "#1E3A2F",
        "switch_thumb_hover": "#142921",
        "status_ok": "#2D6E4E",
        "status_warn": "#9A5B1A",
        "status_err": "#A83B43",
        "nav_active": "#D6E4DB",
        "nav_hover": "#E1EBE4",
        "guide_cards": [
            ("#F2F6F3", "#CFE0D5"),  # 鼠尾草綠
            ("#F8F5EE", "#E3DAC8"),  # 燕麥暖米
            ("#F1F5F8", "#CEDCE6"),  # 霧灰海藍
            ("#F8F2F3", "#E5D2D6"),  # 淡玫瑰陶
            ("#F4F5F2", "#D8DDD4"),  # 淺亞麻灰
            ("#F9F4EE", "#E8D8C5"),  # 柔暖木杏
        ],
    },
    "cozy_night": {
        "id": "cozy_night",
        "display_name": "星空軟糖・柔和夜色",
        "appearance_mode": "dark",
        "bg_main": "#232946",
        "bg_sidebar": "#1B2038",
        "bg_card": "#2E365A",
        "bg_card_alt": "#352F4D",
        "bg_input": "#252C4A",
        "bg_badge": "#39436E",
        "bg_log": "#1C223B",
        "border": "#465180",
        "border_pink": "#6A5476",
        "text_primary": "#F4F6FF",
        "text_secondary": "#C4CCEE",
        "text_on_accent": "#1B2038",
        "accent_primary": "#8BD3DD",
        "accent_primary_hover": "#72C2CE",
        "accent_secondary": "#EEBBC3",
        "accent_secondary_hover": "#E2A2AC",
        "accent_info": "#A7C7E7",
        "accent_info_hover": "#8DB5DF",
        "accent_warn": "#F6D186",
        "accent_warn_hover": "#EBC06A",
        "switch_track_off": "#4A5685",
        "switch_track_on": "#337A86",
        "switch_thumb": "#FFFDF9",
        "switch_thumb_hover": "#EEBBC3",
        "status_ok": "#7EE0B5",
        "status_warn": "#F6C873",
        "status_err": "#F48C9C",
        "nav_active": "#38426E",
        "nav_hover": "#2D3559",
        "guide_cards": [
            ("#352F4D", "#67537B"),  # 星空櫻夜
            ("#273B4A", "#487584"),  # 星空薄荷夜
            ("#2B365A", "#4D6094"),  # 星空靛藍夜
            ("#3A364B", "#746B82"),  # 星空暖琥珀夜
            ("#333057", "#615B96"),  # 星空薰衣草夜
            ("#3D324B", "#785872"),  # 星空珊瑚夜
        ],
    },
}


def get_theme(theme_id: str) -> Dict[str, Any]:
    """取得指定主題配色，無效時回退為預設的櫻花薄荷可愛清新風。"""
    return THEMES.get(theme_id, THEMES["pastel_cute"])


def get_theme_display_names() -> list[str]:
    """回傳所有主題的顯示名稱清單。"""
    return [t["display_name"] for t in THEMES.values()]


def get_theme_id_by_display_name(display_name: str) -> str:
    """依顯示名稱反查主題 ID。"""
    for tid, data in THEMES.items():
        if data["display_name"] == display_name:
            return tid
    return "pastel_cute"
