const runtimeConfig = window.APP_CONFIG || {};
const CLIENT_ID = runtimeConfig.CLIENT_ID || 'kt8900copilot';
const PASSKEY = runtimeConfig.PASSKEY || 'your-secret-passkey';
const API_BASE = runtimeConfig.API_BASE || (window.location.origin + '/api');
const WS_URL = runtimeConfig.WS_URL || null;

let ws = null;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let isTransmitting = false;
let isVerified = false;
let currentAudioInfo = null;
let wsAuthToken = null;

async function md5(str) {
    const encoder = new TextEncoder();
    const data = encoder.encode(str);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.slice(0, 16);
}

async function computeVerifyResponse(clientId, verifyBytes, passkey) {
    const verifyHex = Array.from(verifyBytes).map(b => b.toString(16).padStart(2, '0')).join('');
    const data = clientId + verifyHex + passkey;
    const hash = await md5(data);
    return new Uint8Array(hash);
}

async function verifyConnection() {
    return new Promise((resolve, reject) => {
        const clientIdBytes = new TextEncoder().encode(CLIENT_ID);
        ws.send(clientIdBytes);
        
        let verifyCallback = async (event) => {
            const data = new Uint8Array(event.data);
            
            if (data.length === 0) return;
            
            const cmd = data[0];
            
            if (cmd === 0x01) {
                const verifyBytes = data.slice(1);
                const response = await computeVerifyResponse(CLIENT_ID, Array.from(verifyBytes), PASSKEY);
                ws.send(response);
                
            } else if (cmd === 0x02) {
                console.error('验证失败：无效的客户端');
                ws.close();
                reject(new Error('验证失败'));
                
            } else if (cmd === 0x03) {
                console.error('验证失败：设备忙碌');
                ws.close();
                reject(new Error('设备忙碌'));
                
            } else if (cmd === 0x1D || cmd === 0x1E) {
                isVerified = true;
                console.log('验证成功');
                ws.removeEventListener('message', verifyCallback);
                resolve(true);
                
            }
        };
        
        ws.addEventListener('message', verifyCallback);
        
        setTimeout(() => {
            if (!isVerified) {
                console.error('验证超时');
                ws.close();
                reject(new Error('验证超时'));
            }
        }, 20000);
    });
}

async function fetchWsToken() {
    const response = await apiCall('/auth/ws-token', 'POST', {
        client_id: CLIENT_ID,
        passkey: PASSKEY
    });

    if (!response || response.status !== 'success' || !response.token) {
        throw new Error('未获取到 WS Token');
    }

    wsAuthToken = response.token;
    return wsAuthToken;
}

const pttButton = document.getElementById('pttButton');
const pttStatus = document.getElementById('pttStatus');
const corStatus = document.getElementById('corStatus');
const connectionStatus = document.getElementById('connectionStatus');
const aprsLog = document.getElementById('aprsLog');
const micStatus = document.getElementById('micStatus');
const sendBeaconBtn = document.getElementById('sendBeaconBtn');
const latencyValue = document.getElementById('latencyValue');
const packetCount = document.getElementById('packetCount');
const audioPresetValue = document.getElementById('audioPresetValue');
const speakerHero = document.getElementById('speakerHero');
const activeSpeakerName = document.getElementById('activeSpeakerName');
const activeSpeakerRole = document.getElementById('activeSpeakerRole');

let totalPackets = 0;
let lastPingTime = 0;

function connect() {
    updateConnectionStatus('connecting');

    (async () => {
        try {
            const token = await fetchWsToken();
            const wsUrl = getWebSocketURL(token);
            ws = new WebSocket(wsUrl);
            ws.binaryType = 'arraybuffer';

            ws.onopen = () => {
                console.log('WebSocket 已连接，等待后端令牌校验...');
                updateConnectionStatus('connecting');
            };

            ws.onmessage = async (event) => {
                await handleServerMessage(event.data);
            };

            ws.onclose = () => {
                updateConnectionStatus('disconnected');
                isVerified = false;
                console.log('WebSocket 已断开');
                ws = null;
                setTimeout(connect, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket 错误:', error);
            };
        } catch (e) {
            console.error('获取令牌或连接失败:', e);
            updateConnectionStatus('disconnected');
            setTimeout(connect, 3000);
        }
    })();
    
    async function handleServerMessage(data) {
        totalPackets++;
        packetCount.textContent = totalPackets.toString();

        if (data instanceof ArrayBuffer) {
            const bytes = new Uint8Array(data);
            if (!isVerified && bytes.length > 0 && (bytes[0] === 0x1D || bytes[0] === 0x1E)) {
                isVerified = true;
                updateConnectionStatus('connected');
                console.log('WebSocket 令牌验证成功');
                sendPing();
                return;
            }
            if (!isVerified && bytes.length > 0 && (bytes[0] === 0x02 || bytes[0] === 0x03)) {
                updateConnectionStatus('disconnected');
                console.error('WebSocket 令牌验证失败或客户端忙碌');
                if (ws) {
                    ws.close();
                }
                return;
            }
        }
        
        if (!isVerified) {
            return;
        }
        
        if (data instanceof ArrayBuffer) {
            const bytes = new Uint8Array(data);
            if (bytes.length === 0) return;
            
            const cmd = bytes[0];
            
            switch (cmd) {
                case 0x11:
                    corStatus.classList.add('receiving');
                    break;
                case 0x12:
                    corStatus.classList.remove('receiving');
                    break;
                case 0x13:
                    pttStatus.classList.add('active');
                    break;
                case 0x14:
                    pttStatus.classList.remove('active');
                    break;
                case 0x51:
                    await handleAudioData(bytes.slice(1));
                    break;
                default:
                    await handleAudioData(bytes);
            }
        }
        else if (typeof data === 'string') {
            try {
                const message = JSON.parse(data);
                handleControlMessage(message);
            } catch (e) {
                console.log('收到非 JSON 消息:', data);
            }
        }
    }
    
}

function getWebSocketURL(token = null) {
    if (WS_URL) {
        if (!token) {
            return WS_URL;
        }
        const join = WS_URL.includes('?') ? '&' : '?';
        return `${WS_URL}${join}token=${encodeURIComponent(token)}`;
    }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = location.host;
    if (!token) {
        return `${protocol}//${host}/`;
    }
    return `${protocol}//${host}/?token=${encodeURIComponent(token)}`;
}

function updateConnectionStatus(status) {
    connectionStatus.className = `connection-status ${status}`;
    
    switch (status) {
        case 'connected':
            connectionStatus.textContent = '已连接';
            break;
        case 'disconnected':
            connectionStatus.textContent = '已断开 - 正在重连...';
            break;
        case 'connecting':
            connectionStatus.textContent = '正在连接...';
            break;
    }
}

function handleControlMessage(message) {
    console.log('收到控制消息:', message);
    
    switch (message.type) {
        case 'ptt_status':
            pttStatus.classList.toggle('active', message.active);
            updateActiveSpeaker(message);
            break;
            
        case 'cor_status':
            corStatus.classList.toggle('receiving', message.active);
            if (message.active) {
                logAPRS('检测到载波信号', 'status');
            }
            break;
            
        case 'aprs_response':
            logAPRS(`发送 APRS 信标: ${message.status}`, 'info');
            break;
            
        case 'aprs_packet':
            logAPRS(`收到 APRS: ${message.raw.substring(0, 80)}`, 'packet');
            break;
            
        case 'aprs_position':
            logAPRS(`位置报告: ${message.source} @ ${message.pos}`, 'position');
            break;
            
        case 'aprs_message':
            logAPRS(`消息: ${message.source} -> ${message}: ${message.text}`, 'message');
            break;
            
        case 'pong':
            calculateLatency(message.timestamp);
            break;
    }
}

function updateActiveSpeaker(pttMessage) {
    const typeNames = { 1: '电台设备', 2: '普通用户', 3: '管理员' };

    if (!pttMessage.active) {
        speakerHero.classList.remove('talking');
        activeSpeakerName.textContent = '待机';
        activeSpeakerRole.textContent = '空闲信道';
        return;
    }

    const speakerName = pttMessage.from || '未知来源';
    const speakerRole = typeNames[pttMessage.from_type] || '在线客户端';

    speakerHero.classList.add('talking');
    activeSpeakerName.textContent = speakerName;
    activeSpeakerRole.textContent = `${speakerRole} · 正在发话`;
}

async function handleAudioData(data) {
    try {
        if (!audioContext) {
            const sampleRate = currentAudioInfo?.sample_rate || 8000;
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
        }
        
        let audioBuffer;
        
        if (data instanceof ArrayBuffer) {
            const int16Array = new Int16Array(data);
            const float32Array = new Float32Array(int16Array.length);
            
            for (let i = 0; i < int16Array.length; i++) {
                float32Array[i] = int16Array[i] / 32768.0;
            }
            
            const sr = currentAudioInfo?.sample_rate || 8000;
            audioBuffer = audioContext.createBuffer(1, float32Array.length, sr);
            audioBuffer.getChannelData(0).set(float32Array);
        } else if (data instanceof Blob) {
            const arrayBuffer = await data.arrayBuffer();
            const int16Array = new Int16Array(arrayBuffer);
            const float32Array = new Float32Array(int16Array.length);
            
            for (let i = 0; i < int16Array.length; i++) {
                float32Array[i] = int16Array[i] / 32768.0;
            }
            
            const sr = currentAudioInfo?.sample_rate || 8000;
            audioBuffer = audioContext.createBuffer(1, float32Array.length, sr);
            audioBuffer.getChannelData(0).set(float32Array);
        } else {
            console.warn('未知的音频数据类型:', typeof data);
            return;
        }
        
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        source.start();
        
    } catch (e) {
        console.error('音频解码错误:', e);
    }
}

async function startMicrophone() {
    try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error('浏览器不支持音频访问');
        }
        
        const sampleRate = currentAudioInfo?.sample_rate || 8000;
        
        mediaStream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                sampleRate: sampleRate,
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
            } 
        });
        
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)({ 
                sampleRate: sampleRate
            });
        }
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        const bufferSize = 4096;
        scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);
        
        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);
        
        scriptProcessor.onaudioprocess = (e) => {
            const inputData = e.inputBuffer.getChannelData(0);
            const pcmData = new Int16Array(inputData.length);
            
            for (let i = 0; i < inputData.length; i++) {
                pcmData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32767));
            }
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(pcmData.buffer);
            }
        };
        
        micStatus.classList.add('active');
        console.log('麦克风已启动');
    } catch (e) {
        console.error('麦克风启动失败:', e);
        alert(`无法访问麦克风: ${e.message}`);
    }
}

function stopMicrophone() {
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
    }
    micStatus.classList.remove('active');
    console.log('麦克风已停止');
}

async function handlePTTPress() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert('未连接到服务器');
        return;
    }
    
    if (isTransmitting) {
        return;
    }
    
    isTransmitting = true;
    pttButton.classList.add('active');
    
    try {
        ws.send(JSON.stringify({ type: 'ptt_press' }));
        await startMicrophone();
    } catch (e) {
        console.error('PTT 激活失败:', e);
        isTransmitting = false;
        pttButton.classList.remove('active');
    }
}

function handlePTTRelease() {
    if (!isTransmitting) {
        return;
    }
    
    isTransmitting = false;
    pttButton.classList.remove('active');
    stopMicrophone();
    
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ptt_release' }));
    }
}

pttButton.addEventListener('mousedown', handlePTTPress);
pttButton.addEventListener('mouseup', handlePTTRelease);
pttButton.addEventListener('mouseleave', handlePTTRelease);

pttButton.addEventListener('touchstart', (e) => {
    e.preventDefault();
    handlePTTPress();
});

pttButton.addEventListener('touchend', (e) => {
    e.preventDefault();
    handlePTTRelease();
});

sendBeaconBtn.addEventListener('click', () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'aprs_beacon' }));
        logAPRS('发送 APRS 信标请求...', 'info');
    } else {
        alert('未连接到服务器');
    }
});

function logAPRS(message, type = 'info') {
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.className = 'aprs-packet';
    
    let html = '';
    
    switch (type) {
        case 'status':
            html = `<span class="aprs-timestamp">[${timestamp}]</span> <span class="aprs-content" style="color: #999;">${message}</span>`;
            break;
        
        case 'packet':
            html = `<span class="aprs-timestamp">[${timestamp}]</span> ${message}`;
            break;
        
        case 'position':
            html = `<span class="aprs-timestamp">[${timestamp}]</span> <span class="aprs-content" style="color: #4CAF50;">${message}</span>`;
            break;
        
        case 'message':
            html = `<span class="aprs-timestamp">[${timestamp}]</span> <span class="aprs-content" style="color: #2196F3;">${message}</span>`;
            break;
        
        case 'info':
            html = `<span class="aprs-timestamp">[${timestamp}]</span> <span class="aprs-content" style="color: #666;">${message}</span>`;
            break;
        
        default:
            html = `<span class="aprs-timestamp">[${timestamp}]</span> ${message}`;
    }
    
    logEntry.innerHTML = html;
    aprsLog.appendChild(logEntry);
    aprsLog.scrollTop = aprsLog.scrollHeight;
    
    if (aprsLog.children.length > 100) {
        aprsLog.removeChild(aprsLog.firstChild);
    }
}

function sendPing() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        const timestamp = Date.now();
        ws.send(JSON.stringify({ 
            type: 'ping', 
            timestamp: timestamp 
        }));
        lastPingTime = timestamp;
    }
}

function calculateLatency(pingTimestamp) {
    const currentTime = Date.now();
    const latency = currentTime - pingTimestamp;
    latencyValue.textContent = `${latency} ms`;
    
    setTimeout(sendPing, 5000);
}

async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json'
        }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(API_BASE + endpoint, options);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return await response.json();
    } catch (e) {
        showToast(`API 错误: ${e.message}`, 'error');
        throw e;
    }
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        
        tab.classList.add('active');
        const tabId = tab.dataset.tab + 'Tab';
        document.getElementById(tabId).classList.add('active');
        
        if (tab.dataset.tab === 'admin') {
            loadAdminData();
        }
    });
});

async function loadAdminData() {
    try {
        const audioInfo = await apiCall('/audio/info');
        currentAudioInfo = audioInfo;
        updateAudioUI(audioInfo);
        
        const config = await apiCall('/config');
        updateConfigUI(config);
        
        const clients = await apiCall('/clients');
        updateClientList(clients);
        
        const presets = await apiCall('/audio/presets');
        updatePresetButtons(presets, audioInfo.preset);
    } catch (e) {
        console.error('加载管理数据失败:', e);
    }
}

function updateAudioUI(audioInfo) {
    audioPresetValue.textContent = `${audioInfo.sample_rate / 1000}kHz`;
    
    document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.preset === audioInfo.matched_preset) {
            btn.classList.add('active');
        }
    });
    
    document.getElementById('customSampleRate').value = audioInfo.sample_rate;
    document.getElementById('customChannels').value = audioInfo.channels;
}

function updateConfigUI(config) {
    document.getElementById('wsHost').value = config.websocket?.host || '0.0.0.0';
    document.getElementById('wsPort').value = config.websocket?.port || 8765;
    
    document.getElementById('serialPort').value = config.serial?.port || '/dev/ttyUSB0';
    document.getElementById('serialBaudrate').value = config.serial?.baudrate || 115200;
    document.getElementById('serialAutoDetect').checked = config.serial?.auto_detect ?? true;
    
    document.getElementById('aprsEnabled').checked = config.aprs?.enabled || false;
    document.getElementById('aprsCallsign').value = config.aprs?.my_callsign || '';
    document.getElementById('aprsSsid').value = config.aprs?.my_ssid || 0;
    document.getElementById('aprsLat').value = config.aprs?.my_lat || '';
    document.getElementById('aprsLon').value = config.aprs?.my_lon || '';
    document.getElementById('aprsInterval').value = config.aprs?.beacon_interval || 600;
    
    document.getElementById('debugMode').checked = config.debug || false;
}

function updateClientList(clients) {
    const clientList = document.getElementById('clientList');
    clientList.innerHTML = '';
    
    const typeNames = { 1: 'ESP32', 2: '用户', 3: '管理员' };
    
    clients.forEach(client => {
        const item = document.createElement('div');
        item.className = 'client-item';
        
        const permissions = [];
        if (client.can_tx) permissions.push('发射');
        if (client.can_aprs) permissions.push('APRS');
        
        item.innerHTML = `
            <div class="client-info">
                <div class="client-name">${client.client_name}</div>
                <div class="client-id">ID: ${client.client_id} | 类型: ${typeNames[client.client_type] || client.client_type}</div>
                <div class="client-permissions">权限: ${permissions.join(', ') || '无'}</div>
            </div>
            <div class="client-actions">
                <button class="btn-icon" onclick="editClient('${client.client_id}')" title="编辑">✏️</button>
                <button class="btn-icon delete" onclick="deleteClient('${client.client_id}')" title="删除">🗑️</button>
            </div>
        `;
        
        clientList.appendChild(item);
    });
}

function updatePresetButtons(presets, currentPreset) {
}

document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const preset = btn.dataset.preset;
        
        try {
            await apiCall('/audio/preset', 'POST', { preset });
            showToast(`音频预设已更改为: ${preset}`, 'success');
            
            document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const audioInfo = await apiCall('/audio/info');
            currentAudioInfo = audioInfo;
            updateAudioUI(audioInfo);
        } catch (e) {
            console.error('切换预设失败:', e);
        }
    });
});

document.getElementById('applyCustomAudio').addEventListener('click', async () => {
    const sampleRate = parseInt(document.getElementById('customSampleRate').value);
    const channels = parseInt(document.getElementById('customChannels').value);
    
    try {
        await apiCall('/audio/custom', 'POST', { sample_rate: sampleRate, channels });
        showToast('自定义音频设置已应用', 'success');
        
        const audioInfo = await apiCall('/audio/info');
        currentAudioInfo = audioInfo;
        updateAudioUI(audioInfo);
    } catch (e) {
        console.error('应用自定义设置失败:', e);
    }
});

document.getElementById('saveNetworkSettings').addEventListener('click', async () => {
    const host = document.getElementById('wsHost').value;
    const port = parseInt(document.getElementById('wsPort').value);
    
    try {
        await apiCall('/websocket', 'PUT', { host, port });
        showToast('网络设置已保存，重启服务生效', 'success');
    } catch (e) {
        console.error('保存网络设置失败:', e);
    }
});

document.getElementById('saveSerialSettings').addEventListener('click', async () => {
    const port = document.getElementById('serialPort').value;
    const baudrate = parseInt(document.getElementById('serialBaudrate').value);
    const auto_detect = document.getElementById('serialAutoDetect').checked;
    
    try {
        await apiCall('/serial', 'PUT', { port, baudrate, auto_detect });
        showToast('串口设置已保存', 'success');
    } catch (e) {
        console.error('保存串口设置失败:', e);
    }
});

document.getElementById('saveAprsSettings').addEventListener('click', async () => {
    const enabled = document.getElementById('aprsEnabled').checked;
    const my_callsign = document.getElementById('aprsCallsign').value;
    const my_ssid = parseInt(document.getElementById('aprsSsid').value);
    const my_lat = parseFloat(document.getElementById('aprsLat').value) || 0;
    const my_lon = parseFloat(document.getElementById('aprsLon').value) || 0;
    const beacon_interval = parseInt(document.getElementById('aprsInterval').value);
    
    try {
        await apiCall('/aprs', 'PUT', { 
            enabled, 
            my_callsign, 
            my_ssid, 
            my_lat, 
            my_lon, 
            beacon_interval 
        });
        showToast('APRS 设置已保存', 'success');
    } catch (e) {
        console.error('保存 APRS 设置失败:', e);
    }
});

document.getElementById('backupConfigBtn').addEventListener('click', async () => {
    try {
        const result = await apiCall('/backup', 'POST');
        showToast('配置已备份', 'success');
    } catch (e) {
        console.error('备份配置失败:', e);
    }
});

document.getElementById('restartServerBtn').addEventListener('click', async () => {
    if (!confirm('确定要重启服务吗？这将断开所有连接。')) {
        return;
    }
    
    try {
        await apiCall('/server/restart', 'POST');
        showToast('服务器重启中...', 'success');
    } catch (e) {
        console.error('重启服务失败:', e);
    }
});

document.getElementById('debugMode').addEventListener('change', async (e) => {
    try {
        await apiCall('/debug', 'POST?enabled=' + e.target.checked);
        showToast(`调试模式: ${e.target.checked ? '启用' : '禁用'}`, 'success');
    } catch (err) {
        console.error('设置调试模式失败:', err);
    }
});

document.getElementById('showAddClientBtn').addEventListener('click', () => {
    document.getElementById('addClientModal').classList.add('active');
});

document.getElementById('cancelAddClientBtn').addEventListener('click', () => {
    document.getElementById('addClientModal').classList.remove('active');
});

document.getElementById('addClientBtn').addEventListener('click', async () => {
    const client_id = document.getElementById('newClientId').value;
    const client_name = document.getElementById('newClientName').value;
    const client_type = parseInt(document.getElementById('newClientType').value);
    const can_tx = document.getElementById('newClientCanTx').checked;
    const can_aprs = document.getElementById('newClientCanAprs').checked;
    
    if (!client_id || !client_name) {
        showToast('请填写完整信息', 'error');
        return;
    }
    
    try {
        await apiCall('/clients', 'POST', {
            client_id,
            client_name,
            client_type,
            can_tx,
            can_aprs
        });
        showToast('客户端已添加', 'success');
        document.getElementById('addClientModal').classList.remove('active');
        
        const clients = await apiCall('/clients');
        updateClientList(clients);
    } catch (e) {
        console.error('添加客户端失败:', e);
    }
});

async function deleteClient(clientId) {
    if (!confirm(`确定要删除客户端 ${clientId} 吗？`)) {
        return;
    }
    
    try {
        await apiCall('/clients/' + clientId, 'DELETE');
        showToast('客户端已删除', 'success');
        
        const clients = await apiCall('/clients');
        updateClientList(clients);
    } catch (e) {
        console.error('删除客户端失败:', e);
    }
}

function editClient(clientId) {
    showToast('编辑功能开发中...', 'info');
}

window.addEventListener('beforeunload', () => {
    stopMicrophone();
    if (ws) {
        ws.close();
    }
});

window.addEventListener('DOMContentLoaded', () => {
    console.log('KT8900 Copilot 前端已加载');
    
    apiCall('/audio/info').then(info => {
        currentAudioInfo = info;
        updateAudioUI(info);
    }).catch(() => {});
    
    connect();
});
