"""Shared timer page with circular countdown animation."""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.relativelayout import RelativeLayout
from kivy.graphics import Color, Ellipse

TOTAL_SECONDS = 300.0  # 5 minutes


class CircleTimer(RelativeLayout):
    """Draws only the circular progress ring — no label inside."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress = 1.0  # 1.0 = full circle, 0.0 = empty
        with self.canvas:
            Color(0.25, 0.25, 0.35, 1)
            self._bg = Ellipse()
            Color(1.0, 0.7, 0.3, 1)
            self._fg = Ellipse()
        self.bind(pos=self._update_graphics, size=self._update_graphics)

    def _update_graphics(self, *args):
        size = min(self.width, self.height) * 0.9
        x = self.center_x - size / 1.75
        y = self.center_y - size / 0.75
        self._bg.pos = (x, y)
        self._bg.size = (size, size)
        self._fg.pos = (x, y)
        self._fg.size = (size, size)
        self._fg.angle_start = 0
        self._fg.angle_end = 360 * self.progress

    def set_progress(self, remaining_seconds: float):
        remaining_seconds = max(0.0, min(TOTAL_SECONDS, remaining_seconds))
        self.progress = remaining_seconds / TOTAL_SECONDS
        self._update_graphics()


def build_timer_page(on_home):
    root = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))

    # ── Top row: Home button ──────────────────────────────────────────────────
    top_row = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(60),
    )
    home_btn = Button(
        text="Home",
        size_hint=(None, None),
        width=dp(100),
        height=dp(50),
        background_normal="",
        background_color=(0.9, 0.3, 0.25, 1),
        color=(1, 1, 1, 1),
        border=(0, 0, 0, 0),
        # FIX: do NOT pass on_press here — bind it below to avoid double-firing
    )
    top_row.add_widget(home_btn)
    top_row.add_widget(Widget())       # pushes button to the left
    root.add_widget(top_row)

    # ── Centre: circle + time label stacked vertically ───────────────────────
    # FIX: replace the broken "spacer + timer + spacer" BoxLayout trick with a
    # simple vertical stack.  The CircleTimer fills all available space
    # (size_hint=(1, 1)) so it stays centred automatically.
    centre_area = BoxLayout(orientation="vertical", spacing=dp(8))

    timer_widget = CircleTimer(size_hint=(1, 1))  # fills the centre area

    # FIX: label lives OUTSIDE the RelativeLayout so it appears below the ring
    time_label = Label(
        text="05:00",
        font_size="48sp",
        bold=True,
        color=(1, 1, 1, 1),
        size_hint=(1, None),
        height=dp(60),
    )

    centre_area.add_widget(timer_widget)
    centre_area.add_widget(time_label)
    root.add_widget(centre_area)

    # ── Bottom row: Pause / Resume button ────────────────────────────────────
    bottom_row = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(70),
        spacing=dp(20),
    )
    # FIX: size_hint_x=1 makes the button span the full row width — a large
    # touch target that is impossible to miss on a touchscreen.
    pause_btn = Button(
        text="Pause",
        size_hint=(1, None),      # ← full width, fixed height
        height=dp(55),
        background_normal="",
        background_color=(1.0, 0.6, 0.25, 1),
        color=(0.1, 0.1, 0.1, 1),
        font_size="20sp",
        bold=True,
        border=(0, 0, 0, 0),
    )
    bottom_row.add_widget(pause_btn)
    root.add_widget(bottom_row)

    # ── Timer state & logic ───────────────────────────────────────────────────
    # Use a list so the inner functions can rebind the value via index
    # (avoids any Python-closure ambiguity with plain booleans)
    running = [True]
    remaining = [TOTAL_SECONDS]

    # Initialise display
    timer_widget.set_progress(TOTAL_SECONDS)
    time_label.text = "05:00"

    def tick(dt):
        if not running[0]:          # paused — do nothing
            return
        remaining[0] -= dt
        if remaining[0] <= 0:
            remaining[0] = 0.0
            running[0] = False
        timer_widget.set_progress(remaining[0])
        m = int(remaining[0]) // 60
        s = int(remaining[0]) % 60
        time_label.text = f"{m:02d}:{s:02d}"

    clock_event = Clock.schedule_interval(tick, 0.05)

    # Debounce: store the last time each button fired.
    # Any second trigger arriving within DEBOUNCE_S seconds is discarded.
    DEBOUNCE_S = 0.4
    last_pause_time = [0.0]
    last_home_time  = [0.0]

    def on_pause_release(instance, *_):
        now = Clock.get_time()
        if now - last_pause_time[0] < DEBOUNCE_S:
            return                          # duplicate touch — ignore
        last_pause_time[0] = now
        running[0] = not running[0]
        instance.text = "Resume" if not running[0] else "Pause"

    pause_btn.bind(on_release=on_pause_release)

    def on_home_release(*_):
        now = Clock.get_time()
        if now - last_home_time[0] < DEBOUNCE_S:
            return
        last_home_time[0] = now
        clock_event.cancel()
        on_home()

    home_btn.bind(on_release=on_home_release)

    return root