const API_BASE_URL = '/api';
const DEMO_MODE = false;

const robotStatus = {
  connected: false,
  terminalHealth: {
    laptop: false,
    rpi: false,
  },
  cameraStreamActive: false,
  locationName: 'Unknown',
  mapName: 'No map loaded',
  localizationStatus: 'Unlocalized',
  slamEnabled: false,
  slamState: 'Unknown',
  semanticEnabled: false,
  semanticStatus: 'Inactive',
  navigationState: 'Idle',
  selectedRoom: null,
  demoMode: DEMO_MODE,
  availableFeatures: {
    voice: false,
    slam: false,
    semantic_map: false,
    navigation: false,
    human_follow: false,
    face_auth: false,
    behavior: false,
    alert: false,
    exploration: false,
    robot_stack: false,
  },
};

const demoRoomData = [
  'Living Room',
  'Kitchen',
  'Bedroom',
  'Bedroom 1',
  'Hall',
];

const apiConfig = {
  telemetry: `${API_BASE_URL}/telemetry`,
  camera: `${API_BASE_URL}/camera/stream`,
  map: `${API_BASE_URL}/map/current`,
  voiceCommand: `${API_BASE_URL}/voice/command`,
  slamStart: `${API_BASE_URL}/slam/start`,
  slamStop: `${API_BASE_URL}/slam/stop`,
  semanticStart: `${API_BASE_URL}/semantic-map/start`,
  semanticStop: `${API_BASE_URL}/semantic-map/stop`,
  rooms: `${API_BASE_URL}/navigation/rooms`,
  navigate: `${API_BASE_URL}/navigation/goal`,
  cancelNavigation: `${API_BASE_URL}/navigation/cancel`,
  photoCapture: `${API_BASE_URL}/camera/capture`,
  photoDelivery: `${API_BASE_URL}/media/send-photo`,
  telegramMessage: `${API_BASE_URL}/alert/send-message`,
};

const els = {};
let voiceRecognition = null;
let isListening = false;
let mapZoomFactor = 1;
let lastPhotoData = null;
let pendingRequest = false;

function setEls() {
  els.laptopTerminalStatus = document.getElementById('laptopTerminalStatus');
  els.rpiTerminalStatus = document.getElementById('rpiTerminalStatus');
  els.controlState = document.getElementById('controlState');
  els.cameraStatusChip = document.getElementById('cameraStatusChip');
  els.video = document.getElementById('robotVideo');
  els.cameraFrame = document.getElementById('cameraFrame');
  els.videoPlaceholder = document.getElementById('videoPlaceholder');
  els.toggleStreamBtn = document.getElementById('toggleStreamBtn');
  els.refreshCameraBtn = document.getElementById('refreshCameraBtn');
  els.fullscreenCameraBtn = document.getElementById('fullscreenCameraBtn');
  els.capturePhotoBtn = document.getElementById('capturePhotoBtn');
  els.locationName = document.getElementById('locationName');
  els.mapName = document.getElementById('mapName');
  els.localizationStatus = document.getElementById('localizationStatus');
  els.speechTranscript = document.getElementById('speechTranscript');
  els.toggleListeningBtn = document.getElementById('toggleListeningBtn');
  els.sendVoiceCommandBtn = document.getElementById('sendVoiceCommandBtn');
  els.voiceStateBadge = document.getElementById('voiceStateBadge');
  els.textCommandInput = document.getElementById('textCommandInput');
  els.charCounter = document.getElementById('charCounter');
  els.sendTextCommandBtn = document.getElementById('sendTextCommandBtn');
  els.lastCommandText = document.getElementById('lastCommandText');
  els.robotResponseText = document.getElementById('robotResponseText');
  els.slamToggle = document.getElementById('slamToggle');
  els.slamStatus = document.getElementById('slamStatus');
  els.slamMapStatus = document.getElementById('slamMapStatus');
  els.startSlamBtn = document.getElementById('startSlamBtn');
  els.stopSlamBtn = document.getElementById('stopSlamBtn');
  els.semanticToggle = document.getElementById('semanticToggle');
  els.semanticStatus = document.getElementById('semanticStatus');
  els.semanticProgress = document.getElementById('semanticProgress');
  els.startSemanticBtn = document.getElementById('startSemanticBtn');
  els.stopSemanticBtn = document.getElementById('stopSemanticBtn');
  els.roomSelect = document.getElementById('roomSelect');
  els.selectedRoomText = document.getElementById('selectedRoomText');
  els.navState = document.getElementById('navState');
  els.navResult = document.getElementById('navResult');
  els.navigateBtn = document.getElementById('navigateBtn');
  els.cancelNavBtn = document.getElementById('cancelNavBtn');
  els.capturedPhoto = document.getElementById('capturedPhoto');
  els.photoPlaceholder = document.getElementById('photoPlaceholder');
  els.groupPhotoMessage = document.getElementById('groupPhotoMessage');
  els.sendPhotoMessageBtn = document.getElementById('sendPhotoMessageBtn');
  els.photoDeliveryStatus = document.getElementById('photoDeliveryStatus');
  els.groupMessageInput = document.getElementById('groupMessageInput');
  els.groupMessageCounter = document.getElementById('groupMessageCounter');
  els.groupMessageStatus = document.getElementById('groupMessageStatus');
  els.sendGroupMessageBtn = document.getElementById('sendGroupMessageBtn');
}

function updateTerminalHealthUI() {
  const laptopActive = Boolean(robotStatus.terminalHealth.laptop);
  const rpiActive = Boolean(robotStatus.terminalHealth.rpi);

  els.laptopTerminalStatus.textContent = laptopActive ? 'ACTIVE' : 'MISSING';
  els.laptopTerminalStatus.className = `meta-value ${laptopActive ? 'success' : 'danger'}`;

  els.rpiTerminalStatus.textContent = rpiActive ? 'ACTIVE' : 'MISSING';
  els.rpiTerminalStatus.className = `meta-value ${rpiActive ? 'success' : 'danger'}`;

  const allActive = laptopActive && rpiActive;
  els.controlState.textContent = allActive ? 'READY' : 'TERMINAL MISSING';
  els.controlState.className = `meta-value ${allActive ? 'success' : 'warning'}`;

  if (!allActive) {
    showToast('One or both required terminals are inactive. Start the missing session before running commands.');
  }
}

function setDemoModeState() {
  document.body.dataset.demo = 'true';
  document.querySelector('.header-status').innerHTML = `
    <span class="status-dot ${robotStatus.connected ? 'connected' : 'disconnected'}" aria-hidden="true"></span>
    <span class="status-label">${robotStatus.connected ? 'Connected' : 'Terminal wait'}</span>
  `;
  els.cameraStatusChip.textContent = robotStatus.connected ? 'Camera active' : 'Waiting for terminals';
  els.cameraStatusChip.className = `chip ${robotStatus.connected ? 'chip-success' : 'chip-neutral'}`;
}

function updateMapUI() {
  const mapCanvas = document.getElementById('mapCanvas');
  const placeholder = document.getElementById('mapPlaceholder');

  if (!robotStatus.mapName || robotStatus.mapName === 'No map loaded') {
    if (!placeholder) {
      const fallback = document.createElement('div');
      fallback.id = 'mapPlaceholder';
      fallback.className = 'map-overlay placeholder-surface';
      fallback.innerHTML = '<p>Map unavailable</p><small>Waiting for localization data</small>';
      mapCanvas.appendChild(fallback);
    }
  } else {
    if (placeholder) placeholder.remove();
    mapCanvas.innerHTML = `
      <div class="map-overlay" style="position:absolute; inset:0; background:linear-gradient(135deg, rgba(13,28,39,.65), rgba(8,16,23,.78));">
        <div style="position:absolute; left:14%; top:16%; width:38%; height:26%; border:2px solid rgba(74,215,209,.6); border-radius:18px; background:rgba(74,215,209,.12);"></div>
        <div style="position:absolute; left:52%; top:22%; width:28%; height:20%; border:2px solid rgba(148,163,184,.6); border-radius:14px; background:rgba(148,163,184,.08);"></div>
        <div style="position:absolute; left:34%; top:54%; width:26%; height:18%; border:2px solid rgba(74,222,128,.55); border-radius:14px; background:rgba(74,222,128,.08);"></div>
        <div style="position:absolute; left:50%; top:58%; width:18px; height:18px; border-radius:50%; background:var(--green); box-shadow: 0 0 14px rgba(74,222,128,.9); transform: translate(-50%, -50%) rotate(${(robotStatus.orientation || 0)}deg);"></div>
      </div>
    `;
  }

  els.locationName.textContent = robotStatus.locationName;
  els.mapName.textContent = robotStatus.mapName;
  els.localizationStatus.textContent = robotStatus.localizationStatus;
  els.localizationStatus.className = `meta-value ${robotStatus.localizationStatus === 'Localized' ? 'success' : robotStatus.localizationStatus === 'Unlocalized' ? 'warning' : 'neutral'}`;
}

function bindMapZoom() {
  document.querySelectorAll('[data-map-action]').forEach((button) => {
    button.addEventListener('click', () => {
      const action = button.dataset.mapAction;
      if (action === 'zoom-in') {
        mapZoomFactor = Math.min(mapZoomFactor + 0.1, 1.8);
      } else if (action === 'zoom-out') {
        mapZoomFactor = Math.max(mapZoomFactor - 0.1, 0.7);
      } else {
        mapZoomFactor = 1;
      }
      const canvas = document.getElementById('mapCanvas');
      if (canvas) {
        canvas.style.transform = `scale(${mapZoomFactor})`;
        canvas.style.transformOrigin = 'center center';
      }
    });
  });
}

function updateVoiceUI() {
  const transcript = els.speechTranscript.textContent || 'No speech detected yet.';
  if (transcript.trim().length > 0 && transcript !== 'No speech detected yet.') {
    els.speechTranscript.style.color = 'var(--text)';
  }
}

function updateToggleButton(button, isOn, labelOn = 'On', labelOff = 'Off') {
  const label = button.querySelector('.toggle-text');
  button.classList.toggle('active', isOn);
  button.setAttribute('aria-pressed', String(isOn));
  if (label) {
    label.textContent = isOn ? labelOn : labelOff;
  }
}

function updateSlamUI() {
  const enabled = Boolean(robotStatus.slamEnabled);
  updateToggleButton(els.slamToggle, enabled, 'On', 'Off');
  els.slamStatus.textContent = robotStatus.slamState || 'Unknown';
  els.slamStatus.className = `meta-value ${
    robotStatus.slamState === 'Running' ? 'success' : robotStatus.slamState === 'Stopped' ? 'neutral' : 'warning'
  }`;
  els.slamMapStatus.textContent = enabled ? 'Building map' : 'Idle';
  els.slamMapStatus.className = `meta-value ${enabled ? 'success' : 'neutral'}`;
}

function updateSemanticUI() {
  const enabled = Boolean(robotStatus.semanticEnabled);
  updateToggleButton(els.semanticToggle, enabled, 'On', 'Off');
  els.semanticStatus.textContent = enabled ? 'Running' : 'Inactive';
  els.semanticStatus.className = `meta-value ${enabled ? 'success' : 'neutral'}`;
  els.semanticProgress.textContent = enabled ? 'Processing scene' : 'Idle';
  els.semanticProgress.className = `meta-value ${enabled ? 'success' : 'neutral'}`;
}

function updateNavigationUI() {
  els.selectedRoomText.textContent = robotStatus.selectedRoom || 'None';
  els.navState.textContent = robotStatus.navigationState || 'Idle';
  els.navState.className = `meta-value ${robotStatus.navigationState === 'Navigating' ? 'success' : 'neutral'}`;
  els.navResult.textContent = robotStatus.navigationState === 'Navigating' ? 'Goal active' : 'No destination';
}

function updateDemoRoomList() {
  els.roomSelect.innerHTML = '';
  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'Select a room';
  els.roomSelect.appendChild(defaultOption);

  demoRoomData.forEach((room) => {
    const option = document.createElement('option');
    option.value = room;
    option.textContent = room;
    els.roomSelect.appendChild(option);
  });
}

async function fetchJson(url, options = {}, { timeoutMs = 8000 } = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    const contentType = response.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');
    const payload = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      throw new Error(payload?.message || `Request failed with status ${response.status}`);
    }

    return payload;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Request timed out.');
    }
    throw new Error(error.message || 'Network error.');
  } finally {
    clearTimeout(timeoutId);
  }
}

function setStatusPill(element, state, text) {
  element.textContent = text;
  element.className = `status-pill ${state}`;
}

function setCameraStreamState(active) {
  const visible = Boolean(active);
  els.video.style.display = visible && !DEMO_MODE ? 'none' : visible ? 'block' : 'none';
  els.cameraFrame.hidden = !visible || DEMO_MODE;
  els.cameraFrame.style.display = visible && !DEMO_MODE ? 'block' : 'none';
  els.videoPlaceholder.style.display = visible ? 'none' : 'grid';
  els.cameraStatusChip.textContent = visible ? (DEMO_MODE ? 'Camera online' : 'ROS camera live') : 'Demo camera';
  els.cameraStatusChip.className = `chip ${visible ? 'chip-success' : 'chip-neutral'}`;
  els.toggleStreamBtn.textContent = visible ? 'Stop Stream' : 'Start Stream';
  robotStatus.cameraStreamActive = visible;
}

function refreshCameraFrame() {
  if (!els.cameraFrame) return;
  els.cameraFrame.src = '/api/camera/stream?ts=' + Date.now();
}

function startCameraStream() {
  setCameraStreamState(true);
  if (!DEMO_MODE) {
    if (els.cameraFrame.src !== '/api/camera/stream') {
      els.cameraFrame.src = '/api/camera/stream';
    }
    return;
  }

  if (els.video.src) {
    return;
  }

  const demoUrl = 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4';
  els.video.src = demoUrl;
  els.video.play().catch(() => {
    console.warn('Autoplay blocked; the demo stream needs user interaction.');
  });
}

function stopCameraStream() {
  setCameraStreamState(false);
  if (els.cameraFrame) {
    els.cameraFrame.removeAttribute('src');
  }
  if (els.video.src) {
    els.video.pause();
    els.video.removeAttribute('src');
    els.video.load();
  }
}

function refreshCamera() {
  if (!DEMO_MODE) {
    showToast('Camera refresh requires backend integration.');
    return;
  }
  setCameraStreamState(false);
  setTimeout(() => setCameraStreamState(true), 300);
}

function showToast(message) {
  const status = document.createElement('div');
  status.textContent = message;
  status.style.position = 'fixed';
  status.style.right = '16px';
  status.style.bottom = '18px';
  status.style.padding = '10px 12px';
  status.style.borderRadius = '12px';
  status.style.background = 'rgba(15, 23, 42, 0.9)';
  status.style.border = '1px solid var(--border)';
  status.style.color = 'var(--text)';
  status.style.zIndex = '30';
  status.style.boxShadow = '0 12px 24px rgba(2,6,23,.4)';
  document.body.appendChild(status);
  setTimeout(() => status.remove(), 2200);
}

function handleFullscreen() {
  const video = els.video;
  if (!video || !video.src) {
    showToast('No camera stream is active.');
    return;
  }
  if (video.requestFullscreen) {
    video.requestFullscreen();
  } else {
    showToast('Fullscreen is not supported in this browser.');
  }
}

function capturePhoto() {
  if (!DEMO_MODE) {
    showToast('Photo capture requires backend integration.');
    return;
  }

  const demoImage = 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400">
      <defs>
        <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stop-color="#0f172a"/>
          <stop offset="100%" stop-color="#1e293b"/>
        </linearGradient>
      </defs>
      <rect width="640" height="400" fill="url(#bg)"/>
      <rect x="70" y="70" width="500" height="260" rx="22" fill="rgba(74,215,209,0.08)" stroke="rgba(74,215,209,0.7)"/>
      <circle cx="220" cy="200" r="52" fill="rgba(74,222,128,0.2)" stroke="rgba(74,222,128,0.8)"/>
      <rect x="320" y="130" width="130" height="80" rx="16" fill="rgba(148,163,184,0.18)"/>
      <circle cx="420" cy="220" r="38" fill="rgba(251,191,36,0.2)" stroke="rgba(251,191,36,0.8)"/>
      <text x="320" y="315" text-anchor="middle" font-size="34" fill="#e6edf7" font-family="Segoe UI, sans-serif">AURA Demo Capture</text>
    </svg>
  `);

  lastPhotoData = demoImage;
  els.capturedPhoto.src = demoImage;
  els.capturedPhoto.hidden = false;
  els.photoPlaceholder.hidden = true;
  setStatusPill(els.photoDeliveryStatus, 'neutral', 'Photo ready');
  els.sendPhotoMessageBtn.disabled = false;
  showToast('Demo photo captured.');
}

async function handleToggle(actionType, endpoint) {
  if (pendingRequest) {
    return;
  }

  pendingRequest = true;

  try {
    const response = await fetchJson(endpoint, { method: 'POST' }, { timeoutMs: 6000 });
    if (!response || response.error) {
      throw new Error(response?.message || 'Request failed.');
    }
    showToast(`${actionType} command accepted.`);
  } catch (error) {
    showToast(`${actionType} failed: ${error.message}`);
  } finally {
    pendingRequest = false;
  }
}

function setVoiceMode(mode) {
  document.querySelectorAll('[data-panel]').forEach((panel) => {
    const show = panel.dataset.panel === mode;
    panel.classList.toggle('hidden', !show);
  });
  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.classList.toggle('active', button.dataset.mode === mode);
  });
}

function handleVoiceToggle() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    setStatusPill(els.voiceStateBadge, 'warning', 'Unsupported');
    els.speechTranscript.textContent = 'Web Speech API is not supported in this browser.';
    return;
  }

  if (!voiceRecognition) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    voiceRecognition = new SpeechRecognition();
    voiceRecognition.lang = 'en-US';
    voiceRecognition.interimResults = false;
    voiceRecognition.maxAlternatives = 1;

    voiceRecognition.onstart = () => {
      isListening = true;
      setStatusPill(els.voiceStateBadge, 'success', 'Listening');
      els.speechTranscript.textContent = 'Listening for a command...';
      els.toggleListeningBtn.textContent = 'Stop Listening';
    };

    voiceRecognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      els.speechTranscript.textContent = transcript;
      els.lastCommandText.textContent = transcript;
      setStatusPill(els.voiceStateBadge, 'warning', 'Recognized');
    };

    voiceRecognition.onerror = (event) => {
      const reason = event.error === 'not-allowed' ? 'Microphone permission denied.' : `Speech error: ${event.error}`;
      setStatusPill(els.voiceStateBadge, 'danger', 'Error');
      els.speechTranscript.textContent = reason;
      isListening = false;
      els.toggleListeningBtn.textContent = 'Start Listening';
    };

    voiceRecognition.onend = () => {
      isListening = false;
      els.toggleListeningBtn.textContent = 'Start Listening';
      setStatusPill(els.voiceStateBadge, 'neutral', 'Idle');
    };
  }

  if (isListening) {
    voiceRecognition.stop();
    return;
  }

  try {
    voiceRecognition.start();
  } catch (error) {
    setStatusPill(els.voiceStateBadge, 'danger', 'Error');
    els.speechTranscript.textContent = 'Could not start listening.';
  }
}

function sendVoiceCommand() {
  const text = els.speechTranscript.textContent.trim();
  if (!text || text === 'No speech detected yet.' || text === 'Listening for a command...') {
    showToast('Recognized speech is required before sending the command.');
    return;
  }

  els.lastCommandText.textContent = text;
  els.robotResponseText.textContent = 'Command queued for backend review.';
  setStatusPill(els.voiceStateBadge, 'success', 'Queued');
  return text;
}

function handleTextCommandSend() {
  const text = els.textCommandInput.value.trim();
  if (!text) {
    showToast('Please enter a command.');
    return;
  }

  els.lastCommandText.textContent = text;
  els.robotResponseText.textContent = 'Command queued for backend review.';
  els.textCommandInput.value = '';
  els.charCounter.textContent = '0 / 220';
}

function bindTextCounter() {
  els.textCommandInput.addEventListener('input', () => {
    els.charCounter.textContent = `${els.textCommandInput.value.length} / 220`;
  });

  els.groupMessageInput.addEventListener('input', () => {
    els.groupMessageCounter.textContent = `${els.groupMessageInput.value.length} / 500`;
  });
}

function bindEvents() {
  document.getElementById('toggleStreamBtn').addEventListener('click', () => {
    if (robotStatus.cameraStreamActive) {
      stopCameraStream();
    } else {
      startCameraStream();
    }
  });

  document.getElementById('refreshCameraBtn').addEventListener('click', refreshCamera);
  document.getElementById('fullscreenCameraBtn').addEventListener('click', handleFullscreen);
  document.getElementById('capturePhotoBtn').addEventListener('click', capturePhoto);
  document.getElementById('toggleListeningBtn').addEventListener('click', handleVoiceToggle);
  document.getElementById('sendVoiceCommandBtn').addEventListener('click', sendVoiceCommand);
  document.getElementById('sendTextCommandBtn').addEventListener('click', handleTextCommandSend);
  document.getElementById('startSlamBtn').addEventListener('click', () => handleToggle('SLAM start', apiConfig.slamStart));
  document.getElementById('stopSlamBtn').addEventListener('click', () => handleToggle('SLAM stop', apiConfig.slamStop));
  document.getElementById('startSemanticBtn').addEventListener('click', () => handleToggle('Semantic map start', apiConfig.semanticStart));
  document.getElementById('stopSemanticBtn').addEventListener('click', () => handleToggle('Semantic map stop', apiConfig.semanticStop));
  document.getElementById('navigateBtn').addEventListener('click', () => {
    const room = els.roomSelect.value;
    if (!room) {
      showToast('Select a destination before navigating.');
      return;
    }
    robotStatus.selectedRoom = room;
    robotStatus.navigationState = 'Navigating';
    updateNavigationUI();
    showToast(`Navigation goal queued for ${room}.`);
  });
  document.getElementById('cancelNavBtn').addEventListener('click', () => {
    robotStatus.navigationState = 'Cancelled';
    els.navResult.textContent = 'Navigation cancelled';
    els.navState.textContent = 'Cancelled';
    updateNavigationUI();
  });
  document.getElementById('captureSendPhotoBtn').addEventListener('click', capturePhoto);
  document.getElementById('sendPhotoMessageBtn').addEventListener('click', () => {
    if (!lastPhotoData) {
      showToast('Capture a valid photo before sending.');
      return;
    }
    setStatusPill(els.photoDeliveryStatus, 'warning', 'Sending');
    setTimeout(() => {
      setStatusPill(els.photoDeliveryStatus, 'success', 'Delivered');
    }, 900);
  });
  document.getElementById('sendGroupMessageBtn').addEventListener('click', () => {
    const text = els.groupMessageInput.value.trim();
    if (!text) {
      showToast('Please enter a message to send.');
      return;
    }
    setStatusPill(els.groupMessageStatus, 'warning', 'Sending');
    setTimeout(() => {
      setStatusPill(els.groupMessageStatus, 'success', 'Sent');
      els.groupMessageInput.value = '';
      els.groupMessageCounter.textContent = '0 / 500';
    }, 900);
  });

  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.addEventListener('click', () => setVoiceMode(button.dataset.mode));
  });

  els.slamToggle.addEventListener('click', () => {
    const next = !robotStatus.slamEnabled;
    robotStatus.slamEnabled = next;
    robotStatus.slamState = next ? 'Running' : 'Stopped';
    updateSlamUI();
    showToast(next ? 'SLAM enabled.' : 'SLAM disabled.');
  });

  els.semanticToggle.addEventListener('click', () => {
    const next = !robotStatus.semanticEnabled;
    robotStatus.semanticEnabled = next;
    updateSemanticUI();
    showToast(next ? 'Semantic mapping enabled.' : 'Semantic mapping disabled.');
  });

  els.roomSelect.addEventListener('change', (event) => {
    robotStatus.selectedRoom = event.target.value || null;
    updateNavigationUI();
  });

  els.textCommandInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleTextCommandSend();
    }
  });
}

async function loadSystemStatus() {
  try {
    const data = await fetchJson(`${API_BASE_URL}/system-status`, { method: 'GET' }, { timeoutMs: 6000 });
    robotStatus.connected = data && data.terminals && data.terminals.every((terminal) => terminal.active);
    robotStatus.terminalHealth = {
      laptop: Boolean(data?.terminals?.find((item) => item.label === 'Laptop')?.active),
      rpi: Boolean(data?.terminals?.find((item) => item.label === 'RPI 5')?.active),
    };
    robotStatus.availableFeatures = data?.features || robotStatus.availableFeatures;
    updateTerminalHealthUI();
    setDemoModeState();
    updateAvailableFeatureStates();
  } catch (error) {
    console.error('System status unavailable:', error);
    robotStatus.connected = false;
    robotStatus.terminalHealth = { laptop: false, rpi: false };
    updateTerminalHealthUI();
    setDemoModeState();
    showToast('System status unavailable: check the dashboard server and SSH terminals.');
  }
}

function updateAvailableFeatureStates() {
  const featureButtons = {
    voice: document.getElementById('toggleListeningBtn'),
    slam: document.getElementById('startSlamBtn'),
    semantic_map: document.getElementById('startSemanticBtn'),
    navigation: document.getElementById('navigateBtn'),
    human_follow: document.getElementById('capturePhotoBtn'),
    face_auth: document.getElementById('capturePhotoBtn'),
    behavior: document.getElementById('sendGroupMessageBtn'),
    alert: document.getElementById('sendPhotoMessageBtn'),
    exploration: document.getElementById('navigateBtn'),
    robot_stack: document.getElementById('toggleStreamBtn'),
  };

  Object.entries(featureButtons).forEach(([key, button]) => {
    if (!button) return;
    const enabled = Boolean(robotStatus.availableFeatures[key]);
    button.disabled = !enabled;
    button.title = enabled ? 'Available in workspace' : 'Feature not present in workspace';
  });

  const voicePanel = document.querySelector('[data-panel="voice"]');
  const textPanel = document.querySelector('[data-panel="text"]');
  if (voicePanel && textPanel) {
    const voiceEnabled = Boolean(robotStatus.availableFeatures.voice);
    voicePanel.classList.toggle('hidden', !voiceEnabled);
    textPanel.classList.toggle('hidden', !voiceEnabled);
  }
}

function initializeDemoState() {
  updateMapUI();
  updateSlamUI();
  updateSemanticUI();
  updateNavigationUI();
  updateDemoRoomList();
  setDemoModeState();
  setCameraStreamState(false);
  setVoiceMode('voice');
  setStatusPill(els.voiceStateBadge, 'neutral', 'Idle');
  setStatusPill(els.photoDeliveryStatus, 'neutral', 'No photo');
  setStatusPill(els.groupMessageStatus, 'neutral', 'Ready');
  updateTerminalHealthUI();
  updateAvailableFeatureStates();
}

function init() {
  setEls();
  bindEvents();
  bindMapZoom();
  bindTextCounter();
  initializeDemoState();
  loadSystemStatus();
}

document.addEventListener('DOMContentLoaded', init);
