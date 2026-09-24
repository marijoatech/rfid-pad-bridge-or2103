# RFID Bridge — pad OR2103

Puente HTTP en PHP para operar un lector RFID **OR2103**.
En Windows usa `OR2127LIB.dll`; en Linux, Python y un puerto serial USB.

**Este proyecto corresponde al OR2103.** El pad **R3-U5C** utiliza otro
repositorio porque su comunicación es diferente. En cada máquina, el proyecto
elegido se instala siempre en **`/var/www/html/rfid-bridge`**.

## Instalación rápida en una máquina Linux Mint nueva

Requisitos: **Apache y PHP ya funcionando**, acceso a Internet, Git, permisos
`sudo` y el pad OR2103 conectado por USB. Desde una terminal:

```bash
cd /var/www/html
sudo git clone https://github.com/marijoatech/rfid-pad-bridge-or2103.git rfid-bridge
cd rfid-bridge
sudo bash install.sh
```

El último argumento de `git clone`, **`rfid-bridge`**, fija el nombre de la
carpeta local. El repositorio conserva su nombre en GitHub.

Después de instalar, coloca una etiqueta cerca del pad y abre:

[Probar lectura RFID](http://localhost/rfid-bridge/PADBridge.php?action=read-epc)

Repite esos pasos en cada máquina. No es necesario ejecutar el instalador en
cada encendido: Apache recibe las peticiones y PHP inicia el bridge cuando
se solicita una operación.

> La instalación prepara dependencias, permisos y acceso HTTP. No corrige los
> problemas pendientes del protocolo ni garantiza una lectura física exitosa.

## Qué hace el instalador

- Instala `python3`, `python3-serial`, `php-cli` y `curl` mediante APT.
- Utiliza el Apache y PHP existentes; no instala otro servidor web.
- Agrega al grupo `dialout` al usuario que ejecuta PHP (`www-data` por defecto).
- Comprueba la configuración de Apache y reinicia Apache y los servicios
  PHP-FPM activos para que tomen los nuevos permisos. Programa esta instalación
  cuando puedas reiniciar esos servicios si alojan otras aplicaciones.
- Comprueba archivos, dependencias y permisos del dispositivo como el usuario de PHP.
- Comprueba que la URL del bridge devuelva JSON, sin enviar comandos al lector.

Puede ejecutarse de nuevo. No escribe ni borra etiquetas, no aplica `chmod 666`
al USB y no cambia automáticamente el inicio de servicios al encender Linux.

Si usas un pool PHP-FPM con otro usuario, indica el usuario real del pool:

```bash
sudo bash install.sh --web-user usuario_del_pool
```

Esta opción configura permisos; no cambia el usuario de Apache ni del pool.

## Puerto USB de cada máquina

El puerto predeterminado es `/dev/ttyUSB0`. Si no existe, el instalador lista
los puertos disponibles y explica cómo continuar. También puedes listarlos:

```bash
python3 -m serial.tools.list_ports -v
```

Para configurar un puerto diferente durante la instalación:

```bash
sudo bash install.sh --port /dev/ttyACM0
```

Si el dispositivo tiene una ruta en `/dev/serial/by-id/`, puedes pasar esa ruta
para mantener su identidad aunque cambie el número `ttyUSB`:

```bash
ls -l /dev/serial/by-id/
sudo bash install.sh --port /dev/serial/by-id/RUTA_REAL_DEL_PAD
```

Reemplaza `RUTA_REAL_DEL_PAD` por el nombre real. Con varios dispositivos
conectados, identifica el pad antes de elegirlo; el instalador no adivina el modelo.

**Linux todavía no lee `config.json`.** `--port` actualiza únicamente la
constante `PORT` en `linux/OR2103Bridge.py`. Antes del primer cambio guarda una
copia en `linux/OR2103Bridge.py.install-backup`. Conserva ese ajuste al actualizar
el repositorio. Las constantes de velocidad y potencia siguen en Python:
`BAUD = 115200` y `POWER_HEX = "0A"`.

## Comprobar una instalación existente

Desde `/var/www/html/rfid-bridge`:

```bash
sudo bash install.sh --check
```

`--check` comprueba el entorno sin instalar paquetes, cambiar configuración,
reiniciar servicios ni abrir el lector. Usa `--web-user` si tu usuario de PHP
es distinto de `www-data`.

Si tu Apache utiliza un nombre de host o puerto HTTP diferente:

```bash
sudo bash install.sh --check --url http://mi-equipo/rfid-bridge/PADBridge.php
```

`--url` solo cambia la dirección utilizada para verificar HTTP; no configura Apache.

Para realizar una lectura real:

```bash
curl 'http://localhost/rfid-bridge/PADBridge.php?action=read-epc'
```

Una lectura puede devolver `DETECTED=...` o `NO_TAG` en el campo `resultado`.
Ejecuta las pruebas de una en una; aún no existe coordinación entre procesos
que intentan utilizar el puerto simultáneamente.

## Elegir otro pad conservando la misma carpeta

Para el **R3-U5C**, copia la URL HTTPS desde **Code → HTTPS** de su repositorio
`rfid-bridge-pad-R3-U5C` y úsala como origen:

```bash
cd /var/www/html
sudo git clone URL_HTTPS_DEL_REPOSITORIO_R3_U5C rfid-bridge
```

El marcador `URL_HTTPS_DEL_REPOSITORIO_R3_U5C` debe sustituirse por la URL real.
Los scripts y dependencias de este README corresponden al **OR2103**; sigue
las instrucciones del otro repositorio al instalar el R3-U5C.

Si `rfid-bridge` ya contiene otra instalación, deja de enviarle peticiones y
renombra la carpeta anterior como respaldo antes de clonar. Conserva sus
ajustes locales. No clones los dos proyectos dentro de la misma carpeta.

Para identificar qué proyecto y revisión están instalados:

```bash
cd /var/www/html/rfid-bridge
sudo git remote get-url origin
sudo git log -1 --oneline
```

## Acciones disponibles y límites actuales

Estos estados describen el código; las operaciones físicas deben validarse
con el pad y las etiquetas utilizados.

| Acción HTTP | Windows, fuente principal | Linux |
| --- | --- | --- |
| `read-epc` | Implementada | Implementada; puede perder la respuesta inicial |
| `inventory` | Implementada | No implementada |
| `status` | Devuelve configuración; no comprueba la conexión | No implementada |
| `version` | Consulta la versión del lector | No implementada |
| `write-epc&epc=...` | Implementada | Implementada; protocolo y confirmación pendientes de validar |
| `clear` | Escribe un EPC de ceros | Escribe un EPC de 24 ceros |

Pendientes de corrección:

- Algunos errores de Linux terminan con código cero: **`ok: true` no significa
  éxito si `resultado` contiene `ERROR=...`.**
- PHP no transmite `palabras` a `clear`; cambiar ese parámetro no cambia la
  cantidad borrada.
- La validación del EPC y de las respuestas seriales necesita mejoras.
  Valida escritura y borrado con etiquetas de prueba.
- La API no incluye autenticación y acepta modificaciones mediante GET.
  Restringe su acceso en Apache o en la red antes de habilitar otros equipos.
- Linux utiliza las constantes de Python. La carga de `config.json` en Windows
  también tiene pendiente corregir la ubicación del archivo.

## Problemas frecuentes

| Situación | Qué revisar |
| --- | --- |
| Puerto inexistente | USB conectado y puerto correcto; vuelve a instalar indicando `--port` |
| `Permission denied` | Usuario real de PHP, grupo `dialout` y reinicio de Apache/PHP-FPM |
| No aparece ningún puerto | Cable, conexión USB y reconocimiento del dispositivo por Linux |
| `No module named serial` | Ejecuta el instalador y utiliza el Python del sistema |
| HTTP 404 | Carpeta `/var/www/html/rfid-bridge`, DocumentRoot y host utilizado |
| HTTP devuelve código PHP o HTML | Configuración de PHP en Apache; consulta sus registros |
| `ERROR=UNKNOWN_ACTION` | `status`, `inventory` y `version` no están implementados en Linux |
| `NO_TAG` | Posición y compatibilidad de la etiqueta; no demuestra por sí solo un problema de instalación |
| Lectura falla solo por HTTP | Usuario de PHP, permisos del puerto y disponibilidad de `proc_open` en el PHP del servidor |

No se necesita Composer, .NET ni compilar ejecutables de Windows para usar Linux.
Ejecutar `bash install.sh` no requiere aplicar `chmod +x` al script.

## Windows

PHP utiliza `windows/OR2103Bridge.exe` y `windows/OR2127LIB.dll`.
Para compilar el fuente principal, ejecuta desde una consola Windows:

```bat
cd windows
build-csc.bat
```

El `.csproj` incluye una segunda implementación en `src/Program.cs` que entra
en conflicto con el fuente principal. El script anterior compila únicamente
`OR2103Bridge.cs`.

## Actualizar una máquina instalada

Deja de enviar operaciones mientras actualizas. Comprueba primero los cambios
locales, especialmente el puerto configurado por el instalador:

```bash
cd /var/www/html/rfid-bridge
sudo git status --short
sudo git diff
sudo git pull --ff-only
sudo bash install.sh --check
```

Si Git detecta cambios incompatibles, conserva y revisa tus ajustes antes de
continuar. No descartes el puerto configurado para esa máquina.

Antes de desplegar en las diez máquinas, valida la instalación y una lectura
en la primera. Instala la misma revisión validada en las máquinas que usen el
mismo modelo de pad, en lugar de mezclar revisiones durante el despliegue.

Para administrar varias máquinas, registra por equipo: nombre de máquina,
modelo de pad, URL del repositorio, commit instalado, ruta del puerto, usuario
de PHP y resultado de la prueba física. Así puedes repetir una instalación conocida.

## Referencias

- [Git: elegir el directorio al clonar](https://git-scm.com/docs/git-clone).
- [pySerial: instalación](https://pyserial.readthedocs.io/en/latest/pyserial.html#installation).
- [pySerial: permisos del puerto serial](https://pyserial.readthedocs.io/en/stable/appendix.html#faq).
