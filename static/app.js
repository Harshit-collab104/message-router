// app.js - RAG Router Developer Control Console JS

// State Management
let users = [];
let contacts = [];
let logs = [];
let incomingQueue = [];
let selectedUserId = null;
let activeTab = "inbox"; // inbox, digest, quarantine
let mockDeviceData = { inbox: [], digest: [], quarantine: [] };
let selectedMessageMedia = null;

// DOM Elements
const recipientSelect = document.getElementById("payload-recipient");
const incomingQueueSelect = document.getElementById("incoming-queue");
const conversationSelect = document.getElementById("payload-conversation");
const groupSelectContainer = document.getElementById("group-select-container");
const businessSelectContainer = document.getElementById("business-select-container");
const senderSelectContainer = document.getElementById("sender-select-container");

const groupSelect = document.getElementById("payload-group");
const businessSelect = document.getElementById("payload-business");
const senderSelect = document.getElementById("payload-sender");
const messageText = document.getElementById("payload-text");
const sendBtn = document.getElementById("send-webhook-btn");

const logsFeed = document.getElementById("logs-feed");
const avgLatencyEl = document.getElementById("avg-latency");
const blockedRateEl = document.getElementById("blocked-rate");

// Config Elements
const configModel = document.getElementById("config-model");
const configThreshold = document.getElementById("config-threshold");
const thresholdVal = document.getElementById("threshold-val");
const configDnd = document.getElementById("config-dnd");
const saveConfigBtn = document.getElementById("save-config-btn");

// Phone Mockup Elements
const deviceName = document.getElementById("recipient-device-name");
const deviceDnd = document.getElementById("recipient-device-dnd");
const deviceMessages = document.getElementById("device-messages");
const deviceTime = document.getElementById("device-header-time");
const tabInboxBadge = document.getElementById("badge-inbox");
const tabDigestBadge = document.getElementById("badge-digest");
const tabQuarantineBadge = document.getElementById("badge-quarantine");

// Modal Elements
const modal = document.getElementById("inspector-modal");
const closeModalBtn = document.getElementById("close-modal");

// ----------------- INITIALIZATION -----------------

document.addEventListener("DOMContentLoaded", async () => {
    updateClock();
    setInterval(updateClock, 60000);
    
    await fetchConfig();
    await fetchUsers();
    await fetchLogs();
    
    // No automatic polling to prevent server/UI lagging
    
    setupEventListeners();
});

function updateClock() {
    const now = new Date();
    const hrs = String(now.getHours()).padStart(2, '0');
    const mins = String(now.getMinutes()).padStart(2, '0');
    deviceTime.textContent = `${hrs}:${mins}`;
}

// ----------------- CONFIG & APIS -----------------

async function fetchConfig() {
    try {
        const response = await fetch("/api/gateway/config");
        if (response.ok) {
            const config = await response.json();
            configModel.value = config.active_model;
            configThreshold.value = config.l2_distance_threshold;
            thresholdVal.textContent = config.l2_distance_threshold;
            configDnd.checked = config.dnd_enabled;
        }
    } catch (e) {
        console.error("Error loading config:", e);
    }
}

async function updateConfig() {
    const payload = {
        active_model: configModel.value,
        l2_distance_threshold: parseFloat(configThreshold.value),
        dnd_enabled: configDnd.checked
    };
    try {
        const response = await fetch("/api/gateway/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            alert("Gateway routing configuration applied successfully!");
            await fetchConfig();
        } else {
            const err = await response.json();
            alert(`Error applying config: ${err.detail}`);
        }
    } catch (e) {
        alert("Failed to communicate with gateway config API.");
    }
}

async function fetchUsers() {
    try {
        const response = await fetch("/api/users");
        if (response.ok) {
            users = await response.json();
            populateRecipientOptions();
            if (users.length > 0) {
                selectRecipient(users[0].user_id);
            }
        }
    } catch (e) {
        console.error("Error loading users:", e);
    }
}

async function selectRecipient(userId) {
    selectedUserId = userId;
    recipientSelect.value = userId;
    
    const user = users.find(u => u.user_id === userId);
    if (user) {
        deviceName.textContent = user.user_name || `User ${userId}`;
        deviceDnd.textContent = `DND: ${user.do_not_disturb_window || "None"}`;
    }
    
    await fetchContacts(userId);
    await fetchIncomingQueue(userId);
    await fetchDeviceMessages(userId);
}

async function fetchIncomingQueue(userId) {
    try {
        const response = await fetch(`/api/incoming/${userId}`);
        if (response.ok) {
            incomingQueue = await response.json();
            populateIncomingQueue();
        }
    } catch (e) {
        console.error("Error loading incoming queue:", e);
    }
}

function populateIncomingQueue() {
    incomingQueueSelect.innerHTML = '<option value="">-- Choose message to load --</option>';
    incomingQueue.forEach((msg) => {
        const opt = document.createElement("option");
        opt.value = msg.message_id;
        const textPreview = msg.message_text ? (msg.message_text.length > 50 ? msg.message_text.substring(0, 50) + "..." : msg.message_text) : `[Media: ${msg.media_type}]`;
        opt.textContent = `[${msg.conversation_type.toUpperCase()}] ${textPreview}`;
        incomingQueueSelect.appendChild(opt);
    });
}

async function fetchContacts(userId) {
    try {
        const response = await fetch(`/api/contacts/${userId}`);
        if (response.ok) {
            contacts = await response.json();
            populateSandboxDropdowns();
        }
    } catch (e) {
        console.error("Error loading user contacts:", e);
    }
}

async function fetchDeviceMessages(userId) {
    try {
        const response = await fetch(`/api/client/device/${userId}`);
        if (response.ok) {
            mockDeviceData = await response.json();
            renderDeviceMessages();
        }
    } catch (e) {
        console.error("Error loading device messages:", e);
    }
}

async function fetchLogs() {
    try {
        const response = await fetch("/api/gateway/logs");
        if (response.ok) {
            logs = await response.json();
            renderLogs();
            computeMetrics();
        }
    } catch (e) {
        console.error("Error loading gateway logs:", e);
    }
}

// ----------------- DOM RENDERING -----------------

function populateRecipientOptions() {
    recipientSelect.innerHTML = "";
    users.forEach(user => {
        const option = document.createElement("option");
        option.value = user.user_id;
        const name = user.user_name ? user.user_name : `User ${user.user_id}`;
        option.textContent = `${name} (${user.user_id})`;
        recipientSelect.appendChild(option);
    });
}

function populateSandboxDropdowns() {
    groupSelect.innerHTML = "";
    businessSelect.innerHTML = "";
    senderSelect.innerHTML = "";
    
    // Sort contacts by type
    const pContacts = contacts.filter(c => c.type === 'personal');
    const gContacts = contacts.filter(c => c.type === 'group');
    const bContacts = contacts.filter(c => c.type === 'business');
    
    pContacts.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.name} (${c.id})`;
        senderSelect.appendChild(opt);
    });
    
    gContacts.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.name} (${c.id})`;
        groupSelect.appendChild(opt);
    });
    
    bContacts.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.name} (${c.id})`;
        businessSelect.appendChild(opt);
    });
    
    // Fallback if empty
    if (senderSelect.innerHTML === "") {
        senderSelect.innerHTML = `<option value="u_test_sender">Test Sender (u_test_sender)</option>`;
    }
    if (groupSelect.innerHTML === "") {
        groupSelect.innerHTML = `<option value="group_test">Test Group (group_test)</option>`;
    }
    if (businessSelect.innerHTML === "") {
        businessSelect.innerHTML = `<option value="biz_test">Test Business (biz_test)</option>`;
    }
}

function renderLogs() {
    if (logs.length === 0) {
        logsFeed.innerHTML = `
            <div class="empty-state">
                <p>No traffic intercepted yet. POST a payload using the sandbox to start logging.</p>
            </div>
        `;
        return;
    }
    
    logsFeed.innerHTML = "";
    logs.forEach(log => {
        const logCard = document.createElement("div");
        logCard.className = "log-card";
        logCard.addEventListener("click", () => showInspector(log));
        
        const timestamp = log.timestamp.split(" ")[1] || log.timestamp;
        
        logCard.innerHTML = `
            <div class="log-header">
                <div class="log-meta">
                    <span class="timestamp">${timestamp}</span>
                    <span class="latency ${getLatencyClass(log.latency_ms)}">${log.latency_ms.toFixed(1)} ms</span>
                </div>
                <span class="log-action-badge ${log.action}">${log.action}</span>
            </div>
            <div class="log-body">
                <strong>${log.conversation_type.toUpperCase()} / ${getSenderLabel(log)}:</strong> 
                ${escapeHTML(log.message_text || "[Media Message]")}
            </div>
            <div class="log-footer">
                <span class="log-reason">${escapeHTML(log.reason)}</span>
                <span class="log-model">${log.message_type_pred.toUpperCase()}</span>
            </div>
        `;
        logsFeed.appendChild(logCard);
    });
}

function renderDeviceMessages() {
    deviceMessages.innerHTML = "";
    
    const messagesToRender = mockDeviceData[activeTab] || [];
    
    tabInboxBadge.textContent = mockDeviceData.inbox.length;
    tabDigestBadge.textContent = mockDeviceData.digest.length;
    tabQuarantineBadge.textContent = mockDeviceData.quarantine.length;
    
    if (messagesToRender.length === 0) {
        deviceMessages.innerHTML = `<p class="device-empty-state">No messages categorized under ${activeTab}.</p>`;
        return;
    }
    
    messagesToRender.forEach(msg => {
        const bubble = document.createElement("div");
        bubble.className = `device-msg-bubble incoming delivered-${msg.action}`;
        
        let mediaHtml = "";
        if (msg.media_type === "image") {
            mediaHtml = `<div style="margin-bottom:0.4rem; border-radius:6px; overflow:hidden; background-color:#000; height:100px; display:flex; align-items:center; justify-content:center; color:#fff; font-size:0.65rem;">[Media Poster Preview]</div>`;
        } else if (msg.media_type === "voice") {
            mediaHtml = `<div style="margin-bottom:0.4rem; padding:0.3rem; border-radius:4px; background:#0F172A; display:flex; align-items:center; gap:0.5rem; font-size:0.65rem; color:#60A5FA;">🎙️ Voice Note Recording</div>`;
        }

        let senderNameHtml = "";
        if (msg.conversation_type === "group") {
            // WhatsApp style color hash
            const colors = ["#25D366", "#34B7F1", "#FF8A00", "#E53E3E", "#9F7AEA", "#319795", "#38A169"];
            let hash = 0;
            const senderStr = msg.sender_user_id || msg.sender || "Unknown";
            for (let i = 0; i < senderStr.length; i++) {
                hash = senderStr.charCodeAt(i) + ((hash << 5) - hash);
            }
            const color = colors[Math.abs(hash) % colors.length];
            senderNameHtml = `<div class="device-msg-group-sender" style="color: ${color}; font-weight: 700; font-size: 0.72rem; margin-bottom: 2px;">~${escapeHTML(senderStr)}</div>`;
        } else if (msg.conversation_type === "business") {
            senderNameHtml = `<div class="device-msg-group-sender" style="color: #60A5FA; font-weight: 700; font-size: 0.72rem; margin-bottom: 2px;">${escapeHTML(msg.sender)}</div>`;
        }

        bubble.innerHTML = `
            ${senderNameHtml}
            ${mediaHtml}
            <div style="word-break: break-word;">${escapeHTML(msg.text || "")}</div>
            <div class="device-msg-meta">
                <span>${msg.timestamp}</span>
            </div>
        `;
        deviceMessages.appendChild(bubble);
    });
}

function computeMetrics() {
    if (logs.length === 0) {
        avgLatencyEl.textContent = "0.0 ms";
        blockedRateEl.textContent = "0%";
        return;
    }
    
    const totalLatency = logs.reduce((sum, log) => sum + log.latency_ms, 0);
    const avgLatency = totalLatency / logs.length;
    avgLatencyEl.textContent = `${avgLatency.toFixed(1)} ms`;
    
    const blockedCount = logs.filter(log => log.action === 'mute').length;
    const blockedRate = (blockedCount / logs.length) * 100;
    blockedRateEl.textContent = `${blockedRate.toFixed(0)}%`;
}

// ----------------- ACTIONS & SIMULATION -----------------

async function sendWebhookPayload() {
    const recipientId = recipientSelect.value;
    const conversationType = conversationSelect.value;
    const text = messageText.value.trim();
    
    if (!recipientId) {
        alert("Please select a target recipient user.");
        return;
    }
    
    let groupId = "none";
    let businessId = "none";
    let senderId = "none";
    
    if (conversationType === 'group') {
        groupId = groupSelect.value;
        senderId = senderSelect.value;
    } else if (conversationType === 'business') {
        businessId = businessSelect.value;
    } else {
        senderId = senderSelect.value;
    }
    
    // Generate mock message ID
    const randomHex = Math.floor(Math.random()*16777215).toString(16);
    const messageId = selectedMessageMedia && selectedMessageMedia.message_id ? `${selectedMessageMedia.message_id}_w` : `msg_web_${randomHex}`;
    
    const payload = {
        message_id: messageId,
        user_id: recipientId,
        conversation_type: conversationType,
        sender_user_id: senderId,
        group_id: groupId,
        business_id: businessId,
        message_text: text,
        media_type: selectedMessageMedia ? selectedMessageMedia.media_type : null,
        media_id: selectedMessageMedia ? selectedMessageMedia.media_id : null,
        forwarded_count: selectedMessageMedia ? selectedMessageMedia.forwarded_count : 0
    };
    
    sendBtn.disabled = true;
    sendBtn.textContent = "POSTING Payloads...";
    
    try {
        const response = await fetch("/api/gateway/webhook", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            const result = await response.json();
            messageText.value = "";
            incomingQueueSelect.value = "";
            selectedMessageMedia = null;
            
            // Refresh logs and client list
            await fetchLogs();
            await fetchDeviceMessages(recipientId);
            
            // Play popup feedback sound if notify
            if (result.action === 'notify') {
                playAlertSound();
            }
        } else {
            const err = await response.json();
            alert(`Webhook execution error: ${err.detail || "HTTP Failure"}`);
        }
    } catch (e) {
        alert("Failed to connect to gateway webhook API.");
    } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = "POST Webhook Payload";
    }
}

// ----------------- INSPECTOR MODAL -----------------

function showInspector(log) {
    document.getElementById("inspect-action").textContent = log.action;
    document.getElementById("inspect-action").className = `val badge ${log.action}`;
    document.getElementById("inspect-type").textContent = log.message_type_pred.toUpperCase();
    document.getElementById("inspect-confidence").textContent = log.confidence.toFixed(2);
    document.getElementById("inspect-latency").textContent = `${log.latency_ms.toFixed(1)} ms`;
    
    // Payload JSON block
    const payloadDump = {
        message_id: log.message_id,
        user_id: log.user_id,
        conversation_type: log.conversation_type,
        sender_user_id: log.sender_user_id,
        group_id: log.group_id,
        business_id: log.business_id,
        message_text: log.message_text,
        media_type: log.media_type,
        media_id: log.media_id
    };
    document.getElementById("inspect-message-data").textContent = JSON.stringify(payloadDump, null, 2);
    
    // Prompt compile
    document.getElementById("inspect-prompt").textContent = log.prompt_compiled || "No prompt tracing stored for this engine.";
    
    // RAG results matches
    const matchesContainer = document.getElementById("inspect-rag-matches");
    matchesContainer.innerHTML = "";
    
    const matches = log.rag_matches || [];
    if (matches.length === 0) {
        matchesContainer.innerHTML = `<p class="device-empty-state" style="margin-top:0.5rem;">No historical matches retrieved under threshold.</p>`;
    } else {
        matches.forEach((m, idx) => {
            const card = document.createElement("div");
            card.className = "rag-match-card";
            
            const metaStr = Object.entries(m.metadata || {})
                .map(([k, v]) => `${k}: ${v}`)
                .join(" | ");
                
            card.innerHTML = `
                <div class="rag-match-header">
                    <span>MATCH #${idx + 1}</span>
                    <div class="rag-match-meta">
                        <span>${metaStr}</span>
                        <span class="rag-match-distance">L2: ${m.distance.toFixed(3)}</span>
                    </div>
                </div>
                <div class="rag-match-text">${escapeHTML(m.message_text || "")}</div>
            `;
            matchesContainer.appendChild(card);
        });
    }
    
    modal.classList.add("active");
}

function hideInspector() {
    modal.classList.remove("active");
}

// ----------------- EVENT LISTENERS -----------------

function setupEventListeners() {
    // Recipient profile selector
    recipientSelect.addEventListener("change", (e) => {
        selectRecipient(e.target.value);
    });
    
    document.getElementById("refresh-logs-btn").addEventListener("click", fetchLogs);
    
    incomingQueueSelect.addEventListener("change", (e) => {
        const msgId = e.target.value;
        if (!msgId) {
            selectedMessageMedia = null;
            return;
        }
        const msg = incomingQueue.find(m => m.message_id === msgId);
        if (msg) {
            conversationSelect.value = msg.conversation_type;
            conversationSelect.dispatchEvent(new Event("change"));
            
            messageText.value = msg.message_text || "";
            
            if (msg.conversation_type === "group") {
                // Wait for sandbox selects to populate
                setTimeout(() => {
                    ensureOptionExists(groupSelect, msg.group_id, `Group (${msg.group_id})`);
                    groupSelect.value = msg.group_id;
                    ensureOptionExists(senderSelect, msg.sender_user_id, `User (${msg.sender_user_id})`);
                    senderSelect.value = msg.sender_user_id;
                }, 50);
            } else if (msg.conversation_type === "business") {
                setTimeout(() => {
                    ensureOptionExists(businessSelect, msg.business_id, `Business (${msg.business_id})`);
                    businessSelect.value = msg.business_id;
                }, 50);
            } else {
                setTimeout(() => {
                    ensureOptionExists(senderSelect, msg.sender_user_id, `User (${msg.sender_user_id})`);
                    senderSelect.value = msg.sender_user_id;
                }, 50);
            }
            
            selectedMessageMedia = {
                message_id: msg.message_id,
                media_type: msg.media_type,
                media_id: msg.media_id,
                forwarded_count: msg.forwarded_count || 0
            };
        }
    });
    
    // Conversation type selector
    conversationSelect.addEventListener("change", (e) => {
        const type = e.target.value;
        if (type === 'group') {
            groupSelectContainer.style.display = "block";
            businessSelectContainer.style.display = "none";
            senderSelectContainer.style.display = "block";
        } else if (type === 'business') {
            groupSelectContainer.style.display = "none";
            businessSelectContainer.style.display = "block";
            senderSelectContainer.style.display = "none";
        } else {
            groupSelectContainer.style.display = "none";
            businessSelectContainer.style.display = "none";
            senderSelectContainer.style.display = "block";
        }
    });
    
    // Template suggested badges
    document.querySelectorAll(".badge-suggest").forEach(badge => {
        badge.addEventListener("click", () => {
            messageText.value = badge.getAttribute("data-text");
        });
    });
    
    // Send Webhook payload
    sendBtn.addEventListener("click", sendWebhookPayload);
    
    // Config controls
    configThreshold.addEventListener("input", (e) => {
        thresholdVal.textContent = e.target.value;
    });
    
    saveConfigBtn.addEventListener("click", updateConfig);
    
    // Device screen tabs
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            const target = e.currentTarget;
            target.classList.add("active");
            activeTab = target.getAttribute("data-tab");
            renderDeviceMessages();
        });
    });
    
    // Modal controls
    closeModalBtn.addEventListener("click", hideInspector);
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            hideInspector();
        }
    });
}

// ----------------- UTILITIES -----------------

function getLatencyClass(ms) {
    if (ms < 50) return "text-success";
    if (ms < 200) return "text-warning";
    return "text-danger";
}

function getSenderLabel(log) {
    if (log.conversation_type === 'group') return log.group_id;
    if (log.conversation_type === 'business') return log.business_id;
    return log.sender_user_id;
}

function escapeHTML(str) {
    if (!str) return "";
    return str.replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

function playAlertSound() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        
        osc.type = "sine";
        osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
        osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.1); // A5
        
        gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.35);
        
        osc.start();
        osc.stop(audioCtx.currentTime + 0.35);
    } catch (e) {
        console.warn("Sound play ignored due to user gestures rules.");
    }
}

function ensureOptionExists(selectEl, value, text) {
    if (!value || value === "none") return;
    for (let i = 0; i < selectEl.options.length; i++) {
        if (selectEl.options[i].value === value) {
            return;
        }
    }
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    selectEl.appendChild(opt);
}
