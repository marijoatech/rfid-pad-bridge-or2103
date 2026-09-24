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
    ['action' => 'clear', 'palabras' => '0']] as $request) {
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
check(RfidBridge\parseResult('status', "OK\nPORT=/dev/ttyUSB0\nBAUDRATE=115200\nTIMEOUT_MS=1500", '', 0)['ok'], 'Estado sin acceso al pad');
check(!RfidBridge\parseResult('version', 'ERROR=VERSION_NOT_SUPPORTED', '', 1)['ok'], 'Version no soportada explicita');

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
