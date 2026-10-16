"""Renderer presets for one cylindrical clipboard drum. No Qt dependency."""
DRUM_STYLES = {
    'minimal': {
        'name': 'Минимализм', 'top_alpha': 215, 'bottom_alpha': 224,
        'shadow': 37, 'edge': 80, 'reflection': 26, 'rim': 26,
        'halo': 95, 'accent': 180, 'texture': 0,
    },
    'glass': {
        'name': 'Матовое стекло', 'top_alpha': 148, 'bottom_alpha': 178,
        'shadow': 48, 'edge': 140, 'reflection': 100, 'rim': 140,
        'halo': 130, 'accent': 190, 'texture': 0,
    },
    'metal': {
        'name': 'Шлифованный металл', 'top_alpha': 240, 'bottom_alpha': 246,
        'shadow': 72, 'edge': 160, 'reflection': 80, 'rim': 170,
        'halo': 80, 'accent': 200, 'texture': 14,
    },
    'softdark': {
        'name': 'Мягкий графит', 'top_alpha': 235, 'bottom_alpha': 242,
        'shadow': 85, 'edge': 63, 'reflection': 12, 'rim': 53,
        'halo': 105, 'accent': 150, 'texture': 0,
    },
}


def normalize_drum_style(value):
    return value if value in DRUM_STYLES else 'minimal'
