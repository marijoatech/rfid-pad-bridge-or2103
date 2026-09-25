(() => {
    'use strict';

    const forms = Array.from(document.querySelectorAll('[data-rfid-operation]'));
    const buttons = forms.map(form => form.querySelector('button[type="submit"]'));
    let busy = false;

    for (const form of forms) {
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (busy || !form.reportValidity()) return;

            // Capturar los valores antes de deshabilitar controles; conservar EPC como texto.
            const params = new URLSearchParams(new FormData(form));
            const action = params.get('action');
            const result = document.getElementById(form.dataset.result);
            const status = result.querySelector('.result-status');
            const output = result.querySelector('pre');
            const button = form.querySelector('button[type="submit"]');
            const caption = button.textContent;
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 45000);

            busy = true;
            buttons.forEach(item => { item.disabled = true; });
            form.setAttribute('aria-busy', 'true');
            button.textContent = 'Procesando…';
            result.hidden = false;
            result.dataset.state = 'pending';
            status.textContent = 'Esperando la respuesta del pad…';
            output.textContent = '';

            try {
                // El campo oculto name="action" sombrea form.action: leer el atributo HTML.
                const response = await fetch(form.getAttribute('action'), {
                    method: 'POST',
                    headers: {Accept: 'application/json'},
                    body: params,
                    signal: controller.signal,
                });
                if (!response.ok) throw new Error('El servidor devolvió HTTP ' + response.status + '.');
                const data = await response.json();
                if (!data || typeof data.ok !== 'boolean' || typeof data.resultado !== 'string') {
                    throw new Error('El servidor no devolvió el formato JSON esperado.');
                }

                result.dataset.state = data.ok ? 'success' : 'error';
                let successMessage = 'Operación completada.';
                if (data.resultado === 'NO_TAG') successMessage = 'No se detectaron etiquetas.';
                if (action === 'status') successMessage = 'El pad está conectado y responde.';
                const powerMatch = data.resultado.match(/^POWER=(\d+)$/m);
                if ((action === 'get-power' || action === 'set-power') && powerMatch) {
                    successMessage = (action === 'set-power' ? 'Potencia aplicada: ' : 'Potencia actual: ') + powerMatch[1] + '.';
                }
                status.textContent = data.ok ? successMessage : 'La operación devolvió un error.';
                const connectionError = data.resultado.match(/^ERROR=(READER_NOT_RESPONDING|CONNECT_FAILED)(?::.*)?$/m);
                if (!data.ok && connectionError) {
                    status.textContent = (connectionError[1] === 'CONNECT_FAILED'
                        ? 'Revisa la conexión USB y el puerto configurado. '
                        : 'El lector no responde. ')
                        + 'Desenchufa el USB del lector, espera 10 segundos y vuelve a enchufarlo en modo USB.';
                    if (action === 'set-power') {
                        status.textContent += ' Después de reconectarlo, consulta la potencia antes de repetir: el pad podría haber aplicado el cambio.';
                    } else if (action === 'write-epc' || action === 'clear') {
                        status.textContent += ' Cuando vuelva a responder, lee el EPC antes de repetir: el pad podría haber realizado la operación.';
                    }
                }
                // La respuesta del dispositivo es texto; nunca interpretarla como HTML.
                output.textContent = JSON.stringify(data, null, 2);
            } catch (error) {
                result.dataset.state = 'error';
                status.textContent = 'No se pudo confirmar la respuesta.';
                const detail = error.name === 'AbortError'
                    ? 'Se agotó el tiempo de espera de la respuesta.'
                    : 'Comprueba la conexión y que el bridge esté disponible. ' + error.message;
                output.textContent = detail + ((action === 'write-epc' || action === 'clear')
                    ? ' Lee el EPC antes de repetir la operación: el pad podría haberla realizado.'
                    : (action === 'set-power' ? ' Consulta la potencia antes de repetir: el pad podría haber aplicado el cambio.' : ''));
            } finally {
                clearTimeout(timeout);
                busy = false;
                buttons.forEach(item => { item.disabled = false; });
                button.textContent = caption;
                form.setAttribute('aria-busy', 'false');
            }
        });
        // Sin JavaScript, los botones permanecen deshabilitados: no se abandona esta pagina.
        form.querySelector('button[type="submit"]').disabled = false;
    }
})();
