"""Meal optimization page: run external solar meal planner and show results."""

import csv
import os
import subprocess
from datetime import date
from threading import Thread

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from main_page import GUI_DIR


PROJECT_ROOT = os.path.join(GUI_DIR, "solar_battery_cooking 2", "solar_battery_cooking")
CSV_REL_PATH = os.path.join("outputs", "main_lp", "lp_meal_plan.csv")


def _run_optimizer_async(on_done, on_error):
    """Run the external main.py script in a background thread."""

    def worker():
        if not os.path.isdir(PROJECT_ROOT):
            Clock.schedule_once(lambda dt: on_error("Optimizer folder not found."), 0)
            return

        today_str = date.today().strftime("%Y-%m-%d")

        cmd = [
            "python",
            "main.py",
            "lp",
            "--mode",
            "meal_opt",
            "--location-name",
            "Lagos",
            "--solar-profile-model",
            "suspos",
            "--weather-profile-mode",
            "monthly_climatology",
            "--start",
            today_str,
            "--days",
            "1",
            "--pv-kw-fixed",
            "4.0",
            "--batt-kwh-fixed",
            "8.0",
            "--soc-init",
            "0.5",
            "--meal-cost-weight",
            "1.0",
            "--nutrition-targets",
            "configs/meal_targets.json",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode != 0:
                msg = "Optimizer failed:\n" + result.stderr[-400:]
                Clock.schedule_once(lambda dt: on_error(msg), 0)
                return
        except Exception as exc:
            Clock.schedule_once(lambda dt: on_error(str(exc)), 0)
            return

        csv_path = os.path.join(PROJECT_ROOT, CSV_REL_PATH)
        if not os.path.exists(csv_path):
            Clock.schedule_once(lambda dt: on_error("Result CSV not found."), 0)
            return

        rows = []
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except Exception as exc:
            Clock.schedule_once(lambda dt: on_error(f"Error reading CSV: {exc}"), 0)
            return

        Clock.schedule_once(lambda dt: on_done(rows), 0)

    Thread(target=worker, daemon=True).start()


def build_optimize_page(on_home):
    root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

    # Top bar with home
    top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50), spacing=dp(10))
    home_btn = Button(
        text="home",
        size_hint=(None, None),
        width=dp(90),
        height=dp(40),
        background_normal="",
        background_color=(0.95, 0.35, 0.25, 1),
        color=(1, 1, 1, 1),
        border=(0, 0, 0, 0),
        on_press=lambda *_: on_home(),
    )
    title = Label(
        text="Optimized meal plan",
        font_size="20sp",
        bold=True,
        halign="left",
        valign="middle",
        color=(1, 1, 1, 1),
    )
    title.bind(size=title.setter("text_size"))
    top.add_widget(home_btn)
    top.add_widget(title)
    root.add_widget(top)

    status_label = Label(
        text="Running optimization...",
        font_size="14sp",
        halign="left",
        valign="middle",
        color=(1, 1, 1, 0.9),
        size_hint_y=None,
        height=dp(24),
    )
    status_label.bind(size=status_label.setter("text_size"))
    root.add_widget(status_label)

    # Scrollable area for results
    scroll = ScrollView()
    list_box = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
    list_box.bind(minimum_height=list_box.setter("height"))
    scroll.add_widget(list_box)
    root.add_widget(scroll)

    def on_error(msg: str):
        status_label.text = msg
        list_box.clear_widgets()

    def on_done(rows):
        if not rows:
            status_label.text = "No meals found in optimization result."
            return
        status_label.text = "Optimized meals:"
        list_box.clear_widgets()

        # Try to guess useful columns
        first = rows[0]
        name_key = next((k for k in first if "meal" in k.lower() and "name" in k.lower()), None)
        type_key = next((k for k in first if "type" in k.lower() or "slot" in k.lower()), None)
        power_key = next((k for k in first if "power" in k.lower() or "energy_kwh" in k.lower()), None)
        nutri_key = next((k for k in first if "kcal" in k.lower() or "nutrition" in k.lower()), None)

        for r in rows:
            meal_name = r.get(name_key) if name_key else r.get("meal", "Meal")
            meal_type = r.get(type_key, "")
            power = r.get(power_key, "")
            nutri = r.get(nutri_key, "")

            card = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(4), size_hint_y=None, height=dp(90))
            from kivy.graphics import Color, RoundedRectangle

            with card.canvas.before:
                Color(0.12, 0.16, 0.28, 1)
                card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(12)])

            def _update_bg(instance, value):
                card._bg.pos = card.pos
                card._bg.size = card.size

            card.bind(pos=_update_bg, size=_update_bg)

            title_lbl = Label(
                text=str(meal_name),
                font_size="16sp",
                bold=True,
                halign="left",
                valign="middle",
                color=(1, 1, 1, 1),
                size_hint_y=None,
                height=dp(22),
            )
            title_lbl.bind(size=title_lbl.setter("text_size"))

            meta = ""
            if meal_type:
                meta += f"{meal_type} "
            if power:
                meta += f"· power {power} "
            if nutri:
                meta += f"· nutrition {nutri}"

            meta_lbl = Label(
                text=meta.strip(),
                font_size="13sp",
                halign="left",
                valign="top",
                color=(1, 1, 1, 0.85),
            )
            meta_lbl.bind(size=meta_lbl.setter("text_size"))

            card.add_widget(title_lbl)
            card.add_widget(meta_lbl)
            list_box.add_widget(card)

    _run_optimizer_async(on_done, on_error)

    return root

