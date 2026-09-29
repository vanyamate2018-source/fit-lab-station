# FIT-LAB Control — план прошивок

## Общая модель версий

Все компоненты имеют независимые версии FIT-LAB.

Пример:

```text
FIT-LAB Control Protocol 1
FIT-LAB Bridge 0.1.0
FIT-LAB TX 0.1.0
FIT-LAB RX 0.1.0
```

В бинарник встраиваются:
- FIT-LAB semantic version;
- git commit;
- target board;
- build date;
- upstream/base revision там, где используется сторонний проект.

## 1. FIT-LAB Bridge / RP2040

Рекомендуемая реализация: C/C++ и Raspberry Pi Pico SDK.

### Модули

```text
bridge/
├── app
├── host_uart
├── control_frame
├── crsf_encoder
├── crsf_parser
├── telemetry
├── watchdog
├── state_machine
├── led
├── version
└── boot/update
```

### Требования

- без динамической зависимости от Linux timing;
- фиксированные буферы;
- ограниченные очереди;
- CRC на host frames;
- счётчик sequence;
- monotonic timeout;
- отдельный failsafe state;
- двусторонний CRSF;
- диагностика без утечки секретов.

## 2. FIT-LAB TX Firmware

Основа: отдельный fork/patch-set ExpressLRS для конкретной аппаратной цели Ranger.

### Не удаляем

- штатный RF stack;
- packet scheduling;
- telemetry;
- bind phrase/model match;
- RF power control;
- hardware target;
- обновление/восстановление, пока оно совместимо с нашей схемой.

### Добавляем

- имя FIT-LAB TX;
- FIT-LAB version fields;
- build identification;
- дополнительную диагностику;
- heartbeat/bridge status;
- FIT-LAB service parameter namespace только там, где это не ломает совместимость;
- отображение подтверждённых capabilities.

### Не делаем в первой версии

- собственный новый OTA protocol;
- несовместимое шифрование поверх OTA без отдельного проекта;
- изменение RF timing без стендовой причины;
- скрытое изменение regulatory domain или мощности.

## 3. FIT-LAB RX Firmware

Основа: соответствующий ExpressLRS RX target.

Добавляем:
- FIT-LAB RX name;
- FIT-LAB version;
- build ID;
- hardware identity;
- подтверждённые capabilities;
- дополнительные status/diagnostic fields при необходимости.

Сохраняем:
- CRSF output в FC;
- telemetry return;
- штатный RF failsafe;
- bind/model semantics, пока они нужны совместимости.

## 4. Функции ELRS Lua внутри FIT-LAB

Lua-файл не исполняется приложением.

FIT-LAB реализует собственный CRSF Device Manager и повторяет функциональность через протокол устройств.

Целевые операции:
- Device discovery;
- Device info;
- Parameter discovery;
- Parameter read;
- Parameter write;
- Commands;
- Bind;
- Model Match;
- TX power;
- Dynamic Power;
- Packet Rate;
- Telemetry Ratio;
- Wi-Fi/update mode, если target это предоставляет.

UI строится по реально объявленным параметрам устройства.

## 5. Лицензирование

ExpressLRS распространяется по GPLv3.

FIT-LAB TX/RX модификации на базе ExpressLRS должны хранить upstream attribution, историю версии и соответствовать GPLv3 при распространении.

RP2040 Bridge и остальная архитектура FIT-LAB ведутся как отдельные компоненты, чтобы границы исходников и лицензий были понятны.

## 6. Репозитории и структура

На старте код можно хранить внутри FIT-LAB Station:

```text
firmware/
├── README.md
├── bridge-rp2040/
├── tx-expresslrs/
└── rx-expresslrs/
```

ExpressLRS source tree не следует слепо копировать в основной репозиторий. Предпочтительнее фиксировать upstream commit и хранить наши patches/config/build scripts либо использовать отдельный fork.

## 7. Update / rollback

Для каждого компонента:
- предварительная проверка target;
- проверка версии;
- checksum;
- запрет прошивки не того target;
- сохранение предыдущей версии;
- понятный rollback path;
- журнал результата.

Обновление TX/RX не выполняется автоматически во время активного управления.
