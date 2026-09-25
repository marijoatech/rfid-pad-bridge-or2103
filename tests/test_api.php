<?php
require_once __DIR__ . '/../lib/Bridge.php';

function check($condition, string $message): void
{
    if (!$condition) throw new RuntimeException($message);
}

$root = dirname(__DIR__);
$epc = '000000000000000001000027';
$fixtures = [];
foreach ([false, true] as $windows) {
    $calls = [];
    $write = RfidBridge\handleRequest(['action' => 'write-epc', 'epc' => '1000027'], $root, $windows,
        function ($arguments) use (&$calls, $epc) {
            $calls[] = $arguments;
            check(end($arguments) === $epc, 'Enviar lote con ceros, sin conversion decimal/hex');
            return ['WRITTEN=' . $epc, '', 0];
        });
    check($write['ok'] && $write['resultado'] === 'WRITTEN=' . $epc . "\nOK", 'Contrato de grabarRFID');
    check(count($calls) === 1, 'Una sola llamada al bridge');
    $fixtures['write'] = $write;
}

foreach (['1000027', 1000027, $epc] as $input) {
    check(RfidBridge\normalizeEpc($input) === $epc, 'Normalizacion idempotente');
}
check(RfidBridge\normalizeEpc(' e28436110000100004210970 ') === 'E28436110000100004210970', 'Hexadecimal completo conservado');
check(RfidBridge\normalizeEpc('abcd') === 'ABCD', 'Hexadecimal alineado no numerico conservado');

$invoked = false;
$forbidden = function () use (&$invoked) { $invoked = true; throw new RuntimeException('No ejecutar entradas invalidas'); };
foreach ([[], ['action' => ['read-epc']], ['action' => 'invalid'], ['action' => 'write-epc'],
    ['action' => 'write-epc', 'epc' => []], ['action' => 'write-epc', 'epc' => ''],
    ['action' => 'write-epc', 'epc' => '1000-ZZZZ'], ['action' => 'write-epc', 'epc' => 'ABC'],
    ['action' => 'write-epc', 'epc' => str_repeat('A', 128)],
    ['action' => 'clear', 'palabras' => []], ['action' => 'clear', 'palabras' => '32'],
    ['action' => 'clear', 'palabras' => '0'], ['action' => 'set-power'],
    ['action' => 'set-power', 'power' => []], ['action' => 'set-power', 'power' => true],
    ['action' => 'set-power', 'power' => '4'], ['action' => 'set-power', 'power' => '31'],
    ['action' => 'set-power', 'power' => '10.5'], ['action' => 'set-power', 'power' => '10;echo x']] as $request) {
    $result = RfidBridge\handleRequest($request, $root, false, $forbidden);
    check(!$result['ok'] && is_string($result['resultado']) && strpos($result['resultado'], 'ERROR=') === 0,
        'Errores de validacion mantienen resultado textual');
}
check(!$invoked, 'No se abre hardware con entradas invalidas');
$health = RfidBridge\handleRequest([], $root, false, $forbidden);
check($health['error'] === "Parametro 'action' requerido", 'Conservar la comprobacion del instalador');

foreach ([1, 6, 10, 31] as $words) {
    $result = RfidBridge\handleRequest(['action' => 'clear', 'palabras' => (string) $words], $root, false,
        function ($arguments) use ($words) {
            check(end($arguments) === (string) $words, 'Transmitir palabras');
            return ['WRITTEN=' . str_repeat('0', $words * 4), '', 0];
        });
    check($result['ok'], 'Borrado con cantidad solicitada');
}

$fixtures['inventory'] = RfidBridge\parseResult('inventory', "COM=debug\nDETECTED=$epc\nDETECTED=$epc\n", '', 0);
$fixtures['read'] = RfidBridge\parseResult('read-epc', "COM=debug\nDETECTED=$epc\n", '', 0);
$fixtures['factory'] = RfidBridge\parseResult('read-epc', 'DETECTED=E28436110000100004210970', '', 0);
foreach (['read-epc', 'inventory'] as $action) {
    $fixtures['zeros_' . $action] = RfidBridge\parseResult($action, 'DETECTED=' . str_repeat('0', 24), '', 0);
    check($fixtures['zeros_' . $action]['ok'] && $fixtures['zeros_' . $action]['resultado'] === 'DETECTED=' . str_repeat('0', 24),
        'Una etiqueta en ceros sigue detectada en ' . $action);
}
$fixtures['no_tag'] = RfidBridge\parseResult('inventory', 'NO_TAG', '', 0);
$fixtures['error'] = RfidBridge\parseResult('write-epc', "WRITTEN=$epc\nOK\nERROR=WRITE_FAILED", '', 0, $epc);
check($fixtures['inventory']['resultado'] === 'DETECTED=' . $epc, 'DETECTED comienza en posicion cero, sin duplicados');
check($fixtures['no_tag']['ok'] && $fixtures['no_tag']['resultado'] === 'NO_TAG', 'Conservar reintentos de escaneo');
check(!$fixtures['error']['ok'] && $fixtures['error']['exit_code'] !== 0 && $fixtures['error']['resultado'] === 'ERROR=WRITE_FAILED', 'Errores no contienen indicadores de exito');
check(!RfidBridge\parseResult('write-epc', 'WRITTEN=FFFF', '', 0, $epc)['ok'], 'Confirmacion de otro EPC no es exito');
check(!RfidBridge\parseResult('inventory', '', '', 0)['ok'], 'Salida vacia no es exito');
check(!RfidBridge\parseResult('read-epc', 'DETECTED=' . $epc, 'failed', 1)['ok'], 'Exit code fallido prevalece');
check(!RfidBridge\parseResult('status', "OK\nPORT=/dev/ttyUSB0\nPOWER=10", '', 0)['ok'], 'Configuracion sola no demuestra conexion');
check(RfidBridge\parseResult('status', "OK\nCONNECTED=1\nPORT=/dev/ttyUSB0\nPOWER=10", '', 0)['ok'], 'Estado confirmado por lector');
check(!RfidBridge\parseResult('status', "OK\nCONNECTED=1", '', 0)['ok'], 'Estado sin potencia leida no confirma conexion');
check(!RfidBridge\parseResult('get-power', 'OK', '', 0)['ok'], 'Consultar potencia exige valor real');
check(!RfidBridge\parseResult('get-power', "POWER=10\nPOWER=9\nOK", '', 0)['ok'], 'Rechazar potencia ambigua');
check(!RfidBridge\parseResult('status', "OK\nCONNECTED=1\nPOWER=10\nPOWER=256", '', 0)['ok'], 'Rechazar duplicado de potencia incluso invalido');
check(RfidBridge\parseResult('get-power', "POWER=10\nOK", '', 0)['ok'], 'Potencia actual confirmada');
check(!RfidBridge\parseResult('set-power', "POWER=9\nOK", '', 0, '10')['ok'], 'Exigir lectura de la potencia solicitada');
check(!RfidBridge\parseResult('version', 'ERROR=VERSION_NOT_SUPPORTED', '', 1)['ok'], 'Version no soportada explicita');
$fixtures['status'] = RfidBridge\parseResult('status', "OK\nCONNECTED=1\nCOM=COM5\nPOWER=10", '', 0);
$fixtures['status_offline'] = RfidBridge\parseResult('status', 'ERROR=CONNECT_FAILED', '', 2);

// Persistencia en una instalacion temporal: nunca modifica la potencia guardada del equipo real.
$powerRoot = sys_get_temp_dir() . '/rfid-power-test-' . bin2hex(random_bytes(6));
mkdir($powerRoot . '/linux', 0700, true);
mkdir($powerRoot . '/windows', 0700, true);
file_put_contents($powerRoot . '/linux/OR2103Bridge.py', '');
file_put_contents($powerRoot . '/windows/OR2103Bridge.exe', '');
$powerPath = $powerRoot . '/runtime/antenna-power.json';
try {
    foreach ([false, true] as $onWindows) {
        foreach ([5, 15, 30] as $power) {
            $result = RfidBridge\handleRequest(['action' => 'set-power', 'power' => (string) $power], $powerRoot, $onWindows,
                function ($arguments) use ($power) {
                    check(end($arguments) === (string) $power, 'Pasar potencia validada al backend');
                    return ["POWER=$power\nOK", '', 0];
                });
            check($result['ok'] && $result['resultado'] === "POWER=$power\nOK", 'Cambio confirmado');
            check(json_decode(file_get_contents($powerPath), true) === ['power' => $power], 'Guardar potencia para siguientes operaciones');
        }
    }
    foreach ([["POWER=9\nOK", '', 0], ['ERROR=READER_NOT_RESPONDING', '', 1], ["POWER=10\nOK", '', 1]] as $reply) {
        $result = RfidBridge\handleRequest(['action' => 'set-power', 'power' => '10'], $powerRoot, false,
            function () use ($reply) { return $reply; });
        check(!$result['ok'], 'No confirmar fallos ni valores distintos');
        check(json_decode(file_get_contents($powerPath), true)['power'] === 30, 'Fallo conserva potencia guardada');
    }
    check(count(glob($powerRoot . '/runtime/.power-*')) === 0, 'Eliminar archivos temporales');
    unlink($powerPath);
    mkdir($powerPath);
    $result = RfidBridge\handleRequest(['action' => 'set-power', 'power' => '10'], $powerRoot, false, $forbidden);
    check(!$invoked && !$result['ok'] && $result['resultado'] === 'ERROR=POWER_STORAGE_UNAVAILABLE', 'Destino directorio se rechaza antes de tocar lector');
    rmdir($powerPath);
    rmdir($powerRoot . '/runtime');
    file_put_contents($powerRoot . '/runtime', 'impide crear directorio');
    $result = RfidBridge\handleRequest(['action' => 'set-power', 'power' => '10'], $powerRoot, false, $forbidden);
    check(!$invoked && !$result['ok'] && $result['resultado'] === 'ERROR=POWER_STORAGE_UNAVAILABLE', 'Rechazar falta de almacenamiento antes de tocar lector');
    unlink($powerRoot . '/runtime');
} finally {
    if (is_file($powerPath)) unlink($powerPath);
    if (is_dir($powerRoot . '/runtime')) rmdir($powerRoot . '/runtime');
    if (is_file($powerRoot . '/runtime')) unlink($powerRoot . '/runtime');
    unlink($powerRoot . '/linux/OR2103Bridge.py');
    unlink($powerRoot . '/windows/OR2103Bridge.exe');
    rmdir($powerRoot . '/linux');
    rmdir($powerRoot . '/windows');
    rmdir($powerRoot);
    @unlink(sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'rfid-bridge-' . hash('sha256', $powerRoot) . '.lock');
}

// Proceso real sin hardware: salida simultanea, codigo de retorno y vencimiento.
$windows = DIRECTORY_SEPARATOR === '\\';
$childScript = tempnam(sys_get_temp_dir(), 'rfid-test-');
try {
    file_put_contents($childScript, '<?php fwrite(STDERR, str_repeat("e", 150000)); echo "OK"; exit(7);');
    $command = RfidBridge\commandLine([PHP_BINARY, '-n', $childScript], $windows);
    $execution = RfidBridge\runProcess($command, $root, 5);
    check($execution[0] === 'OK' && strlen($execution[1]) === 150000 && $execution[2] === 7, 'Drenar stdout/stderr sin bloqueo y conservar exit code');
    file_put_contents($childScript, '<?php usleep(2000000);');
    $started = microtime(true);
    $execution = RfidBridge\runProcess($command, $root, 0.1);
    check($execution[0] === 'ERROR=BRIDGE_TIMEOUT' && $execution[2] !== 0 && microtime(true) - $started < 1.5, 'Interrumpir procesos vencidos');
} finally {
    unlink($childScript);
}
$nested = RfidBridge\withReaderLock($root . '-test-' . getmypid(), function () use ($root) {
    return RfidBridge\withReaderLock($root . '-test-' . getmypid(), function () { throw new RuntimeException('No debe entrar'); }, 0.1);
});
check($nested[0] === 'ERROR=BRIDGE_BUSY', 'Dos operaciones no abren el lector a la vez');
@unlink(sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'rfid-bridge-' . hash('sha256', $root . '-test-' . getmypid()) . '.lock');

echo in_array('--fixtures', $argv, true) ? json_encode($fixtures) : "OK: contrato HTTP, validacion, procesos y concurrencia\n";
