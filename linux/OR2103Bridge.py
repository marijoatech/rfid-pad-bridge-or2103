import serial
import time
import sys

PORT = "/dev/ttyUSB0"
BAUD = 115200
POWER_HEX = "0A"  # 0A=10, 0F=15, 1E=30


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


def build_write_epc(epc_hex):
    epc_hex = "".join(c for c in epc_hex.upper() if c in "0123456789ABCDEF")

    if len(epc_hex) % 4 != 0:
        raise ValueError("EPC_LENGTH_MUST_BE_WORD_ALIGNED")

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


def read_epc():
    ser = serial.Serial(PORT, BAUD, timeout=0.15)

    try:
        init_reader(ser, buzzer_off=True)
        ser.reset_input_buffer()

        send_hex(ser, "A5 00 53 53", 0.05)  # start inventory

        end = time.time() + 1.5
        buffer = bytearray()

        while time.time() < end:
            data = ser.read(512)

            if data:
                buffer.extend(data)
                epcs = parse_epcs(buffer)

                if epcs:
                    epc = epcs[0]
                    send_hex(ser, "A5 00 54 54", 0.03)  # stop inventory
                    beep(ser)
                    print("DETECTED=" + epc)
                    beep(ser)
                    return

        send_hex(ser, "A5 00 54 54", 0.03)
        print("NO_TAG")

    finally:
        ser.close()


def is_write_ok(resp):
    if not resp:
        return False

    for i in range(len(resp) - 4):
        if resp[i] == 0xA5 and resp[i + 2] == 0x57:
            return resp[i + 3] == 0x00

    return False


def write_epc(epc):
    ser = serial.Serial(PORT, BAUD, timeout=0.25)

    try:
        init_reader(ser, buzzer_off=True)

        cmd = build_write_epc(epc)
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
        else:
            beep_error(ser)
            print("ERROR=WRITE_FAILED")
            print("RESP1=" + resp1.hex().upper())
            print("RESP2=" + resp2.hex().upper())

    finally:
        ser.close()


def clear_epc():
    write_epc("000000000000000000000000")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR=ACTION_REQUIRED")
        sys.exit(1)

    action = sys.argv[1]

    if action == "read-epc":
        read_epc()

    elif action == "write-epc":
        if len(sys.argv) < 3:
            print("ERROR=EPC_REQUIRED")
            sys.exit(1)
        write_epc(sys.argv[2])

    elif action == "clear":
        clear_epc()

    else:
        print("ERROR=UNKNOWN_ACTION")