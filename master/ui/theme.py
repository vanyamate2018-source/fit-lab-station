"""FIT-LAB themes: graphite base with selectable Amber and Cyan accents."""
import os

THEME_NAMES = ("amber", "cyan")


def selected_theme(name=None):
    value = (name or os.environ.get("FIT_LAB_THEME", "amber")).strip().lower()
    return value if value in THEME_NAMES else "amber"


def _stylesheet_for(name):
    if name == "amber":
        return APP_STYLESHEET
    replacements = {
        "#ffcc87":"#7ed4ff", "#ffca78":"#53c7ff", "#f1c997":"#83d9ff",
        "#ffc570":"#5dccff", "#ffc56f":"#5dccff", "#f8d0a3":"#bdeaff",
        "#f3c89e":"#bdeaff", "#d5b888":"#79cfff", "#ffd18b":"#5fd0ff",
        "#fff2dc":"#eaf8ff", "#e2b574":"#4ec5ff", "#ffdcad":"#d8f4ff",
        "#ffc675":"#39bfff", "#ffd291":"#6ad1ff", "#ffc271":"#29b6ff",
        "#ffe0a5":"#d9f3ff", "#dda45d":"#38bfff", "#ffe0a8":"#bdeaff",
        "#544833":"#173d53", "#ffdea9":"#d9f5ff", "#ffd090":"#4fcaff",
        "#775b34":"#17435c", "#685338":"#17435c", "#ab9877":"#3c6e85",
        "#f1bf77":"#4ac5ff", "#9e7646":"#176a93", "#795b32":"#17435c",
    }
    sheet = APP_STYLESHEET
    for old, new in replacements.items():
        sheet = sheet.replace(old, new)
    return sheet


def apply_theme(app, name=None):
    from PySide6.QtGui import QPalette, QColor
    theme = selected_theme(name)
    app.setStyle("Fusion")
    palette = QPalette()
    accent = "#795b32" if theme == "amber" else "#176a93"
    for role, color in ((QPalette.ColorRole.Window, "#182023"),
                        (QPalette.ColorRole.Base, "#233035"),
                        (QPalette.ColorRole.AlternateBase, "#28353a"),
                        (QPalette.ColorRole.WindowText, "#f1f3f3"),
                        (QPalette.ColorRole.Text, "#f1f3f3"),
                        (QPalette.ColorRole.Button, "#2c393d"),
                        (QPalette.ColorRole.ButtonText, "#f1f3f3"),
                        (QPalette.ColorRole.Highlight, accent),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"),
                        (QPalette.ColorRole.PlaceholderText, "#c2cbce")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#b7c3c7"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#b7c3c7"))
    app.setPalette(palette)
    app.setProperty("fitLabTheme", theme)
    app.setStyleSheet(_stylesheet_for(theme))


APP_STYLESHEET = r"""
QMainWindow, #stationRoot { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1b1f1f,stop:.55 #111617,stop:1 #151a1b); }
QWidget { background: transparent; color: #eeefed; font-family: "Avenir Next"; font-size: 14px; }
QWidget[stationPage="true"] { background: #151a1b; }
QLabel { background: transparent; }
QLabel[title="true"] { font-size: 13px; font-weight: 400; letter-spacing: 2px; color: #dddfde; }
QLabel[section="true"] { font-size: 16px; font-weight: 500; color: #ffcc87; }
QLabel[heroValue="true"] { font-size: 28px; font-weight: 500; color: #ffca78; }
QLabel[muted="true"] { color: #c3c7c7; }
QLabel[eyebrow="true"] { color: #f1c997; font-size: 12px; font-weight: 500; letter-spacing: 1.5px; }
QLabel[metricCaption="true"] { color: #c4caca; font-size: 10px; font-weight: 400; letter-spacing: 1px; }
QLabel[metricValue="true"] { color: #ffc570; font-family: "Menlo"; font-size: 19px; font-weight: 500; }
QLabel[instrumentValue="true"] { font-family: "Menlo"; font-size: 16px; color: #eeeeeb; }
QLabel[inlineValue="true"] { color: #ffc56f; font-family: "Menlo"; font-size: 15px; }
QLabel[receiverName="true"] { color: #dddfdc; font-family: "Menlo"; font-size: 18px; }
QLabel[receiverValue="true"] { color: #edece6; font-family: "Menlo"; font-size: 18px; }
#brandWordmark { font-family: "Avenir Next"; font-size: 24px; font-weight: 600; font-style: italic; color: #f8d0a3; letter-spacing: 3px; }
#footerBrand { font-size: 22px; font-weight: 500; letter-spacing: 2px; color: #f3c89e; padding: 0 14px; }
#sidebar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1c2221,stop:.5 #121819,stop:1 #171d1e); border-top: 1px solid #666052; }
QFrame[card="true"] { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #202526,stop:.55 #161b1c,stop:1 #191e1e); border: 1px solid #62665e; border-radius: 6px; }
QFrame[metric="true"] { background: transparent; border: none; border-right: 1px solid #565d5b; border-radius: 0; }
#telemetryStrip { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #171d1f,stop:1 #202626); border: 1px solid #565d58; border-radius: 5px; }
#receiverTile { background: transparent; border: none; border-top: 1px solid #414848; border-radius: 0; }
#receiverTile QWidget { background: transparent; }
#cameraQuickRow { background: transparent; border: none; border-top: 1px solid #414747; border-radius: 0; }
#controlSeparator { background: #4b5251; border: none; }
#mediaDock { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #252b2b,stop:.48 #141b1d,stop:1 #212a2b); border: 1px solid #65695e; border-radius: 6px; }
QPushButton, QToolButton { background: #282f30; border: 1px solid #666f6d; border-radius: 7px; padding: 4px 14px; min-height: 46px; font-weight: 500; }
QPushButton:hover, QToolButton:hover { background: #354041; border-color: #d5b888; }
QPushButton:pressed, QToolButton:pressed { background: #58472d; border-color: #ffd18b; color: #fff2dc; }
QPushButton:disabled, QToolButton:disabled { background: #1c2324; border-color: #424e4e; color: #939c9b; }
QPushButton[iconOnly="true"] { padding: 0; min-height: 0; }
QPushButton[inspectorArrow="true"] { border: none; background: transparent; padding: 0; min-height: 0; }
QPushButton[role="primary"] { background: #53432d; border-color: #e2b574; color: #ffdcad; }
QPushButton[role="danger"] { background: #452b2b; border-color: #c07b71; color: #ffd8cd; }
QPushButton[active="true"] { background: #52432c; border-color: #ffc675; color: #ffdcad; }
QPushButton[transportChoice="true"]:checked { background: #52432c; border-color: #ffc675; color: #ffdcad; }
QPushButton[recordAction="true"][active="true"] { background: #552b2b; border-color: #ff7668; color: #ffe1d9; }
QToolButton[nav="true"], QToolButton[dockAction="true"] { background: transparent; border: none; padding: 0; min-height: 0; }
QComboBox, QSpinBox, QLineEdit { min-height: 44px; padding: 4px 12px; background: #222b2d; border: 1px solid #6c7877; border-radius: 6px; selection-background-color: #775b34; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #ffd090; }
QComboBox::drop-down { width: 30px; border: none; }
QComboBox QAbstractItemView { background: #283234; color: #f4f6f5; selection-background-color: #685338; selection-color: #ffffff; min-height: 46px; border: 1px solid #8c9b9d; }
QComboBox QAbstractItemView::item { min-height: 48px; }
QSpinBox::up-button, QSpinBox::down-button { width: 30px; }
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { color: #b6c0c3; border-color: #536064; }
QTabWidget::pane { background: #1b2426; border: 1px solid #5e6b6a; border-radius: 6px; }
QTabBar::tab { padding: 14px 20px; color: #d0d5d4; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #ffd291; border-bottom-color: #ffc271; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 12px; background: #192426; }
QScrollBar::handle:vertical { background: #758180; border-radius: 5px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QPlainTextEdit { background: #152123; border: 1px solid #576a6b; border-radius: 7px; padding: 12px; }
QDialog { background: #242e2f; }
QLabel#toast { color: #ffe0a5; background: transparent; }
QLabel[status] { padding: 3px 10px; border: none; font-size: 11px; font-weight: 500; letter-spacing: 1px; }
QLabel[status="ready"] { background: transparent; color: #6fe3a4; }
QLabel[status="warning"] { background: transparent; color: #ffd08a; }
QLabel[status="offline"] { background: transparent; color: #ff948a; }
QLabel[status="error"] { background: transparent; color: #ff9c89; }
QPushButton[role="primary"]:disabled, QPushButton[role="danger"]:disabled { background: #242e2f; border-color: #526262; color: #93a3a2; }
QToolTip { background: #303c3d; color: #f7f6ee; border: 1px solid #ab9877; padding: 8px; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 28px; height: 28px; border-radius: 6px; border: 1px solid #9faeaa; background: #253336; }
QCheckBox::indicator:checked { background: #dda45d; border: 5px solid #ffe0a8; }
#cameraSections { background: #19272a; border: none; border-right: 1px solid #576966; padding: 6px; }
#cameraSections::item { min-height: 46px; padding: 6px 10px; border-radius: 5px; }
#cameraSections::item:selected { background: #544833; color: #ffdea9; }
QPushButton[stepper="true"] { min-width: 46px; max-width: 46px; min-height: 46px; max-height: 46px; padding: 0; font-size: 22px; color: #ffd291; }
"""
