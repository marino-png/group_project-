"""
Low-battery version of the main screen.

Differences vs main_page.py:
- Battery level fixed to 5% and styled as low (red text).
- Charging status text shown in red.
- Egusi Stew, Fried Rice and Jollof Rice buttons are greyed out and
  tapping them shows a "not enough energy" warning instead of opening pages.
"""

import os

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.progressbar import ProgressBar
from kivy.uix.widget import Widget
from kivy.uix.image import Image
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.popup import Popup
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp


# ─────────────────────────────────────────────────────────────────────────────
# PLACEHOLDER SENSOR / SYSTEM DATA (low battery)
# ─────────────────────────────────────────────────────────────────────────────

BATTERY_PCT = 5
IS_CHARGING = True
LIGHT_LUX = 8450


# Image paths relative to this script's directory
GUI_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(GUI_DIR, "images")

RECIPES = [
    {
        "title": "FUFU",
        "subtitle": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        "color": (1.0, 0.75, 0.45, 1),
        "image": os.path.join(IMAGES_DIR, "fufu.png"),
    },
    {
        "title": "EGUSI STEW",
        "subtitle": "Not available – low battery.",
        "color": (0.4, 0.4, 0.4, 1),
        "image": os.path.join(IMAGES_DIR, "egusi stew.png"),
    },
    {
        "title": "FRIED RICE",
        "subtitle": "Not available – low battery.",
        "color": (0.4, 0.4, 0.4, 1),
        "image": os.path.join(IMAGES_DIR, "fried rice.png"),
    },
    {
        "title": "JOLLOF RICE",
        "subtitle": "Not available – low battery.",
        "color": (0.4, 0.4, 0.4, 1),
        "image": os.path.join(IMAGES_DIR, "jollof rice.png"),
    },
]


class RecipeButton(ButtonBehavior, BoxLayout):
    """Recipe row: image on the left, title + subtitle on the right."""

    def __init__(self, title, subtitle, bg_color, image_path, on_press_callback=None, **kwargs):
        super().__init__(
            orientation="horizontal",
            padding=dp(10),
            spacing=dp(12),
            size_hint_y=None,
            height=dp(90),
            **kwargs,
        )
        with self.canvas.before:
            Color(*bg_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._update_rect, size=self._update_rect)

        # Bind on_release instead of on_press so the touch screen
        # doesn't accidentally trigger the callback twice.
        if on_press_callback is not None:
            self.bind(on_release=lambda *_: on_press_callback())

        # Thumbnail (fixed size, keep aspect ratio)
        img = Image(
            source=image_path if os.path.exists(image_path) else "",
            size_hint=(None, None),
            size=(dp(70), dp(70)),
            allow_stretch=True,
            keep_ratio=True,
        )
        img_wrap = BoxLayout(size_hint=(None, None), size=(dp(70), dp(70)))
        img_wrap.add_widget(img)
        self.add_widget(img_wrap)

        # Text column
        text_col = BoxLayout(orientation="vertical", padding=(0, dp(4)))
        title_lbl = Label(
            text=title,
            font_size="20sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(0.08, 0.09, 0.15, 1),
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))
        subtitle_lbl = Label(
            text=subtitle,
            font_size="13sp",
            halign="left",
            valign="top",
            color=(0.15, 0.15, 0.2, 1),
            shorten=True,
        )
        subtitle_lbl.bind(size=subtitle_lbl.setter("text_size"))
        text_col.add_widget(title_lbl)
        text_col.add_widget(subtitle_lbl)
        self.add_widget(text_col)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class StatusPanel(BoxLayout):
    """Right-hand panel showing battery and light status (low battery styling)."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(20), dp(20), dp(20), dp(12)), spacing=dp(10), **kwargs)

        self.size_hint_x = 0.32  # ~one third of the screen

        # Top spacer to move all status content a bit lower
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))

        # Header
        header = Label(
            text="System Status",
            font_size="26sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(45),
        )
        header.bind(size=header.setter("text_size"))

        self.add_widget(header)

        # Battery
        battery_title = Label(
            text="Battery",
            font_size="16sp",
            color=(1, 0.3, 0.3, 1),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        )
        battery_title.bind(size=battery_title.setter("text_size"))
        self.add_widget(battery_title)

        battery_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(24))
        battery_bar = ProgressBar(max=100, value=BATTERY_PCT)
        battery_label = Label(
            text=f"{BATTERY_PCT}%",
            font_size="14sp",
            color=(1, 0.3, 0.3, 1),
            size_hint_x=None,
            width=dp(60),
        )
        battery_row.add_widget(battery_bar)
        battery_row.add_widget(battery_label)
        self.add_widget(battery_row)

        # Charging status, but red to signal problem
        charging_text = "Charging"
        charging_color = (1.0, 0.3, 0.3, 1)
        charging_label = Label(
            text=charging_text,
            font_size="16sp",
            color=charging_color,
            size_hint_y=None,
            height=dp(26),
        )
        charging_label.bind(size=charging_label.setter("text_size"))
        self.add_widget(Widget(size_hint_y=None, height=dp(2)))
        self.add_widget(charging_label)

        # Light sensor
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))
        light_title = Label(
            text="Solar Light",
            font_size="16sp",
            color=(1, 1, 1, 0.9),
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(22),
        )
        light_title.bind(size=light_title.setter("text_size"))
        self.add_widget(light_title)

        light_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(24))
        light_bar = ProgressBar(max=20000, value=LIGHT_LUX)  # arbitrary max for placeholder
        light_label = Label(
            text=f"{LIGHT_LUX} lx",
            font_size="14sp",
            color=(1, 1, 1, 0.9),
            size_hint_x=None,
            width=dp(100),
        )
        light_row.add_widget(light_bar)
        light_row.add_widget(light_label)
        self.add_widget(light_row)

        # Time left to charge message
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))
        charge_left_label = Label(
            text="time left to charge :\n2:30 hours",
            font_size="14sp",
            halign="left",
            valign="top",
            color=(1, 1, 1, 0.95),
            size_hint_y=None,
            height=dp(48),
        )
        charge_left_label.bind(size=charge_left_label.setter("text_size"))
        self.add_widget(charge_left_label)

        # Optimize meal plan button (same as main page)
        from kivy.app import App as _App
        self.add_widget(Widget(size_hint_y=None, height=dp(8)))
        optimize_btn = Button(
            text="optimize meal plan",
            size_hint_y=None,
            height=dp(42),
            background_normal="",
            background_color=(0.2, 0.5, 1.0, 1),
            color=(1, 1, 1, 1),
            border=(0, 0, 0, 0),
        )

        def _go_optimize(instance):
            app = _App.get_running_app()
            if hasattr(app, "show_optimize_page"):
                app.show_optimize_page()

        optimize_btn.bind(on_release=_go_optimize)
        self.add_widget(optimize_btn)

        # Bottom spacer so panel doesn't look cramped
        self.add_widget(Widget(size_hint_y=None, height=dp(6)))


class MainRoot(BoxLayout):
    """Main layout: left area with header + 4 recipe buttons, right status panel."""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", spacing=0, **kwargs)

        # Left side (recipes)
        left = BoxLayout(
            orientation="vertical",
            padding=(dp(20), dp(10), dp(20), dp(10)),
            spacing=dp(12),
        )

        # Header row with Quit on the top left and title to the right
        header_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(16))

        quit_btn = Button(
            text="✕  Quit",
            size_hint=(None, None),
            width=dp(110),
            height=dp(40),
            background_normal="",
            background_color=(0.95, 0.45, 0.45, 1),
            color=(0.08, 0.09, 0.15, 1),
            border=(0, 0, 0, 0),
            on_press=lambda *_: App.get_running_app().stop(),
        )

        title_lbl = Label(
            text="Autonomous Cooking Unit",
            font_size="26sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(1, 1, 1, 1),
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))

        header_row.add_widget(quit_btn)
        header_row.add_widget(title_lbl)

        left.add_widget(header_row)

        left.add_widget(Widget(size_hint_y=None, height=dp(8)))

        subtitle = Label(
            text="Select a recipe to begin",
            font_size="16sp",
            halign="left",
            valign="middle",
            color=(1, 1, 1, 0.8),
            size_hint_y=None,
            height=dp(28),
        )
        subtitle.bind(size=subtitle.setter("text_size"))
        left.add_widget(subtitle)

        # Recipe buttons column
        from kivy.app import App as _App

        recipes_col = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint_y=None,
        )

        for r in RECIPES:
            def make_cb(title=r["title"]):
                def _cb():
                    # FUFU allowed; others show warning
                    if title == "FUFU":
                        app = _App.get_running_app()
                        if hasattr(app, "show_fufu_page"):
                            app.show_fufu_page()
                    else:
                        # Show warning popup
                        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
                        msg = Label(
                            text="not enough energy",
                            font_size="16sp",
                            halign="center",
                            valign="middle",
                            color=(1, 1, 1, 1),
                        )
                        msg.bind(size=msg.setter("text_size"))
                        ok_btn = Button(
                            text="OK",
                            size_hint=(None, None),
                            width=dp(80),
                            height=dp(40),
                            background_normal="",
                            background_color=(1.0, 0.6, 0.25, 1),
                            color=(0.1, 0.1, 0.1, 1),
                            border=(0, 0, 0, 0),
                        )
                        popup = Popup(
                            title="Warning",
                            content=content,
                            size_hint=(0.6, 0.3),
                        )
                        ok_btn.bind(on_press=lambda *_: popup.dismiss())
                        content.add_widget(msg)
                        content.add_widget(Widget())
                        content.add_widget(ok_btn)
                        popup.open()

                return _cb

            recipes_col.add_widget(
                RecipeButton(
                    title=r["title"],
                    subtitle=r["subtitle"],
                    bg_color=r["color"],
                    image_path=r["image"],
                    on_press_callback=make_cb(),
                )
            )

        recipes_col.bind(minimum_height=recipes_col.setter("height"))

        recipes_container = BoxLayout(orientation="vertical")
        recipes_container.add_widget(recipes_col)
        left.add_widget(recipes_container)

        # Right status panel
        right = StatusPanel()

        self.add_widget(left)
        self.add_widget(right)


class CookingUnitLowBatteryApp(App):
    def build(self):
        Window.clearcolor = (0.05, 0.07, 0.15, 1)
        try:
            Window.size = (800, 480)
        except Exception:
            pass
        Window.fullscreen = True

        from kivy.uix.boxlayout import BoxLayout as RootBox

        self._root_container = RootBox()
        self.show_main_page()
        return self._root_container

    def show_main_page(self, *args):
        self._root_container.clear_widgets()
        self._root_container.add_widget(MainRoot())

    def show_fufu_page(self, *args):
        from fufu_page import build_fufu_page

        self._root_container.clear_widgets()
        # Re-use the same timer page integration as the full app
        from main_page import CookingUnitApp
        # On low-battery screen we still allow Fufu + timer
        self._root_container.add_widget(
            build_fufu_page(on_home=self.show_main_page, on_start_timer=self.show_timer_page)
        )

    def show_timer_page(self, *args):
        from timer_page import build_timer_page

        self._root_container.clear_widgets()
        self._root_container.add_widget(build_timer_page(on_home=self.show_main_page))

    def show_optimize_page(self, *args):
        from optimize_page import build_optimize_page

        self._root_container.clear_widgets()
        self._root_container.add_widget(build_optimize_page(on_home=self.show_main_page))


if __name__ == "__main__":
    CookingUnitLowBatteryApp().run()

