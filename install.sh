#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'HELP'
RFID Bridge OR2103: instalar en Linux Mint con Apache y PHP existentes.
Uso: sudo bash install.sh [--port DISPOSITIVO] [--web-user USUARIO] [--url URL]
     sudo bash install.sh --check [--web-user USUARIO] [--url URL]

  --port      Fija linux.port en config.json. Sin esta opcion se detecta el CP2102.
  --web-user  Usuario real de PHP (predeterminado: www-data).
  --url       URL de verificacion (http://localhost/rfid-bridge/PADBridge.php).
  --check     Solo verifica; no instala, modifica, reinicia ni abre el lector.

La instalacion reinicia Apache y los servicios PHP-FPM activos.
No escribe ni borra etiquetas. Consulta README.md para la prueba fisica.
HELP
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

check_only=false
requested_port=
web_user=www-data
bridge_url=http://localhost/rfid-bridge/PADBridge.php
while [[ $# -gt 0 ]]; do
    case $1 in
        --check) check_only=true; shift ;;
        --port|--web-user|--url)
            [[ $# -ge 2 && -n $2 && $2 != --* ]] || { usage >&2; exit 2; }
            case $1 in
                --port) requested_port=$2 ;;
                --web-user) web_user=$2 ;;
                --url) bridge_url=$2 ;;
            esac
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Argumento desconocido: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done
if [[ $check_only == true && -n $requested_port ]]; then
    printf '%s\n' 'ERROR: --check no se combina con --port, porque --port modifica la configuracion.' >&2
    exit 2
fi
[[ $web_user != -* && $web_user != *$'\n'* ]] || fail 'Usuario de PHP invalido.'
[[ $bridge_url == http://* || $bridge_url == https://* ]] || fail 'La URL debe comenzar con http:// o https://.'
[[ $bridge_url != *'?'* && $bridge_url != *'#'* ]] || fail 'Indica la URL de PADBridge.php sin parametros ni fragmentos.'
[[ -z $requested_port || $requested_port == /* ]] || fail '--port debe ser una ruta absoluta.'

[[ $(uname -s) == Linux ]] || fail 'Este instalador corresponde a Linux Mint / Debian / Ubuntu.'
[[ $EUID -eq 0 ]] || fail 'Ejecuta sudo bash install.sh desde la carpeta del proyecto.'
export PATH="/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ $project_dir == /var/www/html/rfid-bridge ]] || fail 'Instala este proyecto en /var/www/html/rfid-bridge antes de ejecutar el script.'
[[ -f $project_dir/PADBridge.php && -f $project_dir/lib/Bridge.php && -f $project_dir/linux/OR2103Bridge.py && -f $project_dir/config.json ]] || fail 'Faltan archivos del bridge OR2103.'
command -v apache2ctl >/dev/null 2>&1 || fail 'Apache debe estar instalado y PHP funcionando antes de instalar el bridge.'
command -v systemctl >/dev/null 2>&1 || fail 'Se necesita systemd para comprobar los servicios de esta instalacion.'
id "$web_user" >/dev/null 2>&1 || fail "No existe el usuario de PHP: $web_user"
[[ $(id -u "$web_user") -ne 0 ]] || fail '--web-user debe ser el usuario no privilegiado que ejecuta PHP.'
apache2ctl configtest

if [[ $check_only == false ]]; then
    command -v apt-get >/dev/null 2>&1 || fail 'Se necesita APT para instalar las dependencias.'
    printf '%s\n' 'Instalando dependencias del bridge OR2103...'
    # Un repositorio de terceros roto no debe impedir instalar con los indices disponibles.
    apt-get update --allow-releaseinfo-change || \
        printf 'Advertencia: apt-get update fallo; se intentara instalar con los indices disponibles.\n' >&2
    apt-get install -y python3 python3-serial php-cli curl
fi

for dependency in python3 php curl runuser; do
    command -v "$dependency" >/dev/null 2>&1 || fail "Falta $dependency. Ejecuta sudo bash install.sh."
done
if [[ -x /usr/bin/python3 ]]; then
    web_python=/usr/bin/python3
else
    web_python=$(runuser -u "$web_user" -- python3 -c 'import sys; print(sys.executable)') || \
        fail "No se pudo ejecutar python3 como $web_user."
fi
runuser -u "$web_user" -- "$web_python" -c 'import serial' || \
    fail "Falta pySerial para $web_user ($web_python). Instala python3-serial o revisa que PHP use ese Python."
printf 'Python de PHP: %s (pySerial OK)\n' "$web_python"
php -l "$project_dir/PADBridge.php"
php -l "$project_dir/lib/Bridge.php"

# Solo esta carpeta local necesita escritura para conservar la potencia elegida.
runtime_dir="$project_dir/runtime"
[[ ! -L $runtime_dir ]] || fail 'runtime no debe ser un enlace simbolico.'
if [[ $check_only == false ]]; then
    install -d -m 0700 -o "$web_user" -g "$(id -gn "$web_user")" -- "$runtime_dir"
fi
[[ -d $runtime_dir ]] || fail 'Falta runtime. Ejecuta sudo bash install.sh para preparar los permisos de potencia.'
runuser -u "$web_user" -- test -w "$runtime_dir" && runuser -u "$web_user" -- test -x "$runtime_dir" || fail "$web_user no puede escribir en runtime. Ejecuta sudo bash install.sh con el usuario PHP correcto."
if [[ -e $runtime_dir/antenna-power.json ]]; then
    runuser -u "$web_user" -- test -r "$runtime_dir/antenna-power.json" || fail "$web_user no puede leer runtime/antenna-power.json."
fi

# Leer, detectar o ajustar linux.port en config.json sin ejecutar el controlador.
reader_port=$(python3 - "$project_dir/config.json" "$project_dir/linux/OR2103Bridge.py" "$requested_port" "$check_only" <<'PY'
import ast
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile

try:
    import serial.tools.list_ports as list_ports
except ImportError:
    list_ports = None


def is_device(path):
    try:
        return stat.S_ISCHR(os.stat(path).st_mode)
    except OSError:
        return False


def usb_serial_ports():
    if list_ports is None:
        return []
    ports = []
    seen = set()
    for info in list_ports.comports():
        # En Linux, un adaptador USB serial expone vid/pid; los ttyS nativos no.
        if info.vid is None or not str(info.device).startswith("/dev/") or info.device in seen:
            continue
        seen.add(info.device)
        ports.append(info)
    return ports


def describe(info):
    return "{} ({:04X}:{:04X}, {})".format(
        info.device, info.vid, info.pid, info.description or "USB serial")


def detect_port(ports):
    cp2102 = [info for info in ports if info.vid == 0x10C4 and info.pid == 0xEA60]
    if len(cp2102) == 1:
        return cp2102[0].device
    if len(cp2102) > 1:
        raise ValueError("Hay varios CP2102 conectados: " +
                         ", ".join(describe(info) for info in cp2102) +
                         ". Indica el puerto del pad con --port.")
    if len(ports) == 1:
        return ports[0].device
    if not ports:
        raise ValueError("No se detecto ningun puerto USB serial. Conecta el pad en modo USB.")
    raise ValueError("Hay varios puertos USB serial: " +
                     ", ".join(describe(info) for info in ports) +
                     ". Indica el puerto del pad con --port.")


def update_port(new_port):
    backup = config_path.with_name(config_path.name + ".install-backup")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    section["port"] = new_port
    updated = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    previous = config_path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=config_path.parent,
                                         delete=False) as output:
            temporary = pathlib.Path(output.name)
            output.write(updated)
        os.chmod(temporary, stat.S_IMODE(previous.st_mode))
        os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, config_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print("linux.port actualizado en config.json: " + new_port +
          ". Respaldo: " + str(backup), file=sys.stderr)


try:
    config_path = pathlib.Path(sys.argv[1])
    source_path = pathlib.Path(sys.argv[2])
    requested = sys.argv[3]
    check_only = sys.argv[4] == "true"

    # La constante del controlador queda como respaldo si config.json no define linux.port.
    source = source_path.read_text(encoding="utf-8-sig")
    assignments = [
        node for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PORT" for target in node.targets
        )
    ]
    if len(assignments) != 1:
        raise ValueError("se esperaba una sola constante PORT en el fuente")
    fallback = ast.literal_eval(assignments[0].value)

    document = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("config.json debe contener un objeto")
    section = document.get("linux")
    if not isinstance(section, dict):
        raise ValueError("config.json debe contener la seccion linux")
    configured = section.get("port", fallback)
    configured_valid = (isinstance(configured, str) and configured.startswith("/") and
                        not any(c in configured for c in "\r\n\x00"))

    if requested:
        if any(c in requested for c in "\r\n\x00"):
            raise ValueError("el puerto contiene caracteres invalidos")
        if not is_device(requested):
            raise ValueError("el puerto indicado no es un dispositivo")
        port = requested
    else:
        ports = usb_serial_ports()
        cp2102 = [info for info in ports if info.vid == 0x10C4 and info.pid == 0xEA60]
        if len(cp2102) == 1:
            port = cp2102[0].device
        elif len(cp2102) > 1 and not (configured_valid and
                                       any(info.device == configured for info in cp2102)):
            detect_port(ports)  # varios CP2102 sin una eleccion configurada
        elif configured_valid and is_device(configured):
            port = configured
        else:
            port = detect_port(ports)

    if port != configured:
        if check_only:
            raise ValueError("Se detecto el puerto " + port + ", pero config.json usa " +
                             str(configured) + ". Ejecuta sudo bash install.sh sin --check " +
                             "para actualizar la configuracion.")
        update_port(port)
    print(port)
except (OSError, SyntaxError, ValueError, TypeError) as error:
    print("ERROR al configurar el puerto: " + str(error), file=sys.stderr)
    sys.exit(1)
PY
)

if [[ $check_only == false ]]; then
    getent group dialout >/dev/null || fail 'No existe el grupo dialout. Revisa los permisos seriales del sistema.'
    if [[ " $(id -nG "$web_user") " != *' dialout '* ]]; then
        usermod -aG dialout "$web_user"
    fi
    # Los procesos existentes deben reiniciarse para adquirir el grupo nuevo.
    active_fpm=$(systemctl list-units --type=service --state=active --no-legend --no-pager 'php*-fpm.service')
    while read -r service _; do
        if [[ $service =~ ^php[0-9]+\.[0-9]+-fpm\.service$ ]]; then
            printf 'Reiniciando %s...\n' "$service"
            systemctl restart "$service"
        fi
    done <<< "$active_fpm"
    systemctl restart apache2
fi

systemctl is-active --quiet apache2 || fail 'Apache no esta activo. Revisa systemctl status apache2.'
runuser -u "$web_user" -- test -r "$project_dir/PADBridge.php" || fail "$web_user no puede leer PADBridge.php o recorrer sus carpetas."
runuser -u "$web_user" -- test -r "$project_dir/lib/Bridge.php" || fail "$web_user no puede leer lib/Bridge.php."
runuser -u "$web_user" -- test -r "$project_dir/linux/OR2103Bridge.py" || fail "$web_user no puede leer el programa Python."
runuser -u "$web_user" -- /usr/bin/python3 -c 'import serial' || fail "El Python ejecutado como $web_user no puede importar pySerial."

printf '\nPad: OR2103\nUsuario de PHP: %s\nPuerto configurado: %s\n' "$web_user" "$reader_port"
if [[ ! -c $reader_port ]]; then
    python3 -m serial.tools.list_ports -v
    fail 'Puerto no disponible. Conecta el pad y repite con --port /dev/RUTA_REAL_DEL_PAD.'
fi
if ! runuser -u "$web_user" -- test -r "$reader_port" || ! runuser -u "$web_user" -- test -w "$reader_port"; then
    ls -l -- "$reader_port" >&2
    fail "$web_user no tiene acceso de lectura y escritura al puerto. Revisa su grupo y los permisos del dispositivo."
fi

# Sin action, PADBridge devuelve este error JSON antes de ejecutar el bridge.
# Esto verifica Apache/PHP sin realizar operaciones RFID.
http_response=$(curl --noproxy '*' --silent --show-error --fail --connect-timeout 5 --max-time 15 "$bridge_url") || fail "No se pudo acceder a $bridge_url. Revisa Apache, su DocumentRoot y el host."
if ! printf '%s' "$http_response" | python3 -c '
import json, sys
try:
    result = json.load(sys.stdin)
    valid = isinstance(result, dict) and result.get("ok") is False and result.get("error") == "Parametro '\''action'\'' requerido"
except (ValueError, TypeError):
    valid = False
sys.exit(0 if valid else 1)
'; then
    fail 'La URL no devuelve el JSON esperado de PADBridge.php. Revisa que Apache ejecute PHP y sirva esta carpeta.'
fi

printf '\n%s\n' 'Entorno comprobado: dependencias, permisos y respuesta HTTP correctos.'
printf 'Prueba fisica pendiente: %s?action=read-epc\n' "$bridge_url"
printf '%s\n' \
    'La comprobacion no abre el lector ni valida proc_open en el PHP de Apache.' \
    'La lectura debe devolver DETECTED=... o NO_TAG; los fallos devuelven ok=false y ERROR=... .'
