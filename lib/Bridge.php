<?php
namespace RfidBridge;

function failure($action, string $code, string $message = '', string $stderr = ''): array
{
    $result = ['ok' => false, 'accion' => $action, 'resultado' => 'ERROR=' . $code,
        'exit_code' => 1, 'stderr' => $stderr];
    if ($message !== '') $result['error'] = $message;
    return $result;
}

function normalizeEpc($value): string
{
    if (!is_string($value) && !is_int($value)) throw new \InvalidArgumentException('EPC_INVALID');
    $epc = strtoupper(trim((string) $value));
    if ($epc === '') throw new \InvalidArgumentException('EPC_EMPTY');
    if (!preg_match('/\A[0-9A-F]+\z/', $epc)) throw new \InvalidArgumentException('EPC_INVALID_HEX');
    // Marijoa envia el numero de lote, no un entero convertido a hexadecimal.
    if (ctype_digit($epc) && strlen($epc) < 24) $epc = str_pad($epc, 24, '0', STR_PAD_LEFT);
    if (strlen($epc) > 124) throw new \InvalidArgumentException('EPC_TOO_LONG');
    if (strlen($epc) % 4 !== 0) throw new \InvalidArgumentException('EPC_LENGTH_MUST_BE_WORD_ALIGNED');
    return $epc;
}

function normalizeWords($value): string
{
    if ((!is_string($value) && !is_int($value)) ||
        !preg_match('/\A[0-9]{1,2}\z/', (string) $value) || (int) $value < 1 || (int) $value > 31) {
        throw new \InvalidArgumentException('PALABRAS_INVALIDAS');
    }
    return (string) (int) $value;
}

function normalizePower($value): string
{
    if ((!is_string($value) && !is_int($value)) ||
        !preg_match('/\A[0-9]{1,2}\z/', (string) $value) || (int) $value < 5 || (int) $value > 30) {
        throw new \InvalidArgumentException('POWER_INVALID');
    }
    return (string) (int) $value;
}

function parseResult(string $action, string $stdout, string $stderr, int $exitCode, string $expectedEpc = ''): array
{
    $lines = array_values(array_filter(array_map('trim', preg_split('/\r\n|\n|\r/', $stdout)), 'strlen'));
    $errors = array_values(array_filter($lines, function ($line) { return strpos($line, 'ERROR=') === 0; }));
    $detected = array_values(array_unique(array_filter($lines, function ($line) {
        return preg_match('/\ADETECTED=[0-9A-Fa-f]+\z/', $line);
    })));

    if ($errors || $exitCode !== 0) {
        // El cliente antiguo busca WRITTEN/DETECTED sin consultar ok: nunca mezclar exito y error.
        $clean = $errors ?: ['ERROR=BRIDGE_FAILED'];
        if ($exitCode === 0) $exitCode = 1;
    } elseif ($action === 'write-epc' || $action === 'clear') {
        $written = 'WRITTEN=' . $expectedEpc;
        if (in_array($written, $lines, true)) {
            $clean = [$written, 'OK'];
        } else {
            $clean = in_array('NO_TAG', $lines, true) ? ['NO_TAG'] : ['ERROR=WRITE_NOT_CONFIRMED'];
            $exitCode = 1;
        }
    } elseif ($action === 'read-epc' || $action === 'inventory') {
        if ($detected) {
            $clean = $action === 'read-epc' ? [$detected[0]] : $detected;
        } elseif (in_array('NO_TAG', $lines, true)) {
            $clean = ['NO_TAG'];
        } else {
            $clean = ['ERROR=EMPTY_RESPONSE'];
            $exitCode = 1;
        }
    } elseif (in_array($action, ['status', 'get-power', 'set-power'], true)) {
        $powerLines = array_values(array_filter($lines, function ($line) {
            return strpos($line, 'POWER=') === 0;
        }));
        // Un ejecutable antiguo que solo imprime configuracion no confirma conexion.
        if (count($powerLines) !== 1 || !preg_match('/\APOWER=(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\z/', $powerLines[0]) || !in_array('OK', $lines, true) ||
            ($action === 'status' && !in_array('CONNECTED=1', $lines, true))) {
            $clean = ['ERROR=READER_RESPONSE_INVALID'];
            $exitCode = 1;
        } elseif ($action === 'set-power' && $powerLines[0] !== 'POWER=' . $expectedEpc) {
            $clean = ['ERROR=POWER_VERIFY_FAILED'];
            $exitCode = 1;
        } else {
            $clean = $action === 'status' ? array_values(array_filter($lines, function ($line) {
                return $line === 'OK' || $line === 'CONNECTED=1' ||
                    preg_match('/\A(?:COM|PORT|BAUDRATE|TIMEOUT_MS|POWER)=/', $line);
            })) : [$powerLines[0], 'OK'];
        }
    } else {
        $clean = array_values(array_filter($lines, function ($line) {
            return $line === 'OK' || preg_match('/\A(?:VERSION|COM|PORT|BAUDRATE|TIMEOUT_MS|POWER)=/', $line);
        }));
        if (!$clean) {
            $clean = ['ERROR=EMPTY_RESPONSE'];
            $exitCode = 1;
        }
    }
    return ['ok' => $exitCode === 0, 'accion' => $action, 'resultado' => implode("\n", $clean),
        'exit_code' => $exitCode, 'stderr' => trim($stderr)];
}

function runPowerChange(string $baseDir, string $power, callable $operation): array
{
    // Preparar el archivo antes de tocar el dispositivo. Guardar solo tras ACK y lectura verificados.
    $directory = $baseDir . '/runtime';
    $destination = $directory . '/antenna-power.json';
    if (file_exists($destination) && !is_file($destination)) {
        return ['ERROR=POWER_STORAGE_UNAVAILABLE', 'runtime/antenna-power.json debe ser un archivo.', 1];
    }
    if ((!is_dir($directory) && !@mkdir($directory, 0700, true)) || !is_writable($directory)) {
        return ['ERROR=POWER_STORAGE_UNAVAILABLE', 'Sin permiso para runtime; en Linux ejecuta sudo bash install.sh.', 1];
    }
    $temporary = @tempnam($directory, '.power-');
    if ($temporary === false || realpath(dirname($temporary)) !== realpath($directory)) {
        if ($temporary !== false) @unlink($temporary);
        return ['ERROR=POWER_STORAGE_UNAVAILABLE', '', 1];
    }
    try {
        $contents = json_encode(['power' => (int) $power]) . "\n";
        if (@file_put_contents($temporary, $contents) !== strlen($contents) ||
            !@chmod($temporary, 0600)) {
            return ['ERROR=POWER_STORAGE_UNAVAILABLE', '', 1];
        }
        $execution = $operation();
        $result = parseResult('set-power', $execution[0], $execution[1], $execution[2], $power);
        if (!$result['ok']) return $execution;
        if (!@rename($temporary, $destination)) {
            return ['ERROR=POWER_SAVE_FAILED',
                'La potencia del lector cambio, pero no pudo guardarse. Consulta get-power y revisa permisos antes de repetir.', 1];
        }
        return $execution;
    } finally {
        if (is_file($temporary)) @unlink($temporary);
    }
}

function commandLine(array $arguments, bool $windows): string
{
    return ($windows ? '' : 'exec ') . implode(' ', array_map('escapeshellarg', $arguments));
}

function runProcess(string $command, string $baseDir, float $timeout = 30.0): array
{
    if (!function_exists('proc_open')) return ['', 'proc_open no esta disponible', 1];
    $outFile = tempnam(sys_get_temp_dir(), 'rfid-out-');
    $errFile = tempnam(sys_get_temp_dir(), 'rfid-err-');
    if ($outFile === false || $errFile === false) {
        if ($outFile !== false) @unlink($outFile);
        if ($errFile !== false) @unlink($errFile);
        return ['ERROR=TEMP_FILE_FAILED', '', 1];
    }
    $process = null;
    try {
        // Archivos separados evitan bloquear stdout esperando que se vacie stderr, tambien en Windows.
        $process = @proc_open($command, [0 => ['file', DIRECTORY_SEPARATOR === '\\' ? 'NUL' : '/dev/null', 'r'],
            1 => ['file', $outFile, 'w'], 2 => ['file', $errFile, 'w']], $pipes, $baseDir, null, ['bypass_shell' => true]);
        if (!is_resource($process)) return ['ERROR=BRIDGE_START_FAILED', '', 1];
        $deadline = microtime(true) + $timeout;
        $problem = '';
        $exitCode = -1;
        while (true) {
            $status = proc_get_status($process);
            clearstatcache(true, $outFile);
            clearstatcache(true, $errFile);
            if (filesize($outFile) > 1048576 || filesize($errFile) > 1048576) {
                $problem = 'OUTPUT_LIMIT';
                break;
            }
            if (!$status['running']) {
                $exitCode = $status['exitcode'];
                break;
            }
            if (microtime(true) >= $deadline) {
                $problem = 'BRIDGE_TIMEOUT';
                break;
            }
            usleep(20000);
        }
        if ($problem !== '') proc_terminate($process);
        $closedCode = proc_close($process);
        $process = null;
        if ($exitCode < 0) $exitCode = $closedCode;
        $stdout = (string) file_get_contents($outFile, false, null, 0, 1048576);
        $stderr = (string) file_get_contents($errFile, false, null, 0, 1048576);
        if ($problem !== '') return ['ERROR=' . $problem, $stderr, 1];
        return [$stdout, $stderr, $exitCode];
    } finally {
        if (is_resource($process)) { proc_terminate($process); proc_close($process); }
        @unlink($outFile);
        @unlink($errFile);
    }
}

function withReaderLock(string $baseDir, callable $operation, float $wait = 5.0): array
{
    $path = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'rfid-bridge-' . hash('sha256', $baseDir) . '.lock';
    $lock = @fopen($path, 'c');
    if ($lock === false) return ['ERROR=LOCK_UNAVAILABLE', '', 1];
    $deadline = microtime(true) + $wait;
    try {
        while (!flock($lock, LOCK_EX | LOCK_NB)) {
            if (microtime(true) >= $deadline) return ['ERROR=BRIDGE_BUSY', '', 1];
            usleep(50000);
        }
        return $operation();
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
        // No borrar: otro proceso puede estar esperando sobre el mismo archivo.
    }
}

function handleRequest(array $request, string $baseDir, bool $windows, callable $runner = null): array
{
    $action = $request['action'] ?? null;
    if ($action === null || $action === '') return failure(null, 'ACTION_REQUIRED', "Parametro 'action' requerido");
    if (!is_string($action)) return failure(null, 'ACTION_INVALID', 'Parametro action invalido');
    if (!in_array($action, ['status', 'version', 'inventory', 'read-epc', 'write-epc', 'clear', 'get-power', 'set-power'], true)) {
        return failure($action, 'UNKNOWN_ACTION', 'Accion no permitida: ' . $action);
    }
    $params = [];
    $expected = '';
    try {
        if ($action === 'write-epc') {
            if (!isset($request['epc'])) return failure($action, 'EPC_REQUIRED', "Falta parametro 'epc'");
            $expected = normalizeEpc($request['epc']);
            $params[] = $expected;
        } elseif ($action === 'clear') {
            $words = normalizeWords($request['palabras'] ?? 6);
            $params[] = $words;
            $expected = str_repeat('0', (int) $words * 4);
        } elseif ($action === 'set-power') {
            if (!isset($request['power'])) return failure($action, 'POWER_REQUIRED', "Falta parametro 'power'");
            $expected = normalizePower($request['power']);
            $params[] = $expected;
        }
    } catch (\InvalidArgumentException $error) {
        return failure($action, $error->getMessage());
    }
    $bridge = $baseDir . ($windows ? '/windows/OR2103Bridge.exe' : '/linux/OR2103Bridge.py');
    if (!is_file($bridge)) return failure($action, 'BRIDGE_NOT_FOUND', 'Bridge no encontrado: ' . $bridge);
    $arguments = array_merge($windows ? [$bridge, $action] : ['python3', $bridge, $action], $params);
    try {
        // El bloqueo cubre la respuesta del pad y el guardado: la siguiente lectura ve el nuevo valor.
        $execution = withReaderLock($baseDir, function () use ($arguments, $windows, $baseDir, $action, $expected, $runner) {
            $operation = function () use ($runner, $arguments, $windows, $baseDir) {
                // Inyeccion solo desde PHP para pruebas; no se controla por parametros HTTP.
                return $runner !== null ? $runner($arguments) : runProcess(commandLine($arguments, $windows), $baseDir);
            };
            return $action === 'set-power' ? runPowerChange($baseDir, $expected, $operation) : $operation();
        });
        return parseResult($action, $execution[0], $execution[1], $execution[2], $expected);
    } catch (\Throwable $error) {
        return failure($action, 'BRIDGE_EXCEPTION', '', $error->getMessage());
    }
}
