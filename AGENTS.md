# Instrucciones del proyecto

## Contexto

- Este repositorio corresponde al pad OR2103: https://github.com/marijoatech/rfid-pad-bridge-or2103.git.
- Trabaja sobre esta raiz Git. Comprueba el directorio y el remoto antes de modificar o publicar archivos; no uses otra copia llamada rfid-bridge por asumir que es la misma.
- En Linux Mint se instala en /var/www/html/rfid-bridge, con Apache y PHP ya configurados.
- Conserva la distincion entre preparar una instalacion y corregir el protocolo RFID. No ejecutes escrituras o borrados de etiquetas como parte de verificaciones de documentacion o instalacion.

## Publicacion autorizada por el propietario

- Al terminar los cambios solicitados, ejecuta las comprobaciones adecuadas, revisa el diff y realiza commit y push automaticamente. No pidas una confirmacion adicional para esas operaciones ordinarias.
- Publica en la rama de trabajo y su upstream existente; actualmente master sigue origin/master. No cambies de rama ni publiques en otro remoto sin una instruccion que lo justifique.
- Incluye solo los archivos correspondientes a la tarea. Conserva cambios ajenos y no agregues automaticamente carpetas locales como nbproject ni credenciales o respaldos.
- Comprueba el estado remoto antes de publicar. No utilices force push ni descartes trabajo para resolver divergencias. Si hay un conflicto que no puedes resolver con seguridad, informa el impedimento.
- Respeta los controles de permisos y autenticacion del entorno. Si impiden el push, conserva el commit local e informa exactamente que falta; no solicites tokens o contrasenas por el chat.
- Verifica que el commit publicado coincida con la rama remota y comunica su identificador. Esta preferencia se aplica al finalizar tareas; no es un servicio que publica cada guardado de archivo.

## Validacion

- Para cambios en install.sh, comprueba la sintaxis con bash -n install.sh y prueba los argumentos y las operaciones de configuracion sin tocar hardware real.
- Para cambios en PHP, utiliza php -l PADBridge.php y comprobaciones pertinentes al comportamiento modificado.
- Indica cuando una validacion de Linux Mint, Apache o hardware real quede pendiente; no la des por realizada con pruebas simuladas.
