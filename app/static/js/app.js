let toastTimer;

function showToast(msg, duration = 3000) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("hidden"), duration);
}

async function triggerScan() {
    const btn = document.getElementById("scan-btn");
    btn.textContent = "⟳ Escaneando...";
    btn.disabled = true;
    showToast("Stage 1: escaneando rutas...", 15000);
    try {
        const r = await fetch("/api/scan", { method: "POST" });
        const d = await r.json();
        showToast(`✓ Scan iniciado en background. Recarga en unos segundos para ver resultados.`);
        setTimeout(() => location.reload(), 2500);
    } catch (e) {
        showToast("✗ Error durante el scan");
    } finally {
        btn.textContent = "⟳ Escanear";
        btn.disabled = false;
    }
}
