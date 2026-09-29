# FIT-LAB Bridge RP2040 + FreeRTOS

## Назначение

RP2040 - последний детерминированный уровень между Linux-модулем управления и CRSF-передатчиком.

FreeRTOS используется не как самоцель, а для чёткого разделения realtime-задач, watchdog, телеметрии и сервисных функций.

## Приоритеты задач

### Critical
- CRSF TX/RX;
- watchdog/failsafe;
- аппаратные таймеры и deadline checks.

### High
- UART Orange Pi -> RP2040;
- проверка sequence/timestamp/CRC/auth;
- control-state machine.

### Medium
- CRSF telemetry parsing;
- Device Info / Parameter frames;
- обратный поток в Orange Pi.

### Low
- Power Board management;
- voltage/current sampling;
- LED и сервисная диагностика;
- обновление прошивки.

## Правила realtime

- Никакого блокирующего логирования в CRSF path.
- Никакого динамического выделения памяти после старта в critical path.
- Фиксированные ring buffers и ограниченные очереди.
- Новое управление заменяет устаревшее; старые RC frames не накапливаются.
- Все таймауты основаны на монотонном аппаратном времени.
- Потеря Linux/LAN не может привести к бесконечному удержанию последнего газа.
- После reconnect ARM остаётся сброшенным до нового явного разрешения.

## Состояния

`BOOT -> WAIT_HOST -> READY -> ACTIVE -> CONTROL_STALE -> FAILSAFE`

Дополнительно:
- `TX_LINK_LOST`
- `POWER_FAULT`
- `UPDATE`

Переход из FAILSAFE обратно в ACTIVE не должен автоматически восстанавливать ARM.
