# FIT-LAB Control

FIT-LAB Control — отдельная подсистема управления в составе FIT-LAB Station.

Цель: отделить видеоприём от управления и построить независимый канал управления с собственными компонентами FIT-LAB поверх проверенной RF-базы ExpressLRS/CRSF.

## Целевая схема

```text
RadioMaster TX12 / другой орган управления
        │ USB HID
        ▼
Mac / FIT-LAB Station
        │ Ethernet / LAN
        ▼
Orange Pi 3B — Модуль управления
        │ UART 3.3 V
        ▼
RP2040 — FIT-LAB Control Bridge
        │ CRSF
        ▼
FIT-LAB TX Firmware
RadioMaster Ranger 2.4 GHz
        │ ExpressLRS RF
        ▼
FIT-LAB RX Firmware
бортовой ELRS-приёмник
        │ CRSF
        ▼
Flight Controller
```

Обратный путь телеметрии идёт в противоположную сторону:

```text
Flight Controller → FIT-LAB RX → RF → FIT-LAB TX → RP2040
→ Orange Pi → LAN → FIT-LAB Station
```

## Главные принципы

- Видеоканал WFB-ng и канал управления не зависят друг от друга.
- Mac формирует команды оператора, но не выполняет realtime-тайминги CRSF/RF.
- Orange Pi отвечает за сетевой транспорт, состояние Control-модуля и оркестрацию.
- RP2040 отвечает за realtime-мост, watchdog и безопасное завершение управляющего потока.
- FIT-LAB TX и FIT-LAB RX используют собственные сборки прошивки.
- На первом этапе OTA-совместимость ExpressLRS сохраняется; радиопротокол не переписывается без отдельной причины и стендовой валидации.
- Потеря LAN, зависание Linux или остановка приложения не должны приводить к бесконечному удержанию последней команды.
- ARM/DISARM, failsafe и критические операции должны иметь отдельную проверяемую логику.
- Все изменения радио сначала проверяются без моторов и без полёта.

## Компоненты

### FIT-LAB Station

Читает USB HID-органы управления, отображает состояние канала, передатчика, приёмника и телеметрии. Передаёт управляющие состояния по LAN в Модуль управления.

### Модуль управления / Orange Pi

Получает команды FIT-LAB Station, проверяет их последовательность и свежесть, передаёт их в RP2040 и принимает обратную телеметрию. Не формирует RF-пакеты ExpressLRS напрямую.

### FIT-LAB Control Bridge / RP2040

Детерминированный мост между Orange Pi и TX-модулем.

Функции:
- UART Orange Pi ↔ RP2040;
- разбор FIT-LAB Control Frames;
- CRC, sequence, timestamp и watchdog;
- генерация CRSF RC Channels;
- передача CRSF service frames;
- приём CRSF telemetry;
- локальный безопасный переход при потере входного потока;
- индикация состояния;
- обновление прошивки с проверкой версии.

### FIT-LAB TX Firmware

Собственная сборка для RadioMaster Ranger на базе ExpressLRS.

Цели:
- имя устройства FIT-LAB TX;
- версия FIT-LAB;
- идентификация аппаратной цели;
- CRSF RC transport;
- телеметрия;
- доступ к параметрам TX из FIT-LAB;
- Bind / Model Match / packet rate / telemetry ratio / Dynamic Power / TX power;
- статус RF, температуры и вентилятора там, где это реально поддерживается;
- heartbeat с мостом;
- диагностические сообщения FIT-LAB.

### FIT-LAB RX Firmware

Собственная сборка для совместимого ELRS-приёмника.

Цели:
- имя устройства FIT-LAB RX;
- версия FIT-LAB;
- RF-связь с FIT-LAB TX;
- выдача CRSF в полётный контроллер;
- телеметрия FC обратно на землю;
- failsafe;
- служебная идентификация и диагностика.

## Документы

- [Архитектура](architecture.md)
- [План прошивок](firmware-plan.md)
- [Чек-лист разработки](checklist.md)
- [Чёткий план реализации](implementation-plan.md)
- [RP2040 + FreeRTOS](freertos-bridge.md)
- [Power Board](power-board.md)
- [UI Video + Control](ui-concept.md)

## Статус

Раздел фиксирует целевую архитектуру. Реальные TX/RX прошивки и RP2040 Bridge ещё не реализованы и не должны считаться готовыми до стендовых тестов, проверки failsafe и подтверждения живого управления без моторов.


## Дополнительно зафиксировано

- RP2040 Bridge работает под FreeRTOS с приоритетом CRSF/watchdog над сервисными задачами.
- Отдельная FIT-LAB Power Board включает/выключает TX по команде через RP2040 и измеряет питание.
- Мастер-пульт получает единый экран Video + Control и две темы: Cyan и Amber.
- Интерактивный макет не управляет реальным железом и используется только для UI/UX проверки.
