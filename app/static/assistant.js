/**
 * 共享助手前端逻辑
 * 通过 URL 参数 ?type=travel|fitness|study|finance|copywriting|coding 区分助手类型
 */
(function () {
    'use strict';

    // 从 URL 获取助手类型
    var params = new URLSearchParams(window.location.search);
    var BIZ_TYPE = params.get('type') || 'travel';

    // 助手配置（前端本地映射）
    var ASSISTANT_INFO = {
        travel: { name: 'AI 旅行规划师', icon: '✈️', desc: '告诉我目的地、预算和时间，我来帮你规划完美旅程' },
        fitness: { name: 'AI 健身教练', icon: '💪', desc: '告诉我你的健身目标和当前状况，我来制定训练计划' },
        study: { name: 'AI 学习伴侣', icon: '📚', desc: '有什么学科问题尽管问，我来帮你逐步理解和解答' },
        finance: { name: 'AI 理财顾问', icon: '💰', desc: '告诉我你的收支情况，我来帮你做财务规划' },
        copywriting: { name: 'AI 文案写手', icon: '✍️', desc: '告诉我文案用途和风格，我来帮你写出好内容' },
        coding: { name: 'AI 编程助手', icon: '💻', desc: '有什么编程问题尽管问，代码、调试、技术答疑都行' },
    };

    var info = ASSISTANT_INFO[BIZ_TYPE] || ASSISTANT_INFO.travel;

    // 用户 ID
    var USER_ID = localStorage.getItem('mailfriend_current_user') || 'default_user';

    // DOM 元素
    var chatArea = document.getElementById('chatArea');
    var msgInput = document.getElementById('msgInput');
    var sendBtn = document.getElementById('sendBtn');
    var sessionList = document.getElementById('sessionList');
    var newSessionBtn = document.getElementById('newSessionBtn');
    var chatTitle = document.getElementById('chatTitle');
    var chatSubtitle = document.getElementById('chatSubtitle');
    var sidebarBrand = document.getElementById('sidebarBrand');
    var emptyIcon = document.getElementById('emptyIcon');
    var emptyDesc = document.getElementById('emptyDesc');
    var emptyState = document.getElementById('emptyState');
    var settingsBtn = document.getElementById('settingsBtn');
    var settingsPopover = document.getElementById('settingsPopover');
    var darkToggle = document.getElementById('darkToggle');
    var darkToggle2 = document.getElementById('darkToggle2');

    // 状态
    var isStreaming = false;
    var currentThreadId = '';

    // 批量管理状态
    var batchMode = false;
    var selectedThreads = {};
    var batchToolbar = document.getElementById('batchToolbar');
    var batchEditBtn = document.getElementById('batchEditBtn');
    var batchActionBar = document.getElementById('batchActionBar');
    var batchSelectAll = document.getElementById('batchSelectAll');
    var batchCount = document.getElementById('batchCount');
    var batchDeleteBtn = document.getElementById('batchDeleteBtn');
    var batchCancelBtn = document.getElementById('batchCancelBtn');

    // === 初始化页面 ===
    function initPage() {
        chatTitle.textContent = info.name;
        sidebarBrand.textContent = info.name;
        chatSubtitle.textContent = '智能对话 · 流式输出';
        emptyIcon.textContent = info.icon;
        emptyDesc.textContent = info.desc;
        document.title = info.name;

        // 应用主题
        applyTheme();

        // 加载会话列表
        loadSessions();

        // 自动获取或创建会话
        var savedTid = localStorage.getItem('assistant_thread_' + BIZ_TYPE);
        if (savedTid) {
            currentThreadId = savedTid;
            loadSessionMessages(savedTid);
        } else {
            createNewSession();
        }

        // 事件绑定
        bindEvents();
    }

    var VALID_THEMES = ['sage', 'misty-blue', 'dusty-rose', 'mauve', 'warm-gray', 'terracotta'];

    function applyTheme() {
        var theme = localStorage.getItem('theme') || 'sage';
        if (VALID_THEMES.indexOf(theme) === -1) theme = 'sage';
        if (theme !== 'sage') {
            document.documentElement.setAttribute('data-theme', theme);
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        var mode = localStorage.getItem('mode');
        if (mode === 'dark') {
            document.documentElement.setAttribute('data-mode', 'dark');
        } else {
            document.documentElement.removeAttribute('data-mode');
        }
        updateThemeDots();
        updateDarkToggle();
    }

    function setTheme(theme) {
        if (VALID_THEMES.indexOf(theme) === -1) return;
        if (theme === 'sage') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
        localStorage.setItem('theme', theme);
        updateThemeDots();
    }

    function toggleDarkMode() {
        var html = document.documentElement;
        var isDark = html.getAttribute('data-mode') === 'dark';
        if (isDark) {
            html.removeAttribute('data-mode');
            localStorage.setItem('mode', 'light');
        } else {
            html.setAttribute('data-mode', 'dark');
            localStorage.setItem('mode', 'dark');
        }
        updateDarkToggle();
    }

    function toggleSettings() {
        settingsPopover.classList.toggle('show');
    }

    function updateThemeDots() {
        var theme = localStorage.getItem('theme') || 'sage';
        document.querySelectorAll('.theme-dot').forEach(function (d) {
            d.classList.toggle('active', d.dataset.theme === theme);
        });
    }

    function updateDarkToggle() {
        var isDark = document.documentElement.getAttribute('data-mode') === 'dark';
        if (darkToggle) darkToggle.classList.toggle('active', isDark);
        if (darkToggle2) darkToggle2.classList.toggle('active', isDark);
    }

    // === 会话管理 ===
    function loadSessions() {
        fetch('/api/v1/sessions?user_id=' + encodeURIComponent(USER_ID) + '&biz_type=' + BIZ_TYPE)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                sessionList.innerHTML = '';
                var sessions = Array.isArray(data) ? data : (data.sessions || []);
                if (sessions.length === 0) {
                    sessionList.innerHTML = '<div class="session-empty">暂无会话</div>';
                    return;
                }
                sessions.forEach(function (s) {
                    var item = document.createElement('div');
                    item.className = 'session-item';
                    item.setAttribute('data-thread-id', s.thread_id);
                    if (s.thread_id === currentThreadId) item.classList.add('active');
                    var title = s.name || '新会话';
                    var time = formatTime(s.updated_at || s.created_at);
                    item.innerHTML =
                        '<input type="checkbox" class="session-checkbox" data-thread-id="' + s.thread_id + '">' +
                        '<div class="session-info">' +
                        '<div class="session-title">' + escapeHtml(title) + '</div>' +
                        '<div class="session-meta">' + time + '</div>' +
                        '</div>' +
                        '<button class="session-delete" title="删除">' +
                        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>' +
                        '</button>';
                    item.querySelector('.session-info').addEventListener('click', function () {
                        if (batchMode) {
                            toggleSelectItem(item, s.thread_id);
                            return;
                        }
                        switchSession(s.thread_id);
                    });
                    item.querySelector('.session-checkbox').addEventListener('click', function (e) {
                        e.stopPropagation();
                        toggleSelectItem(item, s.thread_id);
                    });
                    item.querySelector('.session-delete').addEventListener('click', function (e) {
                        e.stopPropagation();
                        deleteSession(s.thread_id);
                    });
                    sessionList.appendChild(item);
                });
                // 批量模式下恢复选中状态
                if (batchMode) updateBatchUI();
            })
            .catch(function () {
                sessionList.innerHTML = '<div class="session-empty">加载失败</div>';
            });
    }

    function formatTime(iso) {
        if (!iso) return '';
        try {
            var d = new Date(iso);
            if (isNaN(d.getTime())) return '';
            var now = new Date();
            var diff = (now - d) / 1000;
            if (diff < 60) return '刚刚';
            if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
            if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
            if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
            return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
        } catch (e) { return ''; }
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function createNewSession() {
        var name = info.name + ' ' + new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        fetch('/api/v1/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: USER_ID, biz_type: BIZ_TYPE, name: name })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.thread_id) {
                    currentThreadId = data.thread_id;
                    localStorage.setItem('assistant_thread_' + BIZ_TYPE, data.thread_id);
                    // 清空聊天区
                    showEmptyState();
                    loadSessions();
                }
            })
            .catch(function (e) { console.error('创建会话失败:', e); });
    }

    function switchSession(threadId) {
        if (currentThreadId === threadId) return;
        currentThreadId = threadId;
        localStorage.setItem('assistant_thread_' + BIZ_TYPE, threadId);
        // 更新选中状态
        var items = sessionList.querySelectorAll('.session-item');
        items.forEach(function (item) {
            item.classList.toggle('active', item.getAttribute('data-thread-id') === threadId);
        });
        loadSessionMessages(threadId);
    }

    function deleteSession(threadId) {
        if (!confirm('确定删除这个会话吗？')) return;
        fetch('/api/v1/sessions/' + threadId, { method: 'DELETE' })
            .then(function (r) { if (!r.ok) throw new Error('删除失败'); return r.json(); })
            .then(function () {
                if (currentThreadId === threadId) {
                    currentThreadId = '';
                    localStorage.removeItem('assistant_thread_' + BIZ_TYPE);
                    showEmptyState();
                    createNewSession();
                } else {
                    loadSessions();
                }
            })
            .catch(function (e) { alert('删除失败: ' + e.message); });
    }

    // === 消息加载 ===
    function loadSessionMessages(threadId) {
        fetch('/api/v1/sessions/' + threadId + '/messages?biz_type=' + BIZ_TYPE)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                chatArea.innerHTML = '';
                var messages = data.messages || [];
                if (messages.length === 0) {
                    showEmptyState();
                    return;
                }
                messages.forEach(function (msg) {
                    var role = (msg.role === 'human' || msg.role === 'user') ? 'user' : 'assistant';
                    appendMessage(role, msg.content || '');
                });
                chatArea.scrollTop = chatArea.scrollHeight;
            })
            .catch(function (e) {
                console.error('加载消息失败:', e);
                showEmptyState();
            });
    }

    function showEmptyState() {
        chatArea.innerHTML = '';
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.innerHTML =
            '<div class="empty-icon">' + info.icon + '</div>' +
            '<div class="empty-title">开始对话</div>' +
            '<div class="empty-desc">' + info.desc + '</div>';
        chatArea.appendChild(empty);
    }

    // === 消息渲染 ===
    function appendMessage(role, text) {
        var msg = document.createElement('div');
        msg.className = 'msg msg-' + role;

        var avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.textContent = role === 'user' ? '🧑' : info.icon;

        var content = document.createElement('div');
        content.className = 'msg-content';
        if (role === 'assistant' && text) {
            content.innerHTML = renderMarkdown(text);
        } else if (text) {
            content.textContent = text;
        }

        msg.appendChild(avatar);
        msg.appendChild(content);
        chatArea.appendChild(msg);
        chatArea.scrollTop = chatArea.scrollHeight;
        return content;
    }

    function renderMarkdown(text) {
        if (typeof marked !== 'undefined' && marked.parse) {
            try {
                return marked.parse(text);
            } catch (e) {
                return escapeHtml(text).replace(/\n/g, '<br>');
            }
        }
        // 简易 Markdown 渲染
        var html = escapeHtml(text);
        html = html.replace(/### (.+)/g, '<h3>$1</h3>');
        html = html.replace(/## (.+)/g, '<h2>$1</h2>');
        html = html.replace(/# (.+)/g, '<h1>$1</h1>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/`(.+?)`/g, '<code>$1</code>');
        html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        html = html.replace(/\n\n/g, '</p><p>');
        html = '<p>' + html + '</p>';
        return html;
    }

    // === 发送消息 ===
    function sendMessage() {
        var text = msgInput.value.trim();
        if (!text || isStreaming) return;
        if (!currentThreadId) {
            alert('会话初始化中，请稍后...');
            return;
        }

        // 移除空状态
        var empty = chatArea.querySelector('.empty-state');
        if (empty) empty.remove();

        // 显示用户消息
        appendMessage('user', text);

        // 清空输入框
        msgInput.value = '';
        autoResize();
        sendBtn.disabled = true;
        isStreaming = true;

        // 创建助手消息占位
        var contentEl = appendMessage('assistant', '');
        contentEl.classList.add('thinking');

        var fullText = '';
        var sawFirstChunk = false;

        fetch('/api/v1/assistant/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                thread_id: currentThreadId,
                biz_type: BIZ_TYPE
            })
        })
            .then(function (response) {
                if (!response.ok) throw new Error('API错误: ' + response.status);
                var reader = response.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';

                function readChunk() {
                    reader.read().then(function (result) {
                        if (result.done) {
                            isStreaming = false;
                            sendBtn.disabled = false;
                            if (fullText && fullText.replace(/\s/g, '') !== '') {
                                renderFinal();
                            }
                            return;
                        }
                        buffer += decoder.decode(result.value, { stream: true });

                        // SSE 解析
                        var messages = buffer.split('\n\n');
                        buffer = messages.pop();

                        for (var i = 0; i < messages.length; i++) {
                            var message = messages[i].trim();
                            if (!message) continue;

                            var payload = message;
                            if (payload.indexOf('data:') === 0) {
                                payload = payload.slice(5).trim();
                            }
                            if (!payload || payload === '[DONE]') continue;

                            // 还原转义字符
                            payload = payload
                                .replace(/\\r\\n/g, '\n')
                                .replace(/\\n/g, '\n')
                                .replace(/\\t/g, '\t')
                                .replace(/\\"/g, '"')
                                .replace(/\\\\/g, '\\');

                            // 跳过占位字符
                            if (!sawFirstChunk) {
                                var visible = payload.replace(/[\u200B-\u200D\uFEFF]/g, '');
                                if (visible === '') continue;
                                sawFirstChunk = true;
                            }
                            fullText += payload;

                            // 流式渲染（思考模式）
                            contentEl.textContent = fullText;
                            contentEl.classList.add('thinking');
                            chatArea.scrollTop = chatArea.scrollHeight;
                        }
                        readChunk();
                    }).catch(function (err) {
                        isStreaming = false;
                        sendBtn.disabled = false;
                        appendMessage('assistant', '回复失败: ' + err.message);
                    });
                }
                readChunk();
            })
            .catch(function (err) {
                isStreaming = false;
                sendBtn.disabled = false;
                appendMessage('assistant', '连接失败: ' + err.message);
            });

        // 最终渲染：移除思考样式，用 Markdown 渲染
        function renderFinal() {
            contentEl.classList.remove('thinking');
            contentEl.innerHTML = renderMarkdown(fullText);
            chatArea.scrollTop = chatArea.scrollHeight;
        }
    }

    // === 事件绑定 ===
    function bindEvents() {
        sendBtn.addEventListener('click', sendMessage);

        msgInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        msgInput.addEventListener('input', function () {
            autoResize();
            sendBtn.disabled = this.value.trim() === '' || isStreaming;
        });

        newSessionBtn.addEventListener('click', function () {
            if (isStreaming) {
                alert('请等待当前回复完成');
                return;
            }
            createNewSession();
        });

        // 设置面板
        if (settingsBtn) {
            settingsBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                toggleSettings();
            });
        }
        // 点击外部关闭设置面板
        document.addEventListener('click', function (e) {
            if (settingsPopover && settingsPopover.classList.contains('show')) {
                if (!settingsPopover.contains(e.target) && e.target !== settingsBtn) {
                    settingsPopover.classList.remove('show');
                }
            }
        });
        // 主题切换
        document.querySelectorAll('.theme-dot').forEach(function (dot) {
            dot.addEventListener('click', function () {
                setTheme(dot.dataset.theme);
            });
        });
        // 夜间模式
        if (darkToggle) darkToggle.addEventListener('click', toggleDarkMode);
        if (darkToggle2) darkToggle2.addEventListener('click', toggleDarkMode);

        // 批量管理
        if (batchEditBtn) batchEditBtn.addEventListener('click', enterBatchMode);
        if (batchCancelBtn) batchCancelBtn.addEventListener('click', exitBatchMode);
        if (batchSelectAll) batchSelectAll.addEventListener('change', function () {
            selectAllBatch(this.checked);
        });
        if (batchDeleteBtn) batchDeleteBtn.addEventListener('click', deleteSelectedBatch);
    }

    // === 批量管理 ===
    function enterBatchMode() {
        batchMode = true;
        selectedThreads = {};
        sessionList.classList.add('batch-mode');
        batchActionBar.classList.add('show');
        batchEditBtn.style.display = 'none';
        updateBatchUI();
    }

    function exitBatchMode() {
        batchMode = false;
        selectedThreads = {};
        sessionList.classList.remove('batch-mode');
        batchActionBar.classList.remove('show');
        batchEditBtn.style.display = '';
        // 清除选中态
        sessionList.querySelectorAll('.session-item').forEach(function (item) {
            item.classList.remove('selected');
            var cb = item.querySelector('.session-checkbox');
            if (cb) cb.checked = false;
        });
        if (batchSelectAll) batchSelectAll.checked = false;
    }

    function toggleSelectItem(item, threadId) {
        if (selectedThreads[threadId]) {
            delete selectedThreads[threadId];
            item.classList.remove('selected');
            var cb = item.querySelector('.session-checkbox');
            if (cb) cb.checked = false;
        } else {
            selectedThreads[threadId] = true;
            item.classList.add('selected');
            var cb2 = item.querySelector('.session-checkbox');
            if (cb2) cb2.checked = true;
        }
        updateBatchUI();
    }

    function updateBatchUI() {
        var count = Object.keys(selectedThreads).length;
        if (batchCount) batchCount.textContent = '已选 ' + count + ' 项';
        if (batchDeleteBtn) batchDeleteBtn.disabled = count === 0;
        // 同步全选状态
        var items = sessionList.querySelectorAll('.session-item');
        var allChecked = items.length > 0 && count === items.length;
        if (batchSelectAll) batchSelectAll.checked = allChecked;
        // 恢复已选中项的视觉态
        items.forEach(function (item) {
            var tid = item.getAttribute('data-thread-id');
            var cb = item.querySelector('.session-checkbox');
            if (selectedThreads[tid]) {
                item.classList.add('selected');
                if (cb) cb.checked = true;
            } else {
                item.classList.remove('selected');
                if (cb) cb.checked = false;
            }
        });
    }

    function selectAllBatch(checked) {
        var items = sessionList.querySelectorAll('.session-item');
        items.forEach(function (item) {
            var tid = item.getAttribute('data-thread-id');
            var cb = item.querySelector('.session-checkbox');
            if (checked) {
                selectedThreads[tid] = true;
                item.classList.add('selected');
                if (cb) cb.checked = true;
            } else {
                delete selectedThreads[tid];
                item.classList.remove('selected');
                if (cb) cb.checked = false;
            }
        });
        updateBatchUI();
    }

    function deleteSelectedBatch() {
        var tids = Object.keys(selectedThreads);
        if (tids.length === 0) return;
        if (!confirm('确定要删除选中的 ' + tids.length + ' 个会话吗？此操作不可撤销。')) return;
        batchDeleteBtn.disabled = true;
        batchDeleteBtn.textContent = '删除中...';
        var promises = tids.map(function (tid) {
            return fetch('/api/v1/sessions/' + tid, { method: 'DELETE' })
                .then(function (r) { if (!r.ok) throw new Error('删除失败'); return r.json(); })
                .catch(function (e) { console.error('删除会话失败 ' + tid + ':', e); });
        });
        Promise.all(promises).then(function () {
            // 若当前会话被删除，则新建会话
            if (selectedThreads[currentThreadId]) {
                currentThreadId = '';
                localStorage.removeItem('assistant_thread_' + BIZ_TYPE);
                showEmptyState();
                exitBatchMode();
                loadSessions();
                createNewSession();
            } else {
                exitBatchMode();
                loadSessions();
            }
            batchDeleteBtn.disabled = false;
            batchDeleteBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>删除所选';
        });
    }

    function autoResize() {
        msgInput.style.height = 'auto';
        msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
    }

    // === 启动 ===
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPage);
    } else {
        initPage();
    }
})();
