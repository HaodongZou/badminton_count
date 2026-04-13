/**
 * Badminton Score Recorder - JavaScript
 */

// API Base URL
const API_BASE = '';

// Auth keys
const SESSION_KEY = 'badminton_session';
const USER_KEY = 'badminton_user';

// Current user state
let currentUser = null;
let isGuest = false;
let isAdminUser = false;

// Current selected player (default '我')
let currentPlayer = '我';

// Current pending match text for preview
let pendingMatchText = '';
let pendingParsed = null;  // LLM 解析后的结构化结果，供 confirmSave 使用

let currentMatchFilter = 'all'; // all, admin, mine

// Current arrangement data
let currentArrangement = null;

// Get auth headers for API requests
function getAuthHeaders() {
    const token = localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY);
    if (token) {
        return { 'Authorization': `Bearer ${token}` };
    }
    return {};
}

// Check authentication and redirect if not logged in
async function checkAuth() {
    const token = localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY);
    if (!token) {
        // 无token，可能是访客或未登录
        isGuest = true;
        currentUser = '访客';
        return true; // 允许访问，但在前端限制功能
    }

    try {
        const response = await fetch(`${API_BASE}/api/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) {
            const data = await response.json();
            if (data.is_guest) {
                isGuest = true;
                currentUser = '访客';
            } else {
                isGuest = false;
                currentUser = data.user;
            }
            isAdminUser = data.is_admin || false;
            return true;
        } else {
            // token无效
            isGuest = true;
            currentUser = '访客';
            return true; // 仍然允许访问（访客模式）
        }
    } catch (e) {
        isGuest = true;
        currentUser = '访客';
        return true;
    }
}

// Logout function
function logout() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(USER_KEY);
    window.location.href = '/login';
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    // Skip auth check if on login page
    if (window.location.pathname === '/login') return;

    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) return;

    initTabs();
    loadPlayerFilterChips();
    loadRecords();
    loadPlayers();
    applyPermissions();
});

function applyPermissions() {
    // 访客：隐藏添加比赛相关的UI
    if (isGuest) {
        // 隐藏积分板Tab中的预览/保存按钮
        const previewSection = document.getElementById('previewSection');
        if (previewSection) previewSection.style.display = 'none';

        const matchInput = document.getElementById('matchInput');
        if (matchInput) matchInput.placeholder = '访客模式仅可查看和排列';
    }
}

// Tab Navigation
function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.dataset.tab;

            // Update tab buttons
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Update tab content
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');

            // Load data for the tab
            if (tabId === 'records') loadRecords();
            if (tabId === 'stats') {
                loadPlayers();
                loadStats(currentPlayer);
            }
            if (tabId === 'rankings') loadRankings();
        });
    });
}

// Show Toast Notification
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// Preview Match - LLM parse and show result for confirmation
let isParsing = false;

async function previewMatch() {
    const input = document.getElementById('matchInput').value.trim();
    if (!input) {
        showToast('请输入比赛信息', 'error');
        return;
    }

    if (isParsing) return;
    isParsing = true;
    setParseButtonLoading(true);
    pendingMatchText = input;

    try {
        // Step 1: LLM 解析
        const parseRes = await fetch(`${API_BASE}/api/parse_nl`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: input })
        });
        const parseData = await parseRes.json();

        if (parseData.error) {
            showToast(parseData.error, 'error');
            showManualInputOption();
            return;
        }

        // Step 2: 构造 game_results 供预览展示
        const gameResults = [];
        const scores = parseData.scores || [];
        for (let i = 0; i < scores.length; i++) {
            const [myScore, oppScore] = scores[i];
            gameResults.push({
                game: i + 1,
                my_score: myScore,
                opp_score: oppScore,
                result: myScore > oppScore ? '赢' : '输'
            });
        }

        // 保存解析结果供 confirmSave 使用
        pendingParsed = parseData;

        showPreview({ parsed: parseData, game_results: gameResults });

    } catch (error) {
        showToast('解析失败：' + error.message, 'error');
        showManualInputOption();
    } finally {
        isParsing = false;
        setParseButtonLoading(false);
    }
}

function setParseButtonLoading(loading) {
    const btn = document.getElementById('parseBtn');
    if (!btn) return;
    if (loading) {
        btn.disabled = true;
        btn.classList.add('loading');
        btn.dataset.originalHTML = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-sm"></span><span>解析中...</span>';
    } else {
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.innerHTML = btn.dataset.originalHTML || '<span>🔍</span><span>解析并预览</span>';
    }
}

function showManualInputOption() {
    const section = document.querySelector('.input-section');
    const existing = document.getElementById('manualInputBanner');
    if (existing) return;
    const banner = document.createElement('div');
    banner.id = 'manualInputBanner';
    banner.className = 'manual-input-banner';
    banner.innerHTML = `
        <span>解析失败？</span>
        <button class="preview-btn secondary small" onclick="switchToManualInput()">手动录入</button>
    `;
    section.appendChild(banner);
}

function switchToManualInput() {
    document.getElementById('manualInputBanner')?.remove();
    const manualSection = document.getElementById('manualInputSection');
    if (manualSection) {
        manualSection.style.display = 'block';
        manualSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function toggleManualInput() {
    const section = document.getElementById('manualInputSection');
    if (!section) return;
    const isHidden = section.style.display === 'none' || section.style.display === '';
    section.style.display = isHidden ? 'block' : 'none';
    if (isHidden) {
        section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        // 同步 match type → 显示/隐藏第二球员输入框
        toggleTeamInputs();
    }
}

function toggleTeamInputs() {
    const matchType = document.getElementById('manualMatchType')?.value;
    const my2 = document.getElementById('myPlayer2');
    const opp2 = document.getElementById('oppPlayer2');
    if (!my2 || !opp2) return;
    const isDoubles = matchType === 'doubles';
    my2.style.display = isDoubles ? 'inline-block' : 'none';
    my2.required = isDoubles;
    opp2.style.display = isDoubles ? 'inline-block' : 'none';
    opp2.required = isDoubles;
}

function toggleThirdSet() {
    const row = document.getElementById('score3Row');
    const btn = document.getElementById('addThirdSetBtn');
    if (!row) return;
    const isHidden = row.style.display === 'none';
    row.style.display = isHidden ? 'flex' : 'none';
    if (btn) btn.textContent = isHidden ? '- 第3局' : '+ 第3局';
}

function submitManualInput() {
    const matchType = document.getElementById('manualMatchType')?.value || 'singles';
    const myPlayer1 = document.getElementById('myPlayer1')?.value.trim();
    const myPlayer2 = document.getElementById('myPlayer2')?.value.trim();
    const oppPlayer1 = document.getElementById('oppPlayer1')?.value.trim();
    const oppPlayer2 = document.getElementById('oppPlayer2')?.value.trim();

    if (!myPlayer1 || !oppPlayer1) {
        showToast('请填写双方球员', 'error');
        return;
    }

    if (matchType === 'doubles' && (!myPlayer2 || !oppPlayer2)) {
        showToast('双打需要填写双方各两名球员', 'error');
        return;
    }

    const myTeam = matchType === 'doubles'
        ? [myPlayer1, myPlayer2].filter(Boolean)
        : [myPlayer1];
    const oppTeam = matchType === 'doubles'
        ? [oppPlayer1, oppPlayer2].filter(Boolean)
        : [oppPlayer1];

    const scores = [];
    const pushScore = (idx) => {
        const my = parseInt(document.getElementById(`score${idx}_1`)?.value) || 0;
        const opp = parseInt(document.getElementById(`score${idx}_2`)?.value) || 0;
        if (my > 0 || opp > 0) scores.push([my, opp]);
    };
    pushScore(1);
    pushScore(2);
    if (document.getElementById('score3Row')?.style.display !== 'none') {
        pushScore(3);
    }

    if (scores.length === 0) {
        showToast('请至少填写一局比分', 'error');
        return;
    }

    const parsed = { my_team: myTeam, opponent_team: oppTeam, scores, match_type: matchType };

    const gameResults = scores.map(([myScore, oppScore], i) => ({
        game: i + 1,
        my_score: myScore,
        opp_score: oppScore,
        result: myScore > oppScore ? '赢' : '输'
    }));

    pendingParsed = parsed;
    pendingMatchText = '(手动录入)';
    showPreview({ parsed, game_results: gameResults });
}

function showPreview(data) {
    const previewSection = document.getElementById('previewSection');
    const previewContent = document.getElementById('previewContent');

    const parsed = data.parsed;
    const gameResults = data.game_results;
    const matchType = parsed.match_type === 'singles' ? '单打' : '双打';

    previewContent.innerHTML = `
        <div class="preview-type">${matchType}</div>
        <div class="preview-teams">
            <div class="preview-team me">
                <div class="preview-team-label">我方</div>
                <div class="preview-team-name">${parsed.my_team.join('、')}</div>
            </div>
            <div class="preview-vs">VS</div>
            <div class="preview-team opp">
                <div class="preview-team-label">对方</div>
                <div class="preview-team-name">${parsed.opponent_team.join('、')}</div>
            </div>
        </div>
        <div class="preview-games">
            ${gameResults.map(g => `
                <div class="preview-game">
                    <span class="preview-game-label">第${g.game}局</span>
                    <span class="preview-game-score">
                        <span class="my-score">${g.my_score}</span>
                        <span>:</span>
                        <span class="opp-score">${g.opp_score}</span>
                    </span>
                    <span class="preview-game-result ${g.result === '赢' ? 'win' : 'lose'}">${g.result}</span>
                </div>
            `).join('')}
        </div>
    `;

    previewSection.style.display = 'block';
}

function hidePreview() {
    document.getElementById('previewSection').style.display = 'none';
    pendingMatchText = '';
    pendingParsed = null;
}

async function confirmSave() {
    if (!pendingParsed) {
        showToast('请先解析比赛信息', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/matches`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({
                // 直接传结构化数据，不再传 text 走后端正则解析
                my_team: pendingParsed.my_team,
                opponent_team: pendingParsed.opponent_team,
                scores: pendingParsed.scores,
                match_type: pendingParsed.match_type,
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || '保存失败');
        }

        showToast('比赛记录已保存！', 'success');
        document.getElementById('matchInput').value = '';
        hidePreview();
        pendingMatchText = '';
        pendingParsed = null;
        loadRecords();
        loadPlayers();

    } catch (error) {
        showToast(error.message, 'error');
    }
}

// Debounce utility
function debounce(fn, delay) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// Update filter button active states
function updateFilterButtons() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === currentMatchFilter);
    });
}

// Load Records (merged: supports both filter and players parameters)
async function loadRecords() {
    const container = document.getElementById('recordsContainer');

    try {
        let url = `${API_BASE}/api/matches`;
        const params = new URLSearchParams();
        if (currentMatchFilter !== 'all') params.set('filter', currentMatchFilter);
        if (selectedPlayersForFilter.length > 0) params.set('players', selectedPlayersForFilter.join(','));
        if (params.toString()) url += '?' + params.toString();
        const response = await fetch(url, { headers: getAuthHeaders() });
        const data = await response.json();
        const matches = data.matches || [];

        updateFilterButtons();

        if (matches.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🏸</div>
                    <div class="empty-title">暂无比赛记录</div>
                    <p>${currentMatchFilter === 'mine' ? '您还没有添加过比赛记录' : '去记分板添加你的第一场比赛吧！'}</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="records-grid">
                ${matches.map(match => renderRecordCard(match)).join('')}
            </div>
        `;

    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-title">加载失败</div>
                <p>${error.message}</p>
            </div>
        `;
    }
}

// Debounced version for use in player filter (avoids rapid-fire API calls)
const debouncedLoadRecords = debounce(loadRecords, 300);

// State for multi-player filter in records tab
let selectedPlayersForFilter = [];  // 多选球员筛选

// Load player chips for filter
async function loadPlayerFilterChips() {
    const container = document.getElementById('playerFilterChips');
    try {
        const response = await fetch(`${API_BASE}/api/players`, { headers: getAuthHeaders() });
        const players = await response.json();

        container.innerHTML = players.map(player => `
            <button class="player-chip filter-chip ${selectedPlayersForFilter.includes(player) ? 'active' : ''}"
                    data-player="${player}"
                    onclick="togglePlayerFilter('${player}')">
                ${player}
            </button>
        `).join('');
    } catch (error) {
        console.error('Failed to load player chips:', error);
    }
}

function togglePlayerFilter(player) {
    const idx = selectedPlayersForFilter.indexOf(player);
    if (idx >= 0) {
        selectedPlayersForFilter.splice(idx, 1);
    } else {
        selectedPlayersForFilter.push(player);
    }
    loadPlayerFilterChips();
    debouncedLoadRecords();
}

function clearPlayerFilter() {
    selectedPlayersForFilter = [];
    loadPlayerFilterChips();
    debouncedLoadRecords();
}

// Delete Match
async function deleteMatch(matchId) {
    if (!confirm('确定要删除这条记录吗？')) return;

    try {
        const response = await fetch(`${API_BASE}/api/matches/${matchId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            showToast('记录已删除', 'success');
            loadRecords();
            loadPlayers();
        } else {
            showToast('删除失败', 'error');
        }
    } catch (error) {
        showToast('删除失败', 'error');
    }
}

// Render Record Card
function renderRecordCard(match) {
    const date = new Date(match.date);
    const day = date.getDate();
    const monthYear = `${date.getMonth() + 1}月${date.getFullYear()}`;

    const myTeam = match.my_team.split(',').map(p => p.trim()).join('、');
    const oppTeam = match.opponent_team.split(',').map(p => p.trim()).join('、');

    const matchType = match.match_type === 'singles' ? '单打' : '双打';

    // Calculate game wins/losses
    let myWins = 0, oppWins = 0;
    match.scores.forEach(s => {
        if (s[0] > s[1]) myWins++;
        else oppWins++;
    });

    // Determine result style and text
    const isAllWins = myWins > 0 && oppWins === 0;
    const isAllLosses = myWins === 0 && oppWins > 0;
    const isSplit = myWins === oppWins;
    const resultClass = isAllWins ? 'all-wins' : (isAllLosses ? 'all-losses' : 'split');
    const resultText = `${myWins}胜${oppWins}负 ${isAllWins ? '胜' : (isAllLosses ? '负' : '平')}`;

    // 创建者标签
    const isCreatedByAdmin = match.created_by === 'admin';
    const creatorLabel = isCreatedByAdmin ? '管理员' : match.created_by;
    const creatorClass = isCreatedByAdmin ? 'creator-admin' : 'creator-user';

    // 编辑和删除按钮权限
    const canEdit = isAdminUser || (currentUser === match.created_by && !isGuest);
    const canDelete = isAdminUser || (currentUser === match.created_by && !isGuest);
    const editBtn = canEdit
        ? `<button class="record-action-btn edit" onclick="editMatch(${match.id})" title="编辑">✏️</button>`
        : '';
    const deleteBtn = canDelete
        ? `<button class="record-action-btn delete" onclick="deleteMatch(${match.id})" title="删除">🗑️</button>`
        : '';

    return `
        <div class="record-card">
            <div class="record-date">
                <div class="day">${day}</div>
                <div class="month-year">${monthYear}</div>
            </div>
            <div class="record-info">
                <div class="record-players">
                    <span class="match-type-badge">${matchType}</span>
                    <span class="team">🟢 ${myTeam}</span>
                    <span class="vs">VS</span>
                    <span class="team">🔴 ${oppTeam}</span>
                </div>
                <div class="record-scores">
                    ${match.scores.map((s, i) => `
                        <span class="score-badge ${s[0] > s[1] ? 'win' : 'lose'}">
                            ${s[0]}:${s[1]}
                        </span>
                    `).join('')}
                </div>
                <div class="record-creator">
                    <span class="creator-badge ${creatorClass}">${creatorLabel}</span>
                </div>
            </div>
            <div class="record-result ${resultClass}">
                ${resultText}
            </div>
            <div class="record-actions">
                ${editBtn}
                ${deleteBtn}
            </div>
        </div>
    `;
}

// Edit Match - show modal
let editingMatchId = null;
let editingMatchData = null;

async function editMatch(matchId) {
    editingMatchId = matchId;

    try {
        const response = await fetch(`${API_BASE}/api/matches`, { headers: getAuthHeaders() });
        const matches = await response.json();
        const match = matches.find(m => m.id === matchId);
        if (!match) {
            showToast('未找到比赛记录', 'error');
            return;
        }
        editingMatchData = match;
        showEditMatchModal(match);
    } catch (e) {
        showToast('加载失败', 'error');
    }
}

function showEditMatchModal(match) {
    const modal = document.getElementById('editMatchModal');
    const form = document.getElementById('editMatchForm');
    const hint = document.getElementById('editMatchHint');

    const myTeam = match.my_team.split(',').map(p => p.trim()).join('、');
    const oppTeam = match.opponent_team.split(',').map(p => p.trim()).join('、');
    hint.textContent = `${myTeam} VS ${oppTeam}`;

    form.innerHTML = match.scores.map((score, i) => `
        <div class="form-group score-edit-group">
            <label>第${i + 1}局</label>
            <div class="score-inputs">
                <input type="number" class="score-input" id="score1_${i}" value="${score[0]}" min="0" max="99">
                <span class="score-separator">:</span>
                <input type="number" class="score-input" id="score2_${i}" value="${score[1]}" min="0" max="99">
            </div>
        </div>
    `).join('');

    modal.classList.add('show');
}

function closeEditMatchModal() {
    document.getElementById('editMatchModal').classList.remove('show');
    editingMatchId = null;
    editingMatchData = null;
}

function saveEditMatch() {
    if (!editingMatchData) return;

    const newScores = editingMatchData.scores.map((_, i) => {
        const score1 = parseInt(document.getElementById(`score1_${i}`).value) || 0;
        const score2 = parseInt(document.getElementById(`score2_${i}`).value) || 0;
        return [score1, score2];
    });

    updateMatch(editingMatchId, newScores);
    closeEditMatchModal();
}

async function updateMatch(matchId, scores) {
    try {
        const response = await fetch(`${API_BASE}/api/matches/${matchId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ scores })
        });

        if (response.ok) {
            showToast('比分已更新', 'success');
            loadRecords();
            loadPlayers();
        } else {
            showToast('更新失败', 'error');
        }
    } catch (error) {
        showToast('更新失败', 'error');
    }
}

// Load Players
async function loadPlayers() {
    try {
        const response = await fetch(`${API_BASE}/api/players`, { headers: getAuthHeaders() });
        const players = await response.json();

        // Always include '我' first
        const allPlayers = ['我', ...players.filter(p => p !== '我')];

        const selector = document.getElementById('playerSelector');
        selector.innerHTML = allPlayers.map(player => `
            <button class="player-chip ${player === currentPlayer ? 'active' : ''}"
                    data-player="${player}"
                    onclick="selectPlayer('${player}')">
                ${player}
            </button>
        `).join('');

        // Add long-press handlers for delete (except '我')
        addLongPressHandlers();

    } catch (error) {
        console.error('Failed to load players:', error);
    }
}

function addLongPressHandlers() {
    document.querySelectorAll('.player-chip[data-player]').forEach(chip => {
        const playerName = chip.dataset.player;
        if (playerName === '我') return;

        let pressTimer;
        let isLongPress = false;

        chip.addEventListener('mousedown', (e) => {
            e.preventDefault();
            isLongPress = false;
            pressTimer = setTimeout(() => {
                isLongPress = true;
                chip.dataset.hintShown = 'true';
                setTimeout(() => {
                    chip.dataset.hintShown = 'false';
                }, 1500);
            }, 1500);
        });

        chip.addEventListener('mouseup', (e) => {
            clearTimeout(pressTimer);
            if (isLongPress) {
                e.preventDefault();
                deletePlayer(playerName);
            }
        });

        chip.addEventListener('mouseleave', () => {
            clearTimeout(pressTimer);
        });

        // Touch events for mobile
        chip.addEventListener('touchstart', (e) => {
            isLongPress = false;
            pressTimer = setTimeout(() => {
                isLongPress = true;
                e.preventDefault();
                deletePlayer(playerName);
            }, 1500);
        });

        chip.addEventListener('touchend', () => {
            clearTimeout(pressTimer);
        });

        chip.addEventListener('touchmove', () => {
            clearTimeout(pressTimer);
        });
    });
}

async function deletePlayer(name) {
    if (!confirm(`确定要删除选手"${name}"吗？\n\n这将同时删除：\n- 该选手的所有别名\n- 该选手参与的所有比赛记录\n\n此操作不可恢复！`)) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/players/${encodeURIComponent(name)}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            showToast('已删除', 'success');
            currentPlayer = '我';
            loadPlayers();
            loadStats('我');
        } else {
            showToast('删除失败', 'error');
        }
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

// Select Player
let currentPeriod = 'all';
let currentOpponentFilter = '';

function setTimePeriod(period) {
    currentPeriod = period;
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.period === period);
    });
    loadStats(currentPlayer);
}

function setOpponentFilter() {
    currentOpponentFilter = document.getElementById('opponentFilter').value;
    loadStats(currentPlayer);
}

function selectPlayer(player) {
    currentPlayer = player;
    loadPlayers();
    loadStats(player);

    // If alias panel is open, update and reload
    const content = document.getElementById('aliasContent');
    if (content.style.display !== 'none') {
        document.getElementById('aliasSectionTitle').textContent = `${player} 的别名`;
        loadAliases();
    }
}

function updateOpponentDropdown(opponents) {
    const select = document.getElementById('opponentFilter');
    const currentValue = select.value;

    select.innerHTML = '<option value="">所有对手</option>';
    opponents.forEach(opp => {
        const option = document.createElement('option');
        option.value = opp.name;
        option.textContent = `${opp.name} (${opp.games}场)`;
        select.appendChild(option);
    });

    if (currentValue) {
        select.value = currentValue;
    }
}

function filterByOpponent(opponentName) {
    // 1. 切换到 records tab
    const recordsTab = document.querySelector('[data-tab="records"]');
    if (recordsTab) {
        recordsTab.click();
    } else {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById('records').classList.add('active');
    }

    // 2. 添加到球员筛选（如果当前玩家已选择的话追加，否则只选对手）
    if (!selectedPlayersForFilter.includes(currentPlayer)) {
        selectedPlayersForFilter = [currentPlayer];
    }
    if (!selectedPlayersForFilter.includes(opponentName)) {
        selectedPlayersForFilter.push(opponentName);
    }

    // 3. 更新球员筛选UI并加载记录
    loadPlayerFilterChips();
    loadRecords();
}

// Toggle Aliases visibility
function toggleAliases() {
    const content = document.getElementById('aliasContent');
    const icon = document.getElementById('aliasToggleIcon');
    const title = document.getElementById('aliasSectionTitle');
    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.textContent = '▼';
        title.textContent = `${currentPlayer} 的别名`;
        loadAliases();
    } else {
        content.style.display = 'none';
        icon.textContent = '▶';
    }
}

// Load Aliases
async function loadAliases() {
    const container = document.getElementById('aliasesContainer');

    try {
        const response = await fetch(`${API_BASE}/api/aliases`, { headers: getAuthHeaders() });
        const aliases = await response.json();

        // Only show aliases for current player
        const playerAliases = aliases.filter(a => a.canonical_name === currentPlayer);

        if (playerAliases.length === 0) {
            container.innerHTML = `
                <div class="alias-empty">
                    <p>还没有别名</p>
                    <button class="alias-add-btn-small" onclick="showAddAliasModal()">+ 添加</button>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="alias-list-compact">
                    ${playerAliases.map(a => `
                        <div class="alias-tag">
                            <span>${a.alias}</span>
                            <button class="alias-tag-delete" onclick="deleteAlias(${a.id})">✕</button>
                        </div>
                    `).join('')}
                    <button class="alias-add-btn-small" onclick="showAddAliasModal()">+ 添加</button>
                </div>
            `;
        }
    } catch (error) {
        container.innerHTML = '<div class="alias-empty">加载失败</div>';
    }
}

// Show Add Alias Modal
function showAddAliasModal() {
    document.getElementById('aliasModal').classList.add('show');
    document.getElementById('aliasInput').value = '';
    document.getElementById('canonicalDisplay').textContent = currentPlayer;
    document.getElementById('aliasInput').focus();
}

// Close Alias Modal
function closeAliasModal() {
    document.getElementById('aliasModal').classList.remove('show');
}

// Add Alias
async function addAlias() {
    const alias = document.getElementById('aliasInput').value.trim();
    const canonical = currentPlayer;

    if (!alias) {
        showToast('请输入别名', 'error');
        return;
    }

    if (alias === canonical) {
        showToast('别名不能与选手名字相同', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/api/aliases`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ alias, canonical_name: canonical })
        });

        if (response.ok) {
            showToast('别名已添加', 'success');
            closeAliasModal();
            loadAliases();
            loadPlayers();
            loadStats(currentPlayer);
            loadRankings();
        } else {
            const data = await response.json();
            showToast(data.error || '添加失败', 'error');
        }
    } catch (error) {
        showToast('添加失败', 'error');
    }
}

// Delete Alias
async function deleteAlias(aliasId) {
    if (!confirm('确定要删除这个别名吗？')) return;

    try {
        const response = await fetch(`${API_BASE}/api/aliases/${aliasId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            showToast('别名已删除', 'success');
            loadAliases();
            loadPlayers();
            loadStats(currentPlayer);
            loadRankings();
        } else {
            showToast('删除失败', 'error');
        }
    } catch (error) {
        showToast('删除失败', 'error');
    }
}

// Load Rankings
async function loadRankings() {
    const container = document.getElementById('rankingsContainer');

    try {
        const response = await fetch(`${API_BASE}/api/rankings`, { headers: getAuthHeaders() });
        if (!response.ok) {
            container.innerHTML = '<div class="empty-state">暂无排名数据</div>';
            return;
        }
        const data = await response.json();
        const rankings = data.rankings || [];

        if (rankings.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无排名数据</div>';
            return;
        }

        let html = `
            <table class="rankings-table">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>球员</th>
                        <th>ELO</th>
                        <th>胜</th>
                        <th>负</th>
                        <th>胜率</th>
                        <th>场次</th>
                    </tr>
                </thead>
                <tbody>
        `;

        rankings.forEach(player => {
            const rankClass = player.rank <= 3 ? `rank-${player.rank}` : '';
            html += `
                <tr class="${rankClass}">
                    <td class="rank-cell">
                        ${player.rank === 1 ? '🥇' : player.rank === 2 ? '🥈' : player.rank === 3 ? '🥉' : player.rank}
                    </td>
                    <td class="player-cell">${player.player_name}</td>
                    <td class="elo-cell">${player.elo_rating}</td>
                    <td class="wins-cell">${player.wins}</td>
                    <td class="losses-cell">${player.losses}</td>
                    <td class="winrate-cell">${player.win_rate}%</td>
                    <td class="games-cell">${player.games_played}</td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (error) {
        console.error('Load rankings error:', error);
        container.innerHTML = '<div class="empty-state">加载失败</div>';
    }
}

// Load Stats
async function loadStats(playerName) {
    const container = document.getElementById('opponentsContainer');

    try {
        // First fetch all opponents (without filter) to populate dropdown
        const allStatsUrl = `${API_BASE}/api/stats/${encodeURIComponent(playerName)}?period=${currentPeriod}`;
        const allStatsResponse = await fetch(allStatsUrl);
        const allStats = await allStatsResponse.json();
        updateOpponentDropdown(allStats.opponents);

        // Then fetch filtered stats if there's an opponent filter
        let url = `${API_BASE}/api/stats/${encodeURIComponent(playerName)}?period=${currentPeriod}`;
        if (currentOpponentFilter) {
            url += `&opponent=${encodeURIComponent(currentOpponentFilter)}`;
        }

        const response = await fetch(url);
        const stats = await response.json();

        // Update overview
        document.getElementById('totalGamesWon').textContent = stats.total_games_won;
        document.getElementById('totalGamesLost').textContent = stats.total_games_lost;
        document.getElementById('totalWinRate').textContent = `${stats.win_rate}%`;

        // Render opponents
        if (stats.opponents.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📊</div>
                    <div class="empty-title">暂无对战记录</div>
                    <p>开始记录比赛来查看统计数据吧！</p>
                </div>
            `;
            return;
        }

        container.innerHTML = stats.opponents.map(opp => `
            <div class="opponent-card" onclick="filterByOpponent('${opp.name}')">
                <div class="opponent-matchup">
                    <span class="player-badge my-team">${stats.player_name}</span>
                    <div class="matchup-vs">VS</div>
                    <span class="player-badge opp-team">${opp.name}</span>
                </div>
                <div class="opponent-record">
                    <span class="record-badge ${opp.games_won > 0 && opp.games_lost === 0 ? 'all-wins' : opp.games_won === 0 && opp.games_lost > 0 ? 'all-losses' : 'split'}">${opp.games_won}赢${opp.games_lost}输 ${opp.games_won > 0 && opp.games_lost === 0 ? '胜' : opp.games_won === 0 && opp.games_lost > 0 ? '负' : '平'}</span>
                </div>
            </div>
        `).join('');

        // Load best partner
        loadBestPartner(playerName);

    } catch (error) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-title">加载失败</div>
                <p>${error.message}</p>
            </div>
        `;
    }
}

// Load Best Partner
async function loadBestPartner(playerName) {
    const container = document.getElementById('bestPartnerContainer');
    if (!container) return;

    // Helper to escape template strings
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":"&#39;"}[c]));

    try {
        const url = `${API_BASE}/api/players/${encodeURIComponent(playerName)}/best-partner`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        if (!data.best_partner) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🤝</div>
                    <div class="empty-title">暂无搭档数据</div>
                    <p>开始双打比赛来查看最佳搭档！</p>
                </div>
            `;
            return;
        }

        const best = data.best_partner;
        const allPartners = data.all_partners || [];

        container.innerHTML = `
            <div class="best-partner-card">
                <div class="partner-main">
                    <div class="partner-name">${esc(best.name)}</div>
                    <div class="partner-stats">
                        <span class="stat-badge">${esc(best.games_together)}场</span>
                        <span class="stat-badge">${esc(best.win_rate)}%胜率</span>
                        <span class="stat-badge highlight">综合得分 ${esc(best.combined_score)}</span>
                    </div>
                </div>
                ${allPartners.length > 1 ? `
                <div class="partner-list">
                    <div class="partner-list-title">所有搭档排行</div>
                    ${allPartners.slice(0, 5).map((p, i) => `
                        <div class="partner-item ${i === 0 ? 'top' : ''}">
                            <span class="partner-rank">${i + 1}</span>
                            <span class="partner-info">${esc(p.name)}</span>
                            <span class="partner-detail">${esc(p.games_together)}场 ${esc(p.win_rate)}%</span>
                        </div>
                    `).join('')}
                </div>
                ` : ''}
            </div>
        `;

    } catch (error) {
        console.error('loadBestPartner error:', error);
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-title">加载失败</div>
                <p>${esc(error.message)}</p>
            </div>
        `;
    }
}

// =====================
// Arrangement Functions
// =====================

function generateArrangement() {
    const input = document.getElementById('arrangePlayersInput').value.trim();
    if (!input) {
        showToast('请输入选手名字', 'error');
        return;
    }

    // Parse player names
    let players = input.split(/[,\s\n]+/).filter(n => n.trim());
    players = [...new Set(players)]; // Remove duplicates

    if (players.length < 4) {
        showToast('双打需要至少4名选手', 'error');
        return;
    }

    const numMatches = parseInt(document.getElementById('numMatches').value) || 6;

    // Generate matches
    const matches = generateMatches(players, numMatches);

    displayArrangement(matches, players);
}

function generateMatches(players, numMatches) {
    const matches = [];
    const playerPlayCount = {};
    players.forEach(p => playerPlayCount[p] = 0);

    for (let m = 0; m < numMatches; m++) {
        // Sort players by play count (ascending) to prioritize less played
        const sortedPlayers = [...players].sort((a, b) => playerPlayCount[a] - playerPlayCount[b]);

        // Pick 4 players - prioritize those with fewer games
        const match = findBestMatch(sortedPlayers, playerPlayCount, matches);
        if (match) {
            matches.push(match);
            // Update play counts
            match.team1.forEach(p => playerPlayCount[p]++);
            match.team2.forEach(p => playerPlayCount[p]++);
        }
    }

    return matches;
}

function findBestMatch(availablePlayers, playerPlayCount, existingMatches) {
    const n = availablePlayers.length;
    if (n < 4) return null;

    let bestMatch = null;
    let bestScore = -Infinity;

    // Try all combinations of 4 players
    for (let i = 0; i < n - 3; i++) {
        for (let j = i + 1; j < n - 2; j++) {
            for (let k = j + 1; k < n - 1; k++) {
                for (let l = k + 1; l < n; l++) {
                    const team1 = [availablePlayers[i], availablePlayers[j]];
                    const team2 = [availablePlayers[k], availablePlayers[l]];

                    // Score this match (higher is better)
                    const team1Count = playerPlayCount[team1[0]] + playerPlayCount[team1[1]];
                    const team2Count = playerPlayCount[team2[0]] + playerPlayCount[team2[1]];
                    const fairnessScore = -(team1Count + team2Count);

                    // Check if these pairs have played together recently
                    let recentPenalty = 0;
                    for (const prev of existingMatches.slice(-3)) {
                        if (areSameTeams(team1, prev.team1) || areSameTeams(team1, prev.team2)) {
                            recentPenalty += 2;
                        }
                        if (areSameTeams(team2, prev.team1) || areSameTeams(team2, prev.team2)) {
                            recentPenalty += 2;
                        }
                    }

                    const totalScore = fairnessScore - recentPenalty;

                    if (totalScore > bestScore) {
                        bestScore = totalScore;
                        bestMatch = { team1, team2 };
                    }
                }
            }
        }
    }

    return bestMatch;
}

function areSameTeams(t1, t2) {
    return t1.length === t2.length && t1.every(p => t2.includes(p));
}

function displayArrangement(matches, players) {
    const container = document.getElementById('arrangementResult');
    const matchesContainer = document.getElementById('arrangementMatches');

    container.style.display = 'block';

    // Calculate player stats
    const playerGames = {};
    players.forEach(p => playerGames[p] = 0);
    matches.forEach(match => {
        match.team1.forEach(p => playerGames[p]++);
        match.team2.forEach(p => playerGames[p]++);
    });

    // Calculate estimated time
    const totalMinutes = matches.length * 15;
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    const timeText = hours > 0 ? `约${hours}小时${mins > 0 ? mins + '分钟' : ''}` : `约${mins}分钟`;

    // Build HTML
    let html = `
        <div class="arrangement-summary">
            <div class="summary-title">选手上场统计（共${matches.length}场，${timeText}）</div>
            <div class="summary-players">
                ${players.map(p => `
                    <div class="player-stat">
                        <span class="name">${p}</span>
                        <span class="games">${playerGames[p]}场</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;

    matches.forEach((match, matchIndex) => {
        const matchId = `match_${matchIndex}`;

        html += `
            <div class="match-card" id="${matchId}">
                <div class="match-teams">
                    <div class="team-players my-team">
                        ${match.team1.map(p => `<span>${p}</span>`).join('')}
                    </div>
                    <span class="vs-text">VS</span>
                    <div class="team-players opp-team">
                        ${match.team2.map(p => `<span>${p}</span>`).join('')}
                    </div>
                </div>
                <div class="match-score-input">
                    <input type="text" class="score-text-input" id="${matchId}_score"
                        placeholder="例如：第一局21:18，第二局21:13">
                </div>
                <button class="save-match-btn" onclick="saveArrangeMatch('${matchId}', ${matchIndex})">
                    保存比赛
                </button>
            </div>
        `;
    });

    matchesContainer.innerHTML = html;

    // Store arrangement data for saving
    currentArrangement = { matches, players };
}

async function saveArrangeMatch(matchId, matchIndex) {
    if (!currentArrangement) return;

    const match = currentArrangement.matches[matchIndex];
    const scoreInput = document.getElementById(`${matchId}_score`);
    const scoreText = scoreInput.value.trim();

    if (!scoreText) {
        showToast('请输入比分', 'error');
        return;
    }

    // Build match text
    const myTeam = match.team1.join('、');
    const oppTeam = match.team2.join('、');

    // Validate score format - extract scores from text
    const scorePattern = /第[一二三四五六七八九十\d]+局(\d+):(\d+)/g;
    const scores = [];
    let match2;
    while ((match2 = scorePattern.exec(scoreText)) !== null) {
        scores.push([parseInt(match2[1]), parseInt(match2[2])]);
    }

    if (scores.length === 0) {
        showToast('比分格式不正确，请使用如：第一局21:18，第二局21:13', 'error');
        return;
    }

    // Build the full match text
    const gamesText = scores.map((s, i) => `第${i + 1}局${s[0]}:${s[1]}`).join('，');
    const matchText = `我和${myTeam}打${oppTeam}，${gamesText}`;

    // Save via API
    try {
        const response = await fetch(`${API_BASE}/api/matches`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ text: matchText })
        });
        if (response.ok) {
            showToast('比赛已保存', 'success');
            const btn = document.querySelector(`#${matchId} .save-match-btn`);
            btn.textContent = '已保存';
            btn.disabled = true;
            scoreInput.disabled = true;
        } else {
            showToast('保存失败', 'error');
        }
    } catch (err) {
        showToast('保存失败: ' + err.message, 'error');
    }
}
