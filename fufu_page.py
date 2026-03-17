"""
Dedicated Fufu recipe page.

Layout (landscape):
- Top left: red "home" button returning to the main page.
- Top center: wide panel showing the Fufu image.
- Center: orange panel with scrollable Fufu recipe text (title larger than body).
- Right: narrow status panel showing machine state.

NOTE: The sensor-reading logic is local to this file so you can later
replace the placeholders with real smbus/I2C reads.
"""

import os
import threading
import time
import smbus2
import RPi.GPIO as GPIO


from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.metrics import dp


GUI_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(GUI_DIR, "images")

# Text file with the Fufu recipe
FUFU_RECIPE_PATH = os.path.join(GUI_DIR, "fufu.txt")

# I2C Addresses
BH1750_ADDR = 0x23
BME680_ADDR = 0x77

# BME680 Registers
REG_T1 = 0xE9
REG_T2 = 0x8A
REG_T3 = 0x8C
REG_CTRL_MEAS = 0x74
REG_TEMP_DATA = 0x22

# Pin Definitions
DT_PIN = 5
SCK_PIN = 6

# BH1750 Command
BH1750_CONTINUOUS_HIGH_RES = 0x10

bus = smbus2.SMBus(1)



def _load_recipe_text(path: str) -> str:
    if not os.path.exists(path):
        # Fallback placeholder if the recipe file is not yet deployed
        return (
            "Fufu Recipe\n\n"
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Curabitur laoreet sapien sit amet libero hendrerit, a feugiat est venenatis. "
            "Suspendisse potenti. Donec blandit tortor eu sapien efficitur condimentum.\n\n"
            "Please place your fufu.txt file next to fufu_page.py to see the real recipe."
        )

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# SENSOR READING HOOKS (replace these with your real smbus-based reads)
# ─────────────────────────────────────────────────────────────────────────────

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SCK_PIN, GPIO.OUT)
    GPIO.setup(DT_PIN, GPIO.IN)
    GPIO.output(SCK_PIN, False)
def get_bme_calib():
    """Reads factory calibration constants for the BME680."""
    # T1: unsigned short (2 bytes)
    t1 = bus.read_word_data(BME680_ADDR, REG_T1)

    # T2: signed short (2 bytes)
    t2_raw = bus.read_word_data(BME680_ADDR, REG_T2)
    t2 = t2_raw if t2_raw <= 32767 else t2_raw - 65536

    # T3: signed char (1 byte)
    t3_raw = bus.read_byte_data(BME680_ADDR, REG_T3)
    t3 = t3_raw if t3_raw <= 127 else t3_raw - 256

    return t1, t2, t3

def read_light_level() -> float:
    """Reads the light level in Lux from the VMA341."""
    data = bus.read_i2c_block_data(BH1750_ADDR, BH1750_CONTINUOUS_HIGH_RES, 2)
    lux = (data[0] << 8 | data[1]) / 1.2
    return lux


def read_weight() -> float:
    # Wait for the DT pin to go low (ready)
    # If it stays high, the chip isn't ready or connected
    count = 0
    while GPIO.input(DT_PIN) == 1:
        count += 1
        if count > 10000:
            return None # Timeout

    raw_data = 0

    # Read 24 bits of data
    for i in range(24):
        GPIO.output(SCK_PIN, True)
        # Shift bits left and read current state
        raw_data = (raw_data << 1) | GPIO.input(DT_PIN)
        GPIO.output(SCK_PIN, False)

    # 25th pulse sets Gain to 128 for the next reading
    GPIO.output(SCK_PIN, True)
    GPIO.output(SCK_PIN, False)

    # The HX711 output is 2's complement (signed 24-bit)
    if raw_data & 0x800000:
        raw_data -= 0x1000000

    if raw_data is  None:
        return 300
    else:
        return raw_data


def read_pot_temperature(t1, t2, t3) -> float:
    """Triggers a measurement and calculates temperature."""
    # Set to 'Forced Mode' to take a single reading
    bus.write_byte_data(BME680_ADDR, REG_CTRL_MEAS, 0x21)

    # Give the sensor a moment to finish the conversion
    time.sleep(0.1)

    # Read 3 bytes of temperature data
    data = bus.read_i2c_block_data(BME680_ADDR, REG_TEMP_DATA, 3)
    temp_adc = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)

    # Bosch compensation formula
    var1 = ((temp_adc / 16384.0) - (t1 / 1024.0)) * t2
    var2 = (((temp_adc / 131072.0) - (t1 / 8192.0)) ** 2) * (t3 * 16.0)
    t_fine = var1 + var2
    return t_fine / 5120.0


class FufuStatusPanel(BoxLayout):
    """Right-hand status bar for the Fufu page."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(14), spacing=dp(10), **kwargs)
        self.size_hint_x = 0.22

        title = Label(
            text="Machine state",
            font_size="20sp",
            bold=True,
            halign="left",
            valign="middle",
            color=(0.1, 0.1, 0.1, 1),
        )
        title.bind(size=title.setter("text_size"))
        self.add_widget(title)

        # Fixed placeholder values
        self.add_widget(Label(text="power required:", font_size="14sp", halign="left", valign="middle"))
        self.add_widget(Label(text="30 kW", font_size="16sp", bold=True, halign="left", valign="middle"))

        self.add_widget(Widget(size_hint_y=None, height=dp(8)))

        self.add_widget(Label(text="light remaining:", font_size="14sp", halign="left", valign="middle"))
        self.add_widget(Label(text="4 hours", font_size="16sp", bold=True, halign="left", valign="middle"))

        self.add_widget(Widget(size_hint_y=None, height=dp(12)))

        # Live / updated labels
        self.light_label = Label(text="light intensity: 300 lx", font_size="14sp", halign="left", valign="middle")
        self.weight_label = Label(text="weight: 300 g", font_size="14sp", halign="left", valign="middle")
        self.temp_label = Label(text="current pot temp: 40 °C", font_size="14sp", halign="left", valign="middle")

        for lbl in (self.light_label, self.weight_label, self.temp_label):
            lbl.bind(size=lbl.setter("text_size"))
            self.add_widget(lbl)

        # Start a small background thread to refresh from the sensor file
        threading.Thread(target=self._sensor_loop, daemon=True).start()

    def _sensor_loop(self):
        t1, t2, t3 = get_bme_calib()
        setup()
        while True:
            def _update_labels(dt):
                lux = read_light_level()
                w = read_weight()
                temp = read_pot_temperature(t1, t2, t3)
                self.light_label.text = f"light intensity: {lux:.0f} lx"
                self.weight_label.text = f"weight: {w:.0f} g"
                self.temp_label.text = f"current pot temp: {temp:.1f} °C"

            # UI updates must be scheduled on the main thread
            Clock.schedule_once(_update_labels, 0)
            time.sleep(2)


def build_fufu_page(on_home, on_start_timer):
    """Return the root widget for the Fufu page."""

    root = BoxLayout(orientation="horizontal", spacing=dp(10), padding=(dp(10), dp(6), dp(10), dp(10)))

    # LEFT + CENTER AREA
    main_col = BoxLayout(orientation="vertical", spacing=dp(10))

    # Top row: home button near top-left + wide (taller) image panel
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

    # Fufu image panel
    image_panel = BoxLayout(orientation="vertical", padding=dp(10))
    image_panel.size_hint_x = 1.0

    fufu_image_path = os.path.join(IMAGES_DIR, "fufu.png")
    img = Image(
        source=fufu_image_path if os.path.exists(fufu_image_path) else "",
        allow_stretch=True,
        keep_ratio=True,
    )
    image_panel.add_widget(img)

    # Left column in top row contains home + Start cooking stacked vertically
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

    # Middle: orange recipe panel with scrollable text
    recipe_panel = BoxLayout(orientation="vertical", padding=dp(10))
    recipe_panel.size_hint_y = 1.0
    recipe_panel.canvas.before.clear()
    with recipe_panel.canvas.before:
        from kivy.graphics import Color, RoundedRectangle

        Color(1.0, 0.75, 0.3, 1)
        recipe_panel._rect = RoundedRectangle(pos=recipe_panel.pos, size=recipe_panel.size, radius=[dp(18)])

    def _update_rect(*_):
        recipe_panel._rect.pos = recipe_panel.pos
        recipe_panel._rect.size = recipe_panel.size

    recipe_panel.bind(pos=_update_rect, size=_update_rect)

    recipe_text = _load_recipe_text(FUFU_RECIPE_PATH)
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

    # RIGHT STATUS PANEL
    status_panel = FufuStatusPanel()

    root.add_widget(main_col)
    root.add_widget(status_panel)

    return root

