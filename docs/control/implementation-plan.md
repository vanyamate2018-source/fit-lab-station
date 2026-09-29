# FIT-LAB Control - план реализации v1

## Цель

Создать единый проект FIT-LAB Station с независимыми трактами видео и управления.

### Видео
`Камера -> WFB-ng -> Модуль видеоприёма RX1/RX2 -> LAN -> FIT-LAB Station -> декодер/экран/запись/трансляция`

### Управление
`Пульт/джойстик -> Mac -> LAN -> Orange Pi 3B -> UART -> RP2040 + FreeRTOS -> CRSF -> FIT-LAB TX -> ExpressLRS RF -> FIT-LAB RX -> CRSF -> Flight Controller`

### Телеметрия
Идёт в обратную сторону через RX -> RF -> TX -> RP2040 -> Orange Pi -> LAN -> Master.

## Жёстко зафиксированные решения

1. Видео и управление не объединять в один RF-канал.
2. Linux на Orange Pi не является последним уровнем failsafe.
3. RP2040 выполняет realtime CRSF, watchdog, контроль питания и безопасное состояние.
4. Прошивка RP2040 строится на Pico SDK + FreeRTOS, с фиксированными приоритетами задач и без блокирующих операций в критическом тракте.
5. FIT-LAB TX и FIT-LAB RX - собственные сборки на базе ExpressLRS с собственными версиями и идентификацией FIT-LAB.
6. В v1 OTA-совместимость ExpressLRS сохраняется; физический радиопротокол не переписывается.
7. Функции ELRS Lua переносятся в нативный CRSF Device Manager FIT-LAB.
8. Питание TX управляется отдельной цифровой FIT-LAB Power Board через RP2040, а не напрямую Linux GPIO.
9. Power Board измеряет напряжение и, по возможности, ток/мощность; обычный UI показывает минимум напряжение и состояние питания, расширенные значения - в диагностике.
10. Reconnect никогда не должен автоматически возвращать ARM.
11. Прошивки/обновления TX/RX запрещены во время активного управления.
12. Все реальные тесты начинаются без пропеллеров и без полёта.

## Этапы

### Этап 0 - документация и интерфейсы
- Зафиксировать точные модели TX/RX/RP2040/Power Board.
- Зафиксировать GPIO и электрические уровни.
- Зафиксировать Control Protocol v1 и CRSF subset.
- Зафиксировать state machines и failsafe matrix.

### Этап 1 - Mac input
- USB HID TX12/джойстик.
- Калибровка, deadband, mapping 16 каналов.
- Отдельный ARM state.
- Симулятор входов и запись тестовых трасс.

### Этап 2 - LAN control
- UDP control frames 100-250 Hz.
- Session ID, sequence, monotonic timestamp, CRC/auth tag, anti-replay.
- Отдельный надёжный канал для конфигурации/обновлений.

### Этап 3 - Orange Pi service
- Демон управления.
- UART backend к RP2040.
- Heartbeat, telemetry, structured logs, systemd, autostart.
- Брендированный Plymouth + FIT-LAB splash.

### Этап 4 - RP2040 FreeRTOS Bridge
Высокий приоритет:
- CRSF realtime TX/RX.
- Watchdog/failsafe.

Средний приоритет:
- Host UART parser.
- Control state manager.
- Telemetry parser.

Низкий приоритет:
- Power Board state.
- Voltage/current sampling.
- LED/diagnostics/update service.

### Этап 5 - Power Board
- High-side electronic switch/eFuse for Ranger power.
- Команда ON/OFF только через проверенную state machine RP2040.
- Power-good/overcurrent/undervoltage feedback.
- Voltage sensor; current/power sensor after measurement of Ranger consumption.
- Без механического реле в финальной версии.

### Этап 6 - FIT-LAB TX firmware
- Стандартный Ranger target сначала собрать без изменений.
- Recovery path проверить заранее.
- Затем FIT-LAB name/version/build ID/device info.
- CRSF parameters, telemetry, packet rate, power, Dynamic Power, Model Match, Bind.
- Встроенный heartbeat/diagnostics без изменения OTA v1.

### Этап 7 - FIT-LAB RX firmware
- Выбрать конкретный RX target.
- Сначала unmodified build + recovery.
- FIT-LAB name/version/build ID.
- CRSF output, FC telemetry, failsafe, diagnostics.

### Этап 8 - FIT-LAB Master UI
- Единый экран Video + Control.
- Отдельные полноэкранные разделы Video / Control / Telemetry / Map.
- Статусы Orange Pi, RP2040, Power Board, TX, RX.
- LQ/RSSI/SNR, packet rate, TX power, voltage, failsafe.
- Cyan и Amber темы.
- Критические действия требуют подтверждения.

### Этап 9 - стендовые испытания
- Без RF.
- RF без FC.
- FC без моторов/пропеллеров.
- Потеря USB/HID, LAN, UART, RP2040 reset, TX reset, RF loss, RX reset.
- Длительный soak test, latency, jitter, packet loss, temperature, power.

### Этап 10 - поле
Только после закрытия стендового чек-листа.
