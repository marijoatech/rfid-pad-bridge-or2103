<?php
/**
 * PADBridge.php
 * Bridge PHP -> RFID OR2103
 *
 * Windows: windows/OR2103Bridge.exe
 * Linux:   python3 linux/OR2103Bridge.py
 *
 * Autor: Ing. Doglas A. Dembogurski Feix
 */

header('Access-Control-Allow-Origin: *');
header("Access-Control-Allow-Headers: Origin, X-Requested-With, Content-Type, Accept");
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE');
header("Content-Type: application/json; charset=utf-8");

$accion = $_REQUEST['action'] ?? null;

if (!function_exists('str_starts_with')) {
    function str_starts_with($haystack, $needle) {
        return strpos($haystack, $needle) === 0;
    }
}

if (!$accion) {
    error("Parametro 'action' requerido");
}

$acciones = [
    "status"    => [],
    "version"   => [],
    "inventory" => [],
    "read-epc"  => [],
    "write-epc" => ["epc"],
    "clear"     => []
];

if (!isset($acciones[$accion])) {
    error("Accion no permitida: " . $accion);
}
 

$baseDir   = realpath(__DIR__);
$isWindows = strtoupper(substr(PHP_OS, 0, 3)) === 'WIN';

$params = [];
foreach ($acciones[$accion] as $p) {
    if (!isset($_REQUEST[$p])) {
        error("Falta parametro '" . $p . "'");
    }
    $params[] = $_REQUEST[$p];
}

if ($isWindows) {
    $bridge = $baseDir . DIRECTORY_SEPARATOR . "windows" . DIRECTORY_SEPARATOR . "OR2103Bridge.exe";

    if (!file_exists($bridge)) {
        error("Bridge Windows no encontrado: " . $bridge);
    }

    $cmd = escapeshellarg($bridge) . " " . escapeshellarg($accion);
} else {
    $bridge = $baseDir . DIRECTORY_SEPARATOR . "linux" . DIRECTORY_SEPARATOR . "OR2103Bridge.py";

    if (!file_exists($bridge)) {
        error("Bridge Linux no encontrado: " . $bridge);
    }

    $cmd = "python3 " . escapeshellarg($bridge) . " " . escapeshellarg($accion);
}

foreach ($params as $param) {
    $cmd .= " " . escapeshellarg($param);
}

$descriptorspec = [
    1 => ["pipe", "w"],
    2 => ["pipe", "w"],
];

$process = proc_open($cmd, $descriptorspec, $pipes, $baseDir);

if (!is_resource($process)) {
    error("No se pudo ejecutar bridge");
}

$rawStdout = stream_get_contents($pipes[1]);
$rawStderr = stream_get_contents($pipes[2]);

fclose($pipes[1]);
fclose($pipes[2]);

$exitCode = proc_close($process);

$lines = preg_split("/\r\n|\n|\r/", $rawStdout);

$clean = [];
foreach ($lines as $line) {
    $line = trim($line);

    if ($line === '') continue;

    if (
        str_starts_with($line, 'DETECTED=') ||
        str_starts_with($line, 'WRITTEN=')  ||
        str_starts_with($line, 'VERSION=')  ||
        str_starts_with($line, 'COM=')      ||
        str_starts_with($line, 'PORT=')     ||
        str_starts_with($line, 'POWER=')    ||
        str_starts_with($line, 'ERROR=')    ||
        $line === 'OK' ||
        $line === 'NO_TAG'
    ) {
        $clean[] = $line;
    }
}

$stdout = implode("\n", $clean);

echo json_encode([
    "ok"        => ($exitCode === 0),
    "accion"    => $accion,
    "resultado" => $stdout,
    "exit_code" => $exitCode,
    "stderr"    => trim($rawStderr)
], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);

function error(string $msg): void
{
    echo json_encode([
        "ok"    => false,
        "error" => $msg
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    exit;
}
