try:
    import serial
except ImportError:
    serial = None
import re
import time
import sys
import json
from pathlib import Path

PORT = "/dev/ttyUSB0"
BAUD = 115200
POWER_HEX = "0A"  # 0A=10, 0F=15, 1E=30
TIMEOUT_MS = 1500
POWER_CONFIG_PATH = Path(__file__).resolve().parents[1] / "runtime" / "antenna-power.json"


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


def normalize_power(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("POWER_INVALID")
    if not re.fullmatch(r"[0-9]{1,2}", str(value)) or not 5 <= int(value) <= 30:
        raise ValueError("POWER_INVALID")
    return int(value)


def configured_power():
    # PHP guarda el ajuste confirmado; no modificar config.json ni este archivo.
    try:
        content = POWER_CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return normalize_power(int(POWER_HEX, 16))
    except UnicodeError as error:
        raise ValueError("POWER_CONFIG_INVALID") from error
    except OSError as error:
        raise ValueError("POWER_CONFIG_UNREADABLE") from error
    try:
        setting = json.loads(content)
        if not isinstance(setting, dict) or type(setting.get("power")) is not int:
            raise ValueError("invalid power")
        return normalize_power(setting["power"])
    except (ValueError, TypeError) as error:
        raise ValueError("POWER_CONFIG_INVALID") from error


def set_power(ser, power=None):
    power = configured_power() if power is None else normalize_power(power)
    request_response(ser, 0x21, bytes([power]), data_length=1)
    actual = read_power(ser)
    if actual != power:
        raise ValueError("POWER_READBACK_MISMATCH")
    return actual


def request_response(ser, cmd, data=b"", data_length=1):
    """Consulta breve con trama, comando, estado y checksum validados.

    SDK OR2127LIB: longitud total = byte de longitud + 4; el primer dato
    es el estado. Se usa solo para potencia, sin cambiar el parser de EPC.
    """
    ser.reset_input_buffer()
    ser.write(command(cmd, data))
    end = time.monotonic() + TIMEOUT_MS / 1000.0
    buffer = bytearray()
    while time.monotonic() < end:
        buffer.extend(ser.read(256))
        while len(buffer) >= 3:
            start = buffer.find(b"\xA5")
            if start < 0:
                buffer.clear()
                break
            if start:
                del buffer[:start]
            if len(buffer) < 3:
                break
            frame_length = buffer[1] + 4
            if len(buffer) < frame_length:
                break
            frame = bytes(buffer[:frame_length])
            del buffer[:frame_length]
            if frame[2] != cmd:
                continue
            if checksum(frame[:-1]) != frame[-1]:
                raise ValueError("READER_CHECKSUM")
            payload = frame[3:-1]
            if not payload:
                raise ValueError("READER_RESPONSE_INVALID")
            if payload[0] != 0:
                raise ValueError("READER_STATUS_" + format(payload[0], "02X"))
            if len(payload) != data_length:
                raise ValueError("READER_RESPONSE_INVALID")
            return payload
    raise ValueError("READER_NOT_RESPONDING")


def read_power(ser):
    # La respuesta valida demuestra conexion aunque el lector tenga un valor
    # fuera del rango 5..30 que esta aplicacion permite configurar.
    return request_response(ser, 0x22, data_length=2)[1]


def antenna_status(detailed=False):
    ser = serial.Serial(PORT, BAUD, timeout=0.15)
    try:
        power = read_power(ser)
        if detailed:
            print("OK")
            print("CONNECTED=1")
            print("PORT=" + PORT)
            print("BAUDRATE=" + str(BAUD))
            print("TIMEOUT_MS=" + str(TIMEOUT_MS))
            print("POWER=" + str(power))
        else:
            print("POWER=" + str(power))
            print("OK")
        return 0
    finally:
        ser.close()


def configure_power(power):
    power = normalize_power(power)
    ser = serial.Serial(PORT, BAUD, timeout=0.15)
    try:
        actual = set_power(ser, power)
        print("POWER=" + str(actual))
        print("OK")
        return 0
    finally:
        ser.close()


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

            # Una etiqueta con EPC en ceros sigue presente; no confundirla con NO_TAG.
            if epc:
                epcs.append(epc)

        i += frame_len

    return epcs


def init_reader(ser, buzzer_off=True, power=None):
    power = configured_power() if power is None else normalize_power(power)
    send_hex(ser, "A5 00 32 32")          # get mode
    set_power(ser, power)                 # ACK + lectura verifican el ajuste persistido
    send_hex(ser, "A5 03 43 00 00 00 46") # read area EPC
    if buzzer_off:
        send_hex(ser, "A5 01 13 00 14")   # buzzer off


def inventory(only_first=False):
    power = configured_power()
    ser = serial.Serial(PORT, BAUD, timeout=0.15)

    try:
        init_reader(ser, buzzer_off=True, power=power)
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
    power = configured_power()
    ser = serial.Serial(PORT, BAUD, timeout=0.25)

    try:
        init_reader(ser, buzzer_off=True, power=power)

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
    if action == "version":
        print("ERROR=VERSION_NOT_SUPPORTED")
        return 1
    if action not in ("status", "get-power", "set-power", "read-epc", "inventory", "write-epc", "clear"):
        print("ERROR=UNKNOWN_ACTION")
        return 1
    if action == "write-epc" and len(args) < 2:
        print("ERROR=EPC_REQUIRED")
        return 1
    try:
        if action == "set-power":
            if len(args) < 2:
                raise ValueError("POWER_REQUIRED")
            power = normalize_power(args[1])
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
        if action in ("status", "get-power"):
            return antenna_status(detailed=action == "status")
        if action == "set-power":
            return configure_power(power)
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
