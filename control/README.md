# Модуль управления

Будущий отдельный headless-модуль.

План:
- PAN / TILT;
- сервоприводы;
- CRSF;
- INA219;
- IMU;
- датчики положения;
- watchdog и безопасное состояние.

В обычном интерфейсе INA219 показывает только напряжение.


## FIT-LAB Control v1

Полный план будущего контура управления зафиксирован в [docs/control](../docs/control/README.md).

Целевая цепочка:

`Пульт → Mac → LAN → Orange Pi → UART → RP2040/FreeRTOS → CRSF → FIT-LAB TX → ExpressLRS → FIT-LAB RX → CRSF → Flight Controller`.

Для TX предусмотрена отдельная Power Board с программным включением/выключением через RP2040 и контролем питания. Видео WFB-ng остаётся независимым трактом.
