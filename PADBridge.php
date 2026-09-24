<?php
/**
 * Bridge HTTP -> RFID OR2103. Contrato compatible con Marijoa.
 * Autor: Ing. Doglas A. Dembogurski Feix
 *
 * Este archivo es el punto de entrada, no el controlador del lector:
 * - views/help.php: guia visual al abrir esta URL desde un navegador sin action.
 * - lib/Bridge.php: parametros, relleno del EPC, bloqueo, proceso y respuesta JSON.
 * - linux/OR2103Bridge.py o windows/OR2103Bridge.exe: comunicacion con el pad.
 * Con action siempre se usa la API; GET y POST de Marijoa conservan su contrato.
 */
require_once __DIR__ . '/lib/Bridge.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Headers: Origin, X-Requested-With, Content-Type, Accept');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');

$method = $_SERVER['REQUEST_METHOD'] ?? '';
if ($method === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// Solo la navegacion sin action puede mostrar HTML. curl y POST siguen recibiendo JSON.
if ($method === 'GET' && !array_key_exists('action', $_REQUEST)) {
    header('Vary: Accept');
    $acceptsHtml = false;
    foreach (explode(',', $_SERVER['HTTP_ACCEPT'] ?? '') as $acceptedType) {
        $parts = explode(';', $acceptedType);
        if (strtolower(trim($parts[0])) !== 'text/html') continue;
        $quality = 1.0;
        foreach (array_slice($parts, 1) as $parameter) {
            if (preg_match('/^\s*q\s*=\s*([0-9.]+)\s*$/i', $parameter, $match)) $quality = (float) $match[1];
        }
        if ($quality > 0) $acceptsHtml = true;
    }
    if (($_GET['format'] ?? '') !== 'json' && ($acceptsHtml || ($_GET['help'] ?? '') === '1')) {
        header('Content-Type: text/html; charset=utf-8');
        require __DIR__ . '/views/help.php';
        exit;
    }
}

// Conservar HTTP 200 y resultado como texto: los clientes jQuery analizan ERROR= en success.
header('Content-Type: application/json; charset=utf-8');
$result = RfidBridge\handleRequest($_REQUEST, __DIR__, strtoupper(substr(PHP_OS, 0, 3)) === 'WIN');
$flags = JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE;
if (defined('JSON_INVALID_UTF8_SUBSTITUTE')) $flags |= JSON_INVALID_UTF8_SUBSTITUTE;
echo json_encode($result, $flags);
