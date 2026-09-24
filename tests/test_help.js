'use strict';

// Prueba los controles de la ayuda con DOM y fetch simulados. No accede a red ni hardware.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scriptArg = process.argv.indexOf('--script');
if (scriptArg !== -1 && !process.argv[scriptArg + 1]) throw new Error('Falta la ruta de --script');
const scriptPath = scriptArg === -1
    ? path.resolve(__dirname, '../assets/help.js') : path.resolve(process.argv[scriptArg + 1]);
const script = fs.readFileSync(scriptPath, 'utf8');

function textNode(text = '') {
    const node = {textContent: text};
    Object.defineProperty(node, 'innerHTML', {
        set() { throw new Error('Las respuestas deben mostrarse como texto, nunca HTML'); },
    });
    return node;
}

function setup(fetchImplementation = async () => reply({ok: true, resultado: 'OK'})) {
    const calls = [];
    const results = new Map();
    const timers = new Map();
    let nextTimer = 0;
    const definitions = [
        ['write-epc', [['epc', '00000130527']]],
        ['clear', [['palabras', '6']]],
        ['read-epc', []],
        ['inventory', []],
    ];
    const forms = definitions.map(([action, fields]) => {
        const button = Object.assign(textNode('Ejecutar ' + action), {disabled: true});
        const status = textNode();
        const output = textNode();
        const result = {
            hidden: true, dataset: {}, status, output,
            querySelector(selector) {
                if (selector === '.result-status') return status;
                if (selector === 'pre') return output;
                throw new Error('Selector de resultado inesperado: ' + selector);
            },
        };
        const form = {
            dataset: {result: 'resultado-' + action},
            fields: [['action', action], ...fields],
            button, result, listeners: {}, attributes: {}, valid: true,
            reportValidity() { return this.valid; },
            addEventListener(event, handler) { this.listeners[event] = handler; },
            querySelector(selector) {
                assert.equal(selector, 'button[type="submit"]');
                return button;
            },
            getAttribute(name) {
                assert.equal(name, 'action');
                return 'PADBridge.php';
            },
            setAttribute(name, value) { this.attributes[name] = value; },
        };
        // Un input llamado action puede sombrear la propiedad nativa form.action.
        Object.defineProperty(form, 'action', {
            get() { throw new Error('Usar el atributo action, no form.action'); },
        });
        results.set(form.dataset.result, result);
        return form;
    });
    const context = {
        document: {
            querySelectorAll(selector) {
                assert.equal(selector, '[data-rfid-operation]');
                return forms;
            },
            getElementById(id) { return results.get(id); },
        },
        FormData: class {
            constructor(form) { this.fields = form.fields.map(pair => [...pair]); }
            [Symbol.iterator]() { return this.fields[Symbol.iterator](); }
        },
        URLSearchParams,
        AbortController,
        setTimeout(callback, delay) {
            const id = ++nextTimer;
            timers.set(id, {callback, delay});
            return id;
        },
        clearTimeout(id) { timers.delete(id); },
        fetch(url, options) {
            calls.push({url, options});
            return fetchImplementation(url, options);
        },
    };
    vm.runInNewContext(script, context, {filename: scriptPath});
    assert.equal(calls.length, 0, 'Cargar la ayuda no realiza operaciones');
    assert.ok(forms.every(form => !form.button.disabled), 'JavaScript habilita los botones');

    return {
        forms, calls, timers,
        form(action) { return forms.find(form => form.fields[0][1] === action); },
        submit(form) {
            let prevented = false;
            const pending = form.listeners.submit({preventDefault() { prevented = true; }});
            assert.ok(prevented, 'El formulario no navega ni abre otra pagina');
            return pending;
        },
        assertReleased(form) {
            assert.ok(forms.every(item => !item.button.disabled), 'Todos los botones se liberan');
            assert.equal(form.attributes['aria-busy'], 'false');
            assert.equal(form.button.textContent, 'Ejecutar ' + form.fields[0][1]);
            assert.equal(timers.size, 0, 'Se cancela el temporizador tras la respuesta');
        },
    };
}

function reply(data) {
    return {ok: true, status: 200, async json() { return data; }};
}

const tests = [];
function test(name, execute) { tests.push({name, execute}); }

test('POST conserva el EPC como texto y muestra el JSON en su propia tarjeta', async () => {
    const data = {ok: true, accion: 'write-epc', resultado: 'WRITTEN=000000000000000000130527\nOK', exit_code: 0, stderr: ''};
    const app = setup(async () => reply(data));
    const form = app.form('write-epc');
    await app.submit(form);
    assert.equal(app.calls.length, 1);
    const request = app.calls[0];
    assert.equal(request.url, 'PADBridge.php');
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.headers.Accept, 'application/json');
    assert.deepEqual(Array.from(request.options.body), [['action', 'write-epc'], ['epc', '00000130527']]);
    assert.equal(form.result.hidden, false);
    assert.equal(form.result.dataset.state, 'success');
    assert.deepEqual(JSON.parse(form.result.output.textContent), data);
    assert.ok(app.forms.filter(item => item !== form).every(item => item.result.hidden));
    app.assertReleased(form);
});

test('Vaciar EPC transmite las 6 palabras fijas del formulario', async () => {
    const app = setup();
    const form = app.form('clear');
    await app.submit(form);
    assert.deepEqual(Array.from(app.calls[0].options.body), [['action', 'clear'], ['palabras', '6']]);
    app.assertReleased(form);
});

test('NO_TAG es una lectura valida y conserva el JSON', async () => {
    const data = {ok: true, resultado: 'NO_TAG'};
    const app = setup(async () => reply(data));
    const form = app.form('read-epc');
    await app.submit(form);
    assert.equal(form.result.dataset.state, 'success');
    assert.match(form.result.status.textContent, /No se detectaron etiquetas/);
    assert.deepEqual(JSON.parse(form.result.output.textContent), data);
    app.assertReleased(form);
});

test('doble envio y otros formularios quedan bloqueados mientras hay una operacion', async () => {
    let finish;
    const app = setup(() => new Promise(resolve => { finish = resolve; }));
    const form = app.form('write-epc');
    const pending = app.submit(form);
    assert.ok(app.forms.every(item => item.button.disabled));
    assert.equal(form.attributes['aria-busy'], 'true');
    assert.equal(form.result.dataset.state, 'pending');
    await app.submit(form);
    await app.submit(app.form('clear'));
    assert.equal(app.calls.length, 1, 'Ni Enter ni otra tarjeta deben duplicar la operacion');
    form.fields[1][1] = '9999';
    assert.equal(app.calls[0].options.body.get('epc'), '00000130527', 'Se conserva una copia del valor enviado');
    finish(reply({ok: true, resultado: 'WRITTEN=00000130527\nOK'}));
    await pending;
    app.assertReleased(form);
    assert.ok(app.form('clear').result.hidden, 'La otra tarjeta permanece intacta');
});

test('entrada invalida no llama fetch ni bloquea otras tarjetas', async () => {
    const app = setup();
    const form = app.form('write-epc');
    form.valid = false;
    await app.submit(form);
    assert.equal(app.calls.length, 0);
    assert.equal(app.timers.size, 0);
    assert.ok(app.forms.every(item => !item.button.disabled));
    assert.ok(form.result.hidden);
    await app.submit(app.form('inventory'));
    assert.equal(app.calls.length, 1);
});

test('fallos de red o JSON liberan botones y no repiten escrituras automaticamente', async () => {
    for (const action of ['write-epc', 'clear']) {
        for (const failure of ['network', 'json']) {
            const app = setup(async () => {
                if (failure === 'network') throw new Error('Sin conexion');
                return {ok: true, async json() { throw new SyntaxError('JSON incompleto'); }};
            });
            const form = app.form(action);
            await app.submit(form);
            assert.equal(app.calls.length, 1, action + ': no reintentar ante respuesta incierta');
            assert.equal(form.result.dataset.state, 'error');
            assert.match(form.result.output.textContent, /Lee el EPC antes de repetir/);
            app.assertReleased(form);
            const read = app.form('read-epc');
            await app.submit(read);
            assert.equal(app.calls.length, 2, 'El usuario puede solicitar otra operacion tras el fallo');
            app.assertReleased(read);
        }
    }
});

test('HTTP fallido o JSON de formato incorrecto se presentan como errores recuperables', async () => {
    for (const response of [
        {ok: false, status: 503, async json() { throw new Error('No se debe leer este cuerpo'); }},
        reply({ok: 'true', resultado: 'OK'}),
        reply({ok: true}),
        reply(null),
    ]) {
        const app = setup(async () => response);
        const form = app.form('inventory');
        await app.submit(form);
        assert.equal(app.calls.length, 1);
        assert.equal(form.result.dataset.state, 'error');
        assert.doesNotMatch(form.result.output.textContent, /Lee el EPC antes de repetir/);
        app.assertReleased(form);
    }
});

test('HTML en errores del servidor y de red permanece texto literal', async () => {
    const markup = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const data = {ok: false, resultado: 'ERROR=' + markup, exit_code: 1, stderr: markup};
    const app = setup(async () => reply(data));
    const form = app.form('write-epc');
    await app.submit(form);
    assert.equal(form.result.dataset.state, 'error');
    assert.deepEqual(JSON.parse(form.result.output.textContent), data);
    app.assertReleased(form);

    const networkApp = setup(async () => { throw new Error(markup); });
    const networkForm = networkApp.form('inventory');
    await networkApp.submit(networkForm);
    assert.ok(networkForm.result.output.textContent.includes(markup));
    networkApp.assertReleased(networkForm);
});

test('tiempo agotado cancela la espera y conserva la advertencia de escritura incierta', async () => {
    const app = setup((url, options) => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => {
            const error = new Error('Abortada');
            error.name = 'AbortError';
            reject(error);
        }, {once: true});
    }));
    const form = app.form('clear');
    const pending = app.submit(form);
    assert.equal(app.timers.size, 1);
    const timer = [...app.timers.values()][0];
    assert.ok(timer.delay > 0);
    timer.callback();
    await pending;
    assert.equal(app.calls.length, 1);
    assert.equal(app.calls[0].options.signal.aborted, true);
    assert.match(form.result.output.textContent, /tiempo de espera/);
    assert.match(form.result.output.textContent, /Lee el EPC antes de repetir/);
    app.assertReleased(form);
});

(async () => {
    for (const {name, execute} of tests) {
        await execute();
        console.log('OK: ' + name);
    }
    console.log('OK: ' + tests.length + ' pruebas de la ayuda, sin red ni hardware');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
