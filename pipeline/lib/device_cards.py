"""Knowledge cards for the Cardputer device assistant ("Card").

Written by hand from the M5Stack Cardputer v1.1 manual (data/sources/manuals/Cardputer_v1.1.pdf)
and this firmware. Each card stands alone (names its subject, no "it" without a noun) because
BM25 retrieval shows one card at a time. Keep cards short (40 to 90 words) and ASCII only.
Facts not in the manual are limited to well-known ESP32-S3 properties and what this firmware does.
"""

CARDS = [
    # ---------------------------------------------------------------- overview
    "The M5Stack Cardputer v1.1 (SKU K132-V11) is a card-sized computer for engineers and makers. It has a "
    "Stamp-S3A controller with an ESP32-S3FN8, a 56-key keyboard, a 1.14 inch TFT display, a speaker, a "
    "SPM1423 microphone, an infrared emitter, an RGB LED, a microSD slot, a Grove HY2.0-4P port and two "
    "batteries: 120mAh in the Stamp-S3A and 1400mAh in the base.",
    "The Cardputer v1.1 measures 84.0 x 54.0 x 19.7 mm and weighs 90 g. The base has magnets so the "
    "Cardputer can stick to metal surfaces, and LEGO-compatible holes for mounting. The package contains "
    "one Cardputer v1.1 and a 1.5 mm L-shaped hex key for the M2 screws.",
    "The Cardputer v1.1 is meant for rapid prototyping and function checks, industrial control, home control "
    "systems, data logging and sensor monitoring, embedded learning, and Wi-Fi IoT projects. It can be "
    "programmed with Arduino IDE, PlatformIO, ESP-IDF or the UiFlow2 graphical platform.",
    "Card is the assistant running on this Cardputer. Card reads the battery, chip temperature, free RAM, "
    "SD card, sound level, Wi-Fi networks, Grove I2C devices, uptime, screen brightness and volume. Card can "
    "also set the RGB LED colour, change brightness and volume, beep, and send NEC infrared codes. Type /help "
    "for examples.",
    "Card is a tiny language model (espLLM) that runs offline on the ESP32-S3, stored as int8 weights in the "
    "flash partition model. Card does not use the internet. When asked about a sensor, the firmware measures "
    "it and gives Card the reading in a Device line, so the numbers come from the hardware, not from Card.",
    "Card commands: /new starts a new chat, /mute turns the voice off, /talk turns it back on, /vol 0-255 sets "
    "the voice volume, /speed 40-120 sets the voice speed (lower is faster) and /help lists examples. Typing a "
    "new message stops the voice.",
    # ---------------------------------------------------------------- SoC, memory
    "The Cardputer v1.1 uses an ESP32-S3FN8: a Xtensa 32-bit LX7 dual-core processor running at up to 240 MHz, "
    "with 2.4 GHz Wi-Fi and Bluetooth LE radio hardware, USB OTG and USB Serial/JTAG. The FN8 part number "
    "means 8 MB of flash inside the chip and no PSRAM.",
    "The Cardputer v1.1 has 8 MB of flash and no PSRAM. The ESP32-S3 has about 512 KB of internal SRAM, part "
    "of which is used by the firmware, Wi-Fi and the display buffer, so only a few hundred KB of heap is free "
    "for programs. On this firmware most of the heap holds the model's context (KV cache).",
    "Free RAM is the heap memory not in use right now. The largest free block is the biggest single piece "
    "that can be allocated; it is smaller than free RAM when memory is fragmented. Card reserves RAM for its "
    "context of a few hundred tokens, which is why free RAM is low while Card is running.",
    "This firmware's flash layout: the app partition starts at 0x10000 and is 3 MB; the model partition "
    "(subtype 0x40) starts at 0x310000 and holds about 4.9 MB. On boot the firmware copies /espllm/model.bin "
    "from the SD card into the model partition if it has changed, then reads the model directly from flash.",
    "The ESP32-S3 has an internal temperature sensor. It measures the chip, not the room, so it reads warmer "
    "than the air, often 35 to 55 C while the Cardputer is busy. The Cardputer v1.1 operating temperature is "
    "0 to 40 C (ambient). For room temperature, plug an ENV Unit into the Grove port.",
    "The ESP32-S3 chip revision (for example rev 0.2) and the MAC address identify the chip. The Wi-Fi station "
    "MAC address is burned into the chip's eFuse and starts with an Espressif prefix such as 34:85:18. ESP-IDF "
    "is Espressif's framework; the Arduino core for ESP32 is built on top of it.",
    # ---------------------------------------------------------------- display, keyboard, buttons
    "The Cardputer v1.1 display (screen) is a 1.14 inch ST7789V2 TFT with 240 x 135 pixels. Display pins: backlight DISP_BL G38, "
    "RST G33, RS (data/command) G34, DAT (MOSI) G35, SCK G36, CS G37. In Arduino, draw with "
    "M5Cardputer.Display, for example M5Cardputer.Display.drawString(\"hi\", 10, 10).",
    "Screen brightness on the Cardputer is the LCD backlight on G38, driven by PWM. In Arduino, use "
    "M5Cardputer.Display.setBrightness(0 to 255). Lower brightness saves battery. Ask Card to dim the screen, "
    "make it brighter, or set brightness to a percentage from 10 to 100.",
    "The Cardputer v1.1 keyboard has 56 keys in a 4 x 14 matrix, scanned through a 74HC138 decoder: address "
    "lines A0, A1, A2 on G8, G9, G11 and inputs on G13, G15, G3, G4, G5, G6, G7. Since 2025.8.2 the key "
    "operating force is 160gf (was 260gf). In Arduino, read keys with M5Cardputer.Keyboard.",
    "Reading keys in Arduino: call M5Cardputer.begin(cfg, true) to enable the keyboard, then in loop() call "
    "M5Cardputer.update(). When M5Cardputer.Keyboard.isChange() and isPressed() are true, "
    "M5Cardputer.Keyboard.keysState() gives the typed characters in .word and flags such as .enter and .del.",
    "The Cardputer v1.1 has a reset button and a user button. The user button is G0 on the Stamp-S3A; it is "
    "also the boot button used to enter download mode. Stamp-S3A improved the boot key to 4.0 x 3.0 x 2.0 mm "
    "(the old StampS3 key was 2.6 x 1.6 x 0.55 mm).",
    "To enter download mode on the Cardputer v1.1: set the side power switch to OFF, hold the G0 button, "
    "connect the USB Type-C data cable to the computer, then release G0 after the device powers on. Use this "
    "when an upload fails or the firmware crashes at boot.",
    # ---------------------------------------------------------------- power
    "Cardputer v1.1 battery capacity: two lithium batteries, 120mAh inside the Stamp-S3A and 1400mAh in the base, with "
    "built-in charging and power conversion. Charge it through the USB Type-C port, and switch the power switch "
    "to ON while charging, otherwise the batteries are not charged.",
    "The Cardputer measures the battery voltage through the ADC on G10 (battery detect). A full lithium cell "
    "is about 4.1 to 4.2 V and an empty one about 3.3 V, so the percentage is an estimate from the voltage. "
    "It reads a little high while USB power is connected. In Arduino, use M5Cardputer.Power.getBatteryLevel().",
    "Cardputer v1.1 power figures from the manual: sleep current 0.15 uA at 4.2 V; about 139 mA at 4.2 V in "
    "key mode; about 148 mA at 4.2 V while sending infrared. Wi-Fi, the speaker and a bright screen use more. "
    "Dimming the screen and turning Wi-Fi off make the battery last longer.",
    "A low battery on the Cardputer (under about 15 percent or 3.5 V) can cause resets when Wi-Fi or the "
    "speaker draws a burst of current. Plug in USB-C with the power switch ON to charge. The Stamp-S3A adds an "
    "electronic switch that lowers power use compared with the older StampS3.",
    # ---------------------------------------------------------------- audio
    "The Cardputer v1.1 speaker is an 8 ohm 1 W cavity speaker driven by an NS4168 I2S amplifier. Speaker pins: BCLK G41, "
    "SDATA G42, LRCLK G43. In Arduino, use M5Cardputer.Speaker.tone(frequency, milliseconds) for a beep, or "
    "M5Cardputer.Speaker.setVolume(0 to 255). Card's voice is the SAM robot voice.",
    "The Cardputer v1.1 microphone (mic) is a SPM1423 digital MEMS microphone (PDM). Mic pins: DAT G46, CLK G43, 3.3 V. "
    "The microphone clock G43 is shared with the speaker LRCLK, so the speaker and microphone cannot run at the "
    "same time; stop M5Cardputer.Speaker before M5Cardputer.Mic.begin(), and restart it afterwards.",
    "Card's sound level reading is in dBFS: decibels relative to the loudest sound the microphone can record "
    "(0 dBFS). Numbers are negative; closer to 0 is louder. Roughly: below -55 is very quiet, -55 to -40 "
    "quiet, -40 to -25 moderate, above -25 loud. dBFS is not calibrated to dB SPL.",
    "Card's volume levels are percentages of the speaker volume (0 to 100, stored as 0 to 255). Volume 0 is "
    "silent. Ask Card to set the volume to a number, turn it up or down by 20, or mute it. /mute turns only the "
    "voice off; the volume setting stays.",
    # ---------------------------------------------------------------- IR, LED
    "The Cardputer v1.1 infrared (IR) emitter pin is G44 (IR TX). It only transmits; there is no IR receiver. "
    "Range from the manual: about 410 cm straight ahead, 170 cm at 45 degrees and 66 cm at 90 degrees. Most TV "
    "and air-conditioner remotes use a 38 kHz carrier.",
    "NEC is a common infrared remote protocol: each button sends an 8-bit address (the device) and an 8-bit "
    "command (the button) on a 38 kHz carrier. Card sends NEC with: send ir address 4 command 8. To find codes, "
    "read the original remote with an IR receiver, or look up the device's NEC code list.",
    "Sending infrared in Arduino on the Cardputer: install the IRremote library, call IrSender.begin(44), then "
    "IrSender.sendNEC(address, command, repeats). G44 is the IR LED. Point the Cardputer's IR window at the "
    "device; the range is about 4 metres straight ahead.",
    "The Cardputer v1.1 RGB LED is a WS2812; the LED data pin is G21. Its power comes through G38, the same pin as the LCD "
    "backlight, so the RGB LED only works properly when the screen brightness is 100 percent. Card raises the "
    "brightness to 100 percent before setting a colour.",
    "Setting the RGB LED in Arduino on the Cardputer v1.1: set the backlight to full with "
    "M5Cardputer.Display.setBrightness(255), then call neopixelWrite(21, red, green, blue) with values 0 to "
    "255. Card's colours are red, green, blue, white, yellow, orange, purple, pink, cyan and magenta, or off.",
    # ---------------------------------------------------------------- storage
    "The Cardputer v1.1 microSD card slot pins (SPI): CS G12, MOSI G14, CLK G40, MISO G39. In Arduino: "
    "SPI.begin(40, 39, 14, 12) then SD.begin(12, SPI, 25000000). Format the card as FAT32. SDHC cards are 4 to "
    "32 GB; larger SDXC cards must be reformatted as FAT32 to work.",
    "Card's SD card reading shows the card type (SDSC up to 2 GB, SDHC 4 to 32 GB, or MMC), the total size and "
    "how much is used. This firmware keeps its files in /espllm on the SD card: model.bin (the model) and "
    "kb.bin (these knowledge cards).",
    "If the Cardputer says no SD card found: check the card is pushed in fully, formatted FAT32, and not larger "
    "than 32 GB unless reformatted. The SD card is checked at boot, so restart after inserting it. Without the "
    "SD card Card still runs from flash, but without these knowledge cards.",
    # ---------------------------------------------------------------- Grove
    "The Cardputer v1.1 Grove port is a HY2.0-4P connector: black GND, red 5V, yellow G2, white G1. It is a "
    "custom port, so G1 and G2 can be I2C, UART, digital or analog. For M5Stack I2C Units, use SDA G2 and SCL G1, "
    "for example Wire.begin(2, 1).",
    "Card's Grove scan probes every I2C address from 0x08 to 0x77 on SDA G2 and SCL G1 and lists the devices "
    "that answer. Common M5Stack Units: 0x44 SHT30 or SHT40 (ENV temperature and humidity), 0x76 or 0x77 BMP280 "
    "pressure, 0x70 QMP6988 pressure, 0x29 VL53L0X distance, 0x23 BH1750 light.",
    "An I2C address is a 7-bit number that each I2C device answers to, written in hex like 0x44. Two devices "
    "with the same address cannot share one bus. If a Grove Unit is not found, check the cable, that the Unit "
    "is I2C (not UART), and that it is powered from the 5V pin.",
    "The Grove port supplies 5V on the red wire, but the G1 and G2 signals are 3.3 V logic. Do not drive G1 or "
    "G2 with 5V signals. Analog sensors on G1 or G2 can be read with analogRead(); the ADC reads 0 to about "
    "3.1 V.",
    # ---------------------------------------------------------------- Wi-Fi, BLE, USB
    "The Cardputer v1.1 has 2.4 GHz Wi-Fi (802.11 b/g/n); it cannot see 5 GHz networks. Stamp-S3A has an "
    "optimised antenna for better reception than the old StampS3. Card's Wi-Fi scan lists how many networks it "
    "found and the strongest one with its signal (RSSI) and channel.",
    "Wi-Fi signal strength (RSSI) is in dBm and is negative. Roughly: -30 to -50 dBm excellent, -50 to -67 "
    "good, -67 to -80 weak, below -80 unusable. 2.4 GHz channels are 1 to 13; channels 1, 6 and 11 do not "
    "overlap.",
    "Card's Wi-Fi scan needs about 64 KB of free heap, more than is left beside the model's context, so Card "
    "frees the model's memory during the scan and the chat starts over afterwards. Card does not connect to "
    "networks or use the internet; it only scans and then turns Wi-Fi off again to give the RAM back.",
    "The ESP32-S3 in the Cardputer has Bluetooth LE 5 hardware, but this firmware does not use Bluetooth. "
    "Classic Bluetooth (for example audio) is not supported by the ESP32-S3. Arduino sketches can use BLE with "
    "the BLEDevice library.",
    "The Cardputer v1.1 USB Type-C port is for power, charging and programming. The ESP32-S3 has native USB: "
    "USB Serial/JTAG for uploading and the serial monitor, and USB OTG. The serial monitor runs at 115200 baud. "
    "Use a data cable, not a charge-only cable.",
    # ---------------------------------------------------------------- programming
    "PlatformIO setup for the Cardputer v1.1 from the manual: platform espressif32@6.7.0, board "
    "esp32-s3-devkitc-1, framework arduino, upload_speed 1500000, build_flags -DESP32S3 "
    "-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1, lib_deps M5Cardputer from github.com/m5stack/M5Cardputer.",
    "Arduino IDE setup for the Cardputer v1.1: install the esp32 board package and the M5Cardputer library "
    "(it brings M5Unified and M5GFX). Select an ESP32-S3 board such as M5Cardputer or M5StampS3, then "
    "start with auto cfg = M5.config(); M5Cardputer.begin(cfg, true); in setup().",
    "UiFlow2 is M5Stack's graphical (block and MicroPython) programming platform. Flash the UiFlow2 firmware "
    "to the Cardputer v1.1 with M5Burner, then program it from the UiFlow2 web IDE. The Cardputer v1.1 factory "
    "firmware and user demo can be restored with Easyloader or M5Burner.",
    "Flashing new firmware replaces the program on the Cardputer, including this assistant. To restore Card, "
    "upload this firmware again and copy /espllm/model.bin and kb.bin back onto the SD card. If an upload "
    "fails, enter download mode by holding G0 while plugging in USB.",
    "The Cardputer v1.1 schematics are published by M5Stack as three PDFs: Cardputer V1.1, Cardputer V1.1 Base "
    "and Stamp-S3A. Datasheets are available for the SPM1423 microphone, the NS4168 amplifier and the ST7789V2 "
    "display. Structure (3D) files are also available for making cases.",
    "When removing the Stamp-S3A from the Cardputer v1.1 panel, be careful with the FPC cable and connector on "
    "the back. Lift them gently, otherwise the socket for the display connection can be damaged. M5Stack shows "
    "the steps in the Cardputer Accessory Kit video.",
    # ---------------------------------------------------------------- v1.1 vs original
    "Cardputer v1.1 vs the original Cardputer: v1.1 uses the Stamp-S3A instead of the StampS3, has an "
    "optimised antenna, a bigger boot key, lower power use, and an RGB LED that shares power with the screen "
    "backlight (the original powered the LED as soon as it was switched on).",
    "On the Stamp-S3A, an electronic switch controls the RGB LED power, and it is tied to G38 with the LCD "
    "backlight. Set G38 high (full backlight) before controlling the RGB LED. On the original StampS3 the RGB "
    "LED was powered all the time.",
    # ---------------------------------------------------------------- what it does not have
    "The Cardputer v1.1 has no IMU (no accelerometer or gyroscope), no humidity or room temperature sensor, no "
    "light sensor, no GPS, no camera and no vibration motor. Add them with Grove Units on the HY2.0-4P port, "
    "for example an ENV Unit for temperature, humidity and pressure, or an IMU Unit.",
    "The Cardputer v1.1 has no real-time clock battery, so it does not keep the date and time when switched "
    "off. Card's uptime is the time since the last boot. A sketch can get the time over Wi-Fi with NTP, or "
    "from an RTC Unit on the Grove port.",
    "The Cardputer v1.1 has no infrared receiver, so it cannot learn codes from a remote. It can only send "
    "infrared on G44. To read remote codes, connect an IR receiver Unit to the Grove port.",
    "The Cardputer v1.1 has no headphone jack and no vibration motor. Sound comes from the built-in 1 W speaker "
    "only. The Cardputer v1.1 also has no touchscreen; all input is from the 56-key keyboard and the buttons.",
    # ---------------------------------------------------------------- troubleshooting
    "If the Cardputer upload fails with could not connect or port busy: close any serial monitor, use a data "
    "cable, check the port in Device Manager (USB Serial Device, VID 303A PID 1001), then try download mode: "
    "power OFF, hold G0, plug in USB, release G0.",
    "If the Cardputer screen is dark: the brightness may be low, or the battery flat. Ask Card to set "
    "brightness to 100, or charge it over USB-C with the power switch ON. A bright screen is needed for the "
    "RGB LED to work, because they share G38.",
    "If the Cardputer gets warm: the ESP32-S3 chip temperature often reads 40 to 55 C while running the model "
    "or Wi-Fi, which is normal. Above about 70 C, let it cool, lower the brightness, and avoid charging in hot "
    "places. The operating range is 0 to 40 C ambient.",
    "If the RGB LED does not light: the screen brightness must be 100 percent, because the LED's power comes "
    "through G38 with the backlight. Also check the colour is not off. In Arduino, call setBrightness(255) "
    "before neopixelWrite(21, r, g, b).",
]
