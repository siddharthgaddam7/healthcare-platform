const BASE = "https://healthcare-backend-iwkt.onrender.com";

/* ─── Helper: HTML-escape ─── */
function esc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/* ─── Load test dropdown ─── */
async function loadTests() {
    const sel = document.getElementById("testDropdown");
    const r = await fetch(BASE + "/tests", { credentials: "include" });
    const d = await r.json();
    (d.tests || []).forEach(t => {
        const o = document.createElement("option");
        o.value = o.textContent = t;
        sel.appendChild(o);
    });
}

/* ─── Search ─── */
async function search(q) {
    const res = document.getElementById("results");
    if (!q) { res.innerHTML = '<p class="msg-error">Enter a test name.</p>'; return; }
    res.innerHTML = '<p class="msg-searching">Searching...</p>';
    try {
        const r = await fetch(BASE + "/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ query: q })
        });
        const d = await r.json();
        if (!d.results || !d.results.length) {
            res.innerHTML = '<p class="msg-empty">No results found.</p>';
            return;
        }
        res.innerHTML = d.results.map(renderResult).join("");
    } catch (e) {
        res.innerHTML = '<p class="msg-error">Cannot reach backend.</p>';
    }
}

/* ─── Render helpers ─── */
function renderResult(r) {
    const info = r.info || {}, stats = r.statistics || {}, labs = r.results || [];
    const hasInfo = info.description;
    const save = (stats.min_price != null && stats.max_price != null) ? stats.max_price - stats.min_price : 0;

    let h = hasInfo
        ? renderInfo(r.matched_test, info)
        : '<h2 style="font-size:1.25rem;color:var(--blue-dark);margin-bottom:.75rem">' + esc(r.matched_test) + '</h2>';

    h += renderStats(stats);
    if (save > 0) h += '<div class="save-banner">&#10003; Save up to &#8377;' + save + ' by choosing the right lab</div>';
    h += labs.length ? renderTable(r.matched_test, labs) : '<p class="msg-empty">No labs found.</p>';
    return h;
}

function renderInfo(name, info) {
    const badges = (info.parameters || []).map(p => '<span class="param-badge">' + esc(p) + '</span>').join("");
    let h = '<div class="info-card"><h2>' + esc(name) + '</h2>';
    if (info.description) h += '<p class="info-description">' + esc(info.description) + '</p>';
    if (info.why_done) h += '<p class="info-why"><strong>Why it is done: </strong>' + esc(info.why_done) + '</p>';
    h += '<div class="info-grid">';
    if (info.fasting_required) h += '<div><strong>Fasting:</strong> ' + esc(info.fasting_required) + '</div>';
    if (info.sample_type) h += '<div><strong>Sample:</strong> ' + esc(info.sample_type) + '</div>';
    if (info.turnaround_time) h += '<div><strong>Report Time:</strong> ' + esc(info.turnaround_time) + '</div>';
    if (info.normal_range) h += '<div class="full-width"><strong>Normal Range:</strong> ' + esc(info.normal_range) + '</div>';
    h += '</div>';
    if (badges) h += '<div class="params-section"><p class="params-label">Parameters</p><div class="params-badges">' + badges + '</div></div>';
    if (info.preparation) h += '<div class="prep-box"><strong>Preparation: </strong>' + esc(info.preparation) + '</div>';
    return h + '</div>';
}

function renderStats(s) {
    const f = v => v != null ? "&#8377;" + v : "N/A";
    return '<div class="stats-card">'
        + '<div class="stat-item lowest"><div class="stat-label">Lowest</div><div class="stat-value">' + f(s.min_price) + '</div><div class="stat-sub">' + esc(s.min_company || "") + '</div></div>'
        + '<div class="stat-item"><div class="stat-label">Average</div><div class="stat-value">' + f(s.avg_price) + '</div><div class="stat-sub">all labs</div></div>'
        + '<div class="stat-item highest"><div class="stat-label">Highest</div><div class="stat-value">' + f(s.max_price) + '</div><div class="stat-sub">' + esc(s.max_company || "") + '</div></div>'
        + '</div>';
}

function renderTable(testName, labs) {
    const minP = Math.min(...labs.map(l => l.price));
    const rows = labs.map(lab => {
        const best = lab.price === minP;
        return '<tr class="' + (best ? "best-row" : "") + '">'
            + '<td>' + esc(lab.company) + (best ? '<span class="best-badge">Best Value</span>' : "") + '</td>'
            + '<td>' + (lab.location ? esc(lab.location) : "Hyderabad") + '</td>'
            + '<td>&#8377;' + lab.price + '</td>'
            + '<td><button class="add-cart-btn" data-test="' + esc(testName) + '" data-company="' + esc(lab.company) + '" data-price="' + lab.price + '" onclick="handleAdd(this)">+ Add</button></td>'
            + '</tr>';
    }).join("");
    return '<div class="lab-table-wrap"><table class="lab-table"><thead><tr><th>Lab</th><th>Location</th><th>Price (&#8377;)</th><th>Cart</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}

/* ─── Cart functions ─── */
async function loadCart() {
    try {
        const r = await fetch(BASE + "/cart", { credentials: "include" });
        if (!r.ok) return;
        const d = await r.json();
        renderCartUI(d.cart || [], d.total || 0);
    } catch (e) {}
}

function renderCartUI(items, total) {
    const body = document.getElementById("cartBody");
    const foot = document.getElementById("cartFooter");
    const cnt = document.getElementById("cartCount");
    const tot = document.getElementById("cartTotal");
    cnt.textContent = items.length;
    if (!items.length) {
        body.innerHTML = '<p class="cart-empty">Your cart is empty.</p>';
        foot.style.display = "none";
        return;
    }
    body.innerHTML = items.map(i =>
        '<div class="cart-item"><div class="cart-item-info"><div class="cart-item-test">' + esc(i.test_name) + '</div><div class="cart-item-lab">' + esc(i.company) + '</div></div><div style="display:flex;align-items:center;gap:.5rem"><span class="cart-item-price">&#8377;' + i.price + '</span><button class="cart-remove-btn" onclick="removeCartItem(' + i.id + ')" title="Remove">&#10005;</button></div></div>'
    ).join("");
    tot.innerHTML = "&#8377;" + total;
    foot.style.display = "block";
}

async function handleAdd(b) {
    const tn = b.getAttribute("data-test"),
        co = b.getAttribute("data-company"),
        pr = parseInt(b.getAttribute("data-price"));
    b.disabled = true;
    b.textContent = "Adding...";
    try {
        const r = await fetch(BASE + "/cart/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ test_name: tn, company: co, price: pr })
        });
        if (r.ok) { b.textContent = "Added!"; b.classList.add("added"); loadCart(); }
        else { b.textContent = "In Cart"; b.classList.add("added"); }
    } catch (e) { b.textContent = "Error"; }
}

async function removeCartItem(id) {
    await fetch(BASE + "/cart/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ item_id: id })
    });
    loadCart();
}

async function clearCart() {
    await fetch(BASE + "/cart/clear", { method: "POST", credentials: "include" });
    loadCart();
}

function toggleCart() {
    document.getElementById("cartSidebar").classList.toggle("open");
    document.getElementById("cartOverlay").classList.toggle("open");
}

async function doLogout() {
    await fetch(BASE + "/logout", { method: "POST", credentials: "include" });
    window.location.href = "login.html";
}

/* ─── Page init ─── */
window.onload = async function () {
    try {
        const r = await fetch(BASE + "/me", { credentials: "include" });
        const d = await r.json();
        if (d.role === "guest" || !d.role) { window.location.href = "login.html"; return; }
        if (d.role === "admin") { window.location.href = "admin.html"; return; }
        document.getElementById("navUser").textContent = "Hi, " + d.username;
    } catch (e) { window.location.href = "login.html"; return; }

    loadTests();
    loadCart();

    const btn = document.getElementById("searchBtn");
    const inp = document.getElementById("testQuery");
    const sel = document.getElementById("testDropdown");

    btn.addEventListener("click", () => search(inp.value.trim()));
    inp.addEventListener("keydown", e => { if (e.key === "Enter") search(inp.value.trim()); });
    sel.addEventListener("change", function () { if (this.value) { inp.value = this.value; search(this.value); } });
};