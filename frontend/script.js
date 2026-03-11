const BASE = "https://healthcare-backend-iwkt.onrender.com";

/* ─── HTML escape ─────────────────────────────────────────────────────── */
function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ─── Init ────────────────────────────────────────────────────────────── */
window.onload = async function () {
    // Auth check — redirect to login if not logged in
    try {
        const r = await fetch(BASE + "/me", { credentials: "include" });
        if (!r.ok) { window.location.href = "login.html"; return; }
        const d = await r.json();
        if (d.role === "guest") { window.location.href = "login.html"; return; }
        if (d.role === "admin") { window.location.href = "admin.html"; return; }
        if (d.role === "doctor") { window.location.href = "doctor.html"; return; }
        document.getElementById("navUser").textContent = "Hi, " + esc(d.username);
    } catch (e) {
        window.location.href = "login.html";
        return;
    }

    loadTests();
    loadCart();
    loadBookings();
    setupAutosuggest();

    const btn = document.getElementById("searchBtn");
    const inp = document.getElementById("testQuery");
    const sel = document.getElementById("testDropdown");

    btn.onclick = () => search(inp.value.trim());
    inp.addEventListener("keydown", e => { if (e.key === "Enter") search(inp.value.trim()); });
    sel.onchange = function () {
        if (this.value) { inp.value = this.value; search(this.value); }
    };
};

/* ─── Load dropdown ───────────────────────────────────────────────────── */
async function loadTests() {
    try {
        const r = await fetch(BASE + "/tests");
        const d = await r.json();
        const sel = document.getElementById("testDropdown");
        (d.tests || []).forEach(t => {
            const o = document.createElement("option");
            o.value = o.textContent = t;
            sel.appendChild(o);
        });
    } catch (e) { console.error("loadTests failed:", e); }
}

/* ═══ Autosuggest (Task 8) ════════════════════════════════════════════ */
let suggestTimeout = null;

function setupAutosuggest() {
    const inp = document.getElementById("testQuery");
    const box = document.getElementById("suggestBox");

    inp.addEventListener("input", function () {
        clearTimeout(suggestTimeout);
        const q = this.value.trim();
        if (q.length < 2) { box.style.display = "none"; return; }
        suggestTimeout = setTimeout(() => fetchSuggestions(q), 250);
    });

    // Close suggestions on click outside
    document.addEventListener("click", function (e) {
        if (!inp.contains(e.target) && !box.contains(e.target)) {
            box.style.display = "none";
        }
    });
}

async function fetchSuggestions(q) {
    const box = document.getElementById("suggestBox");
    try {
        const r = await fetch(BASE + "/suggest?q=" + encodeURIComponent(q));
        const d = await r.json();
        const items = d.suggestions || [];
        if (!items.length) { box.style.display = "none"; return; }

        box.innerHTML = items.map(s =>
            `<div class="suggest-item" onclick="pickSuggestion('${esc(s)}')">${esc(s)}</div>`
        ).join("");
        box.style.display = "block";
    } catch (e) { box.style.display = "none"; }
}

function pickSuggestion(name) {
    document.getElementById("testQuery").value = name;
    document.getElementById("suggestBox").style.display = "none";
    search(name);
}

/* ─── Search ──────────────────────────────────────────────────────────── */
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

/* ─── Render result block ─────────────────────────────────────────────── */
function renderResult(r) {
    const info = r.info || {};
    const stats = r.statistics || {};
    const labs = r.results || [];
    const savings = (stats.max_price && stats.min_price) ? stats.max_price - stats.min_price : 0;
    const savingsPct = stats.max_price ? Math.round((savings / stats.max_price) * 100) : 0;

    let html = "";

    // Info card (if metadata exists)
    if (info.description) {
        html += `<div class="info-card">
            <h2>${esc(r.matched_test)}</h2>
            <p class="info-description">${esc(info.description)}</p>
            ${info.why_done ? `<p class="info-why"><strong>Why it is done: </strong>${esc(info.why_done)}</p>` : ""}
            <div class="info-grid">
                ${info.fasting_required ? `<div><strong>Fasting:</strong> ${esc(info.fasting_required)}</div>` : ""}
                ${info.sample_type ? `<div><strong>Sample:</strong> ${esc(info.sample_type)}</div>` : ""}
                ${info.turnaround_time ? `<div><strong>Report Time:</strong> ${esc(info.turnaround_time)}</div>` : ""}
                ${info.normal_range ? `<div class="full-width"><strong>Normal Range:</strong> ${esc(info.normal_range)}</div>` : ""}
            </div>
            ${info.preparation ? `<div class="prep-box"><strong>Preparation: </strong>${esc(info.preparation)}</div>` : ""}
        </div>`;
    } else {
        html += `<h2 style="font-size:1.25rem;color:var(--text-primary);margin-bottom:.75rem">${esc(r.matched_test)}</h2>`;
    }

    // Stats card with enhanced analytics (Task 9)
    if (stats.min_price) {
        html += `<div class="stats-card">
            <div class="stat-item lowest">
                <div class="stat-label">Lowest</div>
                <div class="stat-value">&#8377;${stats.min_price}</div>
                <div class="stat-sub">${esc(stats.min_company)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Average</div>
                <div class="stat-value">&#8377;${stats.avg_price}</div>
                <div class="stat-sub">across all labs</div>
            </div>
            <div class="stat-item highest">
                <div class="stat-label">Highest</div>
                <div class="stat-value">&#8377;${stats.max_price}</div>
                <div class="stat-sub">${esc(stats.max_company)}</div>
            </div>
        </div>`;
    }

    // Savings banner with percentage (Task 9 enhancement)
    if (savings > 0) {
        html += `<div class="save-banner">
            &#10003; Save up to <strong>&#8377;${savings}</strong> (${savingsPct}%) by choosing the right lab
        </div>`;
    }

    // Price bar chart (Task 9 — visual analytics)
    if (labs.length > 1 && stats.max_price) {
        html += `<div class="price-chart-wrap">
            <div class="price-chart-title">Price Comparison</div>
            <div class="price-chart">`;
        labs.forEach(l => {
            const widthPct = Math.max(15, Math.round((l.price / stats.max_price) * 100));
            const isMin = l.price === stats.min_price;
            html += `<div class="price-bar-row">
                <div class="price-bar-label">${esc(l.company)}</div>
                <div class="price-bar-track">
                    <div class="price-bar-fill ${isMin ? 'best' : ''}" style="width:${widthPct}%">
                        &#8377;${l.price}
                    </div>
                </div>
            </div>`;
        });
        html += `</div></div>`;
    }

    html += labs.length ? renderTable(r.matched_test, labs) : '<p class="msg-empty">No labs found.</p>';
    return html;
}

/* ─── Lab table with booking button (Task 4) ──────────────────────────── */
function renderTable(testName, labs) {
    const minP = Math.min(...labs.map(l => l.price));
    const rows = labs.map(l => {
        const best = l.price === minP;
        return `<tr class="${best ? "best-row" : ""}">
            <td>${esc(l.company)}${best ? '<span class="best-badge">Best Value</span>' : ""}</td>
            <td>${esc(l.location || "Hyderabad")}</td>
            <td>&#8377;${l.price}</td>
            <td class="action-cell">
                <button class="add-cart-btn"
                    data-test="${esc(testName)}"
                    data-company="${esc(l.company)}"
                    data-price="${l.price}"
                    onclick="handleAdd(this)">+ Add</button>
                <button class="book-btn"
                    data-test="${esc(testName)}"
                    data-lab="${esc(l.company)}"
                    data-price="${l.price}"
                    onclick="openBookingModal(this)">Book</button>
            </td>
        </tr>`;
    }).join("");
    return `<div class="lab-table-wrap">
        <table class="lab-table">
            <thead><tr><th>Lab</th><th>Location</th><th>Price (&#8377;)</th><th>Actions</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
    </div>`;
}

/* ─── Cart: add ───────────────────────────────────────────────────────── */
async function handleAdd(btn) {
    const tn = btn.dataset.test;
    const co = btn.dataset.company;
    const pr = parseInt(btn.dataset.price);
    btn.disabled = true;
    btn.textContent = "Adding...";
    try {
        const r = await fetch(BASE + "/cart/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ test_name: tn, company: co, price: pr })
        });
        if (r.ok) {
            btn.textContent = "Added!";
            btn.classList.add("added");
            loadCart();
        } else {
            btn.textContent = "In Cart";
            btn.classList.add("added");
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "+ Add";
    }
}

/* ─── Cart: load ──────────────────────────────────────────────────────── */
async function loadCart() {
    try {
        const r = await fetch(BASE + "/cart", { credentials: "include" });
        if (!r.ok) return;
        const d = await r.json();
        renderCartUI(d.cart || [], d.total || 0);
    } catch (e) { console.error("loadCart failed:", e); }
}

/* ─── Cart: render ────────────────────────────────────────────────────── */
function renderCartUI(items, total) {
    const body = document.getElementById("cartBody");
    const cnt = document.getElementById("cartCount");
    const totEl = document.getElementById("cartTotal");
    const footer = document.getElementById("cartFooter");

    cnt.textContent = items.length;

    if (!items.length) {
        body.innerHTML = '<p class="cart-empty">Your cart is empty.</p>';
        if (footer) footer.style.display = "none";
        return;
    }

    body.innerHTML = items.map(i => `
        <div class="cart-item">
            <div class="cart-item-info">
                <div class="cart-item-test">${esc(i.test_name)}</div>
                <div class="cart-item-lab">${esc(i.company)}</div>
            </div>
            <div style="display:flex;align-items:center;gap:.5rem">
                <span class="cart-item-price">&#8377;${i.price}</span>
                <button class="cart-remove-btn" onclick="removeCartItem('${i.id}')" title="Remove">&#10005;</button>
            </div>
        </div>
    `).join("");

    if (totEl) totEl.innerHTML = "&#8377;" + total;
    if (footer) footer.style.display = "block";
}

/* ─── Cart: remove ────────────────────────────────────────────────────── */
async function removeCartItem(id) {
    await fetch(BASE + "/cart/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ item_id: id })
    });
    loadCart();
}

/* ─── Cart: clear ─────────────────────────────────────────────────────── */
async function clearCart() {
    await fetch(BASE + "/cart/clear", { method: "POST", credentials: "include" });
    loadCart();
}

/* ─── Cart sidebar toggle ─────────────────────────────────────────────── */
function toggleCart() {
    document.getElementById("cartSidebar").classList.toggle("open");
    document.getElementById("cartOverlay").classList.toggle("open");
}

/* ═══ Booking System (Task 4) ═════════════════════════════════════════ */

function openBookingModal(btn) {
    const testName = btn.dataset.test;
    const labName = btn.dataset.lab;
    const price = btn.dataset.price;

    document.getElementById("bookingTestName").textContent = testName;
    document.getElementById("bookingLabName").textContent = labName;
    document.getElementById("bookingPrice").textContent = "₹" + price;
    document.getElementById("bookTestInput").value = testName;
    document.getElementById("bookLabInput").value = labName;
    document.getElementById("bookingResult").style.display = "none";
    document.getElementById("bookingForm").style.display = "block";

    document.getElementById("bookingModal").classList.add("open");
    document.getElementById("bookingOverlay").classList.add("open");
}

function closeBookingModal() {
    document.getElementById("bookingModal").classList.remove("open");
    document.getElementById("bookingOverlay").classList.remove("open");
}

async function submitBooking() {
    const mode = document.querySelector('input[name="bookMode"]:checked').value;
    const testName = document.getElementById("bookTestInput").value;
    const labName = document.getElementById("bookLabInput").value;

    try {
        const r = await fetch(BASE + "/book", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ test_name: testName, lab_name: labName, mode: mode })
        });
        const d = await r.json();
        if (!r.ok) { alert(d.error || "Booking failed"); return; }

        document.getElementById("bookingForm").style.display = "none";
        const resultDiv = document.getElementById("bookingResult");
        if (mode === "direct_contact") {
            resultDiv.innerHTML = `
                <div class="booking-success">
                    <div class="booking-success-icon">&#10003;</div>
                    <h3>Booking Confirmed!</h3>
                    <p>Your booking ID: <strong>${d.booking_id}</strong></p>
                    ${d.lab_phone ? `<p>Lab Phone: <a href="tel:${d.lab_phone}">${d.lab_phone}</a></p>` : ""}
                    ${d.lab_address ? `<p>Address: ${esc(d.lab_address)}</p>` : ""}
                    <p class="booking-note">Please contact the lab to schedule your appointment.</p>
                </div>`;
        } else {
            resultDiv.innerHTML = `
                <div class="booking-success">
                    <div class="booking-success-icon">&#9993;</div>
                    <h3>Request Sent!</h3>
                    <p>Booking ID: <strong>${d.booking_id}</strong></p>
                    <p class="booking-note">The lab will contact you to confirm your appointment.</p>
                </div>`;
        }
        resultDiv.style.display = "block";
        loadBookings();
    } catch (e) { alert("Server error"); }
}

/* ─── Load bookings ───────────────────────────────────────────────────── */
async function loadBookings() {
    try {
        const r = await fetch(BASE + "/bookings", { credentials: "include" });
        if (!r.ok) return;
        const d = await r.json();
        const list = d.bookings || [];
        const container = document.getElementById("bookingsList");
        const countEl = document.getElementById("bookingsCount");

        if (countEl) countEl.textContent = list.length;

        if (!container) return;
        if (!list.length) {
            container.innerHTML = '<p class="cart-empty">No bookings yet.</p>';
            return;
        }
        container.innerHTML = list.map(b => `
            <div class="booking-item ${b.status}">
                <div class="booking-item-info">
                    <div class="booking-item-test">${esc(b.test_name)}</div>
                    <div class="booking-item-lab">${esc(b.lab_name)}</div>
                    <div class="booking-item-date">${b.created_at ? new Date(b.created_at).toLocaleDateString() : ""}</div>
                </div>
                <div class="booking-item-actions">
                    <span class="booking-status-badge ${b.status}">${esc(b.status)}</span>
                    ${b.status !== "cancelled" ? `<button class="booking-cancel-btn" onclick="cancelBooking('${b.id}')">Cancel</button>` : ""}
                </div>
            </div>
        `).join("");
    } catch (e) { console.error("loadBookings failed:", e); }
}

async function cancelBooking(id) {
    if (!confirm("Cancel this booking?")) return;
    await fetch(BASE + "/bookings/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ booking_id: id })
    });
    loadBookings();
}

/* ─── Bookings sidebar toggle ─────────────────────────────────────────── */
function toggleBookings() {
    document.getElementById("bookingsSidebar").classList.toggle("open");
    document.getElementById("bookingsOverlay").classList.toggle("open");
}

/* ─── Logout ──────────────────────────────────────────────────────────── */
async function doLogout() {
    await fetch(BASE + "/logout", { method: "POST", credentials: "include" });
    window.location.href = "login.html";
}