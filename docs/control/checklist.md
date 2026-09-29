# FIT-LAB Control — чек-лист

## A. Архитектура

- [x] Отделить управление от видеоприёма.
- [x] Зафиксировать путь Mac → LAN → Orange Pi → RP2040 → CRSF → TX → RF → RX → FC.
- [x] Зафиксировать обратный путь телеметрии.
- [x] Выбрать RP2040 как realtime bridge.
- [x] Решить, что TX и RX получают собственные FIT-LAB сборки.
- [x] Сохранить ExpressLRS OTA совместимость в первой версии.

## B. Mac / органы управления

- [ ] Определить точную модель пульта для стенда.
- [ ] Проверить TX12 как USB HID/Simulator на Mac.
- [ ] Создать input profile.
- [ ] Калибровка стиков.
- [ ] Mapping 16 каналов.
- [ ] Отдельный ARM state.
- [ ] UI диагностики входов.

## C. FIT-LAB Control Protocol

- [ ] Зафиксировать бинарный wire format v1.
- [ ] Session ID.
- [ ] Sequence counter.
- [ ] Monotonic timestamp.
- [ ] 16 RC channels.
- [ ] ARM/AUX flags.
- [ ] CRC.
- [ ] Authentication tag.
- [ ] Anti-replay.
- [ ] Версионирование.
- [ ] Тесты serialize/parse/fuzz.

## D. Orange Pi Control service

- [ ] LAN receiver.
- [ ] Master authentication.
- [ ] Control lease.
- [ ] UART backend.
- [ ] Heartbeat RP2040.
- [ ] Telemetry uplink.
- [ ] Structured logging.
- [ ] Reconnect.
- [ ] Systemd service.
- [ ] Boot autostart.
- [ ] FIT-LAB branded boot splash / Plymouth.
- [ ] Переход Plymouth → FIT-LAB splash без видимого рабочего стола Linux.

## E. RP2040 Bridge

- [ ] Pico SDK project.
- [ ] UART host protocol.
- [ ] CRSF encoder.
- [ ] CRSF parser.
- [ ] RC_CHANNELS_PACKED.
- [ ] Extended CRSF device frames.
- [ ] Telemetry parser.
- [ ] Watchdog.
- [ ] Safe state.
- [ ] Status LED.
- [ ] Version command.
- [ ] Bootloader/update.
- [ ] Unit tests.
- [ ] Logic analyzer timing test.

## F. FIT-LAB TX / Ranger

- [ ] Зафиксировать exact hardware target.
- [ ] Зафиксировать upstream ExpressLRS commit.
- [ ] Собрать unmodified upstream target.
- [ ] Проверить восстановление штатной прошивки.
- [ ] Создать FIT-LAB TX build.
- [ ] Имя FIT-LAB TX.
- [ ] FIT-LAB version.
- [ ] Device info.
- [ ] Telemetry.
- [ ] Parameter read/write.
- [ ] TX power.
- [ ] Dynamic Power.
- [ ] Packet Rate.
- [ ] Telemetry Ratio.
- [ ] Model Match.
- [ ] Bind.
- [ ] Thermal/fan status, если target подтверждает.
- [ ] Стендовый RF тест.

## G. FIT-LAB RX

- [ ] Выбрать первый RX target.
- [ ] Зафиксировать upstream commit.
- [ ] Собрать unmodified target.
- [ ] Создать FIT-LAB RX build.
- [ ] Имя FIT-LAB RX.
- [ ] FIT-LAB version.
- [ ] CRSF output.
- [ ] FC telemetry return.
- [ ] Failsafe test.
- [ ] Recovery/rollback test.

## H. FIT-LAB UI

- [ ] Раздел «Управление».
- [ ] Отображение стиков/каналов.
- [ ] Control connection state.
- [ ] RP2040 state.
- [ ] TX state.
- [ ] RX state.
- [ ] LQ / RSSI / SNR.
- [ ] TX power.
- [ ] Packet rate.
- [ ] Telemetry ratio.
- [ ] Device versions.
- [ ] Parameter editor.
- [ ] Bind action.
- [ ] Model Match.
- [ ] Service diagnostics.
- [ ] Критические действия с подтверждением.

## I. Failsafe

- [ ] Потеря USB/HID на Mac.
- [ ] Зависание FIT-LAB Station.
- [ ] Потеря LAN.
- [ ] Перезапуск Orange Pi.
- [ ] Потеря UART.
- [ ] Reset RP2040.
- [ ] Потеря CRSF до TX.
- [ ] Потеря RF.
- [ ] Reset RX.
- [ ] Проверить, что reconnect не ARM-ит систему автоматически.
- [ ] Проверить FC failsafe без моторов.

## J. Испытания

- [ ] Без RF.
- [ ] RF без FC.
- [ ] FC без моторов/пропеллеров.
- [ ] Длительный bench test.
- [ ] Проверка задержки.
- [ ] Проверка jitter.
- [ ] Проверка packet loss.
- [ ] Проверка питания и температуры.
- [ ] Проверка восстановления после сбоев.
- [ ] Полевой тест только после закрытия стендового чек-листа.

## K. Документация

- [x] Общий план FIT-LAB Control.
- [x] Архитектура.
- [x] План прошивок.
- [x] Чек-лист.
- [ ] Электрическая схема Orange Pi ↔ RP2040 ↔ Ranger.
- [ ] PDF-схема.
- [ ] Инструкция сборки Bridge.
- [ ] Инструкция прошивки TX.
- [ ] Инструкция прошивки RX.
- [ ] Таблица совместимых target.
- [ ] Руководство оператора.


## L. FreeRTOS / Power Board

- [x] Зафиксировать FreeRTOS для RP2040 Bridge.
- [x] Зафиксировать приоритет CRSF/watchdog над сервисными задачами.
- [x] Зафиксировать отдельную цифровую Power Board.
- [ ] Выбрать high-side switch/eFuse.
- [ ] Выбрать датчик напряжения/тока после измерения Ranger.
- [ ] Спроектировать Power Good/Fault линии.
- [ ] Реализовать TX power state machine.
- [ ] Проверить normal shutdown.
- [ ] Проверить emergency power cut.
- [ ] Проверить undervoltage/overcurrent fault.

## M. UI / Demo

- [x] Зафиксировать единый экран Video + Control.
- [x] Зафиксировать Cyan и Amber темы.
- [x] Подготовить интерактивный тестовый макет.
- [ ] Встроить Control page в реальный PySide6 Master.
- [ ] Добавить переключатель темы в настройки.
- [ ] Добавить реальные статусы RP2040/Power Board/TX/RX.
