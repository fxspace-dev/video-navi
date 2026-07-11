// === Category Colors ===
const CAT_COLORS = {
    '手法': '#4f46e5', '基礎': '#10b981', 'リアルトレード': '#ef4444',
    '雑談': '#f59e0b', 'メンタル': '#ec4899', '実践': '#f97316',
    '資金管理': '#14b8a6', 'プロップファーム': '#8b5cf6', 'シナリオ': '#3b82f6',
    '実績': '#06b6d4', '企画': '#a855f7', 'インタビュー': '#64748b',
    'トレード環境': '#0ea5e9', 'ゼロプロ(旧プレアストロ)': '#d946ef',
    '過去検証': '#84cc16', 'YTT': '#6366f1', '相場': '#e11d48',
    '税金': '#78716c', 'インジケーター': '#22d3ee', 'ライン': '#fb923c',
    'チャートパターン': '#2dd4bf', 'その他手法': '#a3a3a3', 'プライスアクション': '#c026d3',
    'ナウキャスト': '#7c3aed', 'あるある': '#fbbf24', 'CFD': '#0d9488',
    '損切': '#dc2626', '大会': '#4ade80', 'コミュニティ': '#38bdf8', 'SIRIUS': '#818cf8',
};
function getCatColor(categories) { return (categories && categories.length > 0 && CAT_COLORS[categories[0]]) || '#94a3b8'; }
function isNewVideo(dateStr) {
    if (!dateStr) return false;
    const diff = (new Date() - new Date(dateStr)) / (1000 * 60 * 60 * 24);
    return diff <= 14;
}

// === State ===
let activeLevels = []; // 空 = すべて（複数選択可）
let activeCategories = []; // empty = all
let activeMethod = 'all';
let activeTypes = ['long']; // 既定はメイン動画のみ（空 = すべて・複数選択可）
let currentPage = 1;
const PAGE_SIZE = 12;
const isMobile = () => window.innerWidth <= 640;
let searchQuery = '';
let sortMode = 'date-new';
let viewMode = 'grid';
let showWatchLater = false;
let currentModalIndex = -1;

// === LocalStorage helpers ===
function getHistory() { try { return JSON.parse(localStorage.getItem('vn_history') || '[]'); } catch { return []; } }
function saveHistory(arr) { localStorage.setItem('vn_history', JSON.stringify(arr.slice(0, 20))); }
function addToHistory(vidTitle) {
    let h = getHistory().filter(t => t !== vidTitle);
    h.unshift(vidTitle);
    saveHistory(h);
    renderHistoryRow();
}
function getWatchLater() { try { return JSON.parse(localStorage.getItem('vn_watchlater') || '[]'); } catch { return []; } }
function saveWatchLater(arr) { localStorage.setItem('vn_watchlater', JSON.stringify(arr)); }
function toggleWatchLater(vidTitle) {
    let wl = getWatchLater();
    if (wl.includes(vidTitle)) wl = wl.filter(t => t !== vidTitle);
    else wl.push(vidTitle);
    saveWatchLater(wl);
    updateWatchLaterBadge();
    renderWatchLaterRow();
    renderVideos(); // re-render to update bookmark icons
}
function isWatched(vidTitle) { return getHistory().includes(vidTitle); }
function isWatchLater(vidTitle) { return getWatchLater().includes(vidTitle); }

// === Memo helpers ===
function getAllMemos() { try { return JSON.parse(localStorage.getItem('vn_memos') || '{}'); } catch { return {}; } }
function getMemo(vidTitle) { return getAllMemos()[vidTitle] || ''; }
function saveMemo(vidTitle, text) {
    const memos = getAllMemos();
    if (text.trim()) memos[vidTitle] = text;
    else delete memos[vidTitle];
    localStorage.setItem('vn_memos', JSON.stringify(memos));
}
function hasMemo(vidTitle) { return !!getAllMemos()[vidTitle]; }
function updateWatchLaterBadge() {
    const wl = getWatchLater();
    const badge = document.getElementById('watchLaterBadge');
    const btn = document.getElementById('watchLaterBtn');
    badge.style.display = wl.length > 0 ? 'flex' : 'none';
    badge.textContent = wl.length;
    btn.classList.toggle('active', showWatchLater);
}

// === Init ===
// === YouTube API 自動取得 ===
const YT_API_KEY = 'AIzaSyDwzewTQkfpXMABw_K8WDb6Cn8v56PkvrA';
const YT_CHANNEL_HANDLE = '@fxyosuga';

// === 人気順（再生回数） ===
const viewCounts = {};          // vid_id -> 再生回数
let viewCountsLoaded = false;
let viewCountsLoading = false;

// 全動画の再生回数を YouTube API から取得（50件ずつ）。一度だけ実行。
async function fetchViewCounts() {
    const ids = [...new Set(VIDEOS.map(v => v.vid_id).filter(Boolean))];
    for (let i = 0; i < ids.length; i += 50) {
        const chunk = ids.slice(i, i + 50);
        try {
            const res = await fetch(`https://www.googleapis.com/youtube/v3/videos?part=statistics&id=${chunk.join(',')}&key=${YT_API_KEY}`);
            const data = await res.json();
            for (const item of (data.items || [])) {
                viewCounts[item.id] = parseInt(item.statistics?.viewCount || '0', 10);
            }
        } catch (e) {
            console.warn('再生回数の取得に失敗:', e);
        }
    }
    viewCountsLoaded = true;
}

// 人気順が選ばれたときに一度だけ取得し、完了後に再描画する
async function ensureViewCounts() {
    if (viewCountsLoaded || viewCountsLoading) { renderVideos(); return; }
    viewCountsLoading = true;
    const rc = document.getElementById('resultCount');
    if (rc) rc.classList.add('is-loading');
    await fetchViewCounts();
    viewCountsLoading = false;
    if (rc) rc.classList.remove('is-loading');
    renderVideos();
}

// 再生回数を「1.2万回」形式に整形
function formatViews(n) {
    if (n === undefined || n === null) return '';
    if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, '') + '億回';
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万回';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + '千回';
    return n.toLocaleString() + '回';
}
const VIEW_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

// 再生数を取得（videos.js に保存された views を優先、無ければクライアント取得分）
function getViews(v) {
    if (v && v.views != null) return v.views;
    if (v && viewCounts[v.vid_id] != null) return viewCounts[v.vid_id];
    return undefined;
}
// カードに常時表示する再生数バッジ（控えめ表示）
function viewsBadge(v) {
    const n = getViews(v);
    return n != null ? `<span class="card-views">${VIEW_ICON}${formatViews(n)}</span>` : '';
}

// モバイルのフィルターパネルを閉じる
function closeMobileSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    const ov = document.getElementById('mobileOverlay');
    if (ov) ov.classList.remove('open');
    document.body.style.overflow = '';
}

// ISO 8601 duration (PT#H#M#S) → 秒数
function parseIsoDuration(iso) {
    if (!iso) return 0;
    const m = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
    if (!m) return 0;
    return (parseInt(m[1] || 0) * 3600) + (parseInt(m[2] || 0) * 60) + parseInt(m[3] || 0);
}

async function fetchYouTubeVideos() {
    try {
        // 1. ハンドルからチャンネルIDを取得
        const chRes = await fetch(`https://www.googleapis.com/youtube/v3/channels?part=contentDetails&forHandle=${YT_CHANNEL_HANDLE}&key=${YT_API_KEY}`);
        const chData = await chRes.json();
        if (!chData.items || chData.items.length === 0) return;
        const uploadsPlaylistId = chData.items[0].contentDetails.relatedPlaylists.uploads;

        // 2. アップロード一覧を取得（最新50件）
        const plRes = await fetch(`https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId=${uploadsPlaylistId}&maxResults=50&key=${YT_API_KEY}`);
        const plData = await plRes.json();
        if (!plData.items) return;

        // 3. 既存のvid_idセットを作成
        const existingIds = new Set(VIDEOS.map(v => v.vid_id).filter(Boolean));

        // 4. 未登録の videoId だけに絞る
        const newItems = plData.items.filter(it => !existingIds.has(it.snippet.resourceId.videoId));
        if (newItems.length === 0) return;

        // 5. contentDetails + liveStreamingDetails を追加取得（duration と live 状態判定のため）
        const newIds = newItems.map(it => it.snippet.resourceId.videoId);
        const vRes = await fetch(`https://www.googleapis.com/youtube/v3/videos?part=contentDetails,liveStreamingDetails&id=${newIds.join(',')}&key=${YT_API_KEY}`);
        const vData = await vRes.json();
        const detailsById = {};
        for (const v of (vData.items || [])) {
            detailsById[v.id] = {
                duration: parseIsoDuration(v.contentDetails?.duration),
                isLive: !!v.liveStreamingDetails,
            };
        }

        // 6. 新しい動画をVIDEOSに追加（is_short / duration / url / thumb を正しくセット）
        let addedCount = 0;
        for (const item of newItems) {
            const snippet = item.snippet;
            const videoId = snippet.resourceId.videoId;
            const d = detailsById[videoId] || { duration: 0, isLive: false };
            // ショート判定: ライブ配信でない かつ duration ≤ 180 秒
            const isShortGuess = !d.isLive && d.duration > 0 && d.duration <= 180;

            VIDEOS.push({
                title: snippet.title,
                url: isShortGuess
                    ? `https://www.youtube.com/shorts/${videoId}`
                    : `https://www.youtube.com/watch?v=${videoId}`,
                thumb: isShortGuess
                    ? `https://i.ytimg.com/vi/${videoId}/hq2.jpg`
                    : `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`,
                levels: [],
                categories: ['未分類'],
                method: '一般公開',
                summary: '',
                vid_id: videoId,
                date: snippet.publishedAt.substring(0, 10),
                is_short: isShortGuess,
                duration: d.duration,
                _auto: true
            });
            addedCount++;
        }
        if (addedCount > 0) {
            console.log(`YouTube API: ${addedCount}件の新しい動画を追加しました`);
        }
    } catch (e) {
        console.warn('YouTube API取得エラー:', e);
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    initDarkMode();
    restoreFiltersFromURL();
    generateStars();

    // YouTube APIから最新動画を取得してからUI構築
    await fetchYouTubeVideos();

    buildCategoryFilters();
    updateLevelCounts();
    renderVideos();
    setupEventListeners();
    setupHeaderScroll();
    setupSidebarResize();
    renderRoadmap();
    renderHistoryRow();
    renderWatchLaterRow();
    updateWatchLaterBadge();
    updateMemoBadge();
    // URL復元で人気順が指定されていたら再生回数を取得
    if (sortMode === 'popular') ensureViewCounts();
});

// === Roadmap ===
function renderRoadmap() {
    if (typeof ROADMAP === 'undefined') return;
    const list = document.getElementById('roadmapList');
    if (!list) return;

    list.innerHTML = ROADMAP.map(item => {
        const matchedVideo = VIDEOS.find(v => v.title.includes(item.title.replace(/^\d+[\.\s　]+/, '').trim().substring(0, 20)));
        const watched = matchedVideo ? isWatched(matchedVideo.title) : false;
        const vidIdx = matchedVideo ? VIDEOS.indexOf(matchedVideo) : -1;
        const onclick = vidIdx >= 0 ? `openModal(${vidIdx})` : `window.open('${item.url}','_blank')`;
        // Remove number prefix from title for display
        const displayTitle = item.title.replace(/^\d+[\.\s　]+/, '');

        return `<div class="roadmap-item ${watched ? 'is-watched' : ''}" onclick="${onclick}">
            <div class="roadmap-num"><span>${item.order}</span></div>
            <div class="roadmap-item-title">${displayTitle}</div>
        </div>`;
    }).join('');
}

function generateStars() {
    const container = document.getElementById('heroStars');
    if (!container) return;
    for (let i = 0; i < 80; i++) {
        const star = document.createElement('div');
        star.className = 'hero-star';
        const size = Math.random() * 2 + 0.5;
        star.style.width = size + 'px';
        star.style.height = size + 'px';
        star.style.left = Math.random() * 100 + '%';
        star.style.top = Math.random() * 100 + '%';
        star.style.animationDuration = (Math.random() * 3 + 2) + 's';
        star.style.animationDelay = (Math.random() * 4) + 's';
        container.appendChild(star);
    }
}

function animateNum(id, target) {
    const el = document.getElementById(id);
    let cur = 0; const step = Math.ceil(target / 25);
    const t = setInterval(() => { cur += step; if (cur >= target) { cur = target; clearInterval(t); } el.textContent = cur; }, 30);
}

function updateLevelCounts() {
    document.querySelectorAll('[data-level-count]').forEach(el => {
        const level = el.dataset.levelCount;
        el.textContent = VIDEOS.filter(v => v.levels.includes(level)).length;
    });
}

function buildCategoryFilters() {
    const cats = new Map();
    VIDEOS.forEach(v => v.categories.forEach(c => cats.set(c, (cats.get(c) || 0) + 1)));
    const container = document.getElementById('categoryFilters');
    [...cats.entries()].sort((a, b) => b[1] - a[1]).forEach(([cat]) => {
        const btn = document.createElement('button');
        btn.className = 'sidebar-tag';
        btn.dataset.cat = cat;
        btn.textContent = cat;
        container.appendChild(btn);
    });
}

function setupHeaderScroll() {
    window.addEventListener('scroll', () => document.getElementById('header').classList.toggle('scrolled', window.scrollY > 10));
}

function setupSidebarResize() {
    const handle = document.getElementById('sidebarResize');
    const sidebar = document.getElementById('sidebar');
    if (!handle || !sidebar) return;
    let startX, startW;
    handle.addEventListener('mousedown', e => {
        e.preventDefault();
        startX = e.clientX;
        startW = sidebar.offsetWidth;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        const onMove = e2 => {
            const newW = Math.min(400, Math.max(180, startW + (e2.clientX - startX)));
            sidebar.style.width = newW + 'px';
        };
        const onUp = () => {
            handle.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

function setupEventListeners() {
    document.querySelectorAll('#levelFilters input[name="level"]').forEach(input => {
        input.addEventListener('change', () => {
            if (input.value === 'all') {
                // 「すべて」= 選択解除
                activeLevels = [];
            } else if (input.checked) {
                if (!activeLevels.includes(input.value)) activeLevels.push(input.value);
            } else {
                activeLevels = activeLevels.filter(l => l !== input.value);
            }
            syncLevelCheckboxes();
            currentPage = 1; renderVideos(); updateActiveFilters();
        });
    });
    document.querySelectorAll('#methodFilters input[name="method"]').forEach(input => {
        input.addEventListener('change', () => { activeMethod = input.value; currentPage = 1; renderVideos(); updateActiveFilters(); });
    });
    document.querySelectorAll('#typeFilters input[name="vtype"]').forEach(input => {
        input.addEventListener('change', () => {
            if (input.value === 'all') {
                activeTypes = [];
            } else if (input.checked) {
                if (!activeTypes.includes(input.value)) activeTypes.push(input.value);
            } else {
                activeTypes = activeTypes.filter(t => t !== input.value);
            }
            syncTypeCheckboxes();
            currentPage = 1; renderVideos(); updateActiveFilters();
        });
    });
    document.getElementById('categoryFilters').addEventListener('click', e => {
        if (e.target.classList.contains('sidebar-tag')) {
            const cat = e.target.dataset.cat;
            if (cat === 'all') {
                activeCategories = [];
                document.querySelectorAll('#categoryFilters .sidebar-tag').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
            } else {
                document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.remove('active');
                if (e.target.classList.contains('active')) {
                    e.target.classList.remove('active');
                    activeCategories = activeCategories.filter(c => c !== cat);
                    if (activeCategories.length === 0) {
                        document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.add('active');
                    }
                } else {
                    e.target.classList.add('active');
                    activeCategories.push(cat);
                }
            }
            currentPage = 1; renderVideos(); updateActiveFilters();
        }
    });
    let searchDebounce;
    document.getElementById('searchInput').addEventListener('input', e => {
        clearTimeout(searchDebounce);
        document.getElementById('searchClearBtn').style.display = e.target.value ? 'flex' : 'none';
        searchDebounce = setTimeout(() => { searchQuery = e.target.value.toLowerCase(); currentPage = 1; renderVideos(); updateActiveFilters(); }, 200);
    });
    document.getElementById('searchClearBtn').addEventListener('click', () => {
        const input = document.getElementById('searchInput');
        input.value = '';
        searchQuery = '';
        document.getElementById('searchClearBtn').style.display = 'none';
        currentPage = 1; renderVideos(); updateActiveFilters();
        input.focus();
    });
    document.getElementById('sortSelect').addEventListener('change', e => {
        sortMode = e.target.value;
        if (sortMode === 'popular') ensureViewCounts();
        currentPage = 1; renderVideos();
    });
    document.getElementById('viewGrid').addEventListener('click', () => setView('grid'));
    document.getElementById('viewList').addEventListener('click', () => setView('list'));
    document.getElementById('resetFilters').addEventListener('click', resetAll);
    document.getElementById('sidebarToggle').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('collapsed');
    });
    document.getElementById('watchLaterBtn').addEventListener('click', () => {
        showWatchLater = !showWatchLater;
        updateWatchLaterBadge();
        if (showWatchLater) {
            document.getElementById('watchLaterSection').scrollIntoView({ behavior: 'smooth' });
        }
    });
    document.getElementById('historyClear').addEventListener('click', () => {
        localStorage.removeItem('vn_history');
        renderHistoryRow();
    });
    document.getElementById('watchLaterClear').addEventListener('click', () => {
        localStorage.removeItem('vn_watchlater');
        renderWatchLaterRow();
        updateWatchLaterBadge();
        renderVideos();
    });
    document.getElementById('mobileFilterBtn').addEventListener('click', () => {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.remove('collapsed');
        sidebar.classList.add('open');
        document.body.style.overflow = 'hidden';
    });
    const closeBtn = document.getElementById('sidebarMobileClose');
    if (closeBtn) closeBtn.addEventListener('click', closeMobileSidebar);
    // モバイル: 「この条件で見る」で結果へ戻る
    const applyBtn = document.getElementById('sidebarApplyBtn');
    if (applyBtn) applyBtn.addEventListener('click', () => {
        closeMobileSidebar();
        const content = document.querySelector('.content');
        if (content) content.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    // Sidebar close button (X) handled via pseudo-element click won't work,
    // so add a real button for mobile
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(renderVideos, 200);
    });
    document.getElementById('mobileOverlay').addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('open');
        document.getElementById('mobileOverlay').classList.remove('open');
    });
    document.getElementById('modalBackdrop').addEventListener('click', closeModal);
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('memoListBtn').addEventListener('click', openMemoList);
    document.getElementById('memoListBackdrop').addEventListener('click', closeMemoList);
    document.getElementById('memoListClose').addEventListener('click', closeMemoList);
    document.getElementById('memoSearchInput').addEventListener('input', e => renderMemoListItems(e.target.value));
    document.getElementById('memoExportBtn').addEventListener('click', exportMemos);
    document.addEventListener('keydown', e => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); document.getElementById('searchInput').focus(); }
        if (e.key === 'Escape') { closeModal(); closeMemoList(); }
    });
}

function setView(mode) {
    viewMode = mode;
    document.getElementById('viewGrid').classList.toggle('active', mode === 'grid');
    document.getElementById('viewList').classList.toggle('active', mode === 'list');
    renderVideos();
}

// activeLevels の状態をレベルのチェックボックスUIに反映
function syncLevelCheckboxes() {
    document.querySelectorAll('#levelFilters input[name="level"]').forEach(input => {
        if (input.value === 'all') input.checked = activeLevels.length === 0;
        else input.checked = activeLevels.includes(input.value);
    });
}
// activeTypes の状態を動画タイプのチェックボックスUIに反映
function syncTypeCheckboxes() {
    document.querySelectorAll('#typeFilters input[name="vtype"]').forEach(input => {
        if (input.value === 'all') input.checked = activeTypes.length === 0;
        else input.checked = activeTypes.includes(input.value);
    });
}

function updateActiveFilters() {
    const chips = [];
    activeLevels.forEach(lv => {
        chips.push(`<span class="active-filter-chip">${lv} <span class="chip-remove" onclick="clearOneLevel('${lv}')">×</span></span>`);
    });
    activeCategories.forEach(cat => {
        chips.push(`<span class="active-filter-chip">${cat} <span class="chip-remove" onclick="clearOneCategory('${cat}')">×</span></span>`);
    });
    if (activeMethod !== 'all') chips.push(`<span class="active-filter-chip">${activeMethod === '一般公開' ? '🌐 一般公開' : '🔒 メンバー限定'} <span class="chip-remove" onclick="clearFilter('method')">×</span></span>`);
    if (searchQuery) {
        const keywords = searchQuery.split(/[\s　]+/).filter(k => k.length > 0);
        keywords.forEach(kw => {
            chips.push(`<span class="active-filter-chip">"${kw}" <span class="chip-remove" onclick="removeSearchKeyword('${kw.replace(/'/g, "\\'")}')">×</span></span>`);
        });
    }
    document.getElementById('activeFilters').innerHTML = chips.join('');
    const badge = document.getElementById('filterBadge');
    badge.style.display = chips.length > 0 ? 'inline' : 'none';
    badge.textContent = chips.length;
}

function clearOneLevel(lv) {
    activeLevels = activeLevels.filter(l => l !== lv);
    syncLevelCheckboxes();
    currentPage = 1; renderVideos(); updateActiveFilters();
}

function clearFilter(type) {
    if (type === 'level') { activeLevels = []; syncLevelCheckboxes(); }
    if (type === 'category') { activeCategories = []; document.querySelectorAll('#categoryFilters .sidebar-tag').forEach(b => b.classList.remove('active')); document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.add('active'); }
    if (type === 'method') { activeMethod = 'all'; document.querySelector('#methodFilters input[value="all"]').checked = true; }
    if (type === 'search') { searchQuery = ''; document.getElementById('searchInput').value = ''; }
    currentPage = 1; renderVideos(); updateActiveFilters();
}

function removeSearchKeyword(kw) {
    const keywords = searchQuery.split(/[\s　]+/).filter(k => k.length > 0 && k !== kw);
    searchQuery = keywords.join(' ');
    document.getElementById('searchInput').value = searchQuery;
    currentPage = 1; renderVideos(); updateActiveFilters();
}

function clearOneCategory(cat) {
    activeCategories = activeCategories.filter(c => c !== cat);
    const btn = document.querySelector(`#categoryFilters .sidebar-tag[data-cat="${cat}"]`);
    if (btn) btn.classList.remove('active');
    if (activeCategories.length === 0) {
        document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.add('active');
    }
    currentPage = 1; renderVideos(); updateActiveFilters();
}

function resetAll() {
    activeLevels = []; activeCategories = []; activeMethod = 'all'; activeTypes = ['long']; searchQuery = ''; sortMode = 'date-new';
    syncLevelCheckboxes();
    syncTypeCheckboxes();
    document.querySelector('#methodFilters input[value="all"]').checked = true;
    document.querySelectorAll('#categoryFilters .sidebar-tag').forEach(b => b.classList.remove('active'));
    document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.add('active');
    document.getElementById('searchInput').value = '';
    document.getElementById('sortSelect').value = 'date-new';
    currentPage = 1; renderVideos(); updateActiveFilters();
}

function getFilteredVideos() {
    // Dedupe by title (safety net)
    const seenTitles = new Set();
    const dedupedVideos = VIDEOS.filter(v => {
        const t = (v.title || '').trim();
        if (seenTitles.has(t)) return false;
        seenTitles.add(t);
        return true;
    });
    let result = dedupedVideos.filter(v => {
        if (activeLevels.length > 0 && !v.levels.some(l => activeLevels.includes(l))) return false;
        if (activeCategories.length > 0 && !activeCategories.some(c => v.categories.includes(c))) return false;
        if (activeMethod !== 'all' && v.method !== activeMethod) return false;
        if (activeTypes.length > 0 && !activeTypes.includes(getVideoType(v))) return false;
        if (searchQuery) {
            const keywords = searchQuery.split(/[\s　]+/).filter(k => k.length > 0);
            for (const q of keywords) {
                if (!v.title.toLowerCase().includes(q) && !(v.summary || '').toLowerCase().includes(q) && !v.categories.some(c => c.toLowerCase().includes(q)) && !v.levels.some(l => l.toLowerCase().includes(q))) return false;
            }
        }
        return true;
    });
    if (sortMode === 'date-new') result.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    if (sortMode === 'date-old') result.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
    if (sortMode === 'title-asc') result.sort((a, b) => a.title.localeCompare(b.title, 'ja'));
    if (sortMode === 'title-desc') result.sort((a, b) => b.title.localeCompare(a.title, 'ja'));
    if (sortMode === 'popular') {
        // 再生回数の多い順。未取得(-1)は末尾へ。同数なら新しい順。
        result.sort((a, b) => {
            const va = getViews(a), vb = getViews(b);
            const na = (va == null ? -1 : va), nb = (vb == null ? -1 : vb);
            if (nb !== na) return nb - na;
            return (b.date || '').localeCompare(a.date || '');
        });
    }
    return result;
}

function renderVideos() {
    const filtered = getFilteredVideos();
    const gridEl = document.getElementById('videoGrid');
    const listEl = document.getElementById('videoList');
    const noResults = document.getElementById('noResults');
    const paginationEl = document.getElementById('pagination');
    document.getElementById('resultCount').textContent = filtered.length;
    const applyCount = document.getElementById('sidebarApplyCount');
    if (applyCount) applyCount.textContent = `この条件で見る（${filtered.length}件）`;
    gridEl.classList.toggle('hidden', viewMode !== 'grid');
    listEl.classList.toggle('hidden', viewMode !== 'list');
    if (filtered.length === 0) {
        gridEl.innerHTML = ''; listEl.innerHTML = '';
        noResults.style.display = 'block';
        if (paginationEl) paginationEl.innerHTML = '';
        return;
    }
    noResults.style.display = 'none';

    // Pagination on mobile
    let displayItems = filtered;
    let totalPages = 1;
    if (isMobile()) {
        totalPages = Math.ceil(filtered.length / PAGE_SIZE);
        if (currentPage > totalPages) currentPage = 1;
        const start = (currentPage - 1) * PAGE_SIZE;
        displayItems = filtered.slice(start, start + PAGE_SIZE);
    }

    if (viewMode === 'grid') gridEl.innerHTML = displayItems.map((v, i) => renderGridCard(v, i)).join('');
    else listEl.innerHTML = displayItems.map((v, i) => renderListItem(v, i)).join('');

    if (paginationEl) renderPagination(totalPages, paginationEl);

    saveFiltersToURL();
}

function renderPagination(totalPages, el) {
    if (!isMobile() || totalPages <= 1) { el.innerHTML = ''; return; }
    let html = '';
    html += `<button class="pg-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>‹</button>`;
    // Show page numbers (limited)
    const maxButtons = 5;
    let start = Math.max(1, currentPage - 2);
    let end = Math.min(totalPages, start + maxButtons - 1);
    if (end - start + 1 < maxButtons) start = Math.max(1, end - maxButtons + 1);
    if (start > 1) {
        html += `<button class="pg-btn" onclick="goToPage(1)">1</button>`;
        if (start > 2) html += `<span class="pg-ellipsis">…</span>`;
    }
    for (let i = start; i <= end; i++) {
        html += `<button class="pg-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    if (end < totalPages) {
        if (end < totalPages - 1) html += `<span class="pg-ellipsis">…</span>`;
        html += `<button class="pg-btn" onclick="goToPage(${totalPages})">${totalPages}</button>`;
    }
    html += `<button class="pg-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>›</button>`;
    el.innerHTML = html;
}

function goToPage(page) {
    currentPage = page;
    renderVideos();
    document.querySelector('.content-header').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderGridCard(v, i) {
    const thumbHtml = v.thumb ? `<img src="${v.thumb}" alt="" loading="lazy">` : `<div class="video-thumb-placeholder">🎬</div>`;
    const badgeClass = v.method === 'メンバーシップ限定公開' ? 'badge-member' : 'badge-public';
    const badgeText = v.method === 'メンバーシップ限定公開' ? '🔒 限定' : '🌐 公開';
    const levelTags = v.levels.slice(0, 2).map(l => `<span class="video-level-tag level-${l}">${l}</span>`).join('');
    const catTags = v.categories.slice(0, 2).map(c => `<span class="video-cat-tag"><span class="cat-dot" style="background:${CAT_COLORS[c]||'#94a3b8'}"></span>${c}</span>`).join('');
    const dateStr = v.date ? formatDate(v.date) : '';
    let summaryHint = '';
    if (searchQuery && v.summary) {
        const titleMatch = v.title.toLowerCase().includes(searchQuery);
        const summaryMatch = v.summary.toLowerCase().includes(searchQuery);
        if (summaryMatch && !titleMatch) {
            const idx = v.summary.toLowerCase().indexOf(searchQuery);
            const start = Math.max(0, idx - 15);
            const end = Math.min(v.summary.length, idx + searchQuery.length + 30);
            const excerpt = (start > 0 ? '...' : '') + v.summary.slice(start, end) + (end < v.summary.length ? '...' : '');
            summaryHint = `<div class="search-match-hint">要約に一致: ${excerpt.replace(new RegExp(escapeRegex(searchQuery), 'gi'), m => `<mark>${m}</mark>`)}</div>`;
        }
    }
    const idx = VIDEOS.indexOf(v);
    const catColor = getCatColor(v.categories);
    const watched = isWatched(v.title);
    const saved = isWatchLater(v.title);
    const watchedBadge = watched ? '<span class="video-watched-badge">視聴済み</span>' : '';
    const wlClass = saved ? 'saved' : '';
    const wlIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + (saved ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
    const durationHtml = v.duration ? '<span class="video-duration">' + formatDuration(v.duration) + '</span>' : '';
    const vtype = getVideoType(v);
    const typeLabel = vtype === 'short' ? '<span class="video-short-label">SHORT</span>' : vtype === 'live' ? '<span class="video-live-label">LIVE</span>' : '';
    const viewsHtml = viewsBadge(v);
    return `<a href="${v.url}" target="_blank" class="video-card ${watched ? 'is-watched' : ''}" style="--cat-color:${catColor}" onclick="openModal(${idx}); return false;">
        <div class="video-thumb">${thumbHtml}<div class="video-play-overlay"><div class="play-icon"></div></div>${watchedBadge}${durationHtml}${typeLabel}<button class="card-watchlater ${wlClass}" onclick="event.preventDefault();event.stopPropagation();toggleWatchLater('${v.title.replace(/'/g, "\\'")}');" title="後で見る">${wlIcon}</button></div>
        <div class="video-info"><h3 class="video-title"><span class="video-badge ${badgeClass}">${badgeText}</span>${isNewVideo(v.date) ? '<span class="video-new-badge">NEW</span>' : ''}${searchQuery ? highlightText(v.title, searchQuery) : v.title}</h3>${summaryHint}<div class="video-meta">${dateStr ? `<span class="video-date">${dateStr}</span>` : ''}${viewsHtml}${hasMemo(v.title) ? '<span class="video-memo-icon" title="メモあり">&#9998;</span>' : ''}</div><div class="video-tags">${levelTags}${catTags}</div></div></a>`;
}

function renderListItem(v, i) {
    const thumbHtml = v.thumb ? `<img src="${v.thumb}" alt="" loading="lazy">` : `<div class="list-thumb-placeholder">🎬</div>`;
    const badgeClass = v.method === 'メンバーシップ限定公開' ? 'badge-member' : 'badge-public';
    const badgeText = v.method === 'メンバーシップ限定公開' ? '🔒 限定' : '🌐 公開';
    const levelTags = v.levels.slice(0, 3).map(l => `<span class="video-level-tag level-${l}">${l}</span>`).join('');
    const catTags = v.categories.slice(0, 3).map(c => `<span class="video-cat-tag"><span class="cat-dot" style="background:${CAT_COLORS[c]||'#94a3b8'}"></span>${c}</span>`).join('');
    const dateStr = v.date ? formatDate(v.date) : '';
    const summaryText = v.summary ? v.summary.slice(0, 80) + (v.summary.length > 80 ? '...' : '') : '';
    const idx = VIDEOS.indexOf(v);
    const catColor = getCatColor(v.categories);
    const viewsHtml = viewsBadge(v);
    return `<a href="${v.url}" target="_blank" class="video-list-item" style="--cat-color:${catColor}" onclick="openModal(${idx}); return false;">
        <div class="list-thumb">${thumbHtml}</div>
        <div class="list-info"><h3 class="list-title">${isNewVideo(v.date) ? '<span class="video-new-badge">NEW</span>' : ''}${searchQuery ? highlightText(v.title, searchQuery) : v.title}</h3>${summaryText ? `<p class="list-summary">${searchQuery ? highlightText(summaryText, searchQuery) : summaryText}</p>` : ''}<div class="list-meta"><span class="list-badge ${badgeClass}">${badgeText}</span>${dateStr ? `<span class="list-date">${dateStr}</span>` : ''}${viewsHtml}${levelTags}${catTags}</div></div></a>`;
}

function openModal(index) {
    const v = VIDEOS[index];
    if (!v) return;
    currentModalIndex = index;
    const modal = document.getElementById('videoModal');
    const videoArea = document.getElementById('modalVideo');
    // サムネイルのフォールバック連鎖:
    // maxresdefault(高画質) → hqdefault(全動画に必ず存在) → v.thumb
    // A/Bテスト中などで maxresdefault が404になる動画でも必ず表示されるようにする。
    const modalDurHtml = v.duration ? `<span class="video-duration">${formatDuration(v.duration)}</span>` : '';
    let thumbImgHtml;
    if (v.vid_id) {
        const hq = `https://img.youtube.com/vi/${v.vid_id}/hqdefault.jpg`;
        const maxres = `https://img.youtube.com/vi/${v.vid_id}/maxresdefault.jpg`;
        thumbImgHtml = `<img src="${maxres}" alt="" data-fallback="${hq}" onerror="if(this.dataset.fallback){this.src=this.dataset.fallback;this.dataset.fallback='';}">`;
    } else {
        thumbImgHtml = `<img src="${(v.thumb || '').replace(/"/g, '&quot;')}" alt="">`;
    }
    videoArea.innerHTML = `<a href="${v.url}" target="_blank" class="modal-thumb-link" onclick="addToHistory('${v.title.replace(/'/g, "\\'")}');renderVideos();">${thumbImgHtml}<div class="modal-play-btn"><svg width="48" height="48" viewBox="0 0 48 48"><circle cx="24" cy="24" r="24" fill="rgba(0,0,0,0.55)"/><polygon points="19,14 19,34 36,24" fill="white"/></svg></div>${modalDurHtml}</a>`;
    document.getElementById('modalTitle').textContent = v.title;
    const modalLink = document.getElementById('modalLink');
    modalLink.href = v.url;
    modalLink.textContent = v.url.includes('discord.com') ? 'Discordで視聴する →' : '動画を見る →';
    modalLink.onclick = () => { addToHistory(v.title); renderVideos(); };
    document.getElementById('modalMeta').textContent = v.date ? formatDate(v.date) + (v.method ? ' · ' + v.method : '') : v.method || '';
    document.getElementById('modalTags').innerHTML = v.levels.map(l => `<span class="video-level-tag level-${l}">${l}</span>`).join('') + v.categories.map(c => `<span class="video-cat-tag">${c}</span>`).join('');
    document.getElementById('modalSummary').textContent = v.summary || '';
    // プレイリスト追加
    const plBtn = document.getElementById('modalAddPlaylist');
    if (plBtn) plBtn.onclick = () => showAddToPlaylistMenu(v.title);
    // ブックマーク
    const bmBtn = document.getElementById('modalBookmark');
    const bmLabel = document.getElementById('modalBookmarkLabel');
    const updateBmState = () => {
        const saved = isWatchLater(v.title);
        bmBtn.classList.toggle('saved', saved);
        bmLabel.textContent = saved ? '保存済み' : '後で見る';
    };
    updateBmState();
    bmBtn.onclick = () => { toggleWatchLater(v.title); updateBmState(); };
    // おすすめ動画（「もっと見る」で追加表示）
    recShownCount = 6;
    renderRecommendations(index);
    // シェアボタン
    const shareBtn = document.getElementById('modalShare');
    if (shareBtn) {
        shareBtn.onclick = () => {
            navigator.clipboard.writeText(v.url).then(() => {
                shareBtn.textContent = 'コピーしました！';
                setTimeout(() => { shareBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> URLコピー'; }, 1500);
            });
        };
    }
    // メモ
    const memoArea = document.getElementById('memoTextarea');
    const memoSaved = document.getElementById('memoSaved');
    memoArea.value = getMemo(v.title);
    memoSaved.classList.remove('show');
    memoArea.oninput = () => {
        clearTimeout(memoArea._debounce);
        memoArea._debounce = setTimeout(() => {
            saveMemo(v.title, memoArea.value);
            memoSaved.classList.add('show');
            clearTimeout(memoArea._saveTimer);
            memoArea._saveTimer = setTimeout(() => memoSaved.classList.remove('show'), 1500);
        }, 300);
    };
    // YouTubeコメント
    loadComments(v);
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    document.querySelector('.modal-content').scrollTop = 0;
}

// === YouTubeコメント読み込み ===
// よすが本人のチャンネルID（本人コメント/返信の判定用。一度だけ取得してキャッシュ）
let yosugaChannelId = null;
async function getYosugaChannelId() {
    if (yosugaChannelId) return yosugaChannelId;
    try {
        const res = await fetch(`https://www.googleapis.com/youtube/v3/channels?part=id&forHandle=${YT_CHANNEL_HANDLE}&key=${YT_API_KEY}`);
        const data = await res.json();
        yosugaChannelId = data.items?.[0]?.id || null;
    } catch (e) { yosugaChannelId = null; }
    return yosugaChannelId;
}

// 1コメント（本人/視聴者）を描画。owner=true でよすがバッジ付与
function renderCommentNode(c, owner) {
    const author = escapeHtml(c.authorDisplayName || '');
    const initial = (author.replace('@', '').charAt(0) || '?').toUpperCase();
    const avatar = c.authorProfileImageUrl
        ? `<img class="cmt-avatar" src="${c.authorProfileImageUrl}" alt="" loading="lazy" referrerpolicy="no-referrer">`
        : `<div class="cmt-avatar-fallback">${initial}</div>`;
    const text = escapeHtml(c.textDisplay || '').replace(/\n/g, '<br>');
    const likes = c.likeCount || 0;
    const likesHtml = likes > 0
        ? `<span class="cmt-likes"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>${likes.toLocaleString()}</span>`
        : '';
    const ownerBadge = owner ? '<span class="cmt-owner-badge">よすが</span>' : '';
    const authorClass = owner ? 'cmt-author cmt-author-owner' : 'cmt-author';
    return `${avatar}<div class="cmt-body"><div class="cmt-meta"><span class="${authorClass}">${author}</span>${ownerBadge}<span class="cmt-date">${formatCommentDate(c.publishedAt)}</span></div><div class="cmt-text">${text}</div>${likesHtml}</div>`;
}

let commentsRequestId = 0;
async function loadComments(v) {
    const section = document.getElementById('modalComments');
    const list = document.getElementById('modalCommentsList');
    const allLink = document.getElementById('modalCommentsAll');
    if (!section || !list) return;
    const reqId = ++commentsRequestId;
    // Discord限定動画・vid_idなしはコメント非対応
    if (!v.vid_id || (v.url && v.url.includes('discord.com'))) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';
    allLink.href = `https://www.youtube.com/watch?v=${v.vid_id}`;
    list.innerHTML = '<div class="modal-comments-skeleton">'
        + '<div class="cmt-skel"><div class="cmt-skel-av"></div><div class="cmt-skel-lines"><div class="cmt-skel-line" style="width:40%"></div><div class="cmt-skel-line" style="width:90%"></div></div></div>'
        + '<div class="cmt-skel"><div class="cmt-skel-av"></div><div class="cmt-skel-lines"><div class="cmt-skel-line" style="width:35%"></div><div class="cmt-skel-line" style="width:80%"></div></div></div>'
        + '</div>';
    try {
        const ownerIdPromise = getYosugaChannelId();
        // replies も取得して、よすがが視聴者コメントへ返信しているものを拾う
        const res = await fetch(`https://www.googleapis.com/youtube/v3/commentThreads?part=snippet,replies&videoId=${v.vid_id}&maxResults=30&order=relevance&textFormat=plainText&key=${YT_API_KEY}`);
        if (reqId !== commentsRequestId) return; // 別の動画が開かれた
        const data = await res.json();
        if (data.error) {
            // コメント無効化などは静かに隠す
            section.style.display = 'none';
            return;
        }
        const ownerId = await ownerIdPromise;
        if (reqId !== commentsRequestId) return;
        const items = data.items || [];

        // よすが本人の単独トップレベルコメント（概要欄まるコピー）は除外。
        // 視聴者コメント＋そこへのよすがの返信を対象にする。
        const threads = [];
        for (const it of items) {
            const top = it.snippet.topLevelComment.snippet;
            const topAuthorId = top.authorChannelId && top.authorChannelId.value;
            if (ownerId && topAuthorId === ownerId) continue; // よすが本人の投稿は非表示
            const replyComments = (it.replies && it.replies.comments) || [];
            const yosugaReplies = ownerId
                ? replyComments
                    .filter(r => r.snippet.authorChannelId && r.snippet.authorChannelId.value === ownerId)
                    .map(r => r.snippet)
                : [];
            threads.push({ top, yosugaReplies });
        }
        // よすがが返信しているスレッドを優先（安定ソートで元の関連度順は維持）
        threads.sort((a, b) => (b.yosugaReplies.length > 0) - (a.yosugaReplies.length > 0));
        const shown = threads.slice(0, 8);
        if (shown.length === 0) {
            list.innerHTML = '<p class="modal-comments-status">表示できるコメントがありません。</p>';
            return;
        }
        const threadsHtml = shown.map(t => {
            const topHtml = `<div class="cmt">${renderCommentNode(t.top, false)}</div>`;
            const repliesHtml = t.yosugaReplies
                .map(r => `<div class="cmt cmt-reply">${renderCommentNode(r, true)}</div>`)
                .join('');
            return `<div class="cmt-thread">${topHtml}${repliesHtml}</div>`;
        }).join('');
        // 一部のみ表示のため、YouTubeのコメント欄へ飛ぶ「もっと見る」ボタン
        const moreHtml = `<a class="modal-more-btn" href="https://www.youtube.com/watch?v=${v.vid_id}" target="_blank" rel="noopener">YouTubeでコメントをもっと見る →</a>`;
        list.innerHTML = threadsHtml + moreHtml;
    } catch (e) {
        if (reqId !== commentsRequestId) return;
        section.style.display = 'none';
    }
}
function escapeHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function formatCommentDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 3600) return Math.max(1, Math.floor(diff / 60)) + '分前';
    if (diff < 86400) return Math.floor(diff / 3600) + '時間前';
    if (diff < 2592000) return Math.floor(diff / 86400) + '日前';
    if (diff < 31536000) return Math.floor(diff / 2592000) + 'ヶ月前';
    return Math.floor(diff / 31536000) + '年前';
}

// === おすすめ動画（もっと見る対応） ===
let recShownCount = 6;
function renderRecommendations(index) {
    const wrap = document.getElementById('modalRecommend');
    const recList = document.getElementById('modalRecommendList');
    if (!wrap || !recList) return;
    // 多めに候補を取り、表示件数分だけ描画（残りは「もっと見る」で展開）
    const allRecs = getRecommendations(index, 40);
    if (allRecs.length === 0) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';
    const shown = allRecs.slice(0, recShownCount);
    recList.innerHTML = shown.map(r => {
        const rv = VIDEOS[r];
        const rThumb = rv.thumb ? `<img src="${rv.thumb}" alt="" loading="lazy">` : `<div class="rec-thumb-placeholder">🎬</div>`;
        const rCatColor = getCatColor(rv.categories);
        const rDurHtml = rv.duration ? `<span class="video-duration">${formatDuration(rv.duration)}</span>` : '';
        return `<div class="rec-card" style="--cat-color:${rCatColor}" onclick="openModal(${r})">
            <div class="rec-thumb">${rThumb}${rDurHtml}</div>
            <div class="rec-info"><p class="rec-title">${rv.title}</p><span class="rec-cat"><span class="cat-dot" style="background:${rCatColor}"></span>${rv.categories[0] || ''}</span></div>
        </div>`;
    }).join('');
    // 「もっと見る」ボタン
    let moreBtn = document.getElementById('recMoreBtn');
    if (allRecs.length > recShownCount) {
        if (!moreBtn) {
            moreBtn = document.createElement('button');
            moreBtn.id = 'recMoreBtn';
            moreBtn.className = 'modal-more-btn';
            wrap.appendChild(moreBtn);
        }
        moreBtn.textContent = 'もっと見る';
        moreBtn.onclick = () => { recShownCount += 6; renderRecommendations(index); };
    } else if (moreBtn) {
        moreBtn.remove();
    }
}

function closeModal() {
    document.getElementById('videoModal').classList.remove('open');
    document.getElementById('modalVideo').innerHTML = '';
    document.body.style.overflow = '';
    updateMemoBadge();
    renderVideos();
}

// === Memo List ===
function openMemoList() {
    const searchInput = document.getElementById('memoSearchInput');
    searchInput.value = '';
    renderMemoListItems('');
    document.getElementById('memoListModal').classList.add('open');
    document.body.style.overflow = 'hidden';
}
function renderMemoListItems(query) {
    const memos = getAllMemos();
    let entries = Object.entries(memos).filter(([, text]) => text.trim());
    const q = query.toLowerCase().trim();
    if (q) {
        entries = entries.filter(([title, text]) => title.toLowerCase().includes(q) || text.toLowerCase().includes(q));
    }
    const body = document.getElementById('memoListBody');
    document.getElementById('memoListCount').textContent = entries.length + '件のメモ';
    if (entries.length === 0) {
        body.innerHTML = q
            ? '<div class="memo-list-empty"><p>該当するメモがありません</p></div>'
            : '<div class="memo-list-empty"><p>まだメモがありません</p><p class="memo-list-empty-sub">動画を開いてメモを書いてみましょう</p></div>';
    } else {
        body.innerHTML = entries.map(([title, text]) => {
            const v = VIDEOS.find(vid => vid.title === title);
            const idx = v ? VIDEOS.indexOf(v) : -1;
            const thumb = v && v.thumb ? `<img src="${v.thumb}" alt="" loading="lazy">` : '';
            const catColor = v ? getCatColor(v.categories) : '#94a3b8';
            const catName = v && v.categories[0] ? v.categories[0] : '';
            const displayText = text.replace(/</g, '&lt;').replace(/\n/g, '<br>');
            return `<div class="memo-list-item" style="--cat-color:${catColor}">
                <div class="memo-list-item-header" ${idx >= 0 ? `onclick="closeMemoList();openModal(${idx})"` : ''}>
                    <div class="memo-list-thumb">${thumb}</div>
                    <div class="memo-list-item-info">
                        <h4 class="memo-list-item-title">${title}</h4>
                        ${catName ? `<span class="rec-cat"><span class="cat-dot" style="background:${catColor}"></span>${catName}</span>` : ''}
                    </div>
                </div>
                <div class="memo-list-item-text">${displayText}</div>
                <button class="memo-list-delete" onclick="deleteMemoFromList('${title.replace(/'/g, "\\'")}')">削除</button>
            </div>`;
        }).join('');
    }
}
function exportMemos() {
    const memos = getAllMemos();
    const entries = Object.entries(memos).filter(([, text]) => text.trim());
    if (entries.length === 0) return;
    const lines = entries.map(([title, text]) => {
        const v = VIDEOS.find(vid => vid.title === title);
        const cat = v && v.categories[0] ? '[' + v.categories[0] + '] ' : '';
        return '## ' + cat + title + '\n' + text;
    });
    const content = '# 学習メモ一覧\n' + '出力日: ' + new Date().toLocaleDateString('ja-JP') + '\n\n' + lines.join('\n\n---\n\n') + '\n';
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '学習メモ_' + new Date().toISOString().slice(0, 10) + '.txt';
    a.click();
    URL.revokeObjectURL(a.href);
}
function closeMemoList() {
    document.getElementById('memoListModal').classList.remove('open');
    document.body.style.overflow = '';
}
function deleteMemoFromList(title) {
    saveMemo(title, '');
    updateMemoBadge();
    renderVideos();
    openMemoList();
}
function updateMemoBadge() {
    const count = Object.keys(getAllMemos()).filter(k => getAllMemos()[k].trim()).length;
    const badge = document.getElementById('memoListBadge');
    badge.style.display = count > 0 ? 'flex' : 'none';
    badge.textContent = count;
}

// タイトルから【…】[…]（…）などのシリーズ/タグ表記を抜き出す
function extractBracketTags(title) {
    const tags = [];
    const re = /[【\[（(]([^】\]）)]{1,20})[】\]）)]/g;
    let m;
    while ((m = re.exec(title)) !== null) {
        const t = m[1].trim();
        if (t) tags.push(t);
    }
    return tags;
}
// タイトルを意味のあるトークン集合に（記号で分割し2文字以上を採用）
const REC_STOPWORDS = new Set(['解説', '動画', '完全', '方法', 'よすが', 'について', 'こと', 'ため', 'FX']);
function titleTokens(title) {
    const cleaned = (title || '').replace(/[【】\[\]（）()「」『』・｜|/,、。！？!?~〜\-—\s　]+/g, ' ');
    return new Set(
        cleaned.split(' ')
            .map(s => s.trim())
            .filter(s => s.length >= 2 && !REC_STOPWORDS.has(s))
    );
}

// 「この動画を見た人が次に見たい動画」を推定して並べる
function getRecommendations(currentIndex, count) {
    const current = VIDEOS[currentIndex];
    if (!current) return [];
    const history = getHistory();
    const watchedSet = new Set(history);
    // 視聴履歴からの嗜好プロファイル
    const histCats = {};
    const histLevels = {};
    history.forEach(t => {
        const hv = VIDEOS.find(v => v.title === t);
        if (hv) {
            hv.categories.forEach(c => { histCats[c] = (histCats[c] || 0) + 1; });
            hv.levels.forEach(l => { histLevels[l] = (histLevels[l] || 0) + 1; });
        }
    });

    const curCats = new Set(current.categories || []);
    const curLevels = new Set(current.levels || []);
    const curTags = extractBracketTags(current.title);
    const curTokens = titleTokens(current.title);

    const scored = VIDEOS.map((v, i) => {
        if (i === currentIndex) return { i, score: -1 };
        // ショート・ライブ配信はおすすめから除外（メイン動画の続きに見たいのは通常動画）
        if (isShort(v) || isLive(v)) return { i, score: -1 };

        let score = 0;

        // ① テーマ（カテゴリ）一致 — 最重要。複数重なるほど関連度が高い
        let sharedCats = 0;
        v.categories.forEach(c => { if (curCats.has(c)) { score += 5; sharedCats++; } });
        if (sharedCats >= 2) score += 5;           // 複数テーマ一致は強い関連
        if (sharedCats === 0) score -= 2;          // テーマが全く違うものは下げる

        // ② シリーズ/続編 — 同じ【タグ】は「次に見たい」度が高い（例: 1章→2章）
        const vTags = extractBracketTags(v.title);
        if (curTags.length && vTags.some(t => curTags.includes(t))) score += 8;

        // ③ タイトルの題材キーワード重なり（同じ話題・銘柄・手法名など）
        const vTokens = titleTokens(v.title);
        let sharedTokens = 0;
        curTokens.forEach(t => { if (vTokens.has(t)) sharedTokens++; });
        score += Math.min(sharedTokens * 3, 9);

        // ④ 学習レベルの近さ（同じ段階の視聴者が見やすい）
        let sharedLevels = 0;
        v.levels.forEach(l => { if (curLevels.has(l)) { score += 2; sharedLevels++; } });

        // ⑤ 公開方法が同じ（限定/公開）だと文脈が近い
        if (v.method === current.method) score += 0.5;

        // ⑥ 視聴履歴の嗜好ブースト
        v.categories.forEach(c => { if (histCats[c]) score += Math.min(histCats[c] * 0.5, 2); });
        v.levels.forEach(l => { if (histLevels[l]) score += Math.min(histLevels[l] * 0.3, 1); });

        // ⑦ 人気度（再生数）を軽くブースト — 関連が近い中でよく見られている動画を優先
        const views = getViews(v);
        if (views && score > 0) score += Math.min(Math.log10(views + 1), 6) * 0.7;

        // ⑧ 視聴済みは下げ、未視聴は少し上げる（新規発見）
        if (watchedSet.has(v.title)) score *= 0.4;
        else score += 1;

        return { i, score };
    }).filter(s => s.score > 0);

    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, count).map(s => s.i);
}

// === Playlist ===
function getPlaylists() { try { return JSON.parse(localStorage.getItem('vn_playlists') || '[]'); } catch { return []; } }
function savePlaylists(pls) { localStorage.setItem('vn_playlists', JSON.stringify(pls)); }
function createPlaylist(name) {
    const pls = getPlaylists();
    pls.push({ name, videos: [], created: Date.now() });
    savePlaylists(pls);
}
function deletePlaylist(idx) {
    const pls = getPlaylists();
    pls.splice(idx, 1);
    savePlaylists(pls);
}
function addToPlaylist(plIdx, vidTitle) {
    const pls = getPlaylists();
    if (!pls[plIdx]) return;
    if (!pls[plIdx].videos.includes(vidTitle)) pls[plIdx].videos.push(vidTitle);
    savePlaylists(pls);
}
function removeFromPlaylist(plIdx, vidTitle) {
    const pls = getPlaylists();
    if (!pls[plIdx]) return;
    pls[plIdx].videos = pls[plIdx].videos.filter(t => t !== vidTitle);
    savePlaylists(pls);
}
function openPlaylistModal() {
    const pls = getPlaylists();
    const modal = document.getElementById('playlistModal');
    const body = document.getElementById('playlistBody');

    if (pls.length === 0) {
        body.innerHTML = '<div class="playlist-empty"><p>プレイリストがありません</p><p class="playlist-empty-sub">「新規作成」からプレイリストを作成しましょう</p></div>';
    } else {
        body.innerHTML = pls.map((pl, pi) => {
            const vids = pl.videos.map(t => VIDEOS.find(v => v.title === t)).filter(Boolean);
            const watchedCount = vids.filter(v => isWatched(v.title)).length;
            return `<div class="playlist-item">
                <div class="playlist-item-header" onclick="togglePlaylistExpand(this)">
                    <div class="playlist-item-info">
                        <h4 class="playlist-item-name">${pl.name}</h4>
                        <span class="playlist-item-count">${vids.length}本 · ${watchedCount}本視聴済み</span>
                    </div>
                    <div class="playlist-item-actions">
                        <button class="playlist-delete-btn" onclick="event.stopPropagation();deletePlaylistConfirm(${pi})" title="削除">×</button>
                    </div>
                </div>
                <div class="playlist-item-videos" style="display:none;">
                    ${vids.length === 0 ? '<p class="playlist-videos-empty">動画がありません</p>' : vids.map((v, vi) => {
                        const idx = VIDEOS.indexOf(v);
                        const watched = isWatched(v.title);
                        return `<div class="playlist-video ${watched ? 'is-watched' : ''}" onclick="closePlaylistModal();openModal(${idx})">
                            <span class="playlist-video-num">${vi + 1}</span>
                            <div class="playlist-video-thumb">${v.thumb ? `<img src="${v.thumb}" loading="lazy">` : ''}</div>
                            <span class="playlist-video-title">${v.title}</span>
                            <button class="playlist-video-remove" onclick="event.stopPropagation();removeFromPlaylist(${pi},'${v.title.replace(/'/g, "\\'")}');openPlaylistModal();" title="削除">×</button>
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }).join('');
    }

    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
}
function closePlaylistModal() {
    document.getElementById('playlistModal').classList.remove('open');
    document.body.style.overflow = '';
}
function togglePlaylistExpand(el) {
    const videos = el.nextElementSibling;
    videos.style.display = videos.style.display === 'none' ? '' : 'none';
}
function createPlaylistPrompt() {
    const name = prompt('プレイリスト名を入力');
    if (name && name.trim()) { createPlaylist(name.trim()); openPlaylistModal(); }
}
function deletePlaylistConfirm(idx) {
    if (confirm('このプレイリストを削除しますか？')) { deletePlaylist(idx); openPlaylistModal(); }
}
function playPlaylist(plIdx) {
    const pls = getPlaylists();
    if (!pls[plIdx] || pls[plIdx].videos.length === 0) return;
    const firstTitle = pls[plIdx].videos[0];
    const v = VIDEOS.find(vid => vid.title === firstTitle);
    if (v) { closePlaylistModal(); openModal(VIDEOS.indexOf(v)); }
}
function showAddToPlaylistMenu(vidTitle) {
    // Remove existing popup
    const existing = document.getElementById('plAddPopup');
    if (existing) { existing.remove(); document.removeEventListener('click', closePlAddPopup); return; }

    const pls = getPlaylists();
    const popup = document.createElement('div');
    popup.id = 'plAddPopup';
    popup.className = 'pl-add-popup';
    popup.onclick = e => e.stopPropagation(); // Prevent close on self click

    const header = `<div class="pl-add-header">プレイリストに保存</div>`;

    const list = pls.map((p, i) => {
        const isIn = p.videos.includes(vidTitle);
        return `<label class="pl-add-item" onclick="event.stopPropagation();">
            <input type="checkbox" ${isIn ? 'checked' : ''} data-pl-idx="${i}">
            <span class="pl-add-check">${isIn ? '✓' : ''}</span>
            <span class="pl-add-name">${p.name}</span>
            <span class="pl-add-count">${p.videos.length}本</span>
        </label>`;
    }).join('');

    const saveBtn = `<div class="pl-add-save-wrap" onclick="event.stopPropagation();">
        <button class="pl-add-save-btn" onclick="savePlAddPopup(\`${vidTitle.replace(/`/g, '')}\`)">保存</button>
    </div>`;

    const createBtn = `<div class="pl-add-create" onclick="event.stopPropagation();createPlaylistInline()">
        <span class="pl-add-create-icon">＋</span> 新しいプレイリストを作成
    </div>`;
    const createForm = `<div class="pl-add-create-form" id="plCreateForm" style="display:none;">
        <input type="text" class="pl-add-create-input" id="plCreateInput" placeholder="プレイリスト名" onclick="event.stopPropagation();">
        <button class="pl-add-create-submit" onclick="event.stopPropagation();submitNewPlaylist(\`${vidTitle.replace(/`/g, '')}\`)">作成</button>
    </div>`;

    popup.innerHTML = header + '<div class="pl-add-list">' + list + '</div>' + saveBtn + createBtn + createForm;

    // Update check marks on click
    popup.querySelectorAll('.pl-add-item input').forEach(input => {
        input.addEventListener('change', () => {
            const check = input.parentElement.querySelector('.pl-add-check');
            check.textContent = input.checked ? '✓' : '';
        });
    });

    // Add to modal-actions area (relative parent)
    const actionsDiv = document.querySelector('.modal-actions');
    if (actionsDiv) {
        actionsDiv.style.position = 'relative';
        actionsDiv.appendChild(popup);
    }

    // Close on outside click (delayed to avoid immediate close)
    setTimeout(() => {
        document.addEventListener('click', closePlAddPopup);
    }, 50);
}

function closePlAddPopup(e) {
    const popup = document.getElementById('plAddPopup');
    const addBtn = document.getElementById('modalAddPlaylist');
    if (!popup) return;
    if (popup.contains(e?.target)) return;
    if (addBtn && addBtn.contains(e?.target)) return;
    popup.remove();
    document.removeEventListener('click', closePlAddPopup);
}

function savePlAddPopup(vidTitle) {
    const popup = document.getElementById('plAddPopup');
    if (!popup) return;
    const pls = getPlaylists();
    popup.querySelectorAll('.pl-add-item input').forEach(input => {
        const idx = parseInt(input.dataset.plIdx);
        if (isNaN(idx) || !pls[idx]) return;
        if (input.checked && !pls[idx].videos.includes(vidTitle)) {
            pls[idx].videos.push(vidTitle);
        } else if (!input.checked && pls[idx].videos.includes(vidTitle)) {
            pls[idx].videos = pls[idx].videos.filter(t => t !== vidTitle);
        }
    });
    savePlaylists(pls);
    // Close popup and show confirmation
    popup.remove();
    document.removeEventListener('click', closePlAddPopup);
    const btn = document.getElementById('modalAddPlaylist');
    if (btn) {
        const original = btn.innerHTML;
        btn.innerHTML = '✓ 保存しました';
        setTimeout(() => { btn.innerHTML = original; }, 1500);
    }
}

function createPlaylistInline() {
    const form = document.getElementById('plCreateForm');
    if (form) {
        form.style.display = '';
        document.getElementById('plCreateInput').focus();
    }
}

function submitNewPlaylist(vidTitle) {
    const input = document.getElementById('plCreateInput');
    const name = input.value.trim();
    if (!name) return;
    createPlaylist(name);
    const pls = getPlaylists();
    addToPlaylist(pls.length - 1, vidTitle);
    // Refresh popup
    const popup = document.getElementById('plAddPopup');
    if (popup) popup.remove();
    document.removeEventListener('click', closePlAddPopup);
    showAddToPlaylistMenu(vidTitle);
}

function filterByLevel(level) {
    activeLevels = level === 'all' ? [] : [level];
    syncLevelCheckboxes();
    currentPage = 1; renderVideos(); updateActiveFilters();
    document.querySelector('.main-section').scrollIntoView({ behavior: 'smooth' });
}

// === History Row ===
function renderHistoryRow() {
    const history = getHistory();
    const section = document.getElementById('historySection');
    const scroll = document.getElementById('historyScroll');
    if (history.length === 0) { section.style.display = 'none'; return; }
    section.style.display = '';
    const vids = history.map(t => VIDEOS.find(v => v.title === t)).filter(Boolean).slice(0, 10);
    scroll.innerHTML = vids.map(v => {
        const idx = VIDEOS.indexOf(v);
        return `<a class="history-card" onclick="openModal(${idx}); return false;" href="#">
            <div class="history-card-thumb"><img src="${v.thumb || ''}" alt="" loading="lazy"></div>
            <div class="history-card-title">${v.title}</div>
        </a>`;
    }).join('');
}

// === Watch Later Row ===
function renderWatchLaterRow() {
    const wl = getWatchLater();
    const section = document.getElementById('watchLaterSection');
    const scroll = document.getElementById('watchLaterScroll');
    if (wl.length === 0 && !showWatchLater) { section.style.display = 'none'; return; }
    section.style.display = wl.length > 0 ? '' : 'none';
    const vids = wl.map(t => VIDEOS.find(v => v.title === t)).filter(Boolean);
    scroll.innerHTML = vids.map(v => {
        const idx = VIDEOS.indexOf(v);
        return `<a class="history-card" onclick="openModal(${idx}); return false;" href="#">
            <div class="history-card-thumb"><img src="${v.thumb || ''}" alt="" loading="lazy"></div>
            <div class="history-card-title">${v.title}</div>
        </a>`;
    }).join('');
}

function escapeRegex(str) { return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function highlightText(text, q) { if (!q) return text; return text.replace(new RegExp(escapeRegex(q), 'gi'), m => `<mark>${m}</mark>`); }
function formatDate(d) { if (!d) return ''; const [y, m, day] = d.split('-'); return `${y}/${parseInt(m)}/${parseInt(day)}`; }
function formatDuration(sec) { if (!sec) return ''; const h = Math.floor(sec/3600); const m = Math.floor((sec%3600)/60); const s = sec%60; return h > 0 ? h+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0') : m+':'+String(s).padStart(2,'0'); }
function isShort(v) {
    // 優先順位: is_short フィールド > URL > duration
    // update_videos.py が is_short を必ずセットするよう修正済みのため、
    // 新規動画では is_short が常に存在する。既存データのフォールバックとして URL/duration も見る。
    if (typeof v.is_short === 'boolean') return v.is_short;
    if (v.url && v.url.includes('/shorts/')) return true;
    // YouTube Shorts は最大 180 秒まで許容されているため閾値は 180
    if (v.duration && v.duration <= 180) return true;
    return false;
}
function isLive(v) { return v.title && v.title.includes('ライブ配信'); }
function getVideoType(v) { if (isShort(v)) return 'short'; if (isLive(v)) return 'live'; return 'long'; }

// === Keyboard navigation ===
document.addEventListener('keydown', e => {
    // Skip if memo list modal is open
    const memoListModal = document.getElementById('memoListModal');
    if (memoListModal && memoListModal.classList.contains('open')) return;
    // Skip if video modal is not open
    if (!document.getElementById('videoModal').classList.contains('open')) return;
    // Skip if typing in textarea or input
    if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;

    const filtered = getFilteredVideos();
    const currentFiltered = filtered.findIndex(v => VIDEOS.indexOf(v) === currentModalIndex);

    if (e.key === 'ArrowRight') {
        e.preventDefault();
        if (currentFiltered < filtered.length - 1) openModal(VIDEOS.indexOf(filtered[currentFiltered + 1]));
    } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        if (currentFiltered > 0) openModal(VIDEOS.indexOf(filtered[currentFiltered - 1]));
    }
});

// === Filter URL sync ===
function saveFiltersToURL() {
    try {
        const params = new URLSearchParams();
        if (activeLevels.length > 0) params.set('level', activeLevels.join(','));
        if (activeCategories.length > 0) params.set('cat', activeCategories.join(','));
        if (activeMethod !== 'all') params.set('method', activeMethod);
        if (searchQuery) params.set('q', searchQuery);
        if (sortMode !== 'date-new') params.set('sort', sortMode);
        const str = params.toString();
        history.replaceState(null, '', str ? '?' + str : location.pathname);
    } catch(e) {}
}
function restoreFiltersFromURL() {
    const params = new URLSearchParams(location.search);
    if (params.has('level')) activeLevels = params.get('level').split(',').filter(Boolean);
    if (params.has('cat')) activeCategories = params.get('cat').split(',').filter(Boolean);
    if (params.has('method')) activeMethod = params.get('method');
    if (params.has('q')) { searchQuery = params.get('q'); const si = document.getElementById('searchInput'); if (si) si.value = searchQuery; }
    if (params.has('sort')) sortMode = params.get('sort');
    // Apply to UI after DOM ready
    setTimeout(() => {
        syncLevelCheckboxes();
        if (activeMethod !== 'all') { const r = document.querySelector(`#methodFilters input[value="${activeMethod}"]`); if (r) r.checked = true; }
        if (activeCategories.length > 0) {
            document.querySelector('#categoryFilters .sidebar-tag[data-cat="all"]').classList.remove('active');
            activeCategories.forEach(cat => {
                const btn = document.querySelector(`#categoryFilters .sidebar-tag[data-cat="${cat}"]`);
                if (btn) btn.classList.add('active');
            });
        }
        if (sortMode !== 'date-new') { const sel = document.getElementById('sortSelect'); if (sel) sel.value = sortMode; }
        renderVideos();
        updateActiveFilters();
    }, 100);
}

// === Dark mode ===
function initDarkMode() {
    const saved = localStorage.getItem('vn_darkmode');
    if (saved === '1') document.body.classList.add('dark-mode');
    const btn = document.getElementById('darkModeToggle');
    if (btn) {
        btn.onclick = () => {
            document.body.classList.toggle('dark-mode');
            localStorage.setItem('vn_darkmode', document.body.classList.contains('dark-mode') ? '1' : '0');
        };
    }
}
