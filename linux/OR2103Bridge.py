try:
    import serial
except ImportError:
    serial = None
import re
import time
import sys

PORT = "/dev/ttyUSB0"
BAUD = 115200
POWER_HEX = "0A"  # 0A=10, 0F=15, 1E=30
TIMEOUT_MS = 1500


def checksum(data):
    return sum(data[1:]) & 0xFF


def command(cmd, data=b""):
    payload = bytearray()
    payload.append(0xA5)
    payload.append(len(data))
    payload.append(cmd)
    payload += data
    payload.append(checksum(payload))
    return payload


def send_bytes(ser, data, wait=0.08, read_size=256):
    ser.write(data)
    time.sleep(wait)
    return ser.read(read_size)


def send_hex(ser, hexstr, wait=0.08):
    return send_bytes(ser, bytes.fromhex(hexstr), wait)


def set_power(ser):
    power = int(POWER_HEX, 16)
    send_bytes(ser, command(0x21, bytes([power])))


def beep(ser):
    send_hex(ser, "A5 00 19 19", 0.03)


def beep_error(ser):
    beep(ser)
    time.sleep(0.08)
    beep(ser)


def normalize_epc(epc_hex):
    epc_hex = epc_hex.strip().upper()
    if not epc_hex:
        raise ValueError("EPC_EMPTY")
    if not re.fullmatch(r"[0-9A-F]+", epc_hex):
        raise ValueError("EPC_INVALID_HEX")
    if len(epc_hex) > 124:
        raise ValueError("EPC_TOO_LONG")
    if len(epc_hex) % 4 != 0:
        raise ValueError("EPC_LENGTH_MUST_BE_WORD_ALIGNED")
    return epc_hex


def build_write_epc(epc_hex):
    epc_hex = normalize_epc(epc_hex)

    epc_bytes = bytes.fromhex(epc_hex)
    word_len = len(epc_bytes) // 2

    pc = (word_len << 11) & 0xFFFF
    pc_bytes = pc.to_bytes(2, "big")
    write_len = word_len + 1

    data = bytearray()
    data += b"\x00\x00\x00\x00"  # access password
    data.append(0x01)            # EPC bank
    data.append(0x01)            # start word = 1
    data.append(write_len)
    data += pc_bytes
    data += epc_bytes

    return command(0x57, data)


def parse_epcs(buffer):
    epcs = []
    i = 0

    while i < len(buffer) - 4:
        if buffer[i] != 0xA5:
            i += 1
            continue

        length = buffer[i + 1]
        frame_len = length + 3

        if i + frame_len > len(buffer):
            break

        frame = buffer[i:i + frame_len]

        if len(frame) >= 21 and frame[2] == 0x55:
            epc = frame[5:18].hex().upper()

            if len(epc) > 24:
                epc = epc[-24:]

            if epc and epc != "000000000000000000000000":
                epcs.append(epc)

        i += frame_len

    return epcs


def init_reader(ser, buzzer_off=True):
    send_hex(ser, "A5 00 32 32")          # get mode
    set_power(ser)                        # configurable arriba
    send_hex(ser, "A5 00 22 22")          # get power / no rompe estado
    send_hex(ser, "A5 03 43 00 00 00 46") # read area EPC
    if buzzer_off:
        send_hex(ser, "A5 01 13 00 14")   # buzzer off


def inventory(only_first=False):
    ser = serial.Serial(PORT, BAUD, timeout=0.15)

    try:
        init_reader(ser, buzzer_off=True)
        ser.reset_input_buffer()

        detected = []
        try:
            # La respuesta inicial puede incluir etiquetas, ademas de la confirmacion.
            buffer = bytearray(send_hex(ser, "A5 00 53 53", 0.05))
            end = time.monotonic() + TIMEOUT_MS / 1000.0
            while True:
                for epc in parse_epcs(buffer):
                    if epc not in detected:
                        detected.append(epc)
                if (only_first and detected) or time.monotonic() >= end:
                    break
                buffer.extend(ser.read(512))
        finally:
            send_hex(ser, "A5 00 54 54", 0.03)  # stop inventory incluso ante error

        if detected:
            if only_first:
                beep(ser)
            for epc in (detected[:1] if only_first else detected):
                print("DETECTED=" + epc)
        else:
            print("NO_TAG")
        return 0
    finally:
        ser.close()


def read_epc():
    return inventory(only_first=True)


def is_write_ok(resp):
    if not resp:
        return False

    for i in range(len(resp) - 4):
        if resp[i] == 0xA5 and resp[i + 2] == 0x57:
            return resp[i + 3] == 0x00

    return False


def write_epc(epc):
    # Validar antes de abrir o configurar el pad. No alterar los bytes validos del protocolo.
    epc = normalize_epc(epc)
    cmd = build_write_epc(epc)
    ser = serial.Serial(PORT, BAUD, timeout=0.25)

    try:
        init_reader(ser, buzzer_off=True)

        ser.reset_input_buffer()

        ser.write(cmd)
        time.sleep(0.25)
        resp1 = ser.read(256)

        resp2 = b""
        if not is_write_ok(resp1):
            ser.write(cmd)
            time.sleep(0.25)
            resp2 = ser.read(256)

        if is_write_ok(resp1) or is_write_ok(resp2):
            beep(ser)  
            print("WRITTEN=" + epc)
            print("OK")
            return 0
        else:
            beep_error(ser)
            print("ERROR=WRITE_FAILED")
            print("RESP1=" + resp1.hex().upper())
            print("RESP2=" + resp2.hex().upper())
            return 1

    finally:
        ser.close()


def clear_epc(words=6):
    if not 1 <= words <= 31:
        raise ValueError("PALABRAS_INVALIDAS")
    return write_epc("0" * (words * 4))


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if not args:
        print("ERROR=ACTION_REQUIRED")
        return 1
    action = args[0]
    if action == "status":
        # Igual que Windows: informa la configuracion; no afirma que el lector responda.
        print("OK")
        print("PORT=" + PORT)
        print("BAUDRATE=" + str(BAUD))
        print("TIMEOUT_MS=" + str(TIMEOUT_MS))
        print("POWER=" + str(int(POWER_HEX, 16)))
        return 0
    if action == "version":
        print("ERROR=VERSION_NOT_SUPPORTED")
        return 1
    if action not in ("read-epc", "inventory", "write-epc", "clear"):
        print("ERROR=UNKNOWN_ACTION")
        return 1
    if action == "write-epc" and len(args) < 2:
        print("ERROR=EPC_REQUIRED")
        return 1
    try:
        if action == "write-epc":
            normalize_epc(args[1])
        words = 6
        if action == "clear" and len(args) >= 2:
            if not re.fullmatch(r"[0-9]{1,2}", args[1]) or not 1 <= int(args[1]) <= 31:
                raise ValueError("PALABRAS_INVALIDAS")
            words = int(args[1])
        if serial is None:
            print("ERROR=PYSERIAL_NOT_INSTALLED")
            return 1
        if action == "read-epc":
            return read_epc()
        if action == "inventory":
            return inventory()
        if action == "write-epc":
            return write_epc(args[1])
        return clear_epc(words)
    except ValueError as error:
        print("ERROR=" + str(error).replace("\r", " ").replace("\n", " "))
        return 1
    except Exception as error:
        print("ERROR=SERIAL_ERROR:" + str(error).replace("\r", " ").replace("\n", " "))
        return 1


if __name__ == "__main__":
    sys.exit(main())
