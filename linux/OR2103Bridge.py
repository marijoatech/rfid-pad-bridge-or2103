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


def pop_frame(buffer):
    """Extraer una trama completa sin buscar cabeceras dentro de sus datos."""
    start = buffer.find(b"\xA5")
    if start < 0:
        buffer.clear()
        return None
    if start:
        del buffer[:start]
    if len(buffer) < 3:
        return None
    frame_length = buffer[1] + 4
    if len(buffer) < frame_length:
        return None
    frame = bytes(buffer[:frame_length])
    del buffer[:frame_length]
    if checksum(frame[:-1]) != frame[-1]:
        raise ValueError("READER_CHECKSUM")
    return frame


class FrameReader:
    def __init__(self, ser):
        self.ser = ser
        self.buffer = bytearray()
        self.received = 0
        self.tag_frames = 0

    def read_frame(self, deadline):
        while True:
            frame = pop_frame(self.buffer)
            if frame is not None:
                if frame[2] == 0x55:
                    self.tag_frames += 1
                return frame
            if time.monotonic() >= deadline:
                return None
            chunk = self.ser.read(256)
            self.received += len(chunk)
            self.buffer.extend(chunk)


def response_data(frame, data_length):
    payload = frame[3:-1]
    if not payload:
        raise ValueError("READER_RESPONSE_INVALID")
    if payload[0] != 0:
        raise ValueError("READER_STATUS_" + format(payload[0], "02X"))
    if len(payload) != data_length:
        raise ValueError("READER_RESPONSE_INVALID")
    return payload


def diagnostic(cmd, reader, received_before=0, tags_before=0):
    # Solo contadores: no volcar EPC, memoria de etiquetas ni bytes recibidos.
    print("RFID_DIAG CMD=" + format(cmd, "02X") +
          " RX_BYTES=" + str(reader.received - received_before) +
          " TAG_FRAMES=" + str(reader.tag_frames - tags_before), file=sys.stderr)


def request_response(ser, cmd, data=b"", data_length=1, reader=None, on_tag=None):
    """Esperar ACK sin perder etiquetas recibidas junto a una respuesta.

    SDK OR2127LIB: longitud total = byte de longitud + 4. Un FrameReader
    compartido conserva datos pendientes entre START, inventario y STOP.
    """
    supplied_reader = reader is not None
    reader = reader if supplied_reader else FrameReader(ser)
    received_before, tags_before = reader.received, reader.tag_frames
    try:
        if not supplied_reader:
            ser.reset_input_buffer()
        ser.write(command(cmd, data))
        deadline = time.monotonic() + TIMEOUT_MS / 1000.0
        while True:
            frame = reader.read_frame(deadline)
            if frame is None:
                raise ValueError("READER_NOT_RESPONDING")
            if frame[2] == 0x55 and on_tag is not None:
                on_tag(frame)
            if frame[2] == cmd:
                return response_data(frame, data_length)
    except Exception:
        diagnostic(cmd, reader, received_before, tags_before)
        raise


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


def epc_from_frame(frame):
    if len(frame) < 5 or frame[2] != 0x55:
        raise ValueError("READER_RESPONSE_INVALID")
    if frame[3] != 0:
        raise ValueError("READER_STATUS_" + format(frame[3], "02X"))
    if len(frame) < 12:
        raise ValueError("READER_RESPONSE_INVALID")
    pc = int.from_bytes(frame[4:6], "big")
    epc_length = ((pc >> 11) & 0x1F) * 2
    # Cabecera+estado+PC (6), RSSI (2), antena (1), checksum (1).
    # Los datos opcionales TID/USER pueden aparecer antes de RSSI/antena.
    if epc_length < 2 or len(frame) < epc_length + 10:
        raise ValueError("READER_RESPONSE_INVALID")
    return frame[6:6 + epc_length].hex().upper()


def parse_epcs(buffer):
    pending = bytearray(buffer)
    epcs = []
    while True:
        frame = pop_frame(pending)
        if frame is None:
            return epcs
        if frame[2] == 0x55:
            epcs.append(epc_from_frame(frame))


def init_reader(ser, buzzer_off=True, power=None):
    power = configured_power() if power is None else normalize_power(power)
    send_hex(ser, "A5 00 32 32")          # get mode
    set_power(ser, power)                 # ACK + lectura verifican el ajuste persistido
    # Inventario usa 0x53; no modificar el area HID/RESERVE mediante 0x43.
    # Se conserva buzzer_off como argumento compatible. No enviar 0x13:
    # ese comando dejo al pad sin responder en la prueba fisica de Linux.


def inventory(only_first=False):
    power = configured_power()
    ser = serial.Serial(PORT, BAUD, timeout=0.15)

    try:
        init_reader(ser, buzzer_off=True, power=power)
        ser.reset_input_buffer()
        reader = FrameReader(ser)
        detected = []

        def collect_tag(frame):
            epc = epc_from_frame(frame)
            if epc not in detected:
                detected.append(epc)

        try:
            # El bloque finally tambien intenta STOP si START no fue confirmado.
            request_response(ser, 0x53, reader=reader, on_tag=collect_tag)
            deadline = time.monotonic() + TIMEOUT_MS / 1000.0
            received_before, tags_before = reader.received, reader.tag_frames
            try:
                while not (only_first and detected):
                    frame = reader.read_frame(deadline)
                    if frame is None:
                        break
                    if frame[2] == 0x55:
                        collect_tag(frame)
            except Exception:
                diagnostic(0x55, reader, received_before, tags_before)
                raise
        finally:
            # No vaciar RX: puede haber etiquetas y ACK juntos o fragmentados.
            request_response(ser, 0x54, reader=reader, on_tag=collect_tag)

        # Marijoa solo recibe exito despues de confirmar que el inventario paro.
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
