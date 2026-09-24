<?php
// Cargar la vista no opera el lector; los formularios se envian desde assets/help.js.
$windows = strtoupper(substr(PHP_OS, 0, 3)) === 'WIN';
?>
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title>OR2103 · Guía de RFID Bridge</title>
    <link rel="stylesheet" href="assets/help.css">
    <script src="assets/help.js" defer></script>
</head>
<body>
<header class="topbar">
    <a class="brand" href="PADBridge.php?help=1" aria-label="RFID Bridge, inicio">
        <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="9" width="17" height="14" rx="4"/><path d="M24 9a12 12 0 0 1 0 14M28 5a18 18 0 0 1 0 22M8 14h7M8 18h4"/></svg>
        RFID <span>Bridge</span>
    </a>
    <nav aria-label="Secciones de la ayuda"><a href="#acciones">Acciones</a><a href="#respuestas">Respuestas</a><a href="#integracion">Integración</a></nav>
</header>
<main>
    <section class="hero" aria-labelledby="titulo">
        <div>
            <div class="eyebrow">PAD OR2103 <span>GUÍA DE LA API</span></div>
            <h1>Tu lector RFID,<br> paso a paso.</h1>
            <p class="intro">Consulta las acciones disponibles, sus parámetros y lo que devuelve cada operación.</p>
            <div class="hero-actions"><a class="button" href="#acciones">Ver acciones <span aria-hidden="true">↓</span></a><span class="environment">Servidor <?= $windows ? 'Windows' : 'Linux' ?></span></div>
            <p class="quiet">Abrir esta guía no se comunica con el pad.</p>
        </div>
        <aside class="example" aria-label="Ejemplo de relleno del EPC">
            <div class="example-title"><span>EJEMPLO DE ESCRITURA</span><span class="chip">96 bits</span></div>
            <p>Envías tu número de lote</p>
            <code class="lot">130527</code>
            <div class="connector" aria-hidden="true">↓</div>
            <p>El bridge completa hasta 24 caracteres</p>
            <code class="padded"><span>000000000000000000</span>130527</code>
            <div class="example-note">Los lotes numéricos cortos reciben ceros a la izquierda. No necesitas agregarlos en Marijoa.</div>
        </aside>
    </section>

    <section id="acciones" aria-labelledby="acciones-titulo">
        <div class="section-heading"><div><span class="eyebrow">01 / OPERACIONES</span><h2 id="acciones-titulo">Elige una acción</h2></div><p>Envía <code>action</code> por GET o POST.<br> Las operaciones siempre devuelven JSON.</p></div>
        <noscript><p class="setup-note">Activa JavaScript para ejecutar las operaciones y ver sus respuestas en esta página.</p></noscript>
        <div class="cards">
            <article class="card">
                <div class="card-top"><code>read-epc</code><span class="badge">Lectura</span></div>
                <h3>Leer una etiqueta</h3>
                <p>Obtiene el primer EPC detectado. Coloca una etiqueta sobre el pad.</p>
                <div class="request"><span>GET</span><code>?action=read-epc</code></div>
                <p class="returns">Devuelve <code>DETECTED=…</code> o <code>NO_TAG</code>.</p>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="read-epc-result">
                    <input type="hidden" name="action" value="read-epc">
                    <button class="operation-button" type="submit" aria-controls="read-epc-result" disabled>Leer EPC</button>
                </form>
                <div id="read-epc-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de read-epc"></pre>
                </div>
            </article>
            <article class="card">
                <div class="card-top"><code>inventory</code><span class="badge">Lectura</span></div>
                <h3>Escanear etiquetas</h3>
                <p>Busca etiquetas y devuelve una línea por cada EPC detectado, sin duplicados.</p>
                <div class="request"><span>GET</span><code>?action=inventory</code></div>
                <p class="returns">Devuelve líneas <code>DETECTED=…</code> o <code>NO_TAG</code>.</p>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="inventory-result">
                    <input type="hidden" name="action" value="inventory">
                    <button class="operation-button" type="submit" aria-controls="inventory-result" disabled>Escanear</button>
                </form>
                <div id="inventory-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de inventory"></pre>
                </div>
            </article>
            <article class="card">
                <div class="card-top"><code>status</code><span class="badge neutral">Configuración</span></div>
                <h3>Ver la configuración</h3>
                <p>Muestra el puerto, la velocidad y el tiempo de espera. No comprueba que el pad responda.</p>
                <div class="request"><span>GET</span><code>?action=status</code></div>
                <p class="returns">Devuelve <code>OK</code> y los valores configurados.</p>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="status-result">
                    <input type="hidden" name="action" value="status">
                    <button class="operation-button" type="submit" aria-controls="status-result" disabled>Ver configuración</button>
                </form>
                <div id="status-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de status"></pre>
                </div>
            </article>
            <article class="card">
                <div class="card-top"><code>write-epc</code><span class="badge write">Escritura</span></div>
                <h3>Grabar un EPC</h3>
                <p>Requiere <code>epc</code>. Un lote numérico corto se completa con ceros hasta 24 caracteres.</p>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="write-epc-result">
                    <input type="hidden" name="action" value="write-epc">
                    <label for="write-epc-input">Número de lote o EPC</label>
                    <input id="write-epc-input" name="epc" type="text" placeholder="Ej.: 130527" required maxlength="124" pattern="[0-9A-Fa-f]+" autocomplete="off" autocapitalize="characters" spellcheck="false" aria-describedby="write-epc-hint">
                    <p id="write-epc-hint" class="field-hint">Los números cortos se completan con ceros. También puedes ingresar un EPC hexadecimal.</p>
                    <button class="operation-button" type="submit" aria-controls="write-epc-result" disabled>Grabar EPC</button>
                </form>
                <p class="returns">Devuelve <code>WRITTEN=…</code> y una segunda línea <code>OK</code>.</p>
                <p class="operation-note">Modifica la etiqueta. Después de grabar, vuelve a leer el EPC para comprobarlo.</p>
                <div id="write-epc-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de write-epc"></pre>
                </div>
            </article>
            <article class="card">
                <div class="card-top"><code>clear</code><span class="badge write">Escritura</span></div>
                <h3>Poner el EPC en ceros</h3>
                <p>Acepta <code>palabras</code> de 1 a 31. Por defecto usa 6 palabras: 24 dígitos hexadecimales.</p>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="clear-result">
                    <input type="hidden" name="action" value="clear">
                    <label for="clear-words-input">Cantidad de palabras</label>
                    <input id="clear-words-input" name="palabras" type="number" value="6" min="1" max="31" step="1" required aria-describedby="clear-words-hint">
                    <p id="clear-words-hint" class="field-hint">6 palabras equivalen a 24 dígitos hexadecimales.</p>
                    <button class="operation-button" type="submit" aria-controls="clear-result" disabled>Poner EPC en ceros</button>
                </form>
                <p class="returns">Devuelve <code>WRITTEN=000…</code> seguido de <code>OK</code>.</p>
                <p class="operation-note">Sobrescribe el EPC con ceros; no borra toda la memoria de la etiqueta.</p>
                <?php if (!$windows): ?><p class="field-hint">En Linux, la lectura omite los EPC de 24 ceros; después de limpiar con 6 palabras puede devolver NO_TAG.</p><?php endif; ?>
                <div id="clear-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de clear"></pre>
                </div>
            </article>
            <article class="card">
                <div class="card-top"><code>version</code><span class="badge neutral">Windows</span></div>
                <h3>Consultar la versión</h3>
                <p>Consulta la versión del lector en Windows. Esta operación todavía no está implementada en Linux.</p>
                <div class="request"><span>GET</span><code>?action=version</code></div>
                <p class="returns">En Linux devuelve <code>ERROR=VERSION_NOT_SUPPORTED</code>.</p>
                <?php if ($windows): ?>
                <form class="operation-form" action="PADBridge.php" method="post" data-rfid-operation data-result="version-result">
                    <input type="hidden" name="action" value="version">
                    <button class="operation-button" type="submit" aria-controls="version-result" disabled>Consultar versión</button>
                </form>
                <div id="version-result" class="operation-result" role="status" aria-live="polite" hidden>
                    <p class="result-status"></p>
                    <pre tabindex="0" aria-label="Respuesta de version"></pre>
                </div>
                <?php else: ?>
                <p class="operation-note">No disponible en este servidor Linux.</p>
                <?php endif; ?>
            </article>
        </div>
    </section>

    <section id="respuestas" aria-labelledby="respuestas-titulo">
        <div class="section-heading"><div><span class="eyebrow">02 / RESULTADOS</span><h2 id="respuestas-titulo">Cómo leer una respuesta</h2></div><p><code>\n</code> representa un salto de línea.<br> En una escritura, separa <code>WRITTEN</code> de <code>OK</code>.</p></div>
        <div class="response-grid">
            <div class="json-example"><div class="code-heading"><span class="dot"></span> Ejemplo de escritura confirmada</div><pre><code>{
  "ok": true,
  "accion": "write-epc",
  "resultado": "WRITTEN=000000000000000000130527\nOK",
  "exit_code": 0,
  "stderr": ""
}</code></pre></div>
            <dl class="glossary">
                <div><dt><code>ok</code></dt><dd><code>true</code> si la operación terminó sin error; <code>false</code> si falló.</dd></div>
                <div><dt><code>resultado</code></dt><dd>Texto que consume Marijoa: <code>DETECTED=…</code>, <code>WRITTEN=…</code>, <code>NO_TAG</code> o <code>ERROR=…</code>.</dd></div>
                <div><dt><code>NO_TAG</code></dt><dd>La lectura no encontró etiquetas. Es un resultado normal, con <code>ok=true</code>.</dd></div>
                <div><dt><code>exit_code</code></dt><dd>Cero indica éxito. Un valor distinto de cero indica un error; <code>stderr</code> puede aportar detalles.</dd></div>
            </dl>
        </div>
        <div class="setup-note"><strong>Antes de leer en Linux</strong><span>Selector del pad en <b>USB</b>, puerto configurado y permisos preparados con <code>install.sh</code>. Si aparece <code>ERROR=BRIDGE_BUSY</code>, espera a que termine la operación en curso.</span></div>
    </section>

    <section id="integracion" class="integration" aria-labelledby="integracion-titulo">
        <div><h2 id="integracion-titulo">Tus llamadas siguen igual.</h2><p>Usa la misma URL desde cada equipo y envía los parámetros como formulario. No necesitas cambiar <code>grabarRFID</code>, <code>escanearTAGsRFID</code> ni <code>checkTAGRFID</code>.</p><p class="endpoint"><code>http://localhost/rfid-bridge/PADBridge.php</code></p></div>
        <div class="integration-code"><span>POST · EJEMPLO PARA TU APLICACIÓN</span><pre><code>action=write-epc&amp;epc=130527</code></pre><p>Los errores de operación mantienen HTTP 200. Revisa <code>ok</code> y <code>resultado</code> en el JSON.</p></div>
    </section>

    <details class="technical"><summary>¿Dónde está el código del bridge?</summary><p><code>PADBridge.php</code> recibe las peticiones y elige entre esta ayuda y la API. <code>lib/Bridge.php</code> contiene la validación, el relleno del EPC, el bloqueo, la ejecución y el formato de las respuestas. La comunicación con el pad sigue en <code>linux/OR2103Bridge.py</code> o <code>windows/OR2103Bridge.exe</code>.</p><p>El archivo principal es más corto porque la lógica se organizó por responsabilidad. Para pedir JSON sin acción, usa <a href="PADBridge.php?format=json"><code>?format=json</code></a>. Para abrir siempre esta guía, usa <a href="PADBridge.php?help=1"><code>?help=1</code></a>.</p></details>
</main>
<footer>
    <span>RFID Bridge <b>OR2103</b></span>
    <span>&copy; 2026 · Desarrollado por: Ing. Doglas A. Dembogurski Feix</span>
    <span>Ayuda local · Sin dependencias externas</span>
</footer>
</body>
</html>
