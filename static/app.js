/**
 * YouTube Creator Studio - Frontend Logic
 * Handles chat, tool execution, transcript display, and video preview
 */

// ============================================================================
// State
// ============================================================================

const state = {
    conversationHistory: [],
    transcripts: {},  // Store fetched YouTube transcripts by video_id
    generatedTranscripts: {},  // Store AI-generated transcripts by script_id
    currentVideoId: null,
    tools: [],
    isLoading: false,
    activeTab: 'fetched',  // 'fetched' or 'generated'
    // Mode: 'creative' or 'precise'
    mode: 'creative',
    // Playback state
    isPlaying: false,
    playbackSegmentIndex: 0,
    playbackTimer: null,
    currentSegments: [],
    // Log tracking for export
    chatLogs: [],
    // Server logs state
    serverLogsAutoRefresh: true,
    serverLogsInterval: null
};

// ============================================================================
// DOM Elements
// ============================================================================

const elements = {
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    sendBtn: document.getElementById('send-btn'),
    toolsList: document.getElementById('tools-list'),
    transcriptContainer: document.getElementById('transcript-container'),
    transcriptSelector: document.getElementById('transcript-selector'),
    previewContainer: document.getElementById('preview-container'),
    downloadsList: document.getElementById('downloads-list'),
    refreshVideosBtn: document.getElementById('refresh-videos-btn'),
    modal: document.getElementById('tool-modal'),
    modalTitle: document.getElementById('modal-title'),
    modalClose: document.getElementById('modal-close'),
    modalCancel: document.getElementById('modal-cancel'),
    toolForm: document.getElementById('tool-form'),
    toolParams: document.getElementById('tool-params'),
    modalResult: document.getElementById('modal-result'),
    toolResultContent: document.getElementById('tool-result-content'),
    deleteTranscriptBtn: document.getElementById('delete-transcript-btn'),
    clearAllBtn: document.getElementById('clear-all-btn'),
    // Tab elements
    tabFetched: document.getElementById('tab-fetched'),
    tabGenerated: document.getElementById('tab-generated'),
    // Playback elements
    playTranscriptBtn: document.getElementById('play-transcript-btn'),
    stopTranscriptBtn: document.getElementById('stop-transcript-btn'),
    playbackStatus: document.getElementById('playback-status'),
    // Export elements
    exportLogsBtn: document.getElementById('export-logs-btn'),
    // Server logs elements
    logsContainer: document.getElementById('logs-container'),
    progressSection: document.getElementById('progress-section'),
    progressLabel: document.getElementById('progress-label'),
    progressFill: document.getElementById('progress-fill'),
    progressPercent: document.getElementById('progress-percent'),
    refreshStatus: document.getElementById('refresh-status'),
    toggleRefreshBtn: document.getElementById('toggle-refresh-btn'),
    clearLogsBtn: document.getElementById('clear-logs-btn')
};

// ============================================================================
// Initialize
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadTools();
    loadVideos();
    loadCachedTranscripts();
    loadGeneratedTranscripts();
    setupEventListeners();
});

function setupEventListeners() {
    // Send message
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Transcript selector - select from active tab's data
    elements.transcriptSelector.addEventListener('change', (e) => {
        if (e.target.value) {
            const source = state.activeTab === 'fetched' ? state.transcripts : state.generatedTranscripts;
            displayTranscript(source[e.target.value]);
        }
    });

    // Refresh videos
    elements.refreshVideosBtn.addEventListener('click', loadVideos);

    // Modal
    elements.modalClose.addEventListener('click', closeModal);
    elements.modalCancel.addEventListener('click', closeModal);
    elements.modal.addEventListener('click', (e) => {
        if (e.target === elements.modal) closeModal();
    });
    elements.toolForm.addEventListener('submit', handleToolSubmit);

    // Cache management
    elements.deleteTranscriptBtn.addEventListener('click', deleteSelectedTranscript);
    elements.clearAllBtn.addEventListener('click', clearAllTranscripts);

    // Tab switching
    elements.tabFetched.addEventListener('click', () => switchTab('fetched'));
    elements.tabGenerated.addEventListener('click', () => switchTab('generated'));

    // Playback controls
    elements.playTranscriptBtn.addEventListener('click', startPlayback);
    elements.stopTranscriptBtn.addEventListener('click', stopPlayback);

    // Log export
    elements.exportLogsBtn.addEventListener('click', exportLogsToHtml);

    // Server logs controls
    if (elements.toggleRefreshBtn) {
        elements.toggleRefreshBtn.addEventListener('click', toggleServerLogsRefresh);
    }
    if (elements.clearLogsBtn) {
        elements.clearLogsBtn.addEventListener('click', clearServerLogs);
    }

    // Mode toggle
    document.getElementById('mode-creative')?.addEventListener('click', () => setMode('creative'));
    document.getElementById('mode-precise')?.addEventListener('click', () => setMode('precise'));

    // Start server logs auto-refresh
    startServerLogsRefresh();
}

// ============================================================================
// Chat Functions
// ============================================================================

function setMode(mode) {
    state.mode = mode;

    // Update button states
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Clear conversation history when switching modes
    state.conversationHistory = [];

    // Show mode-specific welcome message
    const modeMessages = {
        creative: '🎨 <strong>Creative Mode</strong>: I\'ll create original remix videos from transcripts.',
        precise: '🎯 <strong>Precise Mode</strong>: I\'ll extract exact words from videos to match your text.'
    };

    addMessageToChat('assistant', `<p>${modeMessages[mode]}</p>`);
}

async function sendMessage() {
    const message = elements.chatInput.value.trim();
    if (!message || state.isLoading) return;

    const timestamp = new Date().toISOString();

    // Add user message to UI and logs
    addMessageToChat('user', message);
    elements.chatInput.value = '';
    state.chatLogs.push({ timestamp, role: 'user', content: message });

    // Add to history
    state.conversationHistory.push({ role: 'user', content: message });

    // Show loading state with pending indicator
    setLoading(true);
    const loadingMsg = addMessageToChat('assistant', `
        <div class="tool-call pending">
            <div class="tool-call-header">
                <span class="tool-icon">⏳</span>
                Processing request...
            </div>
        </div>
    `);

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: state.conversationHistory.slice(0, -1),
                mode: state.mode
            })
        });

        const data = await response.json();

        // Remove loading message
        loadingMsg.remove();

        // Process response
        if (data.error) {
            addMessageToChat('assistant', `❌ Error: ${data.error}`);
            state.chatLogs.push({ timestamp: new Date().toISOString(), role: 'error', content: data.error });
        } else {
            // Build response HTML
            let html = '';

            // Add tool calls if any
            if (data.tool_calls && data.tool_calls.length > 0) {
                for (let i = 0; i < data.tool_calls.length; i++) {
                    const tc = data.tool_calls[i];
                    const tr = data.tool_results?.[i];
                    const status = tr?.success ? 'success' : 'error';
                    const resultStr = tr ? JSON.stringify(tr.result || tr.error, null, 2) : 'pending';

                    // Log tool call
                    state.chatLogs.push({
                        timestamp: new Date().toISOString(),
                        role: 'tool_call',
                        tool_name: tc.name,
                        args: tc.args,
                        result: tr,
                        status: status
                    });

                    html += `
                        <div class="tool-call ${status}">
                            <div class="tool-call-header" onclick="this.nextElementSibling.classList.toggle('expanded')">
                                <span class="tool-icon">${status === 'success' ? '✅' : '❌'}</span>
                                ${tc.name}(${Object.keys(tc.args || {}).join(', ')})
                                <span class="expand-hint">▼ Click to expand</span>
                            </div>
                            <div class="tool-call-details">
                                <strong>Args:</strong>
                                <pre>${JSON.stringify(tc.args, null, 2)}</pre>
                                <strong>Result:</strong>
                                <pre class="result-pre">${escapeHtml(resultStr)}</pre>
                            </div>
                        </div>
                    `;

                    // Store transcript data if available
                    if (tc.name === 'get_youtube_transcript' && tr?.success && tr?.result) {
                        const videoId = tr.result.video_id;
                        state.transcripts[videoId] = tr.result;
                        updateTranscriptSelector();
                    }
                }
            }

            // Add text response
            if (data.response) {
                html += formatMarkdown(data.response);
                state.chatLogs.push({
                    timestamp: new Date().toISOString(),
                    role: 'assistant',
                    content: data.response
                });
            }

            addMessageToChat('assistant', html);
            state.conversationHistory.push({ role: 'assistant', content: data.response });

            // Handle transcript data from response
            if (data.transcript_data) {
                const videoId = data.transcript_data.video_id;
                state.transcripts[videoId] = data.transcript_data;
                updateTranscriptSelector();
                displayTranscript(data.transcript_data);
            }

            // Handle suggested clips
            if (data.suggested_clips && data.suggested_clips.length > 0) {
                showClipPreview(data.suggested_clips[0]);
            }

            // Refresh videos list
            loadVideos();

            // Load any new cached transcripts
            loadCachedTranscripts();
            loadGeneratedTranscripts();
        }
    } catch (error) {
        loadingMsg.remove();
        addMessageToChat('assistant', `❌ Network error: ${error.message}`);
    }

    setLoading(false);
}

function addMessageToChat(role, content, rawContent = null) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    // Store raw content for copying (strip HTML for clean copy)
    const textToCopy = rawContent || content.replace(/<[^>]*>/g, '');
    msg.innerHTML = `
        <div class="message-content">${content}</div>
        <div class="message-actions">
            <button class="copy-btn" onclick="copyToClipboard(this)" data-copy-text="${escapeHtml(textToCopy)}" title="Copy to clipboard">📋</button>
        </div>
    `;
    elements.chatMessages.appendChild(msg);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    return msg;
}

async function copyToClipboard(btn) {
    const text = btn.dataset.copyText;
    try {
        await navigator.clipboard.writeText(text);
        const originalText = btn.textContent;
        btn.textContent = '✅';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = originalText;
            btn.classList.remove('copied');
        }, 2000);
    } catch (err) {
        console.error('Copy failed:', err);
        btn.textContent = '❌';
        setTimeout(() => btn.textContent = '📋', 2000);
    }
}

function setLoading(loading) {
    state.isLoading = loading;
    elements.sendBtn.disabled = loading;
}

// ============================================================================
// Transcript Functions
// ============================================================================

async function loadCachedTranscripts() {
    try {
        const response = await fetch('/api/transcripts');
        const data = await response.json();

        if (data.transcripts) {
            // Merge with existing transcripts
            Object.assign(state.transcripts, data.transcripts);
            if (state.activeTab === 'fetched') {
                updateTranscriptSelector();
            }
        }
    } catch (error) {
        console.error('Failed to load cached transcripts:', error);
    }
}

async function loadGeneratedTranscripts() {
    try {
        const response = await fetch('/api/generated-transcripts');
        const data = await response.json();

        if (data.transcripts) {
            // Merge with existing generated transcripts
            Object.assign(state.generatedTranscripts, data.transcripts);
            if (state.activeTab === 'generated') {
                updateTranscriptSelector();
            }
        }
    } catch (error) {
        console.error('Failed to load generated transcripts:', error);
    }
}

function switchTab(tab) {
    state.activeTab = tab;

    // Update buttons
    elements.tabFetched.classList.toggle('active', tab === 'fetched');
    elements.tabGenerated.classList.toggle('active', tab === 'generated');
    if (elements.tabPrecise) {
        elements.tabPrecise.classList.toggle('active', tab === 'precise');
    }

    // Stop any current playback
    stopPlayback();

    // Toggle visibility based on tab
    if (tab === 'precise') {
        if (elements.transcriptControls) elements.transcriptControls.style.display = 'none';
        if (elements.playbackControls) elements.playbackControls.style.display = 'none';
        elements.transcriptContainer.style.display = 'none';

        // Show precise container
        if (elements.preciseWordsContainer) {
            elements.preciseWordsContainer.style.display = 'flex';
            loadPreciseWords(); // Refresh data
        }
    } else {
        if (elements.transcriptControls) elements.transcriptControls.style.display = 'flex';
        if (elements.playbackControls) elements.playbackControls.style.display = 'flex';
        elements.transcriptContainer.style.display = 'block';

        // Hide precise container
        if (elements.preciseWordsContainer) {
            elements.preciseWordsContainer.style.display = 'none';
        }

        updateTranscriptSelector();

        // Restore empty state if needed
        if (!elements.transcriptContainer.innerHTML.trim()) {
            elements.transcriptContainer.innerHTML = `
                <div class="empty-state">
                    <p>Select a ${tab === 'fetched' ? 'transcript' : 'generated script'} from the dropdown above.</p>
                </div>
            `;
        }
    }
}

function updateTranscriptSelector() {
    const selector = elements.transcriptSelector;
    const currentValue = selector.value;

    // Determine which data source to use based on active tab
    const source = state.activeTab === 'fetched' ? state.transcripts : state.generatedTranscripts;

    // Clear existing options except the first one
    while (selector.options.length > 1) {
        selector.remove(1);
    }

    // Update placeholder text
    selector.options[0].textContent = state.activeTab === 'fetched'
        ? '-- Select a video --'
        : '-- Select a script --';

    // Add options for each transcript
    for (const [videoId, transcript] of Object.entries(source)) {
        const option = document.createElement('option');
        option.value = videoId;
        // Show title and channel if available, otherwise fallback to video ID
        const title = transcript.title || `Video ${videoId}`;
        const channel = transcript.channel || '';
        const duration = formatTime(transcript.total_duration || 0);
        option.textContent = channel ? `${title} - ${channel} (${duration})` : `${title} (${duration})`;
        option.title = `${title} by ${channel}`; // Tooltip
        selector.appendChild(option);
    }

    // Restore selection or select the latest
    if (currentValue && source[currentValue]) {
        selector.value = currentValue;
    } else if (Object.keys(source).length > 0) {
        const lastKey = Object.keys(source).pop();
        selector.value = lastKey;
        displayTranscript(source[lastKey]);
    }
}

async function displayTranscript(transcriptData) {
    if (!transcriptData) return;

    // If we only have the summary, fetch the full transcript from cache
    let segments = transcriptData.segments;
    const videoId = transcriptData.video_id;

    if (!segments && videoId) {
        try {
            // Use correct API endpoint based on active tab
            const endpoint = state.activeTab === 'generated'
                ? `/api/generated-transcripts/${videoId}`
                : `/api/transcripts/${videoId}`;
            const response = await fetch(endpoint);
            if (response.ok) {
                const fullData = await response.json();
                segments = fullData.segments;
                // Update local cache
                if (state.activeTab === 'generated') {
                    state.generatedTranscripts[videoId] = fullData;
                } else {
                    state.transcripts[videoId] = fullData;
                }
            }
        } catch (e) {
            console.error('Failed to load full transcript:', e);
        }
    }

    state.currentVideoId = videoId;
    // Store segments for playback
    state.currentSegments = segments || [];

    // Get title and channel if available
    const title = transcriptData.title || `Video ${videoId}`;
    const channel = transcriptData.channel || 'Unknown Channel';

    let html = `
        <div class="transcript-header">
            <h4>📄 ${escapeHtml(title)}</h4>
            <div class="meta">
                <strong>Channel:</strong> ${escapeHtml(channel)} • 
                <strong>Duration:</strong> ${formatTime(transcriptData.total_duration)} • 
                ${transcriptData.segment_count || (segments?.length || 0)} segments
            </div>
            <div class="video-id">ID: ${videoId}</div>
        </div>
    `;

    if (segments && segments.length > 0) {
        html += '<div class="transcript-segments">';
        for (let i = 0; i < segments.length; i++) {
            const seg = segments[i];
            // Support mixed-source transcripts (scripts)
            const targetVideoId = seg.video_id || videoId;
            const sourceLabel = seg.video_id ? `<span class="segment-source" title="Source Video">${seg.video_id}</span>` : '';

            html += `
                <div class="transcript-segment" 
                     onclick="openYouTubeAtTime('${targetVideoId}', ${seg.start})"
                     data-index="${i}"
                     data-start="${seg.start}" 
                     data-end="${seg.end}"
                     data-video-id="${targetVideoId}">
                    <div class="segment-header">
                        <span class="segment-time">${formatTime(seg.start)}</span>
                        ${sourceLabel}
                    </div>
                    <span class="segment-text">${escapeHtml(seg.text)}</span>
                </div>
            `;
        }
        html += '</div>';
    } else if (transcriptData.full_text) {
        // Show full text if segments not available
        html += `<div class="transcript-full-text">${escapeHtml(transcriptData.full_text)}</div>`;
    }

    elements.transcriptContainer.innerHTML = html;

    // Enable playback button if we have segments
    elements.playTranscriptBtn.disabled = !segments || segments.length === 0;
}

function openYouTubeAtTime(videoId, startTime) {
    const startSeconds = Math.floor(startTime);
    showYouTubeEmbed(videoId, startSeconds);
}

// ============================================================================
// Playback Functions
// ============================================================================

function startPlayback() {
    if (state.currentSegments.length === 0) {
        elements.playbackStatus.textContent = 'No segments to play';
        return;
    }

    state.isPlaying = true;
    state.playbackSegmentIndex = 0;

    // Update UI
    elements.playTranscriptBtn.disabled = true;
    elements.stopTranscriptBtn.disabled = false;

    // Start playing first segment
    playSegment(0);
}

function stopPlayback() {
    state.isPlaying = false;

    // Clear any pending timer
    if (state.playbackTimer) {
        clearTimeout(state.playbackTimer);
        state.playbackTimer = null;
    }

    // Update UI
    elements.playTranscriptBtn.disabled = state.currentSegments.length === 0;
    elements.stopTranscriptBtn.disabled = true;
    elements.playbackStatus.textContent = 'Ready';

    // Remove playing highlight from all segments
    document.querySelectorAll('.transcript-segment.playing').forEach(el => {
        el.classList.remove('playing');
    });
}

function playSegment(index) {
    if (!state.isPlaying || index >= state.currentSegments.length) {
        // Finished playing all segments
        stopPlayback();
        elements.playbackStatus.textContent = 'Finished';
        return;
    }

    const segment = state.currentSegments[index];
    const videoId = segment.video_id || state.currentVideoId;
    const startTime = segment.start;
    const endTime = segment.end;
    const duration = endTime - startTime;

    state.playbackSegmentIndex = index;

    // Update status
    elements.playbackStatus.textContent = `Playing ${index + 1}/${state.currentSegments.length}`;

    // Highlight current segment
    document.querySelectorAll('.transcript-segment.playing').forEach(el => {
        el.classList.remove('playing');
    });
    const currentSegmentEl = document.querySelector(`.transcript-segment[data-index="${index}"]`);
    if (currentSegmentEl) {
        currentSegmentEl.classList.add('playing');
        currentSegmentEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // Load YouTube embed with start and end time
    showYouTubeEmbed(videoId, Math.floor(startTime), Math.ceil(endTime));

    // Schedule next segment after this one's duration
    // Add a small buffer (0.5s) to account for loading time
    state.playbackTimer = setTimeout(() => {
        playSegment(index + 1);
    }, (duration + 0.5) * 1000);
}

// ============================================================================
// Video Functions
// ============================================================================

async function loadVideos() {
    try {
        const response = await fetch('/api/videos');
        const data = await response.json();

        if (data.videos && data.videos.length > 0) {
            // Group videos by source (extract video ID from filename if possible)
            const grouped = {};
            const stitched = [];

            for (const video of data.videos) {
                // Check if it's a stitched video
                if (video.name.includes('stitched') || video.name.includes('final')) {
                    stitched.push(video);
                } else {
                    // Try to extract video ID from filename
                    const match = video.name.match(/([a-zA-Z0-9_-]{11})/);
                    const groupKey = match ? match[1] : 'Other';
                    if (!grouped[groupKey]) grouped[groupKey] = [];
                    grouped[groupKey].push(video);
                }
            }

            let html = '<div class="downloads-header">📁 Downloaded Clips:</div>';

            // Add stitched videos first
            if (stitched.length > 0) {
                html += '<div class="video-group"><div class="group-title">🎬 Final Videos</div>';
                for (const video of stitched) {
                    html += renderVideoItem(video);
                }
                html += '</div>';
            }

            // Add grouped clips with video title from cache
            for (const [groupKey, videos] of Object.entries(grouped)) {
                // Try to get title from cached transcripts
                const cachedTranscript = state.transcripts[groupKey];
                let groupTitle;
                if (cachedTranscript && cachedTranscript.title) {
                    groupTitle = cachedTranscript.channel
                        ? `${cachedTranscript.title} - ${cachedTranscript.channel}`
                        : cachedTranscript.title;
                } else {
                    groupTitle = groupKey === 'Other' ? 'Other Clips' : `Source: ${groupKey}`;
                }

                html += `<div class="video-group collapsed">
                    <div class="group-title" onclick="this.parentElement.classList.toggle('collapsed')">
                        📂 ${escapeHtml(groupTitle)} (${videos.length})
                        <span class="expand-arrow">▶</span>
                    </div>
                    <div class="group-items">`;
                for (const video of videos) {
                    html += renderVideoItem(video);
                }
                html += '</div></div>';
            }

            elements.downloadsList.innerHTML = html;
        } else {
            elements.downloadsList.innerHTML = '';
        }
    } catch (error) {
        console.error('Failed to load videos:', error);
    }
}

function renderVideoItem(video) {
    return `
        <div class="video-item" onclick="playVideo('${video.path}', '${escapeHtml(video.name)}')">
            <span class="video-icon">🎬</span>
            <div class="video-info">
                <div class="video-name">${escapeHtml(video.name)}</div>
                <div class="video-size">${video.size_mb} MB</div>
            </div>
        </div>
    `;
}

function playVideo(path, name) {
    elements.previewContainer.innerHTML = `
        <video controls autoplay>
            <source src="${path}" type="video/mp4">
            Your browser does not support video playback.
        </video>
        <div class="preview-info">${name}</div>
    `;
}

function showYouTubeEmbed(videoId, startTime = 0, endTime = null) {
    let src = `https://www.youtube.com/embed/${videoId}?autoplay=1&start=${startTime}`;
    if (endTime) {
        src += `&end=${endTime}`;
    }

    elements.previewContainer.innerHTML = `
        <iframe 
            src="${src}"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen>
        </iframe>
        <div class="preview-info">
            YouTube: ${videoId} @ ${formatTime(startTime)}${endTime ? ' - ' + formatTime(endTime) : ''}
        </div>
    `;
}

function showClipPreview(clip) {
    if (clip.video_id) {
        showYouTubeEmbed(clip.video_id, clip.start_time, clip.end_time);
    }
}

// ============================================================================
// Tools Functions
// ============================================================================

async function loadTools() {
    try {
        const response = await fetch('/api/tools');
        const data = await response.json();
        state.tools = data.tools || [];
        renderToolsList();
    } catch (error) {
        console.error('Failed to load tools:', error);
    }
}

function renderToolsList() {
    elements.toolsList.innerHTML = state.tools.map(tool => {
        // Get first sentence or first 60 chars for concise summary
        const summary = getToolSummary(tool.description);
        return `
            <div class="tool-item" onclick="openToolModal('${tool.name}')">
                <h4>${formatToolName(tool.name)}</h4>
                <p>${summary}</p>
            </div>
        `;
    }).join('');
}

function getToolSummary(description) {
    // Get first sentence (up to first period followed by space or end)
    const firstSentence = description.match(/^[^.]+\.?/);
    if (firstSentence && firstSentence[0].length <= 80) {
        return firstSentence[0];
    }
    // Fallback to first 60 chars without cutting words
    const words = description.split(' ');
    let summary = '';
    for (const word of words) {
        if ((summary + ' ' + word).length > 60) break;
        summary += (summary ? ' ' : '') + word;
    }
    return summary + '...';
}

function formatToolName(name) {
    return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function openToolModal(toolName) {
    const tool = state.tools.find(t => t.name === toolName);
    if (!tool) return;

    elements.modalTitle.textContent = formatToolName(toolName);
    elements.toolForm.dataset.toolName = toolName;
    elements.modalResult.style.display = 'none';

    // Build form fields with full description at top
    const props = tool.parameters?.properties || {};
    const required = tool.parameters?.required || [];

    // Add full tool description at top of modal form
    let formHtml = `
        <div class="tool-description">
            <p>${escapeHtml(tool.description)}</p>
        </div>
    `;

    formHtml += Object.entries(props).map(([name, prop]) => {
        const isRequired = required.includes(name);
        const type = prop.type === 'array' ? 'textarea' : 'text';
        return `
            <div class="form-group">
                <label>${name}${isRequired ? ' *' : ''}</label>
                ${type === 'textarea'
                ? `<textarea rows="3" name="${name}" ${isRequired ? 'required' : ''} placeholder="${prop.description || ''}"></textarea>`
                : `<input type="text" name="${name}" ${isRequired ? 'required' : ''} placeholder="${prop.description || ''}">`
            }
                <div class="hint">${prop.description || ''}</div>
            </div>
        `;
    }).join('');

    elements.toolParams.innerHTML = formHtml;

    elements.modal.classList.add('active');
}

function closeModal() {
    elements.modal.classList.remove('active');
}

async function handleToolSubmit(e) {
    e.preventDefault();

    const toolName = elements.toolForm.dataset.toolName;
    const formData = new FormData(elements.toolForm);
    const args = {};

    for (const [key, value] of formData.entries()) {
        if (value) {
            // Try to parse as JSON for arrays/objects
            try {
                args[key] = JSON.parse(value);
            } catch {
                // If not JSON, check if it's a number
                const num = parseFloat(value);
                args[key] = isNaN(num) ? value : num;
            }
        }
    }

    // Show loading state
    const submitBtn = elements.toolForm.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="loading">Executing</span>';
    submitBtn.disabled = true;
    elements.modalResult.style.display = 'none';

    try {
        const response = await fetch(`/api/tools/${toolName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_name: toolName, args })
        });

        const data = await response.json();

        elements.toolResultContent.textContent = JSON.stringify(data, null, 2);
        elements.modalResult.style.display = 'block';

        // If this was a transcript call, update the display
        if (toolName === 'get_youtube_transcript' && data.success && data.result) {
            const videoId = data.result.video_id;
            state.transcripts[videoId] = data.result;
            updateTranscriptSelector();
            displayTranscript(data.result);
        }

        // Refresh videos and transcripts after any tool call
        loadVideos();
        loadCachedTranscripts();
    } catch (error) {
        elements.toolResultContent.textContent = `Error: ${error.message}`;
        elements.modalResult.style.display = 'block';
    } finally {
        // Restore button state
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

// ============================================================================
// Cache Management Functions
// ============================================================================

async function deleteSelectedTranscript() {
    const videoId = elements.transcriptSelector.value;
    if (!videoId) {
        alert('Please select a transcript to delete');
        return;
    }

    const source = state.activeTab === 'fetched' ? state.transcripts : state.generatedTranscripts;
    const itemLabel = state.activeTab === 'fetched' ? 'transcript' : 'generated transcript';

    if (!confirm(`Delete ${itemLabel} "${source[videoId]?.title || videoId}"?`)) {
        return;
    }

    try {
        const endpoint = state.activeTab === 'generated'
            ? `/api/generated-transcripts/${videoId}`
            : `/api/transcripts/${videoId}`;
        const response = await fetch(endpoint, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            if (state.activeTab === 'generated') {
                delete state.generatedTranscripts[videoId];
            } else {
                delete state.transcripts[videoId];
            }
            updateTranscriptSelector();
            elements.transcriptContainer.innerHTML = `
                <div class="empty-state">
                    <p>${itemLabel.charAt(0).toUpperCase() + itemLabel.slice(1)} deleted.</p>
                    <p class="hint">Select another ${itemLabel} or create new ones.</p>
                </div>
            `;
        } else {
            alert('Failed to delete: ' + (data.detail || data.message));
        }
    } catch (error) {
        alert('Error deleting: ' + error.message);
    }
}

async function clearAllTranscripts() {
    const source = state.activeTab === 'fetched' ? state.transcripts : state.generatedTranscripts;
    const count = Object.keys(source).length;
    const itemLabel = state.activeTab === 'fetched' ? 'transcripts' : 'generated transcripts';

    if (count === 0) {
        alert(`No ${itemLabel} to clear`);
        return;
    }

    if (!confirm(`Delete ALL ${count} ${itemLabel}? This cannot be undone.`)) {
        return;
    }

    try {
        const endpoint = state.activeTab === 'generated'
            ? '/api/generated-transcripts'
            : '/api/transcripts';
        const response = await fetch(endpoint, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            if (state.activeTab === 'generated') {
                state.generatedTranscripts = {};
            } else {
                state.transcripts = {};
            }
            updateTranscriptSelector();
            elements.transcriptContainer.innerHTML = `
                <div class="empty-state">
                    <p>All ${itemLabel} cleared.</p>
                    <p class="hint">Fetch new transcripts or create scripts to get started.</p>
                </div>
            `;
        } else {
            alert('Failed to clear: ' + (data.detail || data.message));
        }
    } catch (error) {
        alert('Error clearing: ' + error.message);
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatTime(seconds) {
    if (typeof seconds !== 'number') return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatMarkdown(text) {
    if (!text) return '';
    // Basic markdown formatting
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

// ============================================================================
// Log Export Functions
// ============================================================================

function exportLogsToHtml() {
    if (state.chatLogs.length === 0) {
        alert('No logs to export yet. Start a conversation first!');
        return;
    }

    const timestamp = new Date().toLocaleString();
    const filename = `youtube-creator-logs-${new Date().toISOString().slice(0, 10)}.html`;

    // Build modern HTML page
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Creator Studio - Chat Logs</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0f0f1a;
            --bg-secondary: #1a1a2e;
            --bg-tertiary: #252542;
            --accent: #6366f1;
            --accent-light: #8b5cf6;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --success: #10b981;
            --error: #ef4444;
            --warning: #f59e0b;
            --border-color: rgba(255, 255, 255, 0.1);
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            padding: 2rem;
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-light) 100%);
            border-radius: 16px;
            margin-bottom: 2rem;
        }
        
        header h1 {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        
        header p {
            opacity: 0.9;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
        }
        
        .stat-card .value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
        }
        
        .stat-card .label {
            color: var(--text-muted);
            font-size: 0.875rem;
        }
        
        .log-entry {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
        }
        
        .log-entry.user {
            border-left: 4px solid var(--accent);
        }
        
        .log-entry.assistant {
            border-left: 4px solid var(--success);
        }
        
        .log-entry.tool_call {
            border-left: 4px solid var(--warning);
        }
        
        .log-entry.error {
            border-left: 4px solid var(--error);
        }
        
        .log-header {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        
        .log-role {
            background: var(--bg-tertiary);
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .log-time {
            color: var(--text-muted);
            font-size: 0.75rem;
        }
        
        .log-content {
            color: var(--text-secondary);
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .tool-info {
            background: var(--bg-tertiary);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
        }
        
        .tool-info h4 {
            color: var(--accent);
            margin-bottom: 0.5rem;
        }
        
        details {
            margin-top: 0.5rem;
        }
        
        summary {
            cursor: pointer;
            color: var(--text-muted);
            font-size: 0.85rem;
            padding: 0.5rem;
            border-radius: 4px;
            background: var(--bg-primary);
            margin-bottom: 0.5rem;
        }
        
        summary:hover {
            background: var(--bg-secondary);
        }
        
        pre {
            background: var(--bg-primary);
            padding: 1rem;
            border-radius: 8px;
            overflow-x: auto;
            font-size: 0.8rem;
            margin-top: 0.5rem;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 300px;
            overflow-y: auto;
        }
        
        code {
            background: var(--bg-tertiary);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.875rem;
        }
        
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .status-badge.success { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .status-badge.error { background: rgba(239, 68, 68, 0.2); color: var(--error); }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 YouTube Creator Studio</h1>
            <p>Chat & Tool Logs Export</p>
            <p>Generated: ${timestamp}</p>
        </header>
        
        <div class="stats">
            <div class="stat-card">
                <div class="value">${state.chatLogs.filter(l => l.role === 'user').length}</div>
                <div class="label">User Messages</div>
            </div>
            <div class="stat-card">
                <div class="value">${state.chatLogs.filter(l => l.role === 'assistant').length}</div>
                <div class="label">AI Responses</div>
            </div>
            <div class="stat-card">
                <div class="value">${state.chatLogs.filter(l => l.role === 'tool_call').length}</div>
                <div class="label">Tool Calls</div>
            </div>
            <div class="stat-card">
                <div class="value">${state.chatLogs.filter(l => l.role === 'tool_call' && l.status === 'success').length}</div>
                <div class="label">Successful Tools</div>
            </div>
        </div>
        
        <h2 style="margin-bottom: 1rem;">📜 Conversation Log</h2>
        
        ${state.chatLogs.map(log => renderLogEntry(log)).join('')}
        
        <footer>
            <p>Exported from YouTube Creator Studio powered by Gemini AI</p>
        </footer>
    </div>
</body>
</html>`;

    // Download the file
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function renderLogEntry(log) {
    const time = new Date(log.timestamp).toLocaleTimeString();

    if (log.role === 'user') {
        return `
            <div class="log-entry user">
                <div class="log-header">
                    <span class="log-role">👤 User</span>
                    <span class="log-time">${time}</span>
                </div>
                <div class="log-content">${escapeHtml(log.content)}</div>
            </div>
        `;
    }

    if (log.role === 'assistant') {
        return `
            <div class="log-entry assistant">
                <div class="log-header">
                    <span class="log-role">🤖 Assistant</span>
                    <span class="log-time">${time}</span>
                </div>
                <div class="log-content">${escapeHtml(log.content)}</div>
            </div>
        `;
    }

    if (log.role === 'tool_call') {
        const statusBadge = log.status === 'success'
            ? '<span class="status-badge success">✅ Success</span>'
            : '<span class="status-badge error">❌ Error</span>';

        return `
            <div class="log-entry tool_call">
                <div class="log-header">
                    <span class="log-role">🔧 Tool Call</span>
                    <span class="log-time">${time}</span>
                    ${statusBadge}
                </div>
                <div class="tool-info">
                    <h4>${log.tool_name}</h4>
                    <details>
                        <summary>📋 View Arguments & Result (click to expand)</summary>
                        <strong>Arguments:</strong>
                        <pre>${JSON.stringify(log.args, null, 2)}</pre>
                        <strong>Result:</strong>
                        <pre>${JSON.stringify(log.result, null, 2)}</pre>
                    </details>
                </div>
            </div>
        `;
    }

    if (log.role === 'error') {
        return `
            <div class="log-entry error">
                <div class="log-header">
                    <span class="log-role">❌ Error</span>
                    <span class="log-time">${time}</span>
                </div>
                <div class="log-content">${escapeHtml(log.content)}</div>
            </div>
        `;
    }

    return '';
}

// ============================================================================
// Server Logs Functions
// ============================================================================

async function fetchServerLogs() {
    try {
        const response = await fetch('/api/logs');
        if (!response.ok) return;

        const data = await response.json();

        // Update logs display
        if (elements.logsContainer && data.logs) {
            renderServerLogs(data.logs);
        }

        // Update progress bar
        if (data.progress && data.progress.active) {
            showProgress(data.progress);
        } else {
            hideProgress();
        }
    } catch (error) {
        console.error('Failed to fetch server logs:', error);
    }
}

function renderServerLogs(logs) {
    if (!elements.logsContainer) return;

    elements.logsContainer.innerHTML = logs.map(log => `
        <div class="log-entry ${log.level}">
            <span class="log-time">${log.time}</span>
            <span class="log-message">${escapeHtml(log.message)}</span>
        </div>
    `).join('');

    // Auto-scroll to bottom
    elements.logsContainer.scrollTop = elements.logsContainer.scrollHeight;
}

function showProgress(progress) {
    if (!elements.progressSection) return;

    elements.progressSection.style.display = 'block';
    if (elements.progressLabel) elements.progressLabel.textContent = progress.label;
    if (elements.progressFill) elements.progressFill.style.width = `${progress.percent}%`;
    if (elements.progressPercent) elements.progressPercent.textContent = `${progress.percent}%`;
}

function hideProgress() {
    if (elements.progressSection) {
        elements.progressSection.style.display = 'none';
    }
}

function startServerLogsRefresh() {
    // Fetch immediately
    fetchServerLogs();

    // Then every 10 seconds
    state.serverLogsInterval = setInterval(fetchServerLogs, 10000);
    state.serverLogsAutoRefresh = true;

    if (elements.refreshStatus) {
        elements.refreshStatus.textContent = '🔄 Auto-refresh: ON';
        elements.refreshStatus.classList.remove('paused');
    }
    if (elements.toggleRefreshBtn) {
        elements.toggleRefreshBtn.textContent = '⏸️';
    }
}

function stopServerLogsRefresh() {
    if (state.serverLogsInterval) {
        clearInterval(state.serverLogsInterval);
        state.serverLogsInterval = null;
    }
    state.serverLogsAutoRefresh = false;

    if (elements.refreshStatus) {
        elements.refreshStatus.textContent = '⏸️ Auto-refresh: OFF';
        elements.refreshStatus.classList.add('paused');
    }
    if (elements.toggleRefreshBtn) {
        elements.toggleRefreshBtn.textContent = '▶️';
    }
}

function toggleServerLogsRefresh() {
    if (state.serverLogsAutoRefresh) {
        stopServerLogsRefresh();
    } else {
        startServerLogsRefresh();
    }
}

// ============================================================================
// Precise Words Functions
// ============================================================================

async function loadPreciseWords() {
    if (state.isLoading) return;

    try {
        const response = await fetch('/api/precise-words');
        if (!response.ok) throw new Error('Failed to fetch precise words');

        const data = await response.json();
        state.preciseWords = {};

        // Populate state and dropdown
        const selector = elements.preciseSentenceSelector;
        const currentSelection = selector.value;

        // Clear options except default
        while (selector.options.length > 1) {
            selector.remove(1);
        }

        if (data.sentences && data.sentences.length > 0) {
            data.sentences.forEach(s => {
                state.preciseWords[s.sentence_id] = s;

                const option = document.createElement('option');
                option.value = s.sentence_id;
                option.textContent = s.sentence;
                selector.appendChild(option);
            });

            // Restore selection or select latest
            if (currentSelection && state.preciseWords[currentSelection]) {
                selector.value = currentSelection;
            } else if (data.sentences.length > 0) {
                // Select most recent by default?
                selector.value = data.sentences[data.sentences.length - 1].sentence_id;
            }

            renderPreciseWords();
        } else {
            elements.preciseWordsGrid.innerHTML = `
                <div class="empty-state">
                    <p>No word clips extracted yet.</p>
                    <p class="hint">Switch to Precise mode and request a sentence to extract!</p>
                </div>
            `;
            elements.createPreciseVideoBtn.disabled = true;
        }

    } catch (error) {
        console.error('Error loading precise words:', error);
    }
}

function renderPreciseWords() {
    const sentenceId = elements.preciseSentenceSelector.value;
    const grid = elements.preciseWordsGrid;

    if (!sentenceId || !state.preciseWords[sentenceId]) {
        grid.innerHTML = '<div class="empty-state"><p>Select a sentence to view word clips</p></div>';
        elements.createPreciseVideoBtn.disabled = true;
        return;
    }

    const data = state.preciseWords[sentenceId];
    elements.createPreciseVideoBtn.disabled = false;

    // Sort words by index
    const sortedWords = Object.keys(data.words)
        .map(w => ({ word: w, ...data.words[w] }))
        .sort((a, b) => a.word_index - b.word_index);

    grid.innerHTML = sortedWords.map(wordData => {
        const clips = wordData.clips || [];

        let clipsHtml = '';
        if (clips.length === 0) {
            clipsHtml = '<div class="no-clips">No clips found for this word</div>';
        } else {
            clipsHtml = clips.map((clip, idx) => {
                const isSelected = idx === 0; // Default select first
                const confidenceClass = clip.confidence >= 0.9 ? 'high' : 'low';

                // Ensure inputs have unique names per word
                const radioName = `clip-${sentenceId}-${wordData.word_index}`;

                return `
                    <div class="clip-option ${isSelected ? 'selected' : ''}" 
                         onclick="selectClip(this, '${radioName}')">
                        <input type="radio" name="${radioName}" value="${clip.clip_index}" 
                               ${isSelected ? 'checked' : ''} style="pointer-events: none;">
                        <div class="clip-info">
                            <span class="clip-source">${clip.video_title.substring(0, 30)}...</span>
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span class="clip-duration">${clip.duration.toFixed(2)}s</span>
                                <span class="clip-confidence ${confidenceClass}">${(clip.confidence * 100).toFixed(0)}% conf</span>
                            </div>
                        </div>
                        <button class="clip-preview-btn" 
                                onclick="event.stopPropagation(); playVideo('${clip.video_url.replace(/'/g, "\\'")}', 'Preview: ${wordData.word}')">
                            ▶
                        </button>
                    </div>
                `;
            }).join('');
        }

        return `
            <div class="word-card">
                <div class="word-card-header">
                    <span class="word-index">${wordData.word_index + 1}</span>
                    <span class="word-text">${wordData.word}</span>
                </div>
                <div class="word-clips">
                    ${clipsHtml}
                </div>
            </div>
        `;
    }).join('');
}

// Global function for onclick
window.selectClip = function (element, radioName) {
    // Visual selection
    document.querySelectorAll(`input[name="${radioName}"]`).forEach(input => {
        input.closest('.clip-option').classList.remove('selected');
    });

    element.classList.add('selected');
    const radio = element.querySelector('input[type="radio"]');
    radio.checked = true;
};

async function createPreciseVideo() {
    const sentenceId = elements.preciseSentenceSelector.value;
    if (!sentenceId) return;

    // Gather selections
    const selections = {};
    const data = state.preciseWords[sentenceId];

    Object.keys(data.words).forEach(word => {
        const wordIdx = data.words[word].word_index;
        const radioName = `clip-${sentenceId}-${wordIdx}`;
        const selected = document.querySelector(`input[name="${radioName}"]:checked`);
        if (selected) {
            selections[word] = parseInt(selected.value);
        } else {
            selections[word] = 0; // Default
        }
    });

    setLoading(true);
    elements.createPreciseVideoBtn.disabled = true;
    elements.createPreciseVideoBtn.textContent = '⏱️ Stitching...';

    try {
        const response = await fetch('/api/precise-create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sentence_id: sentenceId,
                selections: selections
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to create video');
        }

        const result = await response.json();

        // Show success modal
        const modalBody = elements.toolResultContent;
        modalBody.innerHTML = `
            <h3>✅ Video Created Successfully!</h3>
            <p><strong>Sentence:</strong> "${result.sentence}"</p>
            <div style="margin-top: 15px; border-radius: 8px; overflow: hidden; background: #000;">
                <video controls autoplay style="width: 100%; display: block;" src="/videos/${result.file_path.split(/[\\/]/).pop()}">
                    Your browser does not support the video tag.
                </video>
            </div>
            <div style="margin-top: 15px; text-align: right;">
                <a href="/videos/${result.file_path.split(/[\\/]/).pop()}" download class="btn-primary">⬇️ Download Video</a>
            </div>
        `;
        elements.modalResult.style.display = 'block';

    } catch (error) {
        console.error('Error creating precise video:', error);
        alert(`Error: ${error.message}`);
    } finally {
        setLoading(false);
        elements.createPreciseVideoBtn.disabled = false;
        elements.createPreciseVideoBtn.textContent = '🎬 Create Video from Selection';
    }
}

// Clear logs function
function clearServerLogs() {
    fetch('/api/logs', { method: 'DELETE' })
        .then(() => {
            // UI update handled by auto-refresh
        })
        .catch(err => console.error('Failed to clear logs:', err));
}

// Make functions globally available
window.openToolModal = openToolModal;
window.playVideo = playVideo;
window.openYouTubeAtTime = openYouTubeAtTime;
window.copyToClipboard = copyToClipboard;

