"use strict";
console.log("script.js has been loaded and is running!");
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOMContentLoaded event fired!");
    // =================================================================
    // 1. Constants and DOM Elements
    // =================================================================

    console.log("Searching for DOM elements...");
    const storyUrlInput = document.getElementById('story-url-input');
    const playButton = document.getElementById('play-button');
    console.log("Play button element:", playButton);
    console.log("URL input element:", storyUrlInput);
    if (playButton) {
         console.log("Play button found! Attaching event listener...");
         playButton.addEventListener('click', () => {
             console.log("Play button CLICKED!"); // Log khi nhấn nút
             // ... code xử lý sự kiện click của bạn
         });
    } else {
         console.error("CRITICAL: Play button not found in the DOM!");
    }
    const audioPlayer = document.getElementById('audio-player');
    const statusDisplay = document.getElementById('status-display');
    const navControls = document.getElementById('navigation-controls');
    const prevChapterButton = document.getElementById('prev-chapter-button');
    const nextChapterButton = document.getElementById('next-chapter-button');
    const mainContainer = document.querySelector('.container');
    const loadingSpinner = document.getElementById('loading-spinner');
    const SUPPORTED_DOMAINS = [
        'truyenfull.vn', 
        'tangthuvien.net',
        'truyenconvert.net',
        'truyenfull.vision',
        'truyenhdt.com',
        'bnsach.com',
        'truyenwikidich.net',
        'truyenyy.mobi',
        'gocnhocuasakiblog.wordpress.com'
        // Thêm bất kỳ domain nào khác bạn có
    ];
    const SUPPORTED_SITES_FRIENDLY_NAMES = ["truyenfull.vision, truyenyy.mobi"];
    const REQUEST_TIMEOUT = 30000; // 30 seconds

    const metadataCache = new Map();

    // =================================================================
    // 2. State Management
    // =================================================================

    let playerState = {
        currentUrl: null,
        currentTitle: '',
        nextUrl: null,
        prevUrl: null
    };
    let currentPlaybackController = null;
    let pendingStartTime = 0;
    let lastSaveTime = 0;

    // =================================================================
    // 3. Accessibility & UI Management
    // =================================================================

    function setupAccessibility() {
        playButton.setAttribute('aria-label', 'Phát hoặc thử lại chương truyện');
        storyUrlInput.setAttribute('aria-label', 'Ô dán link chương truyện');
        prevChapterButton.setAttribute('aria-label', 'Chuyển đến chương trước');
        nextChapterButton.setAttribute('aria-label', 'Chuyển đến chương sau');
        statusDisplay.setAttribute('aria-live', 'polite');
    }

    function setUiLoadingState(isLoading, isPlaying = false) {
        playButton.disabled = isLoading;
        storyUrlInput.disabled = isLoading;
        if (loadingSpinner) loadingSpinner.classList.toggle('hidden', !isLoading);

        if (isLoading) {
            playButton.textContent = "Đang tải...";
        } else {
            if (isPlaying) {
                playButton.innerHTML = '❚❚'; // Pause icon
                playButton.setAttribute('aria-label', 'Tạm dừng');
            } else {
                playButton.textContent = "Nghe";
                playButton.setAttribute('aria-label', 'Phát hoặc thử lại chương truyện');
            }
        }
        prevChapterButton.disabled = isLoading || !playerState.prevUrl;
        nextChapterButton.disabled = isLoading || !playerState.nextUrl;
    }

    function dismissRestorePrompt() {
        const promptElement = document.getElementById('restore-prompt');
        if (promptElement) promptElement.remove();
    }

    function createRestorePrompt(state, time) {
        dismissRestorePrompt();
        const promptElement = document.createElement('div');
        promptElement.id = 'restore-prompt';

        const message = document.createElement('p');
        message.textContent = `Mẹ có muốn nghe tiếp "${state.currentTitle || 'chương trước'}" không?`;

        const buttonWrapper = document.createElement('div');
        const continueButton = document.createElement('button');
        continueButton.textContent = 'Nghe tiếp';
        continueButton.style.marginRight = '10px';

        const dismissButton = document.createElement('button');
        dismissButton.textContent = 'Bỏ qua';

        continueButton.addEventListener('click', () => {
            dismissRestorePrompt();
            startPlayback(state.currentUrl, time, true);
        });

        dismissButton.addEventListener('click', () => {
            dismissRestorePrompt();
            localStorage.removeItem('radioTruyenSession');
        });

        buttonWrapper.appendChild(continueButton);
        buttonWrapper.appendChild(dismissButton);
        promptElement.appendChild(message);
        promptElement.appendChild(buttonWrapper);
        mainContainer.insertAdjacentElement('afterbegin', promptElement);
    }

    // =================================================================
    // 4. Error Handling
    // =================================================================

    /**
     * Xử lý tập trung các lỗi xảy ra trong quá trình phát.
     * Phân tích lỗi và hiển thị thông báo thân thiện, có hướng dẫn cho người dùng.
     * @param {Error} error - Đối tượng lỗi được throw ra.
     * @param {HTMLElement} statusElement - Phần tử DOM để hiển thị thông báo.
     * @param {boolean} isRestoring - Cờ báo hiệu nếu lỗi xảy ra khi đang khôi phục phiên.
     */
    async function handlePlaybackError(error, statusElement, isRestoring = false) {
        if (error.name === 'AbortError') {
            if (error.reason === 'timeout') {
                statusElement.textContent = "Yêu cầu quá giờ. Mẹ kiểm tra lại kết nối mạng và thử lại nhé.";
            } else {
                console.log("Request aborted by a new user action.");
            }
            return;
        }

        if (error.response && typeof error.response.json === 'function') {
            try {
                const errorData = await error.response.json();
                switch (errorData.error_code) {
                    case 'METADATA_EXTRACTION_FAILED':
                    case 'CONTENT_EXTRACTION_FAILED':
                        statusElement.innerHTML = `Mẹ ơi, link này bot không đọc được rồi. 😥<br>Hay là mẹ thử tìm tên truyện này trên Google và dán link từ một trong các trang như <strong>${SUPPORTED_SITES_FRIENDLY_NAMES.join(', ')}</strong> thử xem ạ?`;
                        break;
                    case 'TTS_SERVICE_UNAVAILABLE':
                        statusElement.textContent = 'Dịch vụ đọc truyện đang tạm thời gián đoạn, mẹ thử lại sau ít phút nhé.';
                        break;
                    default:
                        statusElement.textContent = errorData.message || 'Bot không đọc được link này, mẹ thử lại nhé.';
                        break;
                }
            } catch (jsonError) {
                statusElement.textContent = `Bot đang gặp chút trục trặc ở máy chủ (mã ${error.response.status}). Con đã biết lỗi này rồi, mẹ thử lại sau nhé.`;
            }
            return;
        }

        let genericMessage = 'Có lỗi xảy ra, mẹ thử lại hoặc dùng link khác nhé.';
        if (isRestoring) {
            genericMessage = "Không thể nghe tiếp. Có lẽ chương truyện cũ này đã bị thay đổi hoặc xóa mẹ ạ.";
        } else if (error.message && error.message.includes('Dữ liệu nhận được')) {
            // Specific message for invalid data from server
            genericMessage = "Bot không tìm thấy nội dung truyện từ link này.";
        } else if (error.message) {
            genericMessage = error.message;
        }
        statusElement.textContent = genericMessage;
    }

    // =================================================================
    // 5. Core Logic
    // =================================================================

    async function fetchMetadata(url, signal) {
        if (metadataCache.has(url)) {
            return metadataCache.get(url);
        }

        const response = await fetch(`/api/metadata?url=${encodeURIComponent(url)}`, { signal });

        if (!response.ok) {
            const error = new Error('API request for metadata failed with status ' + response.status);
            error.response = response;
            throw error;
        }

        const data = await response.json();
        if (!data || !data.title) {
            throw new Error("Dữ liệu nhận được từ máy chủ không hợp lệ.");
        }

        metadataCache.set(url, data);
        return data;
    }

    async function startPlayback(url, startTime = 0, isRestoring = false) {
        if (currentPlaybackController) {
            currentPlaybackController.abort('user_action');
        }
        currentPlaybackController = new AbortController();
        const { signal } = currentPlaybackController;

        const timeoutId = setTimeout(() => {
            currentPlaybackController.abort('timeout');
        }, REQUEST_TIMEOUT);

        setUiLoadingState(true);
        statusDisplay.textContent = 'Đang tìm thông tin chương...';

        try {
            const metadata = await fetchMetadata(url, signal);

            localStorage.removeItem('radioTruyenSession');
            playerState = {
                currentUrl: url,
                currentTitle: metadata.title,
                nextUrl: metadata.next_url,
                prevUrl: metadata.prev_url
            };
            statusDisplay.textContent = 'Đang chuẩn bị giọng đọc...';
            navControls.classList.remove('hidden');
            const audioStreamUrl = `/api/read?url=${encodeURIComponent(url)}`;
            pendingStartTime = startTime;
            audioPlayer.src = audioStreamUrl;
            await audioPlayer.play();
            storyUrlInput.value = url;

        } catch (error) {
            await handlePlaybackError(error, statusDisplay, isRestoring);
            setUiLoadingState(false, false);
            navControls.classList.add('hidden');

        } finally {
            clearTimeout(timeoutId);
        }
    }

    // =================================================================
    // 6. Session Management
    // =================================================================

    function saveSession() {
        if (playerState.currentUrl && audioPlayer.currentTime > 0 && !audioPlayer.ended && !isNaN(audioPlayer.duration)) {
            const remainingTime = audioPlayer.duration - audioPlayer.currentTime;
            if (remainingTime > 5) {
                const sessionData = { state: playerState, time: audioPlayer.currentTime };
                localStorage.setItem('radioTruyenSession', JSON.stringify(sessionData));
            }
        }
    }

    function restoreSession() {
        const savedSession = localStorage.getItem('radioTruyenSession');
        if (!savedSession) return;
        try {
            const { state, time } = JSON.parse(savedSession);
            if (state && typeof state.currentUrl === 'string' && state.currentUrl && typeof time === 'number' && time > 0) {
                createRestorePrompt(state, time);
            } else {
                localStorage.removeItem('radioTruyenSession');
            }
        } catch (e) {
            console.error("Lỗi khi khôi phục phiên:", e);
            localStorage.removeItem('radioTruyenSession');
        }
    }

    // =================================================================
    // 7. Global Event Listeners
    // =================================================================

    playButton.addEventListener('click', () => {
        dismissRestorePrompt();
        const urlString = storyUrlInput.value.trim();

        if (urlString === playerState.currentUrl && audioPlayer.duration > 0 && !audioPlayer.seeking) {
            if (audioPlayer.paused) {
                audioPlayer.play();
            } else {
                audioPlayer.pause();
            }
            return;
        }

        if (!urlString) {
            statusDisplay.textContent = 'Mẹ cần dán link truyện vào ô nhé.';
            return;
        }

        try {
            const url = new URL(urlString);
            const isSupported = SUPPORTED_DOMAINS.some(domain => url.hostname === domain || url.hostname.endsWith('.' + domain));
            if (!isSupported) {
                statusDisplay.textContent = 'Bot chưa đọc được truyện từ trang này mẹ ạ.';
                return;
            }
            startPlayback(urlString);
        } catch (e) {
            statusDisplay.textContent = 'Link mẹ dán vào không hợp lệ.';
        }
    });

    nextChapterButton.addEventListener('click', () => {
        if (!nextChapterButton.disabled && playerState.nextUrl) startPlayback(playerState.nextUrl);
    });

    prevChapterButton.addEventListener('click', () => {
        if (!prevChapterButton.disabled && playerState.prevUrl) startPlayback(playerState.prevUrl);
    });

    audioPlayer.addEventListener('loadedmetadata', () => {
        if (pendingStartTime > 0) {
            audioPlayer.currentTime = pendingStartTime;
            pendingStartTime = 0;
        }
    });

    audioPlayer.addEventListener('playing', () => {
        statusDisplay.innerHTML = '🎧 Đang đọc: ';
        const titleSpan = document.createElement('span');
        titleSpan.textContent = playerState.currentTitle;
        statusDisplay.appendChild(titleSpan);
        setUiLoadingState(false, true);
    });

    audioPlayer.addEventListener('pause', () => {
        setUiLoadingState(false, false);
    });

    audioPlayer.addEventListener('ended', () => {
        if (playerState.nextUrl) {
            statusDisplay.textContent = "Hết chương, đang tự động chuyển chương sau...";
            startPlayback(playerState.nextUrl);
        } else {
            statusDisplay.textContent = "Đã hết truyện. Cảm ơn mẹ đã lắng nghe!";
            navControls.classList.add('hidden');
            setUiLoadingState(false, false);
        }
    });

    audioPlayer.addEventListener('error', (e) => {
        let message = 'Có lỗi khi phát âm thanh, mẹ thử lại nhé.';
        if (e.target.error) {
            switch (e.target.error.code) {
                case e.target.error.MEDIA_ERR_NETWORK:
                    message = 'Lỗi mạng, mẹ kiểm tra lại kết nối nhé.';
                    break;
                case e.target.error.MEDIA_ERR_SRC_NOT_SUPPORTED:
                case e.target.error.MEDIA_ERR_DECODE:
                    message = 'Bot không đọc được link này, mẹ thử link khác nhé.';
                    break;
            }
        }
        statusDisplay.textContent = message;
        setUiLoadingState(false, false);
        playButton.textContent = 'Thử lại';
    });

    audioPlayer.addEventListener('timeupdate', () => {
        const now = Date.now();
        if (now - lastSaveTime > 5000) {
            saveSession();
            lastSaveTime = now;
        }
    });

    window.addEventListener('beforeunload', saveSession);

    // =================================================================
    // 8. Initialization
    // =================================================================

    setupAccessibility();
    restoreSession();
});