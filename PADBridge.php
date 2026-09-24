<?php
/**
 * Bridge HTTP -> RFID OR2103. Contrato compatible con Marijoa.
 * Autor: Ing. Doglas A. Dembogurski Feix
 */
require_once __DIR__ . '/lib/Bridge.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Headers: Origin, X-Requested-With, Content-Type, Accept');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Content-Type: application/json; charset=utf-8');

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// Conservar HTTP 200 y resultado como texto: los clientes jQuery analizan ERROR= en success.
$result = RfidBridge\handleRequest($_REQUEST, __DIR__, strtoupper(substr(PHP_OS, 0, 3)) === 'WIN');
$flags = JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE;
if (defined('JSON_INVALID_UTF8_SUBSTITUTE')) $flags |= JSON_INVALID_UTF8_SUBSTITUTE;
echo json_encode($result, $flags);
