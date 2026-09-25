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

function extract(name, required = true) {
    const pattern = new RegExp('^(?:async )?function ' + name + '\\s*\\(', 'm');
    const start = source.search(pattern);
    if (start < 0 && !required) return null;
    assert(start >= 0, 'Falta ' + name);
    const tail = source.slice(start);
    const next = tail.slice(1).search(/^(?:async )?function \w+\s*\(/m);
    return next < 0 ? tail : tail.slice(0, next + 1);
}

function client(fixture, configuredIp = '') {
    const html = {};
    const requests = [];
    const timers = [];
    const elements = new Map();
    const values = {'#rfid_pad_ip': configuredIp};
    function element(selector) {
        return {
            0: {}, length: selector.startsWith('.fraccion_') ? 0 : 1,
            content: '', properties: {},
            removeClass() { return this; }, addClass() { return this; },
            html(value) {
                if (value === undefined) return this.content;
                this.content = String(value); html[selector] = this.content; return this;
            },
            text(value) { return this.html(value); },
            empty() { return this.html(''); },
            append(...children) {
                return this.html(this.content + children.map(child => typeof child === 'string' ? child : child.content).join(''));
            },
            val(value) {
                if (value === undefined) return values[selector] || '';
                values[selector] = value; return this;
            },
            attr(name, value) { this.properties[name] = value; return this; },
            prop(name, value) { this.properties[name] = value; return this; },
        };
    }
    const $ = selector => {
        // Las creaciones $("<div>") deben producir nodos distintos.
        if (selector.startsWith('<')) return element(selector);
        if (!elements.has(selector)) elements.set(selector, element(selector));
        return elements.get(selector);
    };
    $.ajax = request => {
        requests.push(request);
        if (request.beforeSend) request.beforeSend();
        if (request.success) request.success(fixture);
        return Promise.resolve(fixture);
    };
    const sandbox = { $, console: {log() {}, error() {}}, rfid_enabled: true, intentos_rfid: 0,
        max_intentos: 10, rfid_detected: false, last_rfid_written: '', rfid_pad_consulta: 0,
        setTimeout: (...args) => timers.push(args), errorMsg() {} };
    vm.createContext(sandbox);
    // Versiones recientes de Marijoa permiten elegir IP y consultar status.
    // Cargar los ayudantes reales conserva la prueba de construccion de URL.
    for (const name of ['obtenerIPPADRFID', 'obtenerURLPADRFID', 'mostrarEstadoPADRFID', 'chequearPADRFID']) {
        const helper = extract(name, false);
        if (helper) vm.runInContext(helper, sandbox);
    }
    for (const name of ['escanearTAGsRFID', 'checkTAGRFID', 'grabarRFID']) vm.runInContext(extract(name), sandbox);
    return {sandbox, html, requests, timers};
}

(async () => {
    const write = client(fixtures.write);
    const result = await write.sandbox.grabarRFID('1000027');
    assert.equal(result.status, 'success', 'La escritura real del consumidor debe completar sin errores de dependencias');
    assert.equal(write.requests.length, 1, 'grabarRFID envia una sola peticion');
    assert.equal(write.requests[0].url, 'http://localhost/rfid-bridge/PADBridge.php');
    assert.equal(write.requests[0].type, 'POST');
    assert.equal(write.requests[0].data.action, 'write-epc');
    assert.equal(write.requests[0].data.epc, '1000027');
    assert.equal(result.ok, true);
    assert.equal(result.written, 1000027);
    assert.equal(write.sandbox.last_rfid_written, 1000027);
    if (typeof write.sandbox.obtenerURLPADRFID === 'function') {
        const remote = client(fixtures.write, ' 192.168.2.202 ');
        const remoteResult = await remote.sandbox.grabarRFID('1000027');
        assert.equal(remoteResult.ok, true);
        assert.equal(remote.requests[0].url, 'http://192.168.2.202/rfid-bridge/PADBridge.php');
        assert.equal(remote.requests[0].data.epc, '1000027');
    }

    for (const [name, action] of [['escanearTAGsRFID', 'inventory'], ['checkTAGRFID', 'read-epc']]) {
        const reading = client(action === 'inventory' ? fixtures.inventory : fixtures.read);
        reading.sandbox[name]();
        assert.equal(reading.requests[0].url, 'http://localhost/rfid-bridge/PADBridge.php');
        assert.equal(reading.requests[0].type, 'POST');
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
    if (typeof write.sandbox.chequearPADRFID === 'function') {
        assert.ok(fixtures.status && fixtures.status_offline, 'test_api.php debe proporcionar fixtures status y status_offline');
        for (const [fixture, expected] of [[fixtures.status, true], [fixtures.status_offline, false]]) {
            const statusClient = client(fixture);
            const status = await statusClient.sandbox.chequearPADRFID();
            assert.equal(statusClient.requests[0].url, 'http://localhost/rfid-bridge/PADBridge.php');
            assert.equal(statusClient.requests[0].type, 'GET');
            assert.equal(statusClient.requests[0].data.action, 'status');
            assert.equal(status.ok, expected);
            assert.equal(status.status, expected ? 'connected' : 'disconnected');
            assert.match(statusClient.html['#rfid_pad_estado,#rfid_pad_panel_estado'], expected ? /PAD RFID conectado/ : /PAD RFID no conectado/);
        }
    }
    console.log('OK: funciones RFID reales de Marijoa y sus ayudantes disponibles, sin modificar Marijoa ni acceder a hardware/red');
})().catch(error => { console.error(error); process.exitCode = 1; });
