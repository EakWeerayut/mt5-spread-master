// Global State Cache
const cache = {
    broker1: { bid: null, ask: null, connected: false, symbol: "", contract_size: null, min_volume: null },
    broker2: { bid: null, ask: null, connected: false, symbol: "", contract_size: null, min_volume: null },
    activeDirection: "buy",
    logsCount: 0,
    recommendation: null,
    isFirstPoll: true,
    fvBefore: null
};

const orderStatusCache = {};

// UI Elements
// UI Elements
const els = {
    b1Path: document.getElementById("b1-path"),
    b1Account: document.getElementById("b1-account"),
    statusB1: document.getElementById("status-b1"),

    b2Path: document.getElementById("b2-path"),
    b2Account: document.getElementById("b2-account"),
    statusB2: document.getElementById("status-b2"),

    btnConnect: document.getElementById("btn-connect"),
    btnDisconnect: document.getElementById("btn-disconnect"),
    btnSaveConfig: document.getElementById("btn-save-config"),

    symbol1: document.getElementById("symbol1"),
    symbol2: document.getElementById("symbol2"),
    s1Recs: document.getElementById("s1-recommendations"),
    s2Recs: document.getElementById("s2-recommendations"),

    displaySym1: document.getElementById("display-sym1"),
    displaySym2: document.getElementById("display-sym2"),
    b1Bid: document.getElementById("b1-bid"),
    b1Ask: document.getElementById("b1-ask"),
    b1Pos: document.getElementById("b1-pos"),
    b2Bid: document.getElementById("b2-bid"),
    b2Ask: document.getElementById("b2-ask"),
    b2Pos: document.getElementById("b2-pos"),

    spreadAsk: document.getElementById("spread-ask"),
    spreadBid: document.getElementById("spread-bid"),
    spreadFairValue: document.getElementById("spread-fair-value"),
    spreadFairValueBefore: document.getElementById("spread-fair-value-before"),
    fairValueLabel: document.getElementById("fair-value-label"),

    dirBuy: document.getElementById("dir-buy"),
    dirSell: document.getElementById("dir-sell"),
    orderVol1: document.getElementById("order-vol1"),
    orderVol2: document.getElementById("order-vol2"),
    orderTarget: document.getElementById("order-target"),
    btnSubmitOrder: document.getElementById("btn-submit-order"),
    orderDryRun: document.getElementById("order-dry-run"),

    lotRecContainer: document.getElementById("lot-recommendation-container"),
    lotRecText: document.getElementById("lot-recommendation-text"),
    btnApplyRec: document.getElementById("btn-apply-rec"),

    ordersPlaceholder: document.getElementById("orders-placeholder"),
    ordersContainer: document.getElementById("orders-container"),
    logTerminal: document.getElementById("log-terminal"),
    btnClearLogs: document.getElementById("btn-clear-logs"),

    // Favorites & History
    btnSaveFavorite: document.getElementById("btn-save-favorite"),
    favoritesList: document.getElementById("favorites-list"),
    btnRefreshHistory: document.getElementById("btn-refresh-history"),
    hist24hBid: document.getElementById("hist-24h-bid"),
    hist24hAsk: document.getElementById("hist-24h-ask"),
    hist3dBid: document.getElementById("hist-3d-bid"),
    hist3dAsk: document.getElementById("hist-3d-ask"),
    hist7dBid: document.getElementById("hist-7d-bid"),
    hist7dAsk: document.getElementById("hist-7d-ask")
};

// 1. Load Pre-Configured Accounts
async function loadAccounts() {
    try {
        const res = await fetch("/api/accounts");
        if (res.ok) {
            const accounts = await res.json();
            populateAccountSelect(els.b1Account, accounts);
            populateAccountSelect(els.b2Account, accounts);
        }
    } catch (e) {
        console.error("Failed to load pre-configured accounts", e);
    }
}

function populateAccountSelect(selectEl, accounts) {
    selectEl.innerHTML = "";
    accounts.forEach(acc => {
        const opt = document.createElement("option");
        opt.value = acc.id;
        if (acc.id === "mock") {
            opt.textContent = acc.name;
        } else {
            opt.textContent = `${acc.name} (${acc.login} @ ${acc.server})`;
        }
        selectEl.appendChild(opt);
    });
}

// 2. Initial Load Config
async function loadConfig() {
    try {
        const res = await fetch("/api/config");
        if (res.ok) {
            const config = await res.json();
            if (config.broker1) {
                els.b1Path.value = config.broker1.path || "";
                if (config.broker1.accountId) {
                    els.b1Account.value = config.broker1.accountId;
                }
            }
            if (config.broker2) {
                els.b2Path.value = config.broker2.path || "";
                if (config.broker2.accountId) {
                    els.b2Account.value = config.broker2.accountId;
                }
            }
        }
    } catch (e) {
        console.error("Failed to load saved configuration", e);
    }
}

// 3. Save Config Helper
function getFormConfig() {
    return {
        broker1: {
            path: els.b1Path.value,
            accountId: els.b1Account.value
        },
        broker2: {
            path: els.b2Path.value,
            accountId: els.b2Account.value
        }
    };
}

// 4. Connect/Disconnect Terminals
async function initializeTerminals() {
    const config = getFormConfig();
    
    if (!config.broker1.path || !config.broker1.accountId ||
        !config.broker2.path || !config.broker2.accountId) {
        alert("Please select broker accounts and enter terminal paths first.");
        return;
    }

    els.btnConnect.disabled = true;
    els.btnConnect.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Initializing...';

    try {
        const res = await fetch("/api/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config })
        });
        
        if (res.ok) {
            els.btnDisconnect.disabled = false;
        } else {
            const err = await res.json();
            alert("Initialization request failed: " + err.message);
            els.btnConnect.disabled = false;
            els.btnConnect.innerHTML = '<i class="fa-solid fa-plug"></i> Initialize Terminals';
        }
    } catch (e) {
        alert("Network error: " + e.message);
        els.btnConnect.disabled = false;
        els.btnConnect.innerHTML = '<i class="fa-solid fa-plug"></i> Initialize Terminals';
    }
}

async function disconnectTerminals() {
    els.btnDisconnect.disabled = true;
    try {
        await fetch("/api/disconnect", { method: "POST" });
    } catch (e) {
        console.error("Failed to disconnect", e);
    }
}

// 4. Autocomplete and Symbol Subscriptions
function setupAutocomplete(inputEl, dropdownEl, brokerKey) {
    let debounceTimer;
    
    inputEl.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        const q = inputEl.value;
        
        debounceTimer = setTimeout(async () => {
            if (q.length === 0) {
                dropdownEl.style.display = "none";
                return;
            }
            try {
                const res = await fetch(`/api/search?broker=${brokerKey}&q=${encodeURIComponent(q)}`);
                if (res.ok) {
                    const symbols = await res.json();
                    renderDropdown(symbols, dropdownEl, inputEl, brokerKey);
                }
            } catch (e) {
                console.error("Error searching symbols", e);
            }
        }, 150);
    });

    // Close recommendations on blur, but delay slightly to let clicks trigger
    inputEl.addEventListener("blur", () => {
        setTimeout(() => {
            dropdownEl.style.display = "none";
        }, 200);
    });
    
    inputEl.addEventListener("focus", () => {
        if (inputEl.value.length > 0) {
            dropdownEl.style.display = "block";
        }
    });
}

function renderDropdown(symbols, dropdownEl, inputEl, brokerKey) {
    if (symbols.length === 0) {
        dropdownEl.style.display = "none";
        return;
    }
    
    dropdownEl.innerHTML = "";
    symbols.forEach(sym => {
        const div = document.createElement("div");
        div.className = "autocomplete-item";
        div.textContent = sym;
        div.addEventListener("click", () => {
            inputEl.value = sym;
            dropdownEl.style.display = "none";
            subscribeSymbol(brokerKey, sym);
        });
        dropdownEl.appendChild(div);
    });
    
    dropdownEl.style.display = "block";
}

async function subscribeSymbol(brokerKey, symbol) {
    const data = {};
    if (brokerKey === "broker1") {
        data.symbol1 = symbol;
        data.symbol2 = els.symbol2.value;
    } else {
        data.symbol1 = els.symbol1.value;
        data.symbol2 = symbol;
    }
    
    try {
        const res = await fetch("/api/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            // Trigger history stats load if both symbols are set
            if (data.symbol1 && data.symbol2) {
                setTimeout(loadHistoryStats, 1000); // delay slightly to let symbols initialize
            }
        }
    } catch (e) {
        console.error("Failed to subscribe to symbol", e);
    }
}

// 5. Utility Formatting
function formatVal(val) {
    if (val === null || val === undefined || isNaN(val)) return "-";
    return Number(val).toFixed(2);
}

// 6. Price Flash Animation
function updatePriceElement(el, newVal, oldVal) {
    if (newVal === null || newVal === undefined) {
        el.textContent = "-";
        return;
    }
    
    el.textContent = formatVal(newVal);
    
    if (oldVal !== null && oldVal !== undefined && newVal !== oldVal) {
        el.classList.remove("price-up", "price-down");
        void el.offsetWidth; // Force reflow
        if (newVal > oldVal) {
            el.classList.add("price-up");
        } else {
            el.classList.add("price-down");
        }
    }
}

// 7. Polling Data and Updating Dashboard
async function pollData() {
    try {
        const res = await fetch("/api/data");
        if (!res.ok) return;
        
        const data = await res.json();
        
        // Update connection status
        updateConnectionStatus("broker1", data.broker1, els.statusB1, els.symbol1);
        updateConnectionStatus("broker2", data.broker2, els.statusB2, els.symbol2);
        
        // Enable/Disable Place Order Button
        const connectedBoth = data.broker1.connected && data.broker2.connected;
        const symbolsSelected = data.broker1.symbol && data.broker2.symbol;
        els.btnSubmitOrder.disabled = !(connectedBoth && symbolsSelected && els.orderTarget.value !== "");
        
        // Enable/Disable Save Favorite and Refresh History Buttons
        const bothSymbolsSelected = els.symbol1.value !== "" && els.symbol2.value !== "";
        if (els.btnSaveFavorite) {
            els.btnSaveFavorite.disabled = !bothSymbolsSelected;
        }
        if (els.btnRefreshHistory) {
            els.btnRefreshHistory.disabled = !(connectedBoth && bothSymbolsSelected);
        }
        
        // Update price display cards
        els.displaySym1.textContent = data.broker1.symbol || "-";
        els.displaySym2.textContent = data.broker2.symbol || "-";
        
        updatePriceElement(els.b1Bid, data.broker1.bid, cache.broker1.bid);
        updatePriceElement(els.b1Ask, data.broker1.ask, cache.broker1.ask);
        updatePriceElement(els.b2Bid, data.broker2.bid, cache.broker2.bid);
        updatePriceElement(els.b2Ask, data.broker2.ask, cache.broker2.ask);
        
        // Cache prices and symbol info
        cache.broker1.bid = data.broker1.bid;
        cache.broker1.ask = data.broker1.ask;
        cache.broker1.contract_size = data.broker1.contract_size;
        cache.broker1.min_volume = data.broker1.min_volume;
        cache.broker1.symbol = data.broker1.symbol;
        cache.broker1.sessions = data.broker1.sessions;
        cache.broker1.timezone_offset = data.broker1.timezone_offset;
        
        cache.broker2.bid = data.broker2.bid;
        cache.broker2.ask = data.broker2.ask;
        cache.broker2.contract_size = data.broker2.contract_size;
        cache.broker2.min_volume = data.broker2.min_volume;
        cache.broker2.symbol = data.broker2.symbol;
        cache.broker2.sessions = data.broker2.sessions;
        cache.broker2.timezone_offset = data.broker2.timezone_offset;

        // Update net position display
        function renderPos(el, pos) {
            if (!el) return;
            if (pos !== null && pos !== undefined) {
                const val = Number(pos);
                el.textContent = `Net: ${val.toFixed(2)}`;
                el.style.color = val > 0 ? 'var(--color-success)' : val < 0 ? 'var(--color-danger)' : 'hsl(220, 20%, 75%)';
            }
        }
        renderPos(els.b1Pos, data.broker1.net_position);
        renderPos(els.b2Pos, data.broker2.net_position);

        // Update session button visibility
        updateSessionButtonVisibility("broker1", data.broker1.sessions);
        updateSessionButtonVisibility("broker2", data.broker2.sessions);
        updateCombinedSessionButtonVisibility();
        
        // Calculate lot recommendation
        updateLotRecommendation();
        
        // Update spreads
        if (data.spread.ask_spread !== null) {
            els.spreadAsk.textContent = formatVal(data.spread.ask_spread);
        } else {
            els.spreadAsk.textContent = "-";
        }
        
        if (data.spread.bid_spread !== null) {
            els.spreadBid.textContent = formatVal(data.spread.bid_spread);
        } else {
            els.spreadBid.textContent = "-";
        }

        if (data.spread.fair_value !== undefined && data.spread.fair_value !== null) {
            els.spreadFairValue.textContent = formatVal(data.spread.fair_value);
            els.spreadFairValue.parentElement.style.display = 'flex';
            if (data.spread.asset_type === 'oil') {
                els.fairValueLabel.textContent = '(Oil DTE Regression)';
            } else if (data.spread.asset_type === 'uko_uso') {
                els.fairValueLabel.textContent = '(UKO/USO Average)';
            } else {
                els.fairValueLabel.textContent = '(Gold DTE Regression)';
            }
        } else {
            els.spreadFairValue.textContent = "-";
            els.spreadFairValue.parentElement.style.display = 'none';
        }

        if (data.spread.fair_value_before !== undefined && data.spread.fair_value_before !== null) {
            els.spreadFairValueBefore.textContent = formatVal(data.spread.fair_value_before);
            els.spreadFairValueBefore.parentElement.style.display = 'flex';
            const prevFvBefore = cache.fvBefore;
            cache.fvBefore = data.spread.fair_value_before;
            // Re-render chart if fvBefore just became available and chart is showing
            if (prevFvBefore === null && spreadChartInstance) {
                const s1 = els.symbol1.value;
                const s2 = els.symbol2.value;
                if (s1 && s2) loadHistoryStats();
            }
        } else {
            els.spreadFairValueBefore.textContent = "-";
            els.spreadFairValueBefore.parentElement.style.display = 'none';
            cache.fvBefore = null;
        }
        
        // Check order status changes to trigger toast notifications
        checkOrderStatusChanges(data.orders);
        
        // Update Active Trigger Orders list
        renderActiveOrders(data.orders);
        
        // Update Logs Console
        renderLogs(data.logs);
        
    } catch (e) {
        console.error("Error polling server status", e);
    }
}

function updateConnectionStatus(key, brokerState, statusEl, inputEl) {
    const wasConnected = cache[key].connected;
    const isConnected = brokerState.connected;
    cache[key].connected = isConnected;
    
    if (isConnected) {
        statusEl.className = "status-pill online";
        statusEl.textContent = `Connected (${brokerState.login})`;
        inputEl.disabled = false;
        
        // If just connected, update connect buttons
        if (key === "broker1" || key === "broker2") {
            if (cache.broker1.connected || cache.broker2.connected) {
                els.btnConnect.disabled = true;
                els.btnConnect.innerHTML = '<i class="fa-solid fa-link-slash"></i> Terminals Active';
                els.btnDisconnect.disabled = false;
            }
        }
    } else {
        statusEl.className = "status-pill offline";
        statusEl.textContent = "Offline";
        inputEl.disabled = true;
        
        // Reset prices if offline
        if (wasConnected) {
            if (key === "broker1") {
                els.b1Bid.textContent = "-";
                els.b1Ask.textContent = "-";
            } else {
                els.b2Bid.textContent = "-";
                els.b2Ask.textContent = "-";
            }
        }
        
        // Reset connect buttons if both offline
        if (!cache.broker1.connected && !cache.broker2.connected) {
            els.btnConnect.disabled = false;
            els.btnConnect.innerHTML = '<i class="fa-solid fa-plug"></i> Initialize Terminals';
            els.btnDisconnect.disabled = true;
        }
    }
}

// 1. Toast Notification Helper
function showToast(title, message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    toast.innerHTML = `
        <div class="toast-header">
            <span><i class="fa-solid ${getToastIcon(type)}"></i> ${title}</span>
            <span style="font-size: 10px; opacity: 0.6; cursor: pointer;" onclick="this.closest('.toast').remove()"><i class="fa-solid fa-xmark"></i></span>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;

    container.appendChild(toast);

    // Fade in
    setTimeout(() => {
        toast.classList.add("show");
    }, 10);

    // Auto remove after 4 seconds
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 4000);
}

function getToastIcon(type) {
    switch (type) {
        case "success": return "fa-circle-check";
        case "error": return "fa-circle-xmark";
        case "warning": return "fa-circle-exclamation";
        case "info":
        default: return "fa-circle-info";
    }
}

// 2. Track order status changes to trigger toasts
function checkOrderStatusChanges(orders) {
    orders.forEach(o => {
        const prevStatus = orderStatusCache[o.id];
        if (prevStatus !== o.status) {
            orderStatusCache[o.id] = o.status;
            
            // Skip initial page load caching
            if (cache.isFirstPoll) {
                return;
            }
            
            const isDryRun = o.dry_run ? " (Dry Run)" : "";
            if (o.status === "pending") {
                showToast(`Order Placed${isDryRun}`, `Spread order #${o.id} is pending trigger.`, "info");
            } else if (o.status === "completed") {
                showToast(`Order Confirmed${isDryRun}`, `Order #${o.id} executed successfully at actual spread: ${formatVal(o.actual_spread)}`, "success");
            } else if (o.status === "failed") {
                showToast(`Order Failed${isDryRun}`, `Order #${o.id} failed: ${o.error || "Unknown error"}`, "error");
            } else if (o.status === "cancelled") {
                showToast(`Order Cancelled`, `Order #${o.id} was cancelled.`, "warning");
            }
        }
    });
    
    if (orders.length > 0) {
        cache.isFirstPoll = false;
    }
}

// 3. Render active and recent orders in UI
function renderActiveOrders(orders) {
    if (orders.length === 0) {
        els.ordersPlaceholder.classList.remove("hidden");
        els.ordersContainer.classList.add("hidden");
        return;
    }
    
    els.ordersPlaceholder.classList.add("hidden");
    els.ordersContainer.classList.remove("hidden");
    els.ordersContainer.innerHTML = "";
    
    // Sort orders: pending/executing first, then others by creation order (newer first)
    const sorted = [...orders].sort((a, b) => {
        const aActive = (a.status === "pending" || a.status === "executing");
        const bActive = (b.status === "pending" || b.status === "executing");
        if (aActive && !bActive) return -1;
        if (!aActive && bActive) return 1;
        return 0; 
    });
    
    // Limit to latest 8 orders
    const recentOrders = sorted.slice(0, 8);
    
    recentOrders.forEach(o => {
        const div = document.createElement("div");
        div.className = `order-item-card ${o.status}`;
        
        let statusBadgeClass = o.status;
        let statusText = o.status;
        let actionContent = "";
        
        if (o.status === "pending") {
            statusBadgeClass = "pending";
            statusText = "pending";
            actionContent = `<button class="btn btn-secondary btn-icon" onclick="cancelOrder('${o.id}')" title="Cancel order"><i class="fa-solid fa-times"></i></button>`;
        } else if (o.status === "executing") {
            statusBadgeClass = "executing";
            statusText = "executing";
            actionContent = `<i class="fa-solid fa-spinner fa-spin text-accent"></i>`;
        } else if (o.status === "completed") {
            statusBadgeClass = "completed";
            statusText = o.dry_run ? "confirmed (dry)" : "confirmed";
            actionContent = `<i class="fa-solid fa-circle-check text-success" style="font-size: 16px;"></i>`;
        } else if (o.status === "failed") {
            statusBadgeClass = "failed";
            statusText = "failed";
            actionContent = `<i class="fa-solid fa-circle-xmark text-danger" style="font-size: 16px;" title="${o.error || ''}"></i>`;
        } else if (o.status === "cancelled") {
            statusBadgeClass = "cancelled";
            statusText = "cancelled";
            actionContent = `<i class="fa-solid fa-ban text-muted" style="font-size: 16px;"></i>`;
        }
        
        const modeBadge = o.dry_run ? `<span class="badge badge-dry-run">Dry Run</span>` : `<span class="badge badge-live">Live</span>`;
        
        let fillInfo = "";
        if (o.status === "completed" && o.actual_spread !== undefined) {
            fillInfo = `<div class="order-item-fill">Achieved: <span class="font-mono text-success">${formatVal(o.actual_spread)}</span></div>`;
        } else if (o.status === "failed" && o.error) {
            fillInfo = `<div class="order-item-error" title="${o.error}">Error: ${o.error.substring(0, 45)}${o.error.length > 45 ? '...' : ''}</div>`;
        }
        
        div.innerHTML = `
            <div class="order-item-info">
                <div class="order-item-meta">
                    <span class="order-badge ${o.direction}">${o.direction} spread</span>
                    <span class="order-id-label">#${o.id}</span>
                    <span class="status-badge ${statusBadgeClass}">${statusText}</span>
                    ${modeBadge}
                </div>
                <div class="order-item-price">
                    Target: <span class="font-mono">${formatVal(o.target_spread)}</span>
                </div>
                <div class="order-item-vols">
                    ${o.symbol1}: ${o.volume1} lot | ${o.symbol2}: ${o.volume2} lot
                </div>
                ${fillInfo}
            </div>
            <div class="order-status-wrapper">
                ${actionContent}
            </div>
        `;
        els.ordersContainer.appendChild(div);
    });
}

async function cancelOrder(orderId) {
    try {
        const res = await fetch("/api/order/cancel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order_id: orderId })
        });
        if (res.ok) {
            console.log(`Cancelled order ${orderId}`);
        }
    } catch (e) {
        console.error("Error cancelling order", e);
    }
}
// Expose cancelOrder to global context so inline onclick triggers correctly
window.cancelOrder = cancelOrder;

function renderLogs(logs) {
    // Only update if there are new logs
    if (logs.length === cache.logsCount) return;
    
    els.logTerminal.innerHTML = "";
    logs.forEach(log => {
        const div = document.createElement("div");
        div.className = "log-entry";
        
        // Inline keyword styling matches (standard CSS classes handle colors)
        let text = log;
        
        if (log.includes("[ORDER COMPLETED]") || log.includes("[DRY RUN COMPLETED]")) {
            div.style.color = "var(--color-success)";
        } else if (log.includes("[ORDER FAILED]") || log.includes("WARNING") || log.includes("Error")) {
            div.style.color = "var(--color-danger)";
        } else if (log.includes("[ORDER PLACED]") || log.includes("[TRIGGERED]")) {
            div.style.color = "var(--color-accent)";
        } else if (log.includes("Initialized successfully")) {
            div.style.color = "var(--color-success)";
        }
        
        div.textContent = text;
        els.logTerminal.appendChild(div);
    });
    
    cache.logsCount = logs.length;
    els.logTerminal.scrollTop = els.logTerminal.scrollHeight;
}

// 8. Place limit order form handling
async function submitOrder() {
    const data = {
        direction: cache.activeDirection,
        volume1: els.orderVol1.value,
        volume2: els.orderVol2.value,
        target_spread: els.orderTarget.value,
        dry_run: els.orderDryRun.checked
    };
    
    if (!data.target_spread) {
        alert("Please enter a target spread value.");
        return;
    }
    
    try {
        const res = await fetch("/api/order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        
        if (res.ok) {
            els.orderTarget.value = "";
        } else {
            const err = await res.json();
            alert("Failed to place order: " + err.message);
        }
    } catch (e) {
        alert("Network error: " + e.message);
    }
}

// Event Listeners
function setupEventListeners() {
    els.btnConnect.addEventListener("click", initializeTerminals);
    els.btnDisconnect.addEventListener("click", disconnectTerminals);
    
    // Auto-populate default paths based on account selections
    els.b1Account.addEventListener("change", () => {
        const val = els.b1Account.value;
        if (val === "mock") {
            els.b1Path.value = "MOCK";
        } else if (val === "mts" || val === "acc3") {
            els.b1Path.value = "C:\\MT5_Broker2\\terminal64.exe";
        } else if (val === "vantage") {
            els.b1Path.value = "C:\\MT5_Broker1\\terminal64.exe";
        }
    });

    els.b2Account.addEventListener("change", () => {
        const val = els.b2Account.value;
        if (val === "mock") {
            els.b2Path.value = "MOCK";
        } else if (val === "mts" || val === "acc3") {
            els.b2Path.value = "C:\\MT5_Broker2\\terminal64.exe";
        } else if (val === "vantage") {
            els.b2Path.value = "C:\\MT5_Broker1\\terminal64.exe";
        }
    });
    
    els.btnSaveConfig.addEventListener("click", async () => {
        const config = getFormConfig();
        try {
            const res = await fetch("/api/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ config })
            });
            if (res.ok) {
                alert("Broker configurations saved successfully!");
            } else {
                alert("Failed to save configuration.");
            }
        } catch (e) {
            alert("Network error: " + e.message);
        }
    });

    els.dirBuy.addEventListener("click", () => {
        els.dirBuy.classList.add("active");
        els.dirSell.classList.remove("active");
        cache.activeDirection = "buy";
    });

    els.dirSell.addEventListener("click", () => {
        els.dirSell.classList.add("active");
        els.dirBuy.classList.remove("active");
        cache.activeDirection = "sell";
    });

    els.btnSubmitOrder.addEventListener("click", submitOrder);
    
    els.orderTarget.addEventListener("input", () => {
        const connectedBoth = cache.broker1.connected && cache.broker2.connected;
        const symbolsSelected = els.symbol1.value !== "" && els.symbol2.value !== "";
        els.btnSubmitOrder.disabled = !(connectedBoth && symbolsSelected && els.orderTarget.value !== "");
    });
    
    els.btnClearLogs.addEventListener("click", () => {
        // Just clear UI display
        els.logTerminal.innerHTML = "";
        cache.logsCount = 0;
    });

    els.btnApplyRec.addEventListener("click", () => {
        if (cache.recommendation) {
            els.orderVol1.value = cache.recommendation.vol1;
            els.orderVol2.value = cache.recommendation.vol2;
        }
    });

    if (els.btnSaveFavorite) {
        els.btnSaveFavorite.addEventListener("click", saveFavorite);
    }
    if (els.btnRefreshHistory) {
        els.btnRefreshHistory.addEventListener("click", loadHistoryStats);
    }

    // Set up autocomplete
    setupAutocomplete(els.symbol1, els.s1Recs, "broker1");
    setupAutocomplete(els.symbol2, els.s2Recs, "broker2");
}

// Initialization on load
document.addEventListener("DOMContentLoaded", async () => {
    await loadAccounts();
    await loadConfig();
    setupEventListeners();
    loadFavorites(); // Load saved favorites on startup
    
    // Start Polling Loop (every 1 second)
    setInterval(pollData, 1000);
});

// Favorites & History Management Functions
async function loadFavorites() {
    try {
        const res = await fetch("/api/favorites");
        if (res.ok) {
            const favs = await res.json();
            renderFavorites(favs);
        }
    } catch (e) {
        console.error("Failed to load favorites", e);
    }
}

function renderFavorites(favs) {
    if (!els.favoritesList) return;
    
    if (favs.length === 0) {
        els.favoritesList.innerHTML = '<div class="favorites-empty">No favorites saved yet.</div>';
        return;
    }
    
    els.favoritesList.innerHTML = "";
    favs.forEach(fav => {
        const div = document.createElement("div");
        div.className = "favorite-item";
        
        div.addEventListener("click", (e) => {
            if (e.target.closest(".btn-delete-favorite")) return;
            loadFavoritePair(fav);
        });
        
        div.innerHTML = `
            <div class="favorite-info">
                <div class="favorite-title">${fav.name}</div>
                <div class="favorite-subtitle">${fav.broker1.symbol} (${fav.broker1.accountId}) ↔ ${fav.broker2.symbol} (${fav.broker2.accountId})</div>
            </div>
            <div class="favorite-actions">
                <button class="btn-delete-favorite" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
            </div>
        `;
        
        div.querySelector(".btn-delete-favorite").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteFavorite(fav.id);
        });
        
        els.favoritesList.appendChild(div);
    });
}

async function saveFavorite() {
    const s1 = els.symbol1.value;
    const s2 = els.symbol2.value;
    if (!s1 || !s2) {
        alert("Please select symbols for both brokers first.");
        return;
    }
    
    const defaultName = `${s1} vs ${s2}`;
    const name = prompt("Enter a name for this favorite spread pair:", defaultName);
    if (name === null) return;
    
    const finalName = name.trim() || defaultName;
    
    const data = {
        name: finalName,
        broker1: {
            path: els.b1Path.value,
            accountId: els.b1Account.value,
            symbol: s1
        },
        broker2: {
            path: els.b2Path.value,
            accountId: els.b2Account.value,
            symbol: s2
        }
    };
    
    try {
        const res = await fetch("/api/favorites/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            alert("Spread pair saved to favorites!");
            loadFavorites();
        } else {
            const err = await res.json();
            alert("Failed to save favorite: " + err.message);
        }
    } catch (e) {
        alert("Error saving favorite: " + e.message);
    }
}

async function deleteFavorite(id) {
    if (!confirm("Are you sure you want to delete this favorite?")) return;
    
    try {
        const res = await fetch("/api/favorites/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id })
        });
        if (res.ok) {
            loadFavorites();
        }
    } catch (e) {
        console.error("Failed to delete favorite", e);
    }
}

async function loadFavoritePair(fav) {
    console.log("Loading favorite pair:", fav);
    
    // Set UI inputs
    els.b1Path.value = fav.broker1.path;
    els.b1Account.value = fav.broker1.accountId;
    els.b2Path.value = fav.broker2.path;
    els.b2Account.value = fav.broker2.accountId;
    
    // Connect terminals
    await initializeTerminals();
    
    // Polling check loop
    const maxAttempts = 15;
    let attempts = 0;
    
    const checkInterval = setInterval(async () => {
        attempts++;
        if (cache.broker1.connected && cache.broker2.connected) {
            clearInterval(checkInterval);
            console.log("Both terminals connected! Subscribing to favorite symbols...");
            
            els.symbol1.value = fav.broker1.symbol;
            els.symbol2.value = fav.broker2.symbol;
            
            await subscribeSymbol("broker1", fav.broker1.symbol);
            await subscribeSymbol("broker2", fav.broker2.symbol);
            
            loadHistoryStats();
        } else if (attempts >= maxAttempts) {
            clearInterval(checkInterval);
            console.warn("Connection timeout while loading favorite.");
        }
    }, 1000);
}

async function loadHistoryStats() {
    const s1 = els.symbol1.value;
    const s2 = els.symbol2.value;
    if (!s1 || !s2) return;
    
    if (els.btnRefreshHistory) {
        els.btnRefreshHistory.disabled = true;
        els.btnRefreshHistory.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    }
    
    try {
        const res = await fetch(`/api/history?symbol1=${encodeURIComponent(s1)}&symbol2=${encodeURIComponent(s2)}&_t=${Date.now()}`);
        if (res.ok) {
            const data = await res.json();
            if (data.status === "ok") {
                if (data.stats) {
                    renderHistoryStats(data.stats);
                }
                if (data.chart_data) {
                    // DEBUG: check if fair_value is present
                    const hasFvDebug = data.chart_data.some(p => p.fair_value !== undefined);
                    console.log(`[FV Debug] symbol1=${s1} symbol2=${s2} points=${data.chart_data.length} has_fv=${hasFvDebug}`, data.chart_data[data.chart_data.length-1]);
                    renderSpreadChart(data.chart_data);
                }
            }
        }
    } catch (e) {
        console.error("Failed to load historical spread stats", e);
    } finally {
        if (els.btnRefreshHistory) {
            els.btnRefreshHistory.disabled = false;
            els.btnRefreshHistory.innerHTML = '<i class="fa-solid fa-rotate"></i>';
        }
    }
}

function renderHistoryStats(stats) {
    const formatValue = (val) => {
        if (val === null || val === undefined || isNaN(val)) return "-";
        return Number(val).toFixed(2);
    };
    
    if (els.hist24hBid) els.hist24hBid.textContent = formatValue(stats["24h"].best_bid);
    if (els.hist24hAsk) els.hist24hAsk.textContent = formatValue(stats["24h"].best_ask);
    if (els.hist3dBid) els.hist3dBid.textContent = formatValue(stats["3d"].best_bid);
    if (els.hist3dAsk) els.hist3dAsk.textContent = formatValue(stats["3d"].best_ask);
    if (els.hist7dBid) els.hist7dBid.textContent = formatValue(stats["7d"].best_bid);
    if (els.hist7dAsk) els.hist7dAsk.textContent = formatValue(stats["7d"].best_ask);
}

let spreadChartInstance = null;

function renderSpreadChart(chartData) {
    if (typeof Chart === 'undefined') {
        alert("Chart.js failed to load. Please check your internet connection or adblocker.");
        return;
    }

    const canvas = document.getElementById('spreadChart');
    if (!canvas) return;

    // Destroy existing chart if any
    if (spreadChartInstance) {
        spreadChartInstance.destroy();
    }

    if (!chartData || chartData.length === 0) {
        // Data not ready yet (maybe MT5 is still downloading history)
        // Let's retry after 2 seconds
        setTimeout(loadHistoryStats, 2000);
        return;
    }

    const labels = chartData.map(d => {
        const date = new Date(d.time * 1000);
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + 
               date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    });
    const dataPoints = chartData.map(d => d.mid_spread);

    const ctx = canvas.getContext('2d');
    
    // Create gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'hsla(255, 80%, 68%, 0.5)'); // --color-primary with opacity
    gradient.addColorStop(1, 'hsla(255, 80%, 68%, 0.0)');

    const chartDatasets = [{
        label: 'Mid Spread',
        data: dataPoints,
        borderColor: 'hsl(255, 80%, 68%)', // --color-primary
        backgroundColor: gradient,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.1 // slight curve
    }];

    // Check if we have historical fair value data
    const hasFv = chartData.some(d => d.fair_value !== undefined);
    if (hasFv) {
        const fvData = chartData.map(d => d.fair_value !== undefined ? d.fair_value : null);
        const labelText = els.fairValueLabel ? els.fairValueLabel.textContent : 'Fair Value';
        chartDatasets.push({
            label: labelText,
            data: fvData,
            borderColor: '#facc15', // --color-warning
            borderWidth: 1.5,
            borderDash: [5, 5],
            pointRadius: 0,
            pointHoverRadius: 0,
            fill: false
        });
    }

    const hasFvBefore = chartData.some(d => d.fair_value_before !== undefined);
    const fvBeforeFallback = cache.fvBefore;
    if (hasFvBefore || fvBeforeFallback !== null) {
        const fvBeforeData = chartData.map(d =>
            d.fair_value_before !== undefined ? d.fair_value_before : fvBeforeFallback
        );
        chartDatasets.push({
            label: 'BEFORE WAR FV',
            data: fvBeforeData,
            borderColor: '#22c55e',
            borderWidth: 1.5,
            borderDash: [5, 5],
            pointRadius: 0,
            pointHoverRadius: 0,
            fill: false
        });
    }

    spreadChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: chartDatasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: chartDatasets.length > 1,
                    labels: {
                        color: 'hsl(220, 15%, 65%)',
                        boxWidth: 20,
                        padding: 12,
                        font: { size: 11 },
                        usePointStyle: true,
                        pointStyle: 'line',
                        filter: (item) => item.text !== 'Mid Spread'
                    }
                },
                tooltip: {
                    backgroundColor: 'hsla(222, 25%, 15%, 0.9)',
                    titleColor: 'hsl(220, 20%, 92%)',
                    bodyColor: 'hsl(220, 20%, 92%)',
                    borderColor: 'hsla(255, 75%, 65%, 0.25)',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label || 'Spread';
                            return `${label}: ${context.parsed.y.toFixed(4)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'hsla(222, 25%, 22%, 0.5)',
                        drawBorder: false
                    },
                    ticks: {
                        color: 'hsl(220, 15%, 65%)',
                        maxTicksLimit: 8,
                        maxRotation: 0,
                        autoSkip: true
                    }
                },
                y: {
                    grid: {
                        color: 'hsla(222, 25%, 22%, 0.5)',
                        drawBorder: false
                    },
                    ticks: {
                        color: 'hsl(220, 15%, 65%)'
                    }
                }
            }
        }
    });
}

let lastRecommended = null;

function updateLotRecommendation() {
    const cs1 = cache.broker1.contract_size;
    const minVol1 = cache.broker1.min_volume;
    const cs2 = cache.broker2.contract_size;
    const minVol2 = cache.broker2.min_volume;
    
    if (cs1 && minVol1 && cs2 && minVol2 && cache.broker1.symbol && cache.broker2.symbol) {
        // We want: cs1 * vol1 = cs2 * vol2
        // So vol1 = vol2 * (cs2 / cs1)
        let vol2 = minVol2;
        let vol1 = vol2 * (cs2 / cs1);
        
        if (vol1 < minVol1) {
            vol1 = minVol1;
            vol2 = vol1 * (cs1 / cs2);
        }
        
        vol1 = parseFloat(vol1.toFixed(2));
        vol2 = parseFloat(vol2.toFixed(2));
        
        cache.recommendation = { vol1, vol2 };
        els.lotRecText.textContent = `Recommended hedge lots: ${vol1} lot (Broker 1) & ${vol2} lot (Broker 2) | Contract ratio: ${cs1} to ${cs2} oz.`;
        els.lotRecContainer.classList.remove("hidden");
        
        // Auto-fill inputs if this is a new recommendation (e.g. first time symbols connected or symbols changed)
        const currentRecKey = `${cache.broker1.symbol}:${vol1}-${cache.broker2.symbol}:${vol2}`;
        if (lastRecommended !== currentRecKey) {
            els.orderVol1.value = vol1;
            els.orderVol2.value = vol2;
            lastRecommended = currentRecKey;
        }
    } else {
        cache.recommendation = null;
        els.lotRecContainer.classList.add("hidden");
        lastRecommended = null;
    }
}

// -------------------------------------------------------------
// Market Session Modal & Button Visibility Helper
// -------------------------------------------------------------
function updateSessionButtonVisibility(brokerKey, sessions) {
    const btn = document.getElementById(`${brokerKey === 'broker1' ? 'b1' : 'b2'}-session-btn`);
    if (btn) {
        if (sessions && Object.keys(sessions).length > 0) {
            btn.style.display = "block";
        } else {
            btn.style.display = "none";
        }
    }
}

const sessionModal = document.getElementById("session-modal");
const sessionModalSymbol = document.getElementById("session-modal-symbol");
const sessionModalBroker = document.getElementById("session-modal-broker");
const sessionModalBody = document.getElementById("session-modal-body");
const closeSessionModal = document.getElementById("close-session-modal");

function showSessionsModal(brokerKey) {
    const brokerName = brokerKey === "broker1" ? "Broker 1" : "Broker 2";
    const symbol = cache[brokerKey].symbol || "-";
    const sessions = cache[brokerKey].sessions;
    const brokerOffset = cache[brokerKey].timezone_offset;
    
    if (!sessions || Object.keys(sessions).length === 0) return;
    
    sessionModalSymbol.textContent = symbol;
    
    // Get local timezone details
    const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offsetMinutes = -new Date().getTimezoneOffset();
    const offsetHours = offsetMinutes / 60;
    const gmtStr = `GMT${offsetHours >= 0 ? '+' : ''}${offsetHours}`;
    
    sessionModalBroker.innerHTML = `${brokerName} &nbsp;|&nbsp; <span style="color: var(--accent); font-weight: 500;"><i class="fa-solid fa-earth-asia"></i> Local Time (${tzName}, ${gmtStr})</span>`;
    
    // Calculate conversion shift
    const localOffsetSeconds = offsetMinutes * 60;
    // Default to 0 shift if broker timezone offset is not available yet
    const shift = (brokerOffset !== undefined && brokerOffset !== null) ? (localOffsetSeconds - brokerOffset) : 0;
    
    const wdayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    let bodyHtml = "";
    
    Object.keys(sessions).sort((a,b) => parseInt(a) - parseInt(b)).forEach(wdayStr => {
        const wdayIdx = parseInt(wdayStr);
        const dayName = wdayNames[wdayIdx] || `Day ${wdayStr}`;
        const intervals = sessions[wdayStr];
        
        intervals.forEach(interval => {
            const [minT, maxT] = interval;
            let openWday = wdayIdx;
            let closeWday = wdayIdx;
            
            let openSecs = minT + shift;
            if (openSecs < 0) {
                openSecs += 86400;
                openWday = (openWday - 1 + 7) % 7;
            } else if (openSecs >= 86400) {
                openSecs -= 86400;
                openWday = (openWday + 1) % 7;
            }
            
            let closeSecs = maxT + shift;
            if (closeSecs < 0) {
                closeSecs += 86400;
                closeWday = (closeWday - 1 + 7) % 7;
            } else if (closeSecs >= 86400) {
                closeSecs -= 86400;
                closeWday = (closeWday + 1) % 7;
            }
            
            const formatTime = (sec) => {
                const h = Math.floor(sec / 3600);
                const m = Math.floor((sec % 3600) / 60);
                return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
            };
            
            const openStr = formatTime(openSecs);
            const closeStr = formatTime(closeSecs);
            
            const safeOpenStr = formatTime((openSecs + 300) % 86400);
            const safeCloseStr = formatTime((closeSecs - 300 + 86400) % 86400);
            
            let rangeStr = `${openStr} - ${closeStr}`;
            let safeRangeStr = `Safe: ${safeOpenStr} - ${safeCloseStr}`;
            
            if (openWday !== closeWday) {
                const closeDayShort = wdayNames[closeWday].substring(0, 3);
                rangeStr = `${openStr} - ${closeDayShort} ${closeStr}`;
                
                let safeCloseWday = closeWday;
                if (closeSecs - 300 < 0) {
                    safeCloseWday = (safeCloseWday - 1 + 7) % 7;
                }
                const safeCloseDayShort = wdayNames[safeCloseWday].substring(0, 3);
                safeRangeStr = `Safe: ${safeOpenStr} - ${safeCloseDayShort} ${safeCloseStr}`;
            }
            
            const localDayName = wdayNames[openWday];
            
            bodyHtml += `<div style="display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px;">
                <span style="font-weight: bold; color: var(--accent); width: 85px; display: inline-block;">${localDayName}</span>
                <span style="color: #fff; font-weight: 500;">${rangeStr}</span>
                <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 10px;">(${safeRangeStr})</span>
            </div>`;
        });
    });
    
    sessionModalBody.innerHTML = bodyHtml || "No trading session data available.";
    sessionModal.style.display = "block";
}

// Bind clicks
document.getElementById("b1-session-btn").addEventListener("click", () => showSessionsModal("broker1"));
document.getElementById("b2-session-btn").addEventListener("click", () => showSessionsModal("broker2"));
const combinedBtn = document.getElementById("combined-session-btn");
if (combinedBtn) {
    combinedBtn.addEventListener("click", showCombinedSessionsModal);
}
if (closeSessionModal) {
    closeSessionModal.addEventListener("click", () => {
        sessionModal.style.display = "none";
    });
}
window.addEventListener("click", (e) => {
    if (e.target === sessionModal) {
        sessionModal.style.display = "none";
    }
});

function updateCombinedSessionButtonVisibility() {
    const btn = document.getElementById("combined-session-btn");
    if (btn) {
        const b1Sessions = cache.broker1.sessions;
        const b2Sessions = cache.broker2.sessions;
        if (b1Sessions && Object.keys(b1Sessions).length > 0 && b2Sessions && Object.keys(b2Sessions).length > 0) {
            btn.style.display = "flex";
        } else {
            btn.style.display = "none";
        }
    }
}

function getBrokerLocalIntervals(brokerKey) {
    const intervals = { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [] };
    const b = cache[brokerKey];
    if (!b || !b.sessions) return intervals;
    
    const offsetMinutes = -new Date().getTimezoneOffset();
    const localOffsetSeconds = offsetMinutes * 60;
    
    const brokerOffset = b.timezone_offset;
    const shift = (brokerOffset !== undefined && brokerOffset !== null) ? (localOffsetSeconds - brokerOffset) : 0;
    
    const addInterval = (start, end) => {
        const daySize = 86400;
        let s = start;
        let e = end;
        while (s < e) {
            const dayIdx = Math.floor(s / daySize) % 7;
            const dayStart = Math.floor(s / daySize) * daySize;
            const dayEnd = dayStart + daySize;
            const chunkEnd = Math.min(e, dayEnd);
            
            intervals[dayIdx].push([s - dayStart, chunkEnd - dayStart]);
            s = chunkEnd;
        }
    };
    
    Object.keys(b.sessions).forEach(wdayStr => {
        const wdayIdx = parseInt(wdayStr);
        const intervalsList = b.sessions[wdayStr];
        
        intervalsList.forEach(interval => {
            const [minT, maxT] = interval;
            
            let openSecs = minT + shift;
            let closeSecs = maxT + shift;
            
            let start = wdayIdx * 86400 + openSecs;
            let end = wdayIdx * 86400 + closeSecs;
            
            const totalWeek = 7 * 86400;
            start = (start % totalWeek + totalWeek) % totalWeek;
            end = start + (closeSecs - openSecs);
            
            if (end > totalWeek) {
                addInterval(start, totalWeek);
                addInterval(0, end - totalWeek);
            } else {
                addInterval(start, end);
            }
        });
    });
    
    for (let d = 0; d < 7; d++) {
        intervals[d].sort((a, b) => a[0] - b[0]);
    }
    
    return intervals;
}

function showCombinedSessionsModal() {
    const symbol1 = cache.broker1.symbol || "-";
    const symbol2 = cache.broker2.symbol || "-";
    
    sessionModalSymbol.textContent = `${symbol1} & ${symbol2}`;
    
    const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offsetMinutes = -new Date().getTimezoneOffset();
    const offsetHours = offsetMinutes / 60;
    const gmtStr = `GMT${offsetHours >= 0 ? '+' : ''}${offsetHours}`;
    
    sessionModalBroker.innerHTML = `<span style="color: var(--accent); font-weight: 500;"><i class="fa-solid fa-clock"></i> Combined Safe Trading Window (${tzName}, ${gmtStr})</span>`;
    
    const b1Intervals = getBrokerLocalIntervals("broker1");
    const b2Intervals = getBrokerLocalIntervals("broker2");
    
    const wdayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    let bodyHtml = "";
    
    for (let wdayIdx = 0; wdayIdx < 7; wdayIdx++) {
        const list1 = b1Intervals[wdayIdx] || [];
        const list2 = b2Intervals[wdayIdx] || [];
        
        const overlaps = [];
        list1.forEach(i1 => {
            list2.forEach(i2 => {
                const start = Math.max(i1[0], i2[0]);
                const end = Math.min(i1[1], i2[1]);
                if (start < end) {
                    overlaps.push([start, end]);
                }
            });
        });
        
        overlaps.sort((a, b) => a[0] - b[0]);
        const dayName = wdayNames[wdayIdx];
        
        if (overlaps.length === 0) {
            bodyHtml += `<div style="display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px;">
                <span style="font-weight: bold; color: var(--text-muted); width: 85px; display: inline-block;">${dayName}</span>
                <span style="color: var(--text-muted);">No Overlap (No Trading)</span>
            </div>`;
        } else {
            const formatTime = (sec) => {
                const h = Math.floor(sec / 3600);
                const m = Math.floor((sec % 3600) / 60);
                return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
            };
            
            overlaps.forEach(interval => {
                const openSecs = interval[0];
                const closeSecs = interval[1];
                
                const openStr = formatTime(openSecs);
                const closeStr = formatTime(closeSecs);
                
                const safeOpenSecs = openSecs + 300;
                const safeCloseSecs = closeSecs - 300;
                
                let rangeStr = `${openStr} - ${closeStr}`;
                let safeRangeStr = "";
                
                if (safeOpenSecs < safeCloseSecs) {
                    const safeOpenStr = formatTime(safeOpenSecs);
                    const safeCloseStr = formatTime(safeCloseSecs);
                    safeRangeStr = `Safe: ${safeOpenStr} - ${safeCloseStr}`;
                } else {
                    safeRangeStr = "Safe: No safe window";
                }
                
                bodyHtml += `<div style="display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px;">
                    <span style="font-weight: bold; color: var(--accent); width: 85px; display: inline-block;">${dayName}</span>
                    <span style="color: #fff; font-weight: 500;">${rangeStr}</span>
                    <span style="color: var(--text-muted); font-size: 0.8rem; margin-left: 10px;">(${safeRangeStr})</span>
                </div>`;
            });
        }
    }
    
    sessionModalBody.innerHTML = bodyHtml || "No trading session data available.";
    sessionModal.style.display = "block";
}
