




---

## 1. Jak zainstalować integrację w Home Assistant

Aby uruchomić integrację na swojej działającej instancji Home Assistant:
1. Skopiuj cały katalog `mcprotocol` do katalogu niestandardowych komponentów Twojego Home Assistant: `/config/custom_components/mcprotocol/` (ścieżka zależy od sposobu instalacji HA, np. w Dockerze lub na HAOS).
2. Upewnij się, że Home Assistant ma dostęp do sieci z prawem instalowania bibliotek z PyPI (`pymcprotocol` zostanie pobrana i zainstalowana automatycznie przy pierwszym starcie dzięki zapisowi w pliku `manifest.json`).
3. Zrestartuj Home Assistant.

---

## 2. Przykładowa konfiguracja w `configuration.yaml`

Poniżej znajduje się kompletny, bogato skomentowany przykład konfiguracji, pokazujący pełen wachlarz możliwości integracji (odczyt typów danych, skalowanie, bity w słowach, przyciski chwilowe i bezpieczne przełączniki).

Dodaj poniższy blok do swojego pliku `configuration.yaml` w Home Assistant i dostosuj adresy IP oraz rejestry:

```yaml
mcprotocol:
  - name: "Główny PLC"
    host: "192.168.1.15"       # Adres IP Twojego sterownika PLC
    port: 1025                 # Port skonfigurowany w PLC dla MC Protocol (3E Frame)
    plc_type: "Q"              # Typ PLC: Q, L, QnA, iQ-L, iQ-R
    comm_type: "binary"        # Format transmisji: binary lub ascii
    scan_interval: 5           # Odpytywanie rejestrów co 5 sekund (bloki są automatycznie optymalizowane!)

    # 1. Sensory liczbowe i tekstowe (Rejestry słowne D, W, R, ZR)
    sensors:
      - name: "Temperatura Kotła"
        address: "D100"
        data_type: "int16"      # Standardowa wartość 16-bit ze znakiem
        scale: 0.1             # Skalowanie: wartość z PLC * 0.1 (np. 452 -> 45.2 °C)
        offset: 0.0
        precision: 1           # Zaokrąglenie do 1 miejsca po przecinku
        unit_of_measurement: "°C"
        state_class: "measurement"
        device_class: "temperature"

      - name: "Przepływ Wody"
        address: "D102"
        data_type: "float32"   # 32-bitowy zmiennoprzecinkowy (zajmuje D102 i D103)
        swap_words: false       # Zamiana kolejności słów (jeśli wymagane)
        swap_bytes: false       # Zamiana bajtów w słowie (np. Little/Big Endian)
        unit_of_measurement: "L/min"

      - name: "Ciśnienie Instalacji"
        address: "D104"
        data_type: "uint32"    # 32-bitowy bez znaku (zajmuje D104 i D105)
        scale: 0.001
        precision: 2
        unit_of_measurement: "bar"

      - name: "Status Pracy Tekst"
        address: "D200"
        data_type: "string"    # Odczyt ciągu ASCII z rejestrów D200-D203
        length: 4              # Długość w słowach (4 rejestry = do 8 znaków)

      - name: "Alarm Aktywny (Bit w słowie)"
        address: "D100.5"      # Odczytuje 5. bit ze słowa D100 (wartość 0 lub 1)

    # 2. Sensory binarne (ON/OFF - M, X, Y, B itp.)
    binary_sensors:
      - name: "Czujnik Zbliżeniowy"
        address: "X0"          # Fizyczne wejście PLC (w formacie szesnastkowym dla serii Q)
        device_class: "motion"

      - name: "Styk Pompy Obiegowej"
        address: "M100"         # Cewka pomocnicza PLC
        device_class: "running"

      - name: "Wykryto Błąd PLC"
        address: "D110.15"     # Odczyt 15. bitu słowa D110 jako stan binarny
        device_class: "problem"

    # 3. Przełączniki sterujące (Zapis/Odczyt stanów ON/OFF)
    switches:
      - name: "Zawór Główny"
        address: "Y10"          # Fizyczne wyjście PLC (sterowanie bezpośrednie)

      - name: "Tryb Automatyczny"
        address: "M200"         # Bit wewnętrzny w PLC do włączania automatyki

      - name: "Bezpieczny Włącznik Wentylatora"
        address: "D150.2"      # Włączenie modyfikuje TYLKO 2. bit w rejestrze D150!
                               # Wykorzystuje bezpieczną procedurę Read-Modify-Write,
                               # nie uszkadzając pozostałych 15 bitów w rejestrze.

    # 4. Suwaki / Pola Wprowadzania Wartości (Zapis rejestrów D, W, R)
    numbers:
      - name: "Zadana Temperatura CO"
        address: "D250"
        write_address: "D250"
        data_type: "int16"
        min: 20
        max: 80
        step: 1
        scale: 10.0            # Wprowadzone 45.0 °C zostanie wysłane do PLC jako 450 (wartość / scale)
        unit_of_measurement: "°C"

    # 5. Przyciski Chwilowe (Wyzwalacze typu START / STOP)
    buttons:
      - name: "Reset Alarmów PLC"
        address: "M50"          # Adres bitu resetu w PLC
        trigger_value: 1        # Wartość wysyłana przy naciśnięciu
        reset_value: 0          # Wartość wysyłana po upływie delay
        delay_ms: 150           # Czas trwania impulsu: 150 ms

      - name: "Uruchom Maszynę"
        address: "D300.0"      # Impuls na zerowym bicie słowa D300
        trigger_value: 1
        reset_value: 0
        delay_ms: 100

    # 6. Rolety i Żaluzje (Covers - odczyt i zadawanie pozycji)
    covers:
      - name: "Roleta Salon"
        address: "D500"         # Rejestr odczytu aktualnej pozycji (np. 0-100%)
        write_address: "D502"   # Rejestr zapisu zadanej pozycji (np. 0-100%)
        data_type: "int16"
        position_closed: 0      # Wartość z PLC odpowiadająca zamknięciu
        position_open: 100      # Wartość z PLC odpowiadająca otwarciu

      - name: "Żaluzje Taras (Przyciski Wyzwalające Jazdę)"
        address: "D510"         # Odczyt pozycji rolety (0-1000 z PLC)
        write_address: "D512"   # Zapis zadanej pozycji (0-1000 z PLC)
        position_closed: 0
        position_open: 1000     # Skalowanie liniowe 0-1000 -> 0-100% HA
        open_address: "M300"    # Opcjonalny bit wyzwalający jazdę w górę
        close_address: "M301"   # Opcjonalny bit wyzwalający jazdę w dół
        stop_address: "M302"    # Opcjonalny bit zatrzymujący jazdę
        command_delay_ms: 150   # Impulsy bitów sterujących trwają 150ms

```

---

## 3. Globalne usługi integracji (Home Assistant Services)

Integracja eksponuje 3 potężne usługi w Narzędziach Deweloperskich, które mogą być używane w Twoich automatyzacjach, skryptach oraz Node-RED:

### A. `mcprotocol.write_register`
Pozwala zapisać dowolną wartość numeryczną, zmiennoprzecinkową lub tekst bezpośrednio do rejestru PLC.
*   **address**: `"D100"`
*   **value**: `150` (lub listę wartości np. `[12, 34, 56]` albo tekst `"AUTO"`)
*   **data_type**: `"int16"` (lub `uint16`, `int32`, `uint32`, `float32`, `string`)
*   **swap_words**: `false`
*   **swap_bytes**: `false`

### B. `mcprotocol.write_bit`
Zmienia stan bitu (M, Y, B itp.) lub bitu spakowanego w rejestr słowny.
*   **address**: `"M50"` (lub `"D100.5"`)
*   **value**: `true` (ON) lub `false` (OFF)

### C. `mcprotocol.remote_command`
Pozwala sterować trybem pracy procesora PLC CPU.
*   **command**: `"run"`, `"stop"` lub `"pause"`

---

## 4. Architektura i Optymalizacja Pod Spodem

1. **Lock-Guarding (Bezpieczeństwo wątków):** Ponieważ natywna biblioteka `pymcprotocol` wykonuje synchroniczną komunikację po gniazdach TCP, równoległe zapytania mogłyby uszkodzić bufor sieciowy. Nasz obiekt `MCProtocolHub` wykorzystuje mechanizm `threading.Lock()`, serializując wszystkie odczyty i zapisy.
2. **Batch Reading (Grupowanie):** Podczas startu integracja pobiera wszystkie skonfigurowane adresy i grupuje je w optymalne bloki ciągłe.
   *   Jeśli sensory odpytują np. `D100`, `D101`, `D102`, `D105`, integracja wykona **jeden seryjny odczyt** o długości 6 rejestrów (od D100 do D105) zamiast 4 osobnych połączeń sieciowych.
   *   Ogranicza to ruch sieciowy o ponad **75%** i znacząco odciąża CPU sterownika PLC.
3. **Obsługa Błędów:** W przypadku błędu socketu lub utraty zasilania PLC, hub automatycznie oznacza połączenie jako przerwane, a coordinator podejmie próbę ponownego połączenia przy następnym cyklu odpytywania, chroniąc Home Assistant przed zawieszeniem.
