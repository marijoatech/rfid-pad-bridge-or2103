# RFID Bridge — pad OR2103

Puente HTTP en PHP para operar un lector RFID **OR2103**.
En Windows usa `OR2127LIB.dll`; en Linux, Python y un puerto serial USB.

**Este proyecto corresponde al OR2103.** El pad **R3-U5C** utiliza otro
repositorio porque su comunicación es diferente. En cada máquina, el proyecto
elegido se instala siempre en **`/var/www/html/rfid-bridge`**.

## Instalación rápida en una máquina Linux Mint o Debian nueva

Requisitos: **Apache y PHP ya funcionando**, acceso a Internet, Git, permisos
`sudo` y el pad OR2103 con su **selector inferior en USB**. Coloca el selector
en USB antes de conectar el pad; si estaba conectado en HID, desconéctalo,
cambia el selector a USB y vuelve a conectarlo. Desde una terminal:

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

## Ayuda visual en el navegador

Abre [la guía del bridge](http://localhost/rfid-bridge/PADBridge.php) sin
parámetros. Muestra las seis acciones, ejemplos de parámetros y respuestas,
el relleno del EPC y botones para operar el pad. Cada resultado aparece debajo
de su acción, en la misma página, sin abrir otra pestaña.

En **Grabar un EPC**, ingresa el número de lote o el EPC y pulsa **Grabar EPC**.
El número se completa con ceros desde la API. El botón **Vaciar EPC** escribe
siempre `000000000000000000000000` (24 ceros). Envía 6 palabras de forma fija,
sin pedir una cantidad al usuario. Una etiqueta detectada con el EPC vacío
devuelve `DETECTED=000000000000000000000000` tanto en lectura como en inventario.
`NO_TAG` indica que no se detectó ninguna etiqueta, no que su EPC esté en ceros.

La guía necesita JavaScript para ejecutar los botones, utiliza POST y no envía
comandos al cargarse. Mientras espera una respuesta, bloquea los botones para
evitar operaciones superpuestas. No reintenta automáticamente. Si se pierde la
respuesta de escritura o borrado, lee el EPC antes de repetir: la operación
podría haberse aplicado aunque el navegador no recibiera la confirmación.

- Un GET sin `action` que acepte HTML muestra la guía. `?help=1` permite abrirla
  explícitamente.
- Una petición con `action` devuelve JSON, también desde el navegador.
- POST, curl y las peticiones que solo aceptan JSON conservan la respuesta de
  error JSON cuando falta `action`. El instalador sigue usando esta respuesta.
- `?format=json` fuerza JSON en la URL sin acción, incluso en el navegador.

`PADBridge.php` es el punto de entrada. La lógica de la API está en
`lib/Bridge.php`; la vista en `views/help.php` y sus estilos en `assets/help.css`.
Los controladores del pad siguen en `linux/` y `windows/`. Esta organización
no elimina funciones ni cambia las llamadas de Marijoa.

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

Este bridge utiliza un **puerto serial USB** y no implementa el modo HID del
pad. Si el selector está en HID, el dispositivo puede no aparecer como puerto
serial y la lectura fallará al intentar abrir `/dev/ttyUSB0`.

El puerto predeterminado es `/dev/ttyUSB0`. Si no existe, el instalador lista
los puertos disponibles y explica cómo continuar. También puedes listarlos:

```bash
python3 -m serial.tools.list_ports -v
```

En la prueba de lectura realizada en Debian, el pad apareció como:

```text
/dev/ttyUSB0
    desc: CP2102 USB to UART Bridge Controller
    hwid: USB VID:PID=10C4:EA60
```

La lectura mediante Apache devolvió `DETECTED=...`, código de salida `0` y
`stderr` vacío. Identifica el puerto en cada máquina; el nombre puede cambiar.
Los puertos `ttyS0`, `ttyS1`, etc. que figuren en el listado no deben elegirse
por ser los primeros: busca el dispositivo USB correspondiente al pad.

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
PHP coordina las peticiones de esta instalación mediante un bloqueo: espera
hasta 5 segundos si otra operación está usando el bridge y devuelve
`ERROR=BRIDGE_BUSY` si continúa ocupado. El proceso tiene un límite de 30
segundos (`ERROR=BRIDGE_TIMEOUT`). No ejecutes el Python directamente mientras
otra aplicación está usando el pad: ese acceso no pasa por el bloqueo de PHP.

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
| `read-epc` | Implementada | Devuelve el primer EPC; conserva la respuesta inicial |
| `inventory` | Implementada | Devuelve los EPC detectados sin duplicados |
| `status` | Devuelve configuración; no comprueba la conexión | Devuelve configuración; no abre el puerto |
| `version` | Consulta la versión del lector | Devuelve `ERROR=VERSION_NOT_SUPPORTED`, con `ok=false` |
| `write-epc&epc=...` | Implementada | Implementada; conserva los comandos de escritura existentes |
| `clear&palabras=6` | Escribe un EPC de ceros | Escribe un EPC de ceros; respeta `palabras` |

`clear` utiliza 6 palabras por defecto (24 dígitos hexadecimales). PHP valida y
transmite `palabras`, entre 1 y 31; la capacidad física depende de la etiqueta.

Límites y pendientes:

- La interpretación de las tramas seriales y la validación completa del ACK
  de escritura siguen pendientes de contrastar con capturas del pad. Se
  conservan los comandos que ya funcionaron en Debian. `WRITTEN` indica que
  el bridge reconoció una confirmación; comprueba el EPC con una lectura
  posterior. No es una verificación independiente del contenido grabado.
- Las pruebas automatizadas utilizan un lector simulado. Antes de desplegar,
  valida lectura, inventario y escritura con una etiqueta de prueba en Debian.
- La API no incluye autenticación y acepta modificaciones mediante GET.
  Restringe su acceso en Apache o en la red antes de habilitar otros equipos.
- Linux utiliza las constantes de Python. La carga de `config.json` en Windows
  también tiene pendiente corregir la ubicación del archivo.

## Compatibilidad con Marijoa

No requiere modificar `grabarRFID`, `escanearTAGsRFID` ni `checkTAGRFID` en
`compras/Fraccionar.js`. Se conserva la URL
`http://localhost/rfid-bridge/PADBridge.php`, los parámetros enviados por POST
como formulario y el campo textual `resultado`. GET sigue disponible.

| Función de Marijoa | Parámetros | Resultado esperado |
| --- | --- | --- |
| `grabarRFID(epc)` | `action=write-epc`, `epc` | `WRITTEN=...` y una segunda línea `OK` |
| `escanearTAGsRFID()` | `action=inventory` | Líneas `DETECTED=...` o exactamente `NO_TAG` |
| `checkTAGRFID()` | `action=read-epc` | Una línea `DETECTED=...` o exactamente `NO_TAG` |

Un lote compuesto solo por dígitos y con menos de 24 caracteres se completa
con ceros a la izquierda. Por ejemplo, `epc=1000027` escribe
`000000000000000001000027`. Se conservan los dígitos: **no se convierte el
número decimal a hexadecimal**. Los EPC completos no reciben relleno. Otros
EPC hexadecimales deben tener una longitud múltiplo de 4, hasta 124 caracteres.
La validación se realiza antes de iniciar el proceso o abrir el lector.
El relleno del lote lo realiza PHP; el Python directo requiere un EPC alineado.

Respuesta de escritura para ese ejemplo:

```json
{
  "ok": true,
  "accion": "write-epc",
  "resultado": "WRITTEN=000000000000000001000027\nOK",
  "exit_code": 0,
  "stderr": ""
}
```

Las lecturas comienzan directamente por `DETECTED=`: no se anteponen mensajes
de configuración, porque Marijoa extrae el EPC por su posición. El inventario
puede devolver varias líneas, aunque el cliente actual utiliza solo la primera.

Los errores devuelven `ok=false`, `exit_code` distinto de cero y un `resultado`
que comienza por `ERROR=`. Una escritura sin etiqueta también puede devolver
`NO_TAG` con `ok=false`. La lectura sin etiquetas devuelve `NO_TAG` con `ok=true`.
PHP elimina las líneas de éxito cuando detecta un error, incluso si el ejecutable
terminó con código cero. Los errores de operación mantienen HTTP 200 para que
los manejadores actuales de jQuery puedan procesar el JSON. Se mantienen los
permisos CORS existentes.

## Problemas frecuentes

| Situación | Qué revisar |
| --- | --- |
| Puerto inexistente | USB conectado y puerto correcto; vuelve a instalar indicando `--port` |
| `Permission denied` | Usuario real de PHP, grupo `dialout` y reinicio de Apache/PHP-FPM |
| No aparece el puerto USB del pad | Selector inferior en USB; desconecta y reconecta si estaba en HID. Revisa también el cable y el reconocimiento por Linux |
| `ERROR=PYSERIAL_NOT_INSTALLED` | Ejecuta el instalador y utiliza el Python del sistema |
| HTTP 404 | Carpeta `/var/www/html/rfid-bridge`, DocumentRoot y host utilizado |
| HTTP devuelve código PHP o HTML | Configuración de PHP en Apache; consulta sus registros |
| `ERROR=UNKNOWN_ACTION` | Revisa el nombre de la acción; `status` e `inventory` están implementados. Actualiza si todavía usas una revisión anterior |
| `ERROR=VERSION_NOT_SUPPORTED` | La consulta de versión del lector aún no está implementada en Linux |
| `ERROR=BRIDGE_BUSY` | Otra petición ocupa el bridge; espera a que termine antes de repetir |
| `ERROR=BRIDGE_TIMEOUT` | El proceso excedió el límite; revisa puerto y lector. Antes de repetir una escritura, lee el EPC para saber si se aplicó |
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

## Pruebas de desarrollo sin hardware

Desde la raíz del repositorio:

```bash
php -n tests/test_api.php
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n install.sh
```

Las pruebas cubren validación y respuestas de PHP, ejecución y bloqueo de
procesos, transporte HTTP y operaciones de Python con el puerto simulado.
No escriben ni borran etiquetas. PHP CLI debe estar disponible en PATH.

Con Node.js, comprueba los controles de la ayuda con respuestas simuladas,
sin acceder a la red ni al pad:

```bash
node tests/test_help.js
```

Para comprobar las funciones originales de Marijoa, con Node.js disponible:

```powershell
node tests/test_marijoa.js C:\wamp64\www\marijoa\compras\Fraccionar.js
```

Esta prueba carga esas tres funciones y simula jQuery y sus respuestas, sin
modificar el archivo ni efectuar peticiones de red. Node.js solo es necesario
para esta prueba, no para instalar o utilizar el bridge.

## Referencias

- [Git: elegir el directorio al clonar](https://git-scm.com/docs/git-clone).
- [pySerial: instalación](https://pyserial.readthedocs.io/en/latest/pyserial.html#installation).
- [pySerial: permisos del puerto serial](https://pyserial.readthedocs.io/en/stable/appendix.html#faq).
