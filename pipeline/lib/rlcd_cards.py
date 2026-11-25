"""Knowledge cards for Card on the Waveshare ESP32-S3-RLCD-4.2 (BOARD = "rlcd").

Written by hand from the Waveshare docs (docs.waveshare.com/ESP32-S3-RLCD-4.2 and its Arduino, ESP-IDF
and FAQ pages), Waveshare's example code (github.com/waveshareteam/ESP32-S3-RLCD-4.2, for the TF card pins),
the RLCD Eyes firmware notes (verified pins) and what this firmware does. Same rules as device_cards.py:
each card stands alone (names its subject), 40 to 90 words, ASCII only. General electronics cards state
textbook facts only.
"""

BOARD_CARDS = [
    # ---------------------------------------------------------------- overview
    "The Waveshare ESP32-S3-RLCD-4.2 is a desk board with a 4.2 inch reflective LCD, an ESP32-S3-WROOM-1-N16R8 "
    "module, two microphones and a speaker header, an SHTC3 temperature and humidity sensor, a PCF85063 real-time "
    "clock, a TF card slot, an 18650 battery holder, a USB Type-C port and a 2 x 8 pin expansion header.",
    "Card is the assistant running on this ESP32-S3-RLCD-4.2 board. Card reads the battery, room temperature and "
    "humidity, the time, the radar, the phone link, the I2C bus, chip temperature, RAM, the TF card, sound level, "
    "Wi-Fi networks, uptime and volume. Card can also set the volume, beep, play sounds and change the eyes. "
    "Type /help for examples.",
    "Card is a tiny language model (CardMind) that runs offline on the ESP32-S3 of this RLCD board. The int8 "
    "weights are stored in the model flash partition and copied into PSRAM at boot. When asked about a sensor, "
    "the firmware measures it and gives Card the reading in a Device line, so the numbers come from the "
    "hardware, not from Card.",
    "You talk to Card on the RLCD board through a web page: open http://rlcd-eyes.local/ or the board's IP "
    "address in a browser on the same Wi-Fi network, type a question and press Send. The reply streams in as "
    "it is written. The Card screen on the board shows the same conversation. The board has no keyboard.",
    "Card commands on the RLCD board: /new starts a new chat, /ctx shows what Card was given on the last turn, "
    "/help lists examples, /do runs a script you type, /save NAME keeps the last script on the TF card, "
    "/run NAME runs a saved script and /scripts lists them.",
    "Card scripts on the RLCD board, how scripts work: ask for something repeated, timed or conditional, such as beep 3 times or "
    "if battery is below 20 beep. Card writes a short script and the web page shows Run and Cancel buttons. "
    "While a script runs, the Stop button ends it. Scripts can beep, wait, set the volume, show readings and "
    "test conditions.",
    "How fast Card is: Card answers on the RLCD board at about 4 tokens per second (speed), so a typical reply takes 4 to 9 seconds. "
    "The model has a context of 512 tokens, held in PSRAM. While Card is answering, the eyes and the town "
    "screens pause, because Card runs in the same loop that draws them.",
    # ---------------------------------------------------------------- module, memory
    "The ESP32-S3-RLCD-4.2 main chip is an ESP32-S3 chip in an ESP32-S3-WROOM-1-N16R8 module: a Xtensa 32-bit LX7 dual-core processor at up "
    "to 240 MHz with 512 KB SRAM and 384 KB ROM, 16 MB flash, 8 MB PSRAM, 2.4 GHz Wi-Fi and Bluetooth 5 (LE), "
    "with a built-in antenna. N16R8 means 16 MB of flash memory and 8 MB PSRAM; the flash holds the firmware and the model.",
    "PSRAM is extra RAM outside the ESP32-S3 chip, inside the module. The ESP32-S3-RLCD-4.2 has 8 MB of octal "
    "PSRAM. It is slower than the internal SRAM but large, so Card keeps the model weights (about 2.7 MB) and "
    "its context there. Internal RAM, a few hundred KB, stays free for Wi-Fi, Bluetooth and the display.",
    "Free RAM on the RLCD board is the internal heap not in use right now; the largest free block is the "
    "biggest single piece that can be allocated. PSRAM free is counted separately. Card's memory reading shows "
    "both, plus the 16 MB flash, the model size and the context length.",
    "This firmware's flash layout on the RLCD board: the app partition starts at 0x10000 (6.25 MB), the model "
    "partition at 0x650000 (6.25 MB), the knowledge cards (kb) at 0xC90000 (1 MB), then spiffs and a core dump "
    "area. The NVS partition at 0x9000 keeps settings such as Wi-Fi, volume and time zone.",
    "The ESP32-S3 has an internal temperature sensor that measures the silicon, not the room. It reads warmer than "
    "the air, often 35 to 55 C while Card is working. On the RLCD board, ask for the room temperature to read "
    "the SHTC3 sensor instead, or ask for the chip temperature for the internal one.",
    # ---------------------------------------------------------------- display, buttons, LEDs
    "The ESP32-S3-RLCD-4.2 display (screen) is a 4.2 inch fully reflective LCD with 300 x 400 pixels, used as 400 x 300 "
    "in landscape. It has no backlight: it reflects room light like paper, so it is easy to read in daylight, "
    "uses little power and needs a lamp in the dark. The display panel is black and white.",
    "The RLCD display pins: the display controller is an ST7305 on SPI: SCK G11, MOSI G12, CS G40, DC G5 and RST G41. This "
    "firmware draws with the U8g2 library (U8G2_ST7305_300X400_F_4W_HW_SPI, rotation R1). Call SPI.begin() "
    "before u8g2.begin(). The U8g2 release in the PlatformIO registry lacks this panel, so use U8g2 from GitHub.",
    "The reflective screen on the RLCD board has no backlight, so there is no brightness to set. Grey tones are "
    "made by dithering black and white dots. The firmware redraws the eyes about 30 times a second; Waveshare's "
    "U8g2 example reaches about 74 frames per second.",
    "The ESP32-S3-RLCD-4.2 has three buttons. BOOT: hold it while powering on to enter download mode. PWR: a "
    "single click powers on, a long press powers off. KEY is a user button on G18 (active low); in this "
    "firmware KEY cycles the screens: eyes, town, mic, Wi-Fi and Card.",
    "What the LEDs on the ESP32-S3-RLCD-4.2 board mean: it has two indicator LEDs and no RGB LED. CHG is the charging light; it turns off when "
    "the battery is full. WRN is the warning light; it stays on if the battery is inserted the wrong way round. "
    "Neither LED can be switched by software.",
    "To enter download mode on the ESP32-S3-RLCD-4.2, hold the BOOT button while powering the board on, then "
    "release it. Use this when an upload fails or the firmware crashes at boot. The board appears as a USB "
    "serial device (VID 303A, PID 1001) for uploading.",
    # ---------------------------------------------------------------- power
    "The ESP32-S3-RLCD-4.2 battery is one 18650 rechargeable lithium cell in the holder on the back; the board "
    "also runs from USB Type-C. The board charges the cell from USB. After fitting a battery, plug in USB-C once to wake the "
    "board before it will run on the battery alone.",
    "Card's battery reading on the RLCD board comes from the ADC on G4 through a 1/3 voltage divider. The "
    "percentage uses Waveshare's scale: 3.0 V is 0 percent and 4.12 V is 100 percent, so it is an estimate. "
    "With no battery fitted the reading shows the USB supply and Card reports about 100 percent.",
    "Battery life and power use of the ESP32-S3-RLCD-4.2 from Waveshare's FAQ (how long the battery lasts): about 5.32 V at 0.09 A with the factory firmware, "
    "and about 24 hours from a full 18650 battery in the factory standby mode. Wi-Fi, Bluetooth and Card's "
    "model use more power than the reflective screen.",
    # ---------------------------------------------------------------- sensors, clock
    "The ESP32-S3-RLCD-4.2 has an SHTC3 temperature and humidity sensor on I2C address 0x70. Card's room "
    "reading comes from it. The board warms the sensor a little, so this firmware subtracts 4 C from the raw "
    "temperature, as Waveshare recommends. Relative humidity is in percent.",
    "Humidity explained: relative humidity is how much water vapour the air holds compared with the most it could hold at that "
    "temperature, in percent. Indoors, 40 to 60 percent humidity is comfortable. Above about 70 percent, mould and "
    "condensation become likely; below about 30 percent, the air feels dry.",
    "The ESP32-S3-RLCD-4.2 has a PCF85063 real-time clock (RTC) on I2C address 0x51. This firmware stores UTC in "
    "the RTC and shows local time using the time zone setting (default SGT-8). The time is set from the "
    "internet (NTP) over Wi-Fi, or from the phone through the Chronos app.",
    "RTC backup battery: the RTC on the ESP32-S3-RLCD-4.2 has its own power connector for a backup battery cell (PH1.0, J7). Use only a "
    "rechargeable cell such as an ML1220, because the board charges it. Do not fit a CR1220. Without a backup "
    "cell the clock loses the time when the power is off, and the firmware gets it again from Wi-Fi.",
    "Card's clock reading on the RLCD board gives the local time, the day and the date. If the clock has not "
    "been set since the board lost power, Card says so; connect Wi-Fi or the Chronos phone app once to set it. "
    "Uptime is different: it is the time since the last boot.",
    # ---------------------------------------------------------------- audio
    "The ESP32-S3-RLCD-4.2 microphone and speaker audio uses two codecs on I2S and I2C: an ES7210 ADC for the two microphones (a dual microphone array "
    "on I2C 0x40, with an echo cancellation circuit) and an ES8311 codec for the speaker (I2C 0x18). I2S pins: MCLK G16, "
    "BCLK G9, WS G45, DIN G10 (microphone), DOUT G8 (speaker). The speaker amplifier is enabled on G46.",
    "The speaker connects to the MX1.25 2-pin speaker header on the ESP32-S3-RLCD-4.2. Card's volume is the "
    "speaker volume from 0 to 100 percent (default 30), saved across restarts. Ask Card to set the volume to a "
    "number, turn it up or down by 20, or mute it.",
    "Card can play the board's named sounds on the RLCD speaker: chime, woof, ribbit, tweet, honk, ring, ufo, "
    "thunder, roar, notify and startup. Ask, for example, play the woof sound or ring the bell. Card can also "
    "beep a plain tone. A new sound is skipped while another one is still playing.",
    "Card's sound level reading on the RLCD board averages the microphones for about 0.6 seconds, in dBFS: "
    "decibels relative to the loudest sound the microphone can record (0 dBFS). Numbers are negative; closer "
    "to 0 is louder. Below -55 is very quiet, -55 to -40 quiet, -40 to -25 moderate, above -25 loud.",
    # ---------------------------------------------------------------- storage
    "TF card pins: the TF (microSD) card slot of the ESP32-S3-RLCD-4.2 is wired for 1-bit SDMMC: CLK G38, CMD G21, D0 G39. In "
    "Arduino: SD_MMC.setPins(38, 21, 39) then SD_MMC.begin(\"/sdcard\", true). Format the card as FAT32. SDHC "
    "cards are 4 to 32 GB; larger cards must be reformatted as FAT32.",
    "Card's SD card reading on the RLCD board shows the card type (SDSC, SDHC or MMC), the total size and how "
    "much is used. This firmware keeps its files in /espllm on the TF card: model.bin, kb.bin and the scripts "
    "folder. The TF card is checked at boot, so restart after inserting it.",
    "To update Card on the RLCD board, copy a new model.bin and kb.bin into /espllm on the TF card and restart. "
    "At boot the firmware compares them with the flash partitions and copies any file that differs, so an "
    "older file on the card replaces a newer one. Without a TF card, Card runs from the copy it already has.",
    # ---------------------------------------------------------------- header, I2C, radar
    "The ESP32-S3-RLCD-4.2 expansion header P1 is a 2 x 8 pin 2.54 mm female header: 1 3V3, 2 VBUS, 3 and 4 GND, "
    "5 G0, 6 and 8 USB D- and D+, 7 G1, 9 G2, 10 U0TXD (G43), 11 G3, 12 U0RXD (G44), 13 G17, 14 I2C SDA (G13), "
    "15 G18 (KEY), 16 I2C SCL (G14). VBUS is 5 V only while USB is connected.",
    "The ESP32-S3-RLCD-4.2 has no Grove port. External I2C sensors connect to header P1: SDA on pin 14 (G13), "
    "SCL on pin 16 (G14), 3V3 on pin 1 and GND on pins 3 and 4. The bus is shared with the board's own chips, "
    "so a new sensor must not use addresses 0x18, 0x40, 0x51 or 0x70.",
    "Card's I2C scan on the RLCD board probes every address from 0x08 to 0x77 on SDA G13 and SCL G14 and lists "
    "the devices that answer. The board's own chips always appear: 0x18 ES8311 speaker codec, 0x40 ES7210 "
    "microphone ADC, 0x51 PCF85063 clock and 0x70 SHTC3 temperature and humidity sensor.",
    "This firmware supports an optional HLK-LD2451 radar on the RLCD board, a sensor that detects moving targets "
    " with their distance, angle and speed. Wiring on header P1: radar TX to pin 12 (G44), radar RX to "
    "pin 10 (G43), power from VBUS on pin 2 and GND. It talks UART at 115200 baud.",
    "Card's radar reading on the RLCD board gives the number of moving targets the HLK-LD2451 sees and the "
    "nearest one: distance in metres, angle in degrees (0 is straight ahead) and whether it is approaching or "
    "moving away, with its speed in km/h. A person standing still may not be detected.",
    # ---------------------------------------------------------------- Wi-Fi, Bluetooth, USB
    "The ESP32-S3-RLCD-4.2 has 2.4 GHz Wi-Fi (802.11 b/g/n) and cannot see 5 GHz networks. This firmware joins "
    "the network saved with the serial commands ssid NAME and pass PASSWORD, gets the time over NTP and serves "
    "Card's chat page. Card's Wi-Fi scan lists the networks it can see.",
    "This firmware's Bluetooth LE link on the RLCD board is for the Android Chronos app. Pair the board, which "
    "advertises as RLCD Eyes, in Chronos; the phone then forwards notifications and incoming calls, which show "
    "as cards on the eyes screen, and sets the clock. Card's phone reading says whether a phone is connected.",
    "The ESP32-S3-RLCD-4.2 USB Type-C port is for power, charging, uploading firmware and the serial monitor at "
    "115200 baud. The ESP32-S3 has native USB Serial/JTAG. Use a data cable, not a charge-only cable. Opening "
    "the serial port can reset the board unless DTR and RTS are kept off.",
    # ---------------------------------------------------------------- the RLCD Eyes firmware
    "The RLCD Eyes firmware on this board has five screens, cycled with the KEY button: animated eyes, an "
    "isometric town that follows the real time and weather, a microphone spectrum, a Wi-Fi network list and "
    "Card. Asking Card a question on the web page switches to the Card screen.",
    "The eyes on the RLCD board show emotions: they react to sounds and voices, watch visitors that cross the "
    "screen, look hot or cold from the room temperature, sad on low battery and sleep from 20:00 to 08:00. Ask "
    "Card to look happy, sad, angry, surprised, sleepy, suspicious, confused, curious or in love for a minute.",
    "The RLCD Eyes firmware plays an hourly chime from 08:00 to 20:00 and shows a Go Home banner at 18:00 on "
    "working days. It skips weekends and public holidays, which it downloads for the chosen country while "
    "online. At night the eyes stay quiet apart from the chime.",
    # ---------------------------------------------------------------- programming
    "Programming the ESP32-S3-RLCD-4.2 (how to program the board): Waveshare provides Arduino and ESP-IDF examples on GitHub "
    "(waveshareteam/ESP32-S3-RLCD-4.2), including the display, SHTC3, PCF85063, TF card and audio. Waveshare "
    "recommends Arduino-ESP32 3.3.12 or ESP-IDF 5.5.5. This firmware uses PlatformIO with arduino-esp32 2.0.11 "
    "(ESP-IDF 4.4).",
    "Flashing new firmware replaces the firmware on the RLCD board, including Card. To restore Card, upload this "
    "firmware again and copy /espllm/model.bin and kb.bin onto the TF card, or write them to flash at 0x650000 "
    "and 0xC90000 with esptool. If an upload fails, hold BOOT while powering on.",
    # ---------------------------------------------------------------- what it does not have
    "The ESP32-S3-RLCD-4.2 has no RGB LED, no infrared transmitter or receiver, no Grove port, no keyboard and "
    "no touchscreen. It also has no IMU, light sensor, GPS or camera. Add sensors on the I2C pins or the free "
    "GPIOs of header P1.",
    "Card on the RLCD board has no voice and cannot speak or talk: replies appear on the web page and the screen, and the speaker plays "
    "sounds and beeps only. There is no backlight, so brightness cannot be set. Card cannot connect to the "
    "internet itself; Wi-Fi is used for the chat page, the clock and the holiday list.",
    # ---------------------------------------------------------------- troubleshooting
    "If Card's chat page does not open: the RLCD board must be on the same Wi-Fi network as your phone or "
    "computer. Check the IP address on the Card screen, or try http://rlcd-eyes.local/. If the board has no "
    "Wi-Fi, set it over USB serial with ssid NAME and pass PASSWORD, then wait for it to connect.",
    "If the RLCD board does not start on battery: plug in USB-C once to wake it, check the 18650 cell is the "
    "right way round (the WRN light is on if it is reversed) and charged. The CHG light shows charging and goes "
    "off when the battery is full.",
    "If the room temperature on the RLCD board looks too high: the board heats the SHTC3 a little, especially "
    "while Wi-Fi and Card are busy, and the firmware subtracts 4 C. Keep the board out of sunlight and away "
    "from the charger for a fair reading.",
]

ESP32_CARDS = [
    "The ESP32-S3 revision (for example rev 0.2) and the MAC address identify the silicon. The Wi-Fi station "
    "MAC address is burned into the chip's eFuse and starts with an Espressif prefix. ESP-IDF is Espressif's "
    "framework; the Arduino core for ESP32 is built on top of it.",
    "Wi-Fi signal strength (RSSI) is in dBm and is negative. Roughly: -30 to -50 dBm excellent, -50 to -67 "
    "good, -67 to -80 weak, below -80 unusable. 2.4 GHz channels are 1 to 13; channels 1, 6 and 11 do not "
    "overlap.",
    "Classic Bluetooth (for example audio) is not supported by the ESP32-S3; it has Bluetooth LE 5 only. "
    "Arduino sketches can use BLE with the NimBLE-Arduino library or the BLEDevice library.",
    "The ESP32-S3 GPIOs are 3.3 V logic and are not 5 V tolerant. Keep the current through a pin to a "
    "few milliamps, about 20 mA at most. Many peripherals (I2C, SPI, UART, PWM) can be routed to almost any GPIO "
    "through the GPIO matrix.",
    "The ESP32-S3 deep sleep turns off the CPUs and most of the chip and wakes on a timer, a GPIO or a touch "
    "pin, using a few microamps. On wake the program starts again from setup(). RTC memory can keep a small "
    "amount of data across deep sleep.",
    "The ESP32-S3 ADC is 12-bit and reads 0 to about 3.1 V with the default attenuation. In Arduino, "
    "analogReadMilliVolts(pin) gives a calibrated reading. ADC2 cannot be used while Wi-Fi is on, so use ADC1 "
    "pins (G1 to G10) for analog sensors.",
]

GENERAL_CARDS = [
    "I2C (Inter-Integrated Circuit) is a two-wire bus: SDA carries data and SCL the clock. With I2C, one controller "
    "talks to many devices, each with its own 7-bit address such as 0x44. Both lines need pull-up resistors, usually 4.7 kOhm to 3.3 V. Common "
    "speeds are 100 kHz and 400 kHz. In Arduino, start the I2C bus with Wire.begin(sda, scl).",
    "An I2C address is a 7-bit number that each I2C device answers to, written in hex like 0x44. Two devices "
    "with the same address cannot share one bus. If a device is not found in a scan, check the wiring, the "
    "power, the pull-up resistors and that the device really uses that bus.",
    "A pull-up resistor connects a signal line to the supply voltage, so the line reads high when nothing "
    "drives it low. Buttons and I2C lines need pull-ups. Typical values are 4.7 kOhm to 10 kOhm. A pull-down "
    "resistor does the opposite, holding the line low. ESP32 pins have weak internal pull-ups (INPUT_PULLUP).",
    "SPI (Serial Peripheral Interface) is a fast four-wire bus: SCK (clock), MOSI (controller out), MISO (controller in) and CS (chip select, "
    "one per device). It runs at several MHz, faster than I2C, and is used for displays, SD cards and flash "
    "memory. On an SPI bus, only the device whose CS is low listens to SPI data.",
    "UART (universal asynchronous receiver-transmitter) is serial communication with two data wires: TX sends and RX receives, so TX of one device goes to "
    "RX of the other, with a shared GND. Both sides must use the same baud rate, such as 9600 or 115200 bits "
    "per second. A UART has no clock wire.",
    "PWM (pulse width modulation) switches a pin on and off quickly; the duty cycle, the share of time it is "
    "on, sets the average power. It dims LEDs and controls motor speed and servos. On the ESP32, use the LEDC "
    "peripheral for PWM, for example ledcAttachPin and ledcWrite in Arduino.",
    "An ADC (analog to digital converter) turns a voltage into a number. A 12-bit ADC gives 0 to 4095. Read a "
    "sensor or battery voltage that is higher than the ADC range through a voltage divider. ADC readings are "
    "noisy, so average several samples.",
    "A voltage divider is two resistors in series; the output between them is Vout = Vin x R2 / (R1 + R2). "
    "Two equal resistors halve the voltage. Dividers measure higher voltages with an ADC, such as a battery "
    "through a 1/3 divider. They are not a power supply for loads.",
    "I2S (Inter-IC Sound) is a digital audio bus with a bit clock (BCLK), a word select or left-right clock (WS or LRCLK) and "
    "data lines in and out; some codecs also need a master clock (MCLK). It carries audio samples between a "
    "processor and a codec, amplifier or microphone. The RLCD board uses I2S for its audio.",
    "Ohm's law: voltage = current x resistance (V = I x R). For example 3.3 V across 330 Ohm drives 10 mA. "
    "Power is P = V x I. To size an LED resistor, divide the supply voltage minus the LED forward voltage by "
    "the current you want.",
    "To calculate an LED resistor: an LED needs a series resistor to limit its current. From a 3.3 V pin with a red LED (about 2 V forward "
    "voltage) at 10 mA: (3.3 - 2.0) / 0.010 = 130 Ohm, so use 150 Ohm. The long leg is the anode (+), the short "
    "leg the cathode (-).",
    "Switch bounce: a mechanical button makes and breaks contact several times in the first few milliseconds. "
    "Debounce it by ignoring changes for about 20 to 50 ms after the first one, or with a small capacitor. "
    "Without debouncing, one press can count as several.",
    "A decoupling capacitor, usually 100 nF ceramic, sits next to each chip's power pin to supply short current "
    "bursts and filter noise. A larger capacitor (10 uF or more) near the regulator steadies the supply. Missing "
    "decoupling causes random resets and noisy readings.",
    "3.3 V and 5 V logic: an ESP32 pin outputs 3.3 V and must not receive 5 V. To connect a 5 V device, use a "
    "level shifter or a voltage divider on signals going into the ESP32. Many 5 V inputs accept 3.3 V as high, "
    "but check the datasheet.",
    "Lithium-ion cells such as the 18650 are 3.7 V nominal, about 4.2 V full and 3.0 V empty. Charge them only "
    "with a proper charger circuit, never short them, and do not use damaged or swollen cells. Insert them the "
    "right way round, matching + and -.",
    "Baud rate is the number of signal changes per second on a serial line; for UART it equals bits per "
    "second. 115200 baud sends about 11,500 bytes per second, because each byte takes 10 bits with the start "
    "and stop bits. A wrong baud rate shows garbage characters.",
    "An interrupt makes the processor stop what it is doing and run a short function when a pin changes or a "
    "timer fires. In Arduino, use attachInterrupt(digitalPinToInterrupt(pin), handler, FALLING). Keep the "
    "handler short and set a flag for the main loop to act on.",
    "FAT32 is the file system most microcontroller SD libraries read. It works on cards up to 32 GB with "
    "standard tools; larger cards come as exFAT and must be reformatted to FAT32. A single file on FAT32 can be "
    "at most 4 GB.",
    "A real-time clock (RTC) is a small chip that keeps the date and time with its own crystal, using very "
    "little power, often from a backup battery while the main power is off. Microcontrollers read it over "
    "I2C. Without a backup cell an RTC loses the time at power-off.",
    "A MEMS microphone is a tiny silicon sound sensor. Digital MEMS types send PDM or I2S data; analog ones "
    "need an ADC. Sound level in dBFS is relative to the loudest level it can record, so it is not "
    "the same as dB SPL measured by a sound meter.",
]

CARDS = BOARD_CARDS + ESP32_CARDS + GENERAL_CARDS
