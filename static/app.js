/**
 * YouTube Creator Studio - Frontend Logic
 * Handles chat, tool execution, transcript display, and video preview
 */

// ============================================================================
// State
// ============================================================================

const state = {
    conversationHistory: [],
    transcripts: {},  // Store multiple transcripts by video_id
    currentVideoId: null,
    tools: [],
    isLoading: false
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
    clearAllBtn: document.getElementById('clear-all-btn')
};

// ============================================================================
// Initialize
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    loadTools();
    loadVideos();
    loadCachedTranscripts();
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

    // Transcript selector
    elements.transcriptSelector.addEventListener('change', (e) => {
        if (e.target.value) {
            displayTranscript(state.transcripts[e.target.value]);
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
}

// ============================================================================
// Chat Functions
// ============================================================================

async function sendMessage() {
    const message = elements.chatInput.value.trim();
    if (!message || state.isLoading) return;

    // Add user message to UI
    addMessageToChat('user', message);
    elements.chatInput.value = '';

    // Add to history
    state.conversationHistory.push({ role: 'user', content: message });

    // Show loading state
    setLoading(true);
    const loadingMsg = addMessageToChat('assistant', '<span class="loading">Thinking</span>');

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: state.conversationHistory.slice(0, -1)
            })
        });

        const data = await response.json();

        // Remove loading message
        loadingMsg.remove();

        // Process response
        if (data.error) {
            addMessageToChat('assistant', `❌ Error: ${data.error}`);
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
        }
    } catch (error) {
        loadingMsg.remove();
        addMessageToChat('assistant', `❌ Network error: ${error.message}`);
    }

    setLoading(false);
}

function addMessageToChat(role, content) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    msg.innerHTML = `<div class="message-content">${content}</div>`;
    elements.chatMessages.appendChild(msg);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    return msg;
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
            updateTranscriptSelector();
        }
    } catch (error) {
        console.error('Failed to load cached transcripts:', error);
    }
}

function updateTranscriptSelector() {
    const selector = elements.transcriptSelector;
    const currentValue = selector.value;

    // Clear existing options except the first one
    while (selector.options.length > 1) {
        selector.remove(1);
    }

    // Add options for each transcript
    for (const [videoId, transcript] of Object.entries(state.transcripts)) {
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
    if (currentValue && state.transcripts[currentValue]) {
        selector.value = currentValue;
    } else if (Object.keys(state.transcripts).length > 0) {
        const lastKey = Object.keys(state.transcripts).pop();
        selector.value = lastKey;
        displayTranscript(state.transcripts[lastKey]);
    }
}

async function displayTranscript(transcriptData) {
    if (!transcriptData) return;

    // If we only have the summary, fetch the full transcript from cache
    let segments = transcriptData.segments;
    const videoId = transcriptData.video_id;

    if (!segments && videoId) {
        try {
            const response = await fetch(`/api/transcripts/${videoId}`);
            if (response.ok) {
                const fullData = await response.json();
                segments = fullData.segments;
                // Update local cache
                state.transcripts[videoId] = fullData;
            }
        } catch (e) {
            console.error('Failed to load full transcript:', e);
        }
    }

    state.currentVideoId = videoId;

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
        for (const seg of segments) {
            // Support mixed-source transcripts (scripts)
            const targetVideoId = seg.video_id || videoId;
            const sourceLabel = seg.video_id ? `<span class="segment-source" title="Source Video">${seg.video_id}</span>` : '';

            html += `
                <div class="transcript-segment" 
                     onclick="openYouTubeAtTime('${targetVideoId}', ${seg.start})"
                     data-start="${seg.start}" 
                     data-end="${seg.end}">
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
}

function openYouTubeAtTime(videoId, startTime) {
    const startSeconds = Math.floor(startTime);
    showYouTubeEmbed(videoId, startSeconds);
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
    elements.toolsList.innerHTML = state.tools.map(tool => `
        <div class="tool-item" onclick="openToolModal('${tool.name}')">
            <h4>${formatToolName(tool.name)}</h4>
            <p>${tool.description.substring(0, 80)}...</p>
        </div>
    `).join('');
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

    // Build form fields
    const props = tool.parameters?.properties || {};
    const required = tool.parameters?.required || [];

    elements.toolParams.innerHTML = Object.entries(props).map(([name, prop]) => {
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

    if (!confirm(`Delete transcript for "${state.transcripts[videoId]?.title || videoId}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/transcripts/${videoId}`, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            delete state.transcripts[videoId];
            updateTranscriptSelector();
            elements.transcriptContainer.innerHTML = `
                <div class="empty-state">
                    <p>Transcript deleted.</p>
                    <p class="hint">Select another transcript or fetch new ones.</p>
                </div>
            `;
        } else {
            alert('Failed to delete: ' + (data.detail || data.message));
        }
    } catch (error) {
        alert('Error deleting transcript: ' + error.message);
    }
}

async function clearAllTranscripts() {
    const count = Object.keys(state.transcripts).length;
    if (count === 0) {
        alert('No transcripts to clear');
        return;
    }

    if (!confirm(`Delete ALL ${count} cached transcripts? This cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch('/api/transcripts', { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            state.transcripts = {};
            updateTranscriptSelector();
            elements.transcriptContainer.innerHTML = `
                <div class="empty-state">
                    <p>All transcripts cleared.</p>
                    <p class="hint">Fetch new transcripts to get started.</p>
                </div>
            `;
        } else {
            alert('Failed to clear: ' + (data.detail || data.message));
        }
    } catch (error) {
        alert('Error clearing transcripts: ' + error.message);
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

// Make functions globally available
window.openToolModal = openToolModal;
window.playVideo = playVideo;
window.openYouTubeAtTime = openYouTubeAtTime;
