const API_BASE = '';
const BIZ_TYPE = 'email-assistant';

// 当用户切换时更新 USER_ID
function _computeUserId() {
    const user = localStorage.getItem('mailfriend_current_user');
    return user ? user : '';
}
let USER_ID = _computeUserId();

function isLoggedIn() {
    return !!localStorage.getItem('mailfriend_current_user');
}
window.isLoggedIn = isLoggedIn;

function updateUserId() {
    USER_ID = _computeUserId();
}
window.updateUserId = updateUserId;

/**
 * 退出登录时被 email.html 中的 _clearAuthState 调用
 * 清空所有会话数据，重置 UI
 */
function resetAppForLogout() {
    USER_ID = '';
    sessions = [];
    currentSession = null;
    currentThreadId = null;
    currentInterrupt = null;
    currentActionName = '';
    // 渲染空列表（保留占位提示）
    renderSessionList();
    // 清空消息区
    clearChat();
    // 禁用输入框
    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    if (input) {
        input.value = '';
        input.disabled = true;
        input.placeholder = '请先登录邮箱账号后再发送消息...';
        input.style.height = 'auto';
    }
    if (sendBtn) sendBtn.disabled = true;
    const title = document.getElementById('chatTitle');
    if (title) title.textContent = '请先登录邮箱账号';
    // 刷新空状态区域文案
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        emptyState.style.display = 'flex';
        const ph = emptyState.querySelector('p');
        if (ph) ph.textContent = '请先登录邮箱账号，再开始管理邮件';
    }
    var newBtn = document.getElementById('newSessionBtn');
    if (newBtn) newBtn.style.display = 'none';
    // 同步刷新 email.html 页面中的 userProfile / 登录按钮文案
    if (typeof window.updateUserArea === 'function') window.updateUserArea();
}
window.resetAppForLogout = resetAppForLogout;

let sessions = [];
let currentSession = null;
let currentThreadId = null;
let currentInterrupt = null;
let currentActionName = '';
let isEditMode = false;

// 批量管理状态
let batchMode = false;
let selectedThreads = {};

document.addEventListener('DOMContentLoaded', () => {
    // DOM 就绪后先做一次登录态 UI 控制
    applyLoginGate();
    loadSessions();
    setupInputHandler();
    setupBatchButtons();
});

// 批量管理按钮绑定
function setupBatchButtons() {
    const editBtn = document.getElementById('batchEditBtn');
    const cancelBtn = document.getElementById('batchCancelBtn');
    const selectAll = document.getElementById('batchSelectAll');
    const deleteBtn = document.getElementById('batchDeleteBtn');
    if (editBtn) editBtn.addEventListener('click', enterBatchMode);
    if (cancelBtn) cancelBtn.addEventListener('click', exitBatchMode);
    if (selectAll) selectAll.addEventListener('change', function () { selectAllBatch(this.checked); });
    if (deleteBtn) deleteBtn.addEventListener('click', deleteSelectedBatch);
}

function enterBatchMode() {
    batchMode = true;
    selectedThreads = {};
    const list = document.getElementById('sessionList');
    if (list) list.classList.add('batch-mode');
    const bar = document.getElementById('batchActionBar');
    if (bar) bar.classList.add('show');
    const editBtn = document.getElementById('batchEditBtn');
    if (editBtn) editBtn.style.display = 'none';
    renderSessionList();
    updateBatchUI();
}
window.enterBatchMode = enterBatchMode;

function exitBatchMode() {
    batchMode = false;
    selectedThreads = {};
    const list = document.getElementById('sessionList');
    if (list) list.classList.remove('batch-mode');
    const bar = document.getElementById('batchActionBar');
    if (bar) bar.classList.remove('show');
    const editBtn = document.getElementById('batchEditBtn');
    if (editBtn) editBtn.style.display = '';
    const sa = document.getElementById('batchSelectAll');
    if (sa) sa.checked = false;
    renderSessionList();
}
window.exitBatchMode = exitBatchMode;

function updateBatchUI() {
    const count = Object.keys(selectedThreads).length;
    const countEl = document.getElementById('batchCount');
    if (countEl) countEl.textContent = '已选 ' + count + ' 项';
    const delBtn = document.getElementById('batchDeleteBtn');
    if (delBtn) delBtn.disabled = count === 0;
    const items = document.querySelectorAll('#sessionList .session-item');
    const allChecked = items.length > 0 && count === items.length;
    const sa = document.getElementById('batchSelectAll');
    if (sa) sa.checked = allChecked;
}

function selectAllBatch(checked) {
    const items = document.querySelectorAll('#sessionList .session-item');
    items.forEach(function (item) {
        const tid = item.getAttribute('data-thread-id');
        if (checked) {
            selectedThreads[tid] = true;
        } else {
            delete selectedThreads[tid];
        }
    });
    renderSessionList();
    updateBatchUI();
}
window.selectAllBatch = selectAllBatch;

async function deleteSelectedBatch() {
    const tids = Object.keys(selectedThreads);
    if (tids.length === 0) return;
    if (!confirm('确定要删除选中的 ' + tids.length + ' 个会话吗？此操作不可撤销。')) return;
    const delBtn = document.getElementById('batchDeleteBtn');
    if (delBtn) { delBtn.disabled = true; delBtn.textContent = '删除中...'; }
    let deletedAny = false;
    for (const tid of tids) {
        try {
            await fetch(`${API_BASE}/api/v1/sessions/${tid}`, { method: 'DELETE' });
            sessions = sessions.filter(s => s.thread_id !== tid);
            deletedAny = true;
        } catch (e) {
            console.error('删除会话失败 ' + tid + ':', e);
        }
    }
    // 若当前会话被删除，则清空聊天区
    if (selectedThreads[currentThreadId]) {
        currentSession = null;
        currentThreadId = null;
        clearChat();
    }
    exitBatchMode();
    renderSessionList();
    if (delBtn) {
        delBtn.disabled = false;
        delBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>删除所选';
    }
}
window.deleteSelectedBatch = deleteSelectedBatch;

/**
 * 根据登录态锁定/解锁相关 UI（会话可见性、输入框、新建会话按钮）
 */
function applyLoginGate() {
    const loggedIn = isLoggedIn();
    const newBtn = document.getElementById('newSessionBtn');
    if (newBtn) newBtn.style.display = loggedIn ? '' : 'none';

    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const hint = document.getElementById('sessionEmptyHint');

    if (!loggedIn) {
        sessions = [];
        currentSession = null;
        currentThreadId = null;
        // 显示未登录占位提示
        if (hint) hint.style.display = 'block';
        if (input) {
            input.disabled = true;
            input.placeholder = '请先登录邮箱账号后再发送消息...';
            input.style.height = 'auto';
        }
        if (sendBtn) sendBtn.disabled = true;
        const title = document.getElementById('chatTitle');
        if (title) title.textContent = '请先登录邮箱账号';
        const emptyState = document.getElementById('emptyState');
        if (emptyState) {
            emptyState.style.display = 'flex';
            const ph = emptyState.querySelector('p');
            if (ph) ph.textContent = '请先登录邮箱账号，再开始管理邮件';
        }
    } else {
        if (hint) hint.style.display = 'none';
        if (newBtn) newBtn.style.display = '';
    }
    // 同步刷新 email.html 页面中的 userProfile / 登录按钮文案
    if (typeof window.updateUserArea === 'function') window.updateUserArea();
}
window.applyLoginGate = applyLoginGate;

function setupInputHandler() {
    const input = document.getElementById('messageInput');
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Reject 弹窗键盘支持：Enter 确认，Esc 取消
    document.addEventListener('keydown', (e) => {
        const rejectModal = document.getElementById('rejectModal');
        if (rejectModal.classList.contains('show')) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                confirmReject();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                closeRejectModal();
            }
        }
    });
}

async function loadSessions() {
    // 未登录：不请求 API，保持空列表，applyLoginGate 会显示占位
    if (!isLoggedIn()) {
        sessions = [];
        renderSessionList();
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/v1/sessions?user_id=${USER_ID}&biz_type=${BIZ_TYPE}`);
        const data = await response.json();
        sessions = Array.isArray(data) ? data : (data.sessions || []);
        renderSessionList();

        // 如果 localStorage 中保存了登录认证时返回的 thread_id，且会话列表里有这个线程，就优先选中它
        const pinnedTid = localStorage.getItem('mailfriend_thread_id');
        if (pinnedTid && sessions.some(s => s.thread_id === pinnedTid)) {
            const pinned = sessions.find(s => s.thread_id === pinnedTid);
            currentThreadId = null; // 强制触发选中
            setTimeout(() => selectSessionById(pinned.thread_id, pinned.name), 50);
            return;
        }
    } catch (error) {
        console.error('加载会话失败:', error);
    }
}

async function createSession() {
    if (!isLoggedIn()) {
        showToast('请先登录邮箱账号再创建会话', 'error');
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/api/v1/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: USER_ID,
                biz_type: BIZ_TYPE,
                name: `新会话 ${sessions.length + 1}`
            })
        });
        const data = await response.json();
        sessions.unshift(data);
        renderSessionList();
        selectSessionById(data.thread_id, data.name);
    } catch (error) {
        console.error('创建会话失败:', error);
    }
}

async function deleteSession(e, threadId) {
    e.stopPropagation();
    if (!confirm('确定要删除这个会话吗？')) return;
    try {
        await fetch(`${API_BASE}/api/v1/sessions/${threadId}`, { method: 'DELETE' });
        sessions = sessions.filter(s => s.thread_id !== threadId);
        renderSessionList();
        if (currentThreadId === threadId) {
            currentSession = null;
            currentThreadId = null;
            clearChat();
        }
    } catch (error) {
        console.error('删除会话失败:', error);
    }
}

function renderSessionList() {
    const list = document.getElementById('sessionList');
    list.innerHTML = sessions.map(session => {
        const timeTitle = formatRelativeTime(session.created_at);
        const summary = session.name || '新会话';
        const activeClass = currentThreadId === session.thread_id ? 'active' : '';
        const selectedClass = selectedThreads[session.thread_id] ? 'selected' : '';
        return `
            <div class="session-item ${activeClass} ${selectedClass}"
                 data-thread-id="${session.thread_id}"
                 onclick="onSessionItemClick(event, '${session.thread_id}', '${(session.name || '').replace(/'/g, "\\'")}')">
                <input type="checkbox" class="session-checkbox" data-thread-id="${session.thread_id}"
                       onclick="onSessionCheckboxClick(event, '${session.thread_id}')" ${selectedThreads[session.thread_id] ? 'checked' : ''}>
                <div class="session-time">
                    <span class="dot"></span>
                    ${timeTitle}
                </div>
                <div class="session-summary">${escapeHtml(summary)}</div>
                <button class="delete-btn" onclick="deleteSession(event, '${session.thread_id}')" title="删除会话">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                    </svg>
                </button>
            </div>
        `;
    }).join('');

    if (sessions.length > 0 && !currentThreadId && !batchMode) {
        setTimeout(() => selectSessionById(sessions[0].thread_id, sessions[0].name), 100);
    }
}

function onSessionItemClick(event, threadId, name) {
    if (batchMode) {
        event.stopPropagation();
        toggleSelectThread(threadId);
        return;
    }
    selectSessionById(threadId, name);
}
window.onSessionItemClick = onSessionItemClick;

function onSessionCheckboxClick(event, threadId) {
    event.stopPropagation();
    toggleSelectThread(threadId);
}
window.onSessionCheckboxClick = onSessionCheckboxClick;

function toggleSelectThread(threadId) {
    if (selectedThreads[threadId]) {
        delete selectedThreads[threadId];
    } else {
        selectedThreads[threadId] = true;
    }
    renderSessionList();
    updateBatchUI();
}
window.toggleSelectThread = toggleSelectThread;

function selectSessionById(threadId, name) {
    selectSessionByIdAsync(threadId, name);
}

async function selectSessionByIdAsync(threadId, name) {
    // 未登录：不允许切换，提示先登录
    if (!isLoggedIn()) {
        showToast('请先登录邮箱账号再查看会话', 'error');
        return;
    }
    currentSession = sessions.find(s => s.thread_id === threadId);
    currentThreadId = threadId;
    renderSessionList();
    document.getElementById('chatTitle').textContent = name || '新会话';
    document.getElementById('messageInput').disabled = false;
    document.getElementById('messageInput').placeholder = '输入消息...';
    document.getElementById('sendBtn').disabled = false;
    const emptyState = document.getElementById('emptyState');
    if (emptyState) emptyState.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/api/v1/sessions/${threadId}/messages`);
        const data = await response.json();
        const messages = data.messages || [];
        renderMessages(messages);
        if (data.has_interrupt && data.interrupt) {
            showHitlModal(data.interrupt);
        }
    } catch (error) {
        console.error('加载历史消息失败:', error);
        renderMessages([]);
    }
}

function renderMessages(messages) {
    const container = document.getElementById('chatMessages');
    let html = '';
    for (const msg of messages) {
        html += createMessageElement(msg);
    }
    container.innerHTML = html;
    scrollToBottom();
}

function createMessageElement(msg) {
    const role = msg.type || msg.role || '';
    let cssRole, avatarHtml;
    if (role === 'human' || role === 'user') {
        cssRole = 'user';
        avatarHtml = 'U';
    } else {
        cssRole = 'assistant';
        avatarHtml = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M3 7l9 6.5L21 7"/></svg>`;
    }
    const content = msg.content || '';
    return `
        <div class="message ${cssRole}">
            <div class="message-avatar">${avatarHtml}</div>
            <div class="message-content">
                <div class="message-bubble">${parseMarkdown(content)}</div>
            </div>
        </div>
    `;
}

function parseMarkdown(content) {
    if (!content) return '';
    return marked.parse(content);
}

async function sendMessage() {
    // 双重校验：未登录不允许发送
    if (!isLoggedIn()) {
        showToast('请先登录邮箱账号再发送消息', 'error');
        return;
    }
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message || !currentThreadId) return;

    input.value = '';
    input.style.height = 'auto';
    const sendBtn = document.getElementById('sendBtn');
    sendBtn.disabled = true;

    appendMessage({ role: 'user', content: message });

    const assistantMsg = { role: 'assistant', content: '' };
    appendMessage(assistantMsg);

    try {
        const response = await fetch(`${API_BASE}/api/v1/email/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId,
                user_id: USER_ID || undefined
            })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const raw = line.slice(6);
                    try {
                        handleSSEEvent(JSON.parse(raw), assistantMsg);
                    } catch (e) { /* ignore */ }
                }
            }
        }
        updateSessionMessage(assistantMsg);
    } catch (error) {
        console.error('发送消息失败:', error);
        appendMessage({ role: 'assistant', content: '发送失败，请确认已登录邮箱账号后重试。' });
    } finally {
        sendBtn.disabled = false;
    }
}

function handleSSEEvent(data, assistantMsg) {
    switch (data.type) {
        case 'message':
            assistantMsg.content += data.content || '';
            updateLastMessage(assistantMsg);
            break;
        case 'interrupt':
            currentInterrupt = data.interrupt;
            showHitlModal(data.interrupt);
            break;
        case 'done':
            break;
        case 'error':
            console.error('Error:', data.error || data.content);
            break;
    }
}

function appendMessage(msg) {
    const container = document.getElementById('chatMessages');
    container.insertAdjacentHTML('beforeend', createMessageElement(msg));
    scrollToBottom();
}

function updateLastMessage(msg) {
    const container = document.getElementById('chatMessages');
    const messages = container.querySelectorAll('.message.assistant');
    const lastMsg = messages[messages.length - 1];
    if (lastMsg) {
        const bubble = lastMsg.querySelector('.message-bubble');
        bubble.innerHTML = parseMarkdown(msg.content);
    }
    scrollToBottom();
}

function updateSessionMessage(msg) {
    if (currentSession) {
        if (!currentSession.messages) currentSession.messages = [];
        currentSession.messages.push(msg);
    }
}

function clearChat() {
    document.getElementById('chatMessages').innerHTML = `
        <div class="empty-state" id="emptyState">
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
            </svg>
            <p>${isLoggedIn() ? '选择会话或创建新会话，开始使用 MailFriend' : '请先登录邮箱账号，再开始管理邮件'}</p>
        </div>
    `;
    document.getElementById('chatTitle').textContent = isLoggedIn() ? '选择一个会话开始聊天' : '请先登录邮箱账号';
    // 只有未登录时才禁用输入框；已登录未选中会话保持默认禁用（后面选会话时再启用）
    if (!isLoggedIn()) {
        document.getElementById('messageInput').disabled = true;
        document.getElementById('sendBtn').disabled = true;
    }
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    container.scrollTop = container.scrollHeight;
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);
    const dateDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    const timeStr = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

    if (dateDay.getTime() === today.getTime()) {
        return `今天 ${timeStr}`;
    } else if (dateDay.getTime() === yesterday.getTime()) {
        return `昨天 ${timeStr}`;
    } else if (dateDay.getTime() > today.getTime() - 7 * 86400000) {
        const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
        return `${days[date.getDay()]} ${timeStr}`;
    } else {
        return `${date.getMonth() + 1}月${date.getDate()}日 ${timeStr}`;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ========== 中断决策处理 ==========

async function sendInterruptDecision(decision) {
    closeHitlModal();

    const assistantMsg = { role: 'assistant', content: '' };
    appendMessage(assistantMsg);

    try {
        const response = await fetch(`${API_BASE}/api/v1/email/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: currentThreadId,
                interrupt_decision: decision,
                user_id: USER_ID || undefined
            })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const raw = line.slice(6);
                    try {
                        handleSSEEvent(JSON.parse(raw), assistantMsg);
                    } catch (e) { /* ignore */ }
                }
            }
        }
        updateSessionMessage(assistantMsg);
    } catch (error) {
        console.error('发送中断决策失败:', error);
    }
}

function approveInterrupt() {
    sendInterruptDecision({ type: 'approve' });
}

function rejectInterrupt() {
    document.getElementById('hitlModal').classList.remove('show');
    document.getElementById('rejectModal').classList.add('show');
    document.getElementById('rejectReasonInput').value = '';
    document.getElementById('rejectReasonInput').focus();
}

function closeRejectModal() {
    document.getElementById('rejectModal').classList.remove('show');
    // 用户取消 reject，重新打开 HITL 弹窗
    if (currentInterrupt) {
        document.getElementById('hitlModal').classList.add('show');
    }
}

function confirmReject() {
    const reason = document.getElementById('rejectReasonInput').value.trim();
    closeRejectModal();
    sendInterruptDecision({ type: 'reject', message: reason || '' });
}

function submitEdit() {
    const editedAction = {
        name: currentActionName || 'send_email',
        args: {
            to: document.getElementById('editTo').value,
            subject: document.getElementById('editSubject').value,
            body: document.getElementById('editBody').value
        }
    };
    sendInterruptDecision({ type: 'edit', edited_action: editedAction });
}

// ========== HITL 弹窗 ==========

function showHitlModal(interrupt) {
    const modal = document.getElementById('hitlModal');
    const body = document.getElementById('hitlModalBody');
    const footer = document.getElementById('hitlModalFooter');

    isEditMode = false;
    currentInterrupt = interrupt;
    currentActionName = '';

    const details = interrupt.details || interrupt || {};
    let action, params;
    if (Array.isArray(details) && details.length > 0) {
        const item = details[0];
        const actionReq = (item.action_requests && item.action_requests[0]) || {};
        action = actionReq.name || 'send_email';
        params = actionReq.args || {};
    } else if (details.action_requests) {
        const actionReq = details.action_requests[0] || {};
        action = actionReq.name || 'send_email';
        params = actionReq.args || {};
    } else {
        action = details.action || 'send_email';
        params = details.args || details.params || {};
    }
    currentActionName = action;

    body.innerHTML = `
        <div class="param-group">
            <label class="param-label">操作类型</label>
            <div class="param-value">${action}</div>
        </div>
        <div class="param-group">
            <label class="param-label">收件人</label>
            <div class="param-value" id="viewTo">${params.to || ''}</div>
            <input type="text" class="edit-input hidden" id="editTo" value="${params.to || ''}">
        </div>
        <div class="param-group">
            <label class="param-label">主题</label>
            <div class="param-value" id="viewSubject">${params.subject || ''}</div>
            <input type="text" class="edit-input hidden" id="editSubject" value="${params.subject || ''}">
        </div>
        <div class="param-group">
            <label class="param-label">内容</label>
            <div class="param-value" id="viewBody">${params.body || ''}</div>
            <textarea class="edit-input hidden" id="editBody">${params.body || ''}</textarea>
        </div>
    `;

    footer.innerHTML = `
        <button class="modal-btn cancel" onclick="closeHitlModal()">取消</button>
        <button class="modal-btn edit" onclick="showEditMode()">Edit</button>
        <button class="modal-btn reject" onclick="rejectInterrupt()">Reject</button>
        <button class="modal-btn approve" onclick="approveInterrupt()">Approve</button>
    `;

    modal.classList.add('show');
}

function closeHitlModal() {
    document.getElementById('hitlModal').classList.remove('show');
    currentInterrupt = null;
}

function showEditMode() {
    isEditMode = true;
    ['viewTo', 'viewSubject', 'viewBody'].forEach(id => document.getElementById(id).classList.add('hidden'));
    ['editTo', 'editSubject', 'editBody'].forEach(id => document.getElementById(id).classList.remove('hidden'));

    document.getElementById('hitlModalFooter').innerHTML = `
        <button class="modal-btn cancel" onclick="cancelEdit()">取消</button>
        <button class="modal-btn approve" onclick="submitEdit()">确认修改</button>
    `;
}

function cancelEdit() {
    isEditMode = false;
    ['viewTo', 'viewSubject', 'viewBody'].forEach(id => document.getElementById(id).classList.remove('hidden'));
    ['editTo', 'editSubject', 'editBody'].forEach(id => document.getElementById(id).classList.add('hidden'));

    document.getElementById('hitlModalFooter').innerHTML = `
        <button class="modal-btn cancel" onclick="closeHitlModal()">取消</button>
        <button class="modal-btn edit" onclick="showEditMode()">Edit</button>
        <button class="modal-btn reject" onclick="rejectInterrupt()">Reject</button>
        <button class="modal-btn approve" onclick="approveInterrupt()">Approve</button>
    `;
}
