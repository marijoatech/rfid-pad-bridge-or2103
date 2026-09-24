#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'HELP'
RFID Bridge OR2103: instalar en Linux Mint con Apache y PHP existentes.
Uso: sudo bash install.sh [--port DISPOSITIVO] [--web-user USUARIO] [--url URL]
     sudo bash install.sh --check [--web-user USUARIO] [--url URL]

  --port      Configura PORT en Python, guardando una copia antes del primer cambio.
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
[[ -f $project_dir/PADBridge.php && -f $project_dir/linux/OR2103Bridge.py ]] || fail 'Faltan archivos del bridge OR2103.'
command -v apache2ctl >/dev/null 2>&1 || fail 'Apache debe estar instalado y PHP funcionando antes de instalar el bridge.'
command -v systemctl >/dev/null 2>&1 || fail 'Se necesita systemd para comprobar los servicios de esta instalacion.'
id "$web_user" >/dev/null 2>&1 || fail "No existe el usuario de PHP: $web_user"
[[ $(id -u "$web_user") -ne 0 ]] || fail '--web-user debe ser el usuario no privilegiado que ejecuta PHP.'
apache2ctl configtest

if [[ $check_only == false ]]; then
    command -v apt-get >/dev/null 2>&1 || fail 'Se necesita APT para instalar las dependencias.'
    printf '%s\n' 'Instalando dependencias del bridge OR2103...'
    apt-get update
    apt-get install -y python3 python3-serial php-cli curl
fi

for dependency in python3 php curl runuser; do
    command -v "$dependency" >/dev/null 2>&1 || fail "Falta $dependency. Ejecuta sudo bash install.sh."
done
python3 -c 'import serial' || fail 'Falta pySerial para el Python del sistema.'
php -l "$project_dir/PADBridge.php"

# Leer o ajustar la constante sin importar ni ejecutar el controlador del lector.
reader_port=$(python3 - "$project_dir/linux/OR2103Bridge.py" "$requested_port" <<'PY'
import ast
import os
import pathlib
import shutil
import stat
import sys
import tempfile

try:
    source = pathlib.Path(sys.argv[1])
    requested = sys.argv[2]
    original = source.read_bytes()
    text = original.decode("utf-8-sig")
    assignments = [
        node for node in ast.parse(text).body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PORT" for target in node.targets
        )
    ]
    if len(assignments) != 1:
        raise ValueError("se esperaba una sola constante PORT en el fuente")
    assignment = assignments[0]
    port = ast.literal_eval(assignment.value)
    if requested:
        if any(c in requested for c in "\r\n\x00"):
            raise ValueError("el puerto contiene caracteres invalidos")
        if not stat.S_ISCHR(os.stat(requested).st_mode):
            raise ValueError("el puerto indicado no es un dispositivo")
        if port != requested:
            if assignment.lineno != assignment.end_lineno or len(assignment.targets) != 1:
                raise ValueError("PORT debe ser una asignacion simple en una linea")
            lines = text.splitlines(keepends=True)
            # Los desplazamientos del AST son bytes UTF-8, no indices Unicode.
            line = lines[assignment.lineno - 1].encode("utf-8")
            replacement = ("PORT = " + repr(requested)).encode("utf-8")
            lines[assignment.lineno - 1] = (
                line[:assignment.col_offset] + replacement + line[assignment.end_col_offset:]
            ).decode("utf-8")
            updated = "".join(lines).encode("utf-8")
            if original.startswith(b"\xef\xbb\xbf"):
                updated = b"\xef\xbb\xbf" + updated
            backup = source.with_name(source.name + ".install-backup")
            if not backup.exists():
                shutil.copy2(source, backup)
            previous = source.stat()
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=source.parent, delete=False) as output:
                    temporary = pathlib.Path(output.name)
                    output.write(updated)
                os.chmod(temporary, stat.S_IMODE(previous.st_mode))
                os.chown(temporary, previous.st_uid, previous.st_gid)
                os.replace(temporary, source)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            print("PORT actualizado. Respaldo: " + str(backup), file=sys.stderr)
        port = requested
    if not isinstance(port, str) or not os.path.isabs(port) or any(c in port for c in "\r\n\x00"):
        raise ValueError("PORT debe contener una ruta absoluta del dispositivo serial")
    print(port)
except (OSError, SyntaxError, ValueError, TypeError) as error:
    print("ERROR al configurar PORT: " + str(error), file=sys.stderr)
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
    'Comprueba resultado en la lectura: ok=true puede acompanarse de ERROR con el codigo actual.'
