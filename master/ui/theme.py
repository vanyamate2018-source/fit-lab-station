APP_STYLESHEET = r"""
QWidget {
    background: #0b0f14;
    color: #e8edf3;
    font-family: "SF Pro Display", "Inter", "Arial";
    font-size: 14px;
}
QMainWindow { background: #0b0f14; }
#sidebar {
    background: #0f151c;
    border-right: 1px solid #202a35;
}
#brand {
    font-size: 20px;
    font-weight: 700;
}
QPushButton {
    background: #151c24;
    border: 1px solid #263240;
    border-radius: 8px;
    padding: 9px 12px;
}
QPushButton:hover {
    background: #1a2430;
    border-color: #334354;
}
QPushButton:pressed { background: #101820; }
QPushButton:disabled {
    color: #66717d;
    background: #11171e;
    border-color: #1d2630;
}
QPushButton[nav="true"] {
    text-align: left;
    padding: 11px 14px;
    border: 1px solid transparent;
    background: transparent;
}
QPushButton[nav="true"]:hover { background: #151d26; }
QPushButton[nav="true"][selected="true"] {
    background: #172330;
    border-color: #29435d;
    font-weight: 600;
}
QPushButton[mode="true"] {
    min-width: 100px;
    border-radius: 9px;
}
QPushButton[mode="true"][selected="true"] {
    background: #1d3144;
    border-color: #3f6b91;
    font-weight: 700;
}
QFrame[card="true"] {
    background: #10171f;
    border: 1px solid #202c38;
    border-radius: 12px;
}
QFrame[video="true"] {
    background: #020304;
    border: 1px solid #202a35;
    border-radius: 12px;
}
QLabel[muted="true"] { color: #84909d; }
QLabel[title="true"] {
    font-size: 25px;
    font-weight: 700;
}
QLabel[section="true"] {
    font-size: 16px;
    font-weight: 700;
}
QLabel[pill="true"] {
    background: #142119;
    border: 1px solid #285036;
    border-radius: 9px;
    padding: 5px 10px;
    font-weight: 700;
}
QLabel[metricValue="true"] {
    font-size: 16px;
    font-weight: 700;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget { background: transparent; }
"""
