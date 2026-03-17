"""Jollof Rice page – same layout pattern as Fufu."""

import os

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from fufu_page import FufuStatusPanel, _load_recipe_text, GUI_DIR, IMAGES_DIR


JOLLOF_RECIPE_PATH = os.path.join(GUI_DIR, "jollof_rice.txt")


def build_jollof_page(on_home, on_start_timer):
    root = BoxLayout(orientation="horizontal", spacing=dp(10), padding=(dp(10), dp(6), dp(10), dp(10)))

    main_col = BoxLayout(orientation="vertical", spacing=dp(10))

    top_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(190))

    home_btn = Button(
        text="home",
        size_hint=(None, None),
        width=dp(90),
        height=dp(70),
        background_normal="",
        background_color=(0.95, 0.35, 0.25, 1),
        color=(1, 1, 1, 1),
        border=(0, 0, 0, 0),
        on_press=lambda *_: on_home(),
    )

    image_panel = BoxLayout(orientation="vertical", padding=dp(10))
    img_path = os.path.join(IMAGES_DIR, "jollof rice.png")
    img = Image(source=img_path if os.path.exists(img_path) else "", allow_stretch=True, keep_ratio=True)
    image_panel.add_widget(img)

    left_buttons = BoxLayout(orientation="vertical", spacing=dp(8), size_hint=(None, 1))
    left_buttons.add_widget(home_btn)
    start_btn = Button(
        text="Start cooking",
        size_hint=(None, None),
        width=dp(120),
        height=dp(60),
        background_normal="",
        background_color=(1.0, 0.7, 0.3, 1),
        color=(0.1, 0.1, 0.1, 1),
        border=(0, 0, 0, 0),
        on_press=lambda *_: on_start_timer(),
    )
    left_buttons.add_widget(start_btn)

    top_row.add_widget(left_buttons)
    top_row.add_widget(image_panel)
    main_col.add_widget(top_row)

    recipe_panel = BoxLayout(orientation="vertical", padding=dp(10))
    recipe_panel.size_hint_y = 1.0
    recipe_panel.canvas.before.clear()
    from kivy.graphics import Color, RoundedRectangle

    with recipe_panel.canvas.before:
        Color(1.0, 0.75, 0.3, 1)
        recipe_panel._rect = RoundedRectangle(pos=recipe_panel.pos, size=recipe_panel.size, radius=[dp(18)])

    def _update_rect(*_):
        recipe_panel._rect.pos = recipe_panel.pos
        recipe_panel._rect.size = recipe_panel.size

    recipe_panel.bind(pos=_update_rect, size=_update_rect)

    recipe_text = _load_recipe_text(JOLLOF_RECIPE_PATH)
    scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
    recipe_label = Label(
        text=recipe_text,
        font_size="16sp",
        halign="left",
        valign="top",
        color=(0.1, 0.1, 0.1, 1),
        size_hint_y=None,
    )
    recipe_label.bind(
        texture_size=lambda instance, value: setattr(instance, "height", value[1]),
        size=lambda instance, value: setattr(instance, "text_size", (value[0], None)),
    )
    scroll.add_widget(recipe_label)
    recipe_panel.add_widget(scroll)
    main_col.add_widget(recipe_panel)

    status_panel = FufuStatusPanel()

    root.add_widget(main_col)
    root.add_widget(status_panel)

    return root

