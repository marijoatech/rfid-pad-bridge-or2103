// Ejecuta las funciones reales del consumidor sin copiar su codigo ni realizar AJAX real.
// Uso: node tests/test_marijoa.js /ruta/marijoa/compras/Fraccionar.js
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');

if (!process.argv[2]) throw new Error('Indica la ruta a compras/Fraccionar.js');
const source = fs.readFileSync(process.argv[2], 'utf8');
const fixtures = JSON.parse(execFileSync('php', ['-n', path.join(__dirname, 'test_api.php'), '--fixtures'], {encoding: 'utf8'}));

function extract(name) {
    const pattern = new RegExp('^(?:async )?function ' + name + '\\s*\\(', 'm');
    const start = source.search(pattern);
    assert(start >= 0, 'Falta ' + name);
    const tail = source.slice(start);
    const next = tail.slice(1).search(/^(?:async )?function \w+\s*\(/m);
    return next < 0 ? tail : tail.slice(0, next + 1);
}

function client(fixture) {
    const html = {};
    const requests = [];
    const timers = [];
    const $ = selector => ({
        length: 0,
        removeClass() { return this; }, addClass() { return this; },
        html(value) { html[selector] = value; return this; }
    });
    $.ajax = request => {
        requests.push(request);
        if (request.beforeSend) request.beforeSend();
        if (request.success) request.success(fixture);
        return Promise.resolve(fixture);
    };
    const sandbox = { $, console: {log() {}, error() {}}, rfid_enabled: true, intentos_rfid: 0,
        max_intentos: 10, rfid_detected: false, last_rfid_written: '',
        setTimeout: (...args) => timers.push(args), errorMsg() {} };
    vm.createContext(sandbox);
    for (const name of ['escanearTAGsRFID', 'checkTAGRFID', 'grabarRFID']) vm.runInContext(extract(name), sandbox);
    return {sandbox, html, requests, timers};
}

(async () => {
    const write = client(fixtures.write);
    const result = await write.sandbox.grabarRFID('1000027');
    assert.equal(write.requests[0].url, 'http://localhost/rfid-bridge/PADBridge.php');
    assert.equal(write.requests[0].type, 'POST');
    assert.equal(write.requests[0].data.action, 'write-epc');
    assert.equal(write.requests[0].data.epc, '1000027');
    assert.equal(result.ok, true);
    assert.equal(result.status, 'success');
    assert.equal(result.written, 1000027);
    assert.equal(write.sandbox.last_rfid_written, 1000027);

    for (const [name, action] of [['escanearTAGsRFID', 'inventory'], ['checkTAGRFID', 'read-epc']]) {
        const reading = client(action === 'inventory' ? fixtures.inventory : fixtures.read);
        reading.sandbox[name]();
        assert.equal(reading.requests[0].data.action, action);
        assert.equal(reading.sandbox.rfid_detected, true);
        assert.match(reading.html['.panel-info'], /1000027/);
        const factory = client(fixtures.factory);
        factory.sandbox[name]();
        assert.match(factory.html['.panel-info'], /E28436110000100004210970/);
        const cleared = client(fixtures['zeros_' + action]);
        cleared.sandbox[name]();
        assert.equal(cleared.sandbox.rfid_detected, true);
        assert.match(cleared.html['.panel-info'], /<div>0<\/div>/);
        assert.equal(cleared.timers.length, 0, 'Una etiqueta vacia no inicia reintentos de NO_TAG');
        const empty = client(fixtures.no_tag);
        empty.sandbox[name]();
        assert.equal(empty.sandbox.rfid_detected, false);
        assert.equal(empty.timers.length, 1);
        const failed = client(fixtures.error);
        failed.sandbox[name]();
        assert.match(failed.html['.panel-info'], /ERROR PAD RFID/);
    }
    const failedWrite = await client(fixtures.error).sandbox.grabarRFID('1000027');
    assert.equal(failedWrite.ok, false);
    assert.equal(failedWrite.status, 'write_failed');
    console.log('OK: grabarRFID, escanearTAGsRFID y checkTAGRFID reales, sin modificar Marijoa ni acceder a hardware/red');
})().catch(error => { console.error(error); process.exitCode = 1; });
