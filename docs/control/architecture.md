# FIT-LAB Control — архитектура

## 1. Назначение

FIT-LAB Control создаёт независимый контур дистанционного управления, отделённый от видеоприёма WFB-ng.

Основной путь:

```text
TX12/джойстик
→ Mac
→ Ethernet
→ Orange Pi 3B
→ UART
→ RP2040
→ CRSF
→ RadioMaster Ranger
→ ExpressLRS 2.4 GHz
→ FIT-LAB RX
→ CRSF
→ Flight Controller
```

Видео остаётся отдельным:

```text
камера → WFB-ng → Модуль видеоприёма → LAN → FIT-LAB Station
```

## 2. Ввод управления на Mac

На первом этапе RadioMaster TX12 используется как USB HID/Simulator.

FIT-LAB считывает:
- Roll;
- Pitch;
- Throttle;
- Yaw;
- ARM;
- Flight Mode;
- AUX-каналы;
- дополнительные кнопки и переключатели.

Приложение выполняет:
- калибровку;
- deadband;
- нормализацию;
- mapping каналов;
- профиль устройства;
- проверку диапазонов;
- формирование Control Frame.

## 3. LAN-протокол FIT-LAB Control

Для быстрого потока управления используется датаграммный транспорт; служебные операции и конфигурация могут использовать отдельный надёжный канал.

Минимальный Control Frame v1:

```text
magic
protocol_version
session_id
sequence
monotonic_timestamp
channels[16]
control_flags
arm_state
source_health
crc32
auth_tag
```

Требования:
- старые пакеты не переигрываются;
- sequence должен возрастать;
- слишком старые timestamp отбрасываются;
- session_id меняется при новом сеансе;
- контроль целостности обязателен;
- аутентификация включается до реального RF-управления;
- журнал не содержит секретов.

Начальная целевая частота LAN-control: 100–250 Гц. Конкретное значение выбирается после замеров.

## 4. Orange Pi 3B

Модуль управления на Orange Pi:
- принимает control frames;
- ведёт heartbeat Master ↔ Control;
- проверяет состояние RP2040;
- передаёт realtime-команды в Pico по UART;
- принимает телеметрию;
- публикует статус в FIT-LAB Station;
- пишет сервисный журнал;
- не подменяет watchdog RP2040.

Linux может зависнуть или временно задержать процесс, поэтому финальное решение failsafe не должно находиться только в userspace Linux.

## 5. UART Orange Pi ↔ RP2040

Первичная цель — обычный full-duplex UART 3.3 V.

Линии:
- Orange Pi TX → Pico RX;
- Orange Pi RX ← Pico TX;
- GND ↔ GND.

Начальная скорость: 460800 baud.
При необходимости после измерений возможен переход на 921600 baud.

Питание Pico проектируется отдельно от логических линий; перед подключением проверяются общая земля, уровни и схема конкретной платы.

## 6. RP2040 Bridge

RP2040 получает короткие управляющие кадры и выдаёт CRSF с предсказуемым таймингом.

Состояния:
- BOOT;
- WAIT_HOST;
- READY;
- ACTIVE;
- CONTROL_STALE;
- FAILSAFE;
- TX_LINK_LOST;
- UPDATE.

Watchdog:
- отслеживает время последнего валидного host frame;
- не продолжает бесконечно последнюю команду;
- при превышении порога переводит выход в заранее определённое безопасное состояние;
- событие фиксируется и передаётся наверх.

Точный timeout не фиксируется до измерений задержки и теста failsafe.

## 7. CRSF

RP2040 должен поддерживать как минимум:
- RC_CHANNELS_PACKED;
- LINK_STATISTICS;
- DEVICE_PING;
- DEVICE_INFO;
- PARAMETER_READ;
- PARAMETER_WRITE;
- COMMAND;
- необходимые extended frames.

Это позволит перенести возможности ELRS Lua в FIT-LAB UI без запуска Lua внутри приложения.

## 8. FIT-LAB TX

RadioMaster Ranger остаётся RF-модулем. FIT-LAB TX Firmware отвечает за:
- ExpressLRS RF;
- совместимость с выбранным RX;
- RF power;
- packet rate;
- telemetry;
- bind/model match;
- fan/thermal status, если аппаратная цель это предоставляет;
- FIT-LAB identification.

В первой версии не меняется OTA packet structure ExpressLRS. Это уменьшает объём новой RF-валидации.

## 9. FIT-LAB RX

FIT-LAB RX на борту:
- принимает ExpressLRS;
- выдаёт CRSF в FC;
- получает telemetry FC;
- возвращает её к TX;
- выполняет RF/receiver failsafe согласно прошивке и настройкам FC.

## 10. FIT-LAB Device Manager

В UI появляется раздел «Передатчик управления».

Он должен динамически читать реальные CRSF device parameters, а не хранить жёсткий список.

Планируемые поля:
- имя устройства;
- FIT-LAB version;
- RF base version;
- packet rate;
- TX power;
- Dynamic Power;
- telemetry ratio;
- Model Match;
- bind state;
- LQ;
- RSSI;
- SNR;
- RF mode;
- температура;
- fan state;
- RX firmware/version.

Запись параметров разрешается только после успешного чтения и проверки capability.

## 11. Безопасность

Обязательные свойства:
- отдельный arm state;
- защита от повторного использования старых пакетов;
- watchdog Pico;
- failsafe FC;
- запрет автоматического ARM после reconnect;
- смена сессии после reconnect;
- раздельные права на read-only telemetry и управление;
- подтверждение критичных конфигурационных операций.

## 12. Тестирование

Порядок:
1. TX12 → Mac без RF.
2. Mac → LAN → Orange Pi loopback.
3. Orange Pi → RP2040 UART.
4. RP2040 генерирует CRSF в логический анализатор.
5. Подключение Ranger без моторов.
6. Чтение TX device info/telemetry.
7. FIT-LAB TX ↔ FIT-LAB RX.
8. RX ↔ FC без пропеллеров.
9. failsafe при потере Mac.
10. failsafe при потере LAN.
11. failsafe при перезагрузке Orange Pi.
12. failsafe при reset RP2040.
13. длительный стенд.
14. только после этого полевые испытания.

## 13. Что не входит в v1

- собственный новый RF PHY;
- собственная модуляция;
- изменение OTA структуры ExpressLRS;
- автономное наведение;
- автоматический полёт;
- объединение control и video в один радиоканал.

Эти темы рассматриваются отдельно только после стабильной базовой системы.
