APP_STYLESHEET = r"""
QWidget {
    background: #0a0e13;
    color: #edf2f7;
    font-family: "SF Pro Display", "Inter", "Arial";
    font-size: 14px;
}

QMainWindow {
    background: #0a0e13;
}

#sidebar {
    background: #0d131a;
    border-right: 1px solid #1e2935;
}

#brand {
    font-size: 21px;
    font-weight: 800;
    letter-spacing: 1px;
}

#brandCaption {
    color: #657487;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}

#topbar {
    background: #0d131a;
    border: 1px solid #1e2935;
    border-radius: 12px;
}

QPushButton {
    min-height: 36px;
    background: #151d26;
    border: 1px solid #263342;
    border-radius: 9px;
    padding: 4px 13px;
    font-weight: 600;
}

QPushButton:hover {
    background: #1a2531;
    border-color: #38506a;
}

QPushButton:pressed {
    background: #111923;
    border-color: #446482;
}

QPushButton:disabled {
    color: #566270;
    background: #10161d;
    border-color: #1b2530;
}

QPushButton[role="primary"] {
    background: #1b5f9e;
    border-color: #2f7dc2;
    color: #ffffff;
}

QPushButton[role="primary"]:hover {
    background: #226fb5;
    border-color: #4192d9;
}

QPushButton[role="danger"] {
    background: #24171a;
    border-color: #573037;
    color: #f0a3ac;
}

QPushButton[role="danger"]:hover {
    background: #321b20;
    border-color: #79404a;
}

QPushButton[role="ghost"] {
    background: transparent;
    border-color: #23303d;
    color: #aeb9c6;
}

QPushButton[role="ghost"]:hover {
    background: #121a23;
    color: #ffffff;
}

QPushButton[nav="true"] {
    min-height: 42px;
    text-align: left;
    padding: 3px 14px;
    background: transparent;
    border: 1px solid transparent;
    color: #aeb8c4;
    font-weight: 600;
}

QPushButton[nav="true"]:hover {
    background: #131c25;
    color: #f4f7fa;
}

QPushButton[nav="true"][selected="true"] {
    background: #152638;
    border-color: #244b70;
    color: #ffffff;
    font-weight: 700;
}

QPushButton[mode="true"] {
    min-width: 112px;
    min-height: 38px;
    border-radius: 9px;
    background: transparent;
    border-color: transparent;
    color: #8492a2;
}

QPushButton[mode="true"]:hover {
    background: #121a23;
    color: #dfe7ef;
}

QPushButton[mode="true"][selected="true"] {
    background: #18324a;
    border-color: #285d88;
    color: #ffffff;
    font-weight: 800;
}

QPushButton[quick="true"] {
    min-height: 42px;
    text-align: left;
    padding-left: 15px;
    background: #10171f;
    border-color: #202d3a;
}

QPushButton[quick="true"]:hover {
    background: #16212c;
    border-color: #37516b;
}

#collapseButton {
    min-width: 38px;
    max-width: 38px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    background: #121a23;
    border-color: #253342;
    font-size: 18px;
}

QFrame[card="true"] {
    background: #0f161e;
    border: 1px solid #202c38;
    border-radius: 13px;
}

QFrame[card="true"]:hover {
    border-color: #2a3b4d;
}

QFrame[video="true"] {
    background: #020406;
    border: 1px solid #202c38;
    border-radius: 14px;
}

QFrame[toolbar="true"] {
    background: #0f161e;
    border: 1px solid #202c38;
    border-radius: 11px;
}

QFrame[modeSelector="true"] {
    background: #101820;
    border: 1px solid #202d3a;
    border-radius: 11px;
}

QLabel[muted="true"] {
    color: #8290a0;
}

QLabel[title="true"] {
    font-size: 27px;
    font-weight: 800;
}

QLabel[section="true"] {
    font-size: 16px;
    font-weight: 750;
}

QLabel[eyebrow="true"] {
    color: #6285a5;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel[metricValue="true"] {
    font-size: 17px;
    font-weight: 800;
}

QLabel[metricCaption="true"] {
    color: #718093;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

QLabel[status="ready"] {
    background: #10251a;
    border: 1px solid #275a38;
    color: #78dda0;
    border-radius: 9px;
    padding: 5px 10px;
    font-weight: 800;
}

QLabel[status="warning"] {
    background: #2a2111;
    border: 1px solid #655022;
    color: #efc567;
    border-radius: 9px;
    padding: 5px 10px;
    font-weight: 800;
}

QLabel[status="offline"] {
    background: #171d24;
    border: 1px solid #2b3744;
    color: #8491a0;
    border-radius: 9px;
    padding: 5px 10px;
    font-weight: 700;
}

QLabel[status="error"] {
    background: #291719;
    border: 1px solid #633238;
    color: #f28d98;
    border-radius: 9px;
    padding: 5px 10px;
    font-weight: 800;
}

QLabel[topInfo="true"] {
    background: #101820;
    border: 1px solid #202d3a;
    border-radius: 9px;
    padding: 6px 10px;
    color: #a7b2be;
    font-weight: 650;
}

QLabel#videoTitle {
    background: transparent;
    color: #d8e0e8;
    font-size: 19px;
    font-weight: 750;
}

QLabel#videoHint {
    background: transparent;
    color: #657383;
    font-size: 13px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QToolTip {
    background: #121a23;
    color: #edf2f7;
    border: 1px solid #314153;
    padding: 6px;
}
"""
