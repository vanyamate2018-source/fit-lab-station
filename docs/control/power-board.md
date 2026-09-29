# FIT-LAB Power Board

## Цель

Отдельная цифровая силовая плата управляет питанием RadioMaster Ranger и измеряет состояние питания.

Команда идёт:
`Mac -> Orange Pi -> UART -> RP2040 -> Power Board`.

Orange Pi не управляет силовым ключом напрямую.

## Силовая часть

Целевая архитектура:
- electronic high-side switch или eFuse;
- отдельное питание Ranger 6-16.8 V;
- Power Enable;
- Power Good;
- Fault/Overcurrent;
- измерение напряжения;
- измерение тока/мощности после выбора датчика и реального замера потребления Ranger.

Механическое реле не является целевым вариантом финальной платы.

## Логика включения

1. RP2040 загрузился, TX питание выключено.
2. Установлена связь Orange Pi <-> RP2040.
3. Есть свежий и валидный control stream.
4. Система DISARM.
5. Получена разрешённая команда TX POWER ON.
6. RP2040 включает Power Board.
7. Проверяются Power Good и отсутствие fault.
8. Ожидается CRSF Device Info от FIT-LAB TX.
9. Только после этого TX считается READY.

## Логика отключения

Нормально:
`DISARM -> прекратить активный control -> TX shutdown request -> power off`.

Аварийно:
`FAILSAFE -> журнал события -> при необходимости немедленный power cut`.

Причины отключения должны различаться:
- команда оператора;
- потеря LAN;
- watchdog;
- undervoltage;
- overcurrent;
- thermal fault;
- отсутствие TX heartbeat.

## Телеметрия питания

Операторский UI:
- TX Power: ON/OFF;
- напряжение;
- состояние Power Good/Fault.

Диагностика:
- ток;
- мощность;
- минимальное/максимальное напряжение;
- счётчики undervoltage/overcurrent;
- время работы TX.
