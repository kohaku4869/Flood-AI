// Configuration
const BACKEND_URL = 'http://localhost:5000';
const AGENT_URL   = 'http://localhost:8001';
const AI_SERVICE_URL = 'http://localhost:8000'; // FastAPI AI service

// FastAPI WebSocket
const WS_URL = AGENT_URL.replace(/^http/, 'ws') + '/ws/frontend';
const socket = new WebSocket(WS_URL);

// State
const state = {
    startPoint: null, // {lat, lng}
    endPoint: null,   // {lat, lng}
    cameras: [],      // Array of camera objects
    cameraLayer: null, // Leaflet LayerGroup
    floodLayer: null,  // Leaflet LayerGroup
    routeLayer: null,  // Leaflet LayerGroup for route segments
    trafficLayer: null, // Not used anymore - traffic shown on route
    startMarker: null,
    endMarker: null,
    blockRadius: 150,  // Block radius in meters (will be updated from backend)
    currentCameraPopup: null,  // Currently open camera popup
    floodTestMode: false  // Flood test mode: shows severity analysis in popups
};

// Global coordinate storage for autocomplete
let startCoords = null; // [lat, lon]
let endCoords = null;   // [lat, lon]

// ============================================================================
// Utility Functions
// ============================================================================

// Debounce function to limit API calls
function debounce(func, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
}

// Map Initialization (Center on HCMC)
const map = L.map('map').setView([10.7769, 106.7009], 13); // Central HCMC

// Base Tile Layer (CartoDB Dark Matter for dark theme)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19
}).addTo(map);

// Layers
state.cameraLayer = L.layerGroup(); // Not added by default
state.floodLayer = L.layerGroup().addTo(map); // Added by default

// Icons
const startIcon = L.divIcon({
    className: 'location-icon-start',
    html: '<i class="fa-solid fa-location-dot"></i>',
    iconSize: [30, 30],
    iconAnchor: [15, 30]
});

const endIcon = L.divIcon({
    className: 'location-icon-end',
    html: '<i class="fa-solid fa-location-dot"></i>',
    iconSize: [30, 30],
    iconAnchor: [15, 30]
});

// ============================================================================
// Data Fetching
// ============================================================================

async function fetchFloodStatus() {
    try {
        const response = await fetch(`${BACKEND_URL}/flood-status`);
        const data = await response.json();
        
        state.cameras = data.cameras;
        updateMapMarkers();
        
        // Only update status if there's no active route info
        if (!currentRouteInfo) {
            updateStatus(`Loaded ${data.total_cameras} cameras. ${data.flooded_count} flooded.`);
        }
    } catch (error) {
        console.error('Error fetching flood status:', error);
        if (!currentRouteInfo) {
            updateStatus('Error loading flood data', 'danger');
        }
    }
}

async function findRoute() {
    if (!state.startPoint || !state.endPoint) {
        alert("Please select both start and end points.");
        return;
    }

    showLoading(true);
    
    try {
        const payload = {
            start_coords: state.startPoint,
            end_coords: state.endPoint,
            camera_ids: [] // Deprecated but required by schema if not optional? Schema says default=[]
        };

        const response = await fetch(`${BACKEND_URL}/route_request`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error('Route calculation failed');

        const result = await response.json();
        const routeData = result.data;

        // Draw Route with Traffic Visualization
        if (state.routeLayer) map.removeLayer(state.routeLayer);
        
        // Create a layer group for route segments
        state.routeLayer = L.layerGroup().addTo(map);
        
        // Backend returns path as array of {lat, lng} objects
        const pathCoords = routeData.path.map(coord => [coord.lat, coord.lng]);
        
        // Determine how to color the route based on ACTUAL traffic delay
        // Don't trust backend status field, calculate ourselves
        let trafficStatus = 'unknown';
        
        // Calculate traffic status from actual delay
        if (routeData.traffic_duration !== null && routeData.traffic_duration !== undefined) {
            const delaySeconds = routeData.traffic_delay || 0;
            const orsSeconds = routeData.ors_duration || 1;
            
            if (orsSeconds > 0) {
                const delayRatio = delaySeconds / orsSeconds;
                
                // More strict thresholds for better accuracy
                if (delayRatio >= 0.25) {  // 25%+ delay = heavy
                    trafficStatus = 'heavy';
                } else if (delayRatio >= 0.10) {  // 10-25% delay = moderate
                    trafficStatus = 'moderate';
                } else {  // < 10% delay = clear
                    trafficStatus = 'clear';
                }
            } else {
                trafficStatus = 'clear';
            }
        }
        
        // Color mapping for traffic status
        const getTrafficColor = (status) => {
            switch(status) {
                case 'clear': return '#00D000';      // Green
                case 'moderate': return '#FFD700';   // Yellow/Gold
                case 'heavy': return '#FF0000';      // Red
                default: return '#0ea5e9';           // Blue (no traffic data)
            }
        };
        
        // Draw base route (green - no traffic or clear)
        // Base route shadow
        L.polyline(pathCoords, {
            color: '#000000',
            weight: 10,
            opacity: 0.2,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(state.routeLayer);
        
        // Base route (green)
        L.polyline(pathCoords, {
            color: '#00D000',
            weight: 6,
            opacity: 0.9,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(state.routeLayer);
        
        // Overlay traffic sections with colors based on status
        const trafficSections = routeData.traffic_sections || [];
        
        if (trafficSections.length > 0) {
            console.log(`Drawing ${trafficSections.length} traffic segments`);
            
            trafficSections.forEach(section => {
                const sectionCoords = section.coords.map(c => [c[0], c[1]]);
                
                if (sectionCoords.length >= 2) {
                    // Draw segment with appropriate color
                    // All segments are drawn - green ones overlay the base green,
                    // yellow/red ones create visible contrast
                    L.polyline(sectionCoords, {
                        color: getTrafficColor(section.status),
                        weight: 6,
                        opacity: 0.95,
                        lineCap: 'round',
                        lineJoin: 'round'
                    }).addTo(state.routeLayer);
                }
            });
        }

        // Fit map to route bounds
        const bounds = L.latLngBounds(pathCoords);
        map.fitBounds(bounds, { padding: [50, 50] });
        
        // Update block radius if provided by backend
        if (routeData.block_radius_meters) {
            state.blockRadius = routeData.block_radius_meters;
            updateMapMarkers();
        }
        
        // Format status message
        let statusMsg = `Route found! Avoided ${routeData.flooded_count} floods.`;
        
        // Add time estimates
        const orsMin = Math.round((routeData.ors_duration || 0) / 60);
        
        if (routeData.traffic_duration !== null && routeData.traffic_duration !== undefined) {
            const trafficMin = Math.round(routeData.traffic_duration / 60);
            const delayMin = Math.round((routeData.traffic_delay || 0) / 60);
            
            // Show both ORS estimate and TomTom traffic time
            statusMsg += ` | Thời gian: ${orsMin} phút`;
            
            if (delayMin > 0) {
                statusMsg += ` (+${delayMin} phút tắc đường)`;
            }
        } else {
            statusMsg += ` | Thời gian ước tính: ${orsMin} phút`;
        }
        
        // Update route info (persistent display)
        updateRouteInfo(statusMsg);

    } catch (error) {
        console.error('Error finding route:', error);
        alert('Could not calculate safe route. Please try different points.');
    } finally {
        showLoading(false);
    }
}

// ============================================================================
// Map Updates
// ============================================================================

function updateMapMarkers() {
    state.cameraLayer.clearLayers();
    state.floodLayer.clearLayers();

    state.cameras.forEach(cam => {
        // Validate camera data
        if (!cam || !cam.coords || !cam.coords.lat || !cam.coords.lng) {
            console.warn('Skipping camera with invalid coordinates:', cam);
            return;
        }
        
        const isFlooded = cam.is_flooded;
        const isValid = cam.is_valid !== false;  // Default to true if field is missing
        
        // Extract coordinates from the API response structure
        const lat = cam.coords.lat;
        const lng = cam.coords.lng;
        
        // 1. Camera Marker (for Camera Layer)
        // Icon based on status and validity
        const iconHtml = '<i class="fa-solid fa-video"></i>';
        
        // Determine marker class based on validity and flood status
        let markerClass;
        if (!isValid) {
            markerClass = 'camera-icon-invalid';  // Gray for invalid cameras
        } else if (isFlooded) {
            markerClass = 'camera-icon-flood';    // Red for flooded
        } else {
            markerClass = 'camera-icon-normal';   // Green for normal
        }

        const marker = L.marker([lat, lng], {
            icon: L.divIcon({
                className: markerClass,
                html: iconHtml,
                iconSize: [30, 30],
                iconAnchor: [15, 15]  // Center horizontally and vertically
            })
        });
        
        // Add click event to show camera popup with image
        marker.on('click', () => {
            showCameraPopup(cam, marker);
        });
        
        state.cameraLayer.addLayer(marker);

        // 2. Flood Visualization (Red Blend) - Only if flooded
        if (isFlooded) {
            const circle = L.circle([lat, lng], {
                color: 'red',
                fillColor: '#f03',
                fillOpacity: 0.3,
                radius: state.blockRadius, // Use radius from backend (default 150m)
                stroke: false
            });
            state.floodLayer.addLayer(circle);

            // Add a pulsing effect marker in center
            // const pulse = L.marker([lat, lng], {
            //     icon: L.divIcon({
            //         className: 'flood-pulse-icon',
            //         iconSize: [20, 20],
            //         iconAnchor: [10, 10]
            //     })
            // });
            // state.floodLayer.addLayer(pulse);
        }
    });
}

// ============================================================================
// Camera Popup Functionality
// ============================================================================

function showCameraPopup(camera, marker) {
    // Close previous popup if exists
    if (state.currentCameraPopup) {
        map.closePopup(state.currentCameraPopup);
    }
    
    const cameraName = camera.name || camera.camera_id;
    const status = camera.is_flooded ? 'Ngập lụt' : 'Khô ráo';
    const statusClass = camera.is_flooded ? 'flooded' : 'dry';
    const confidence = camera.confidence ? (camera.confidence * 100).toFixed(1) : 'N/A';
    const lastChecked = camera.last_checked ? new Date(camera.last_checked).toLocaleString('vi-VN') : 'Chưa kiểm tra';
    const analysisPanelId = `severity-panel-${camera.camera_id}`;
    const imageUrl = `${BACKEND_URL}/camera/${camera.camera_id}/image?t=${Date.now()}`;
    
    // Severity analysis card (visible only in test mode)
    const severitySection = state.floodTestMode ? `
        <div class="severity-analysis-card" id="${analysisPanelId}">
            <div class="severity-analysis-header">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"/>
                </svg>
                <span>Phân tích mức ngập</span>
                <div class="severity-spinner" id="spinner-${camera.camera_id}"></div>
            </div>
            <div class="severity-result hidden" id="result-${camera.camera_id}">
                <div class="severity-row">
                    <span class="severity-badge-label">Mức độ:</span>
                    <span class="severity-badge" id="badge-${camera.camera_id}">--</span>
                </div>
                <div class="severity-row">
                    <span class="severity-badge-label">Độ phủ nước:</span>
                    <span class="severity-coverage-text" id="coverage-${camera.camera_id}">--</span>
                </div>
                <div class="coverage-bar-wrap">
                    <div class="coverage-bar-fill" id="bar-${camera.camera_id}" style="width:0%"></div>
                </div>
                <div class="severity-row" id="wheels-row-${camera.camera_id}" style="display:none">
                    <span class="severity-badge-label">Bánh xe phát hiện:</span>
                    <span id="wheels-${camera.camera_id}">0</span>
                </div>
                <div class="mask-preview-wrap">
                    <img class="mask-preview" id="mask-${camera.camera_id}" alt="Water mask" />
                </div>
            </div>
            <div class="severity-error hidden" id="sev-err-${camera.camera_id}">Không thể phân tích ảnh</div>
        </div>` : '';
    
    // Build popup HTML
    const popupContent = `
        <div class="camera-popup">
            <div class="camera-popup-header">
                <h3 class="camera-popup-title">${cameraName}</h3>
                <span class="camera-popup-status ${statusClass}">${status}</span>
            </div>
            <div class="camera-popup-main">
                <div class="camera-popup-left">
                    <div class="camera-popup-image-container">
                        <img 
                            class="camera-popup-image" 
                            id="camera-img-${camera.camera_id}"
                            src="${imageUrl}"
                            alt="Camera ${cameraName}"
                            onload="this.style.display='block'; document.getElementById('loading-${camera.camera_id}').style.display='none';"
                            onerror="this.style.display='none'; document.getElementById('error-${camera.camera_id}').style.display='block'; document.getElementById('loading-${camera.camera_id}').style.display='none';"
                            style="display: none;"
                        />
                        <div class="camera-popup-loading" id="loading-${camera.camera_id}">
                            <div class="spinner-small"></div>
                            <span>Đang tải ảnh...</span>
                        </div>
                        <div class="camera-popup-error" id="error-${camera.camera_id}" style="display: none;">
                            <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                            </svg>
                            <span>Không thể tải ảnh camera</span>
                        </div>
                    </div>
                    <div class="camera-popup-metadata">
                        <div class="metadata-item">
                            <span class="metadata-label">Độ tin cậy:</span>
                            <span class="metadata-value">${confidence}%</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Kiểm tra lần cuối:</span>
                            <span class="metadata-value">${lastChecked}</span>
                        </div>
                    </div>
                </div>
                ${severitySection ? `<div class="camera-popup-right">${severitySection}</div>` : ''}
            </div>
        </div>
    `;
    
    // Create and open popup
    const popup = L.popup({
        maxWidth: 900,
        className: 'custom-camera-popup'
    })
    .setLatLng([camera.coords.lat, camera.coords.lng])
    .setContent(popupContent)
    .openOn(map);
    
    // Store reference to current popup
    state.currentCameraPopup = popup;

    // Trigger severity analysis after popup renders (only in test mode)
    if (state.floodTestMode) {
        setTimeout(() => analyzeCameraFloodSeverity(camera.camera_id, imageUrl), 300);
    }
}

// ============================================================================
// Flood Severity Analysis
// ============================================================================

/**
 * Fetch the camera image, POST it to /analyze-severity, then populate
 * the severity card that is already in the open popup DOM.
 */
async function analyzeCameraFloodSeverity(cameraId, imageUrl) {
    const spinnerId  = `spinner-${cameraId}`;
    const resultId   = `result-${cameraId}`;
    const errId      = `sev-err-${cameraId}`;
    const badgeId    = `badge-${cameraId}`;
    const coverageId = `coverage-${cameraId}`;
    const barId      = `bar-${cameraId}`;
    const wheelsRowId= `wheels-row-${cameraId}`;
    const wheelsId   = `wheels-${cameraId}`;
    const maskId     = `mask-${cameraId}`;

    const spinner  = document.getElementById(spinnerId);
    const resultEl = document.getElementById(resultId);
    const errEl    = document.getElementById(errId);
    if (!resultEl) return; // popup closed before analysis finished

    try {
        // 1. Fetch image as blob
        const imgResp = await fetch(imageUrl);
        if (!imgResp.ok) throw new Error('Image fetch failed');
        const blob = await imgResp.blob();

        // 2. Build multipart form
        const form = new FormData();
        // Give the blob a proper filename so the server can validate the extension
        const fileName = `camera_${cameraId}.jpg`;
        form.append('file', blob, fileName);

        // 3. POST to AI service
        const resp = await fetch(`${AI_SERVICE_URL}/api/v1/analyze-severity`, {
            method: 'POST',
            body: form,
        });
        if (!resp.ok) throw new Error(`API ${resp.status}`);
        const data = await resp.json();

        if (!data.success) throw new Error('Analysis failed');

        // 4. Populate UI elements
        const badge    = document.getElementById(badgeId);
        const coverage = document.getElementById(coverageId);
        const bar      = document.getElementById(barId);
        const wheelsRow= document.getElementById(wheelsRowId);
        const wheelsEl = document.getElementById(wheelsId);
        const maskImg  = document.getElementById(maskId);

        if (!badge) return; // popup closed

        // Severity badge
        const severityMap = { None: 'sev-none', Low: 'sev-low', Medium: 'sev-medium', High: 'sev-high' };
        badge.textContent = { None: 'Không ngập', Low: 'Nhẹ', Medium: 'Trung bình', High: 'Nặng' }[data.severity] || data.severity;
        badge.className = 'severity-badge ' + (severityMap[data.severity] || '');

        // Coverage bar
        const pct = (data.coverage_ratio * 100).toFixed(1);
        if (coverage) coverage.textContent = `${pct}%`;
        if (bar) {
            bar.style.width = `${Math.min(100, pct)}%`;
            bar.className = 'coverage-bar-fill ' + (severityMap[data.severity] || '');
        }

        // Wheels
        if (data.wheels_detected > 0 && wheelsRow && wheelsEl) {
            wheelsRow.style.display = 'flex';
            wheelsEl.textContent = data.wheels_detected;
        }

        // Water mask overlay
        if (data.mask_b64 && maskImg) {
            maskImg.src = `data:image/png;base64,${data.mask_b64}`;
        }

        // Show result, hide spinner
        if (spinner) spinner.style.display = 'none';
        if (resultEl) resultEl.classList.remove('hidden');

    } catch (e) {
        console.warn('Severity analysis error:', e);
        if (spinner) spinner.style.display = 'none';
        if (errEl) errEl.classList.remove('hidden');
    }
}

// ============================================================================
// Autocomplete Functionality
// ============================================================================

async function searchLocation(inputElement, suggestionsListId) {
    const query = inputElement.value.trim();
    const suggestionsList = document.getElementById(suggestionsListId);
    
    // Clear suggestions if query is empty
    if (!query || query.length < 3) {
        suggestionsList.innerHTML = '';
        suggestionsList.classList.remove('active');
        return;
    }
    
    try {
        // Call Nominatim API with Vietnam filter
        const url = `https://nominatim.openstreetmap.org/search?` +
            `format=json` +
            `&q=${encodeURIComponent(query)}` +
            `&countrycodes=vn` +
            `&limit=5` +
            `&addressdetails=1`;
        
        const response = await fetch(url, {
            headers: {
                'User-Agent': 'FloodAI-Map-App' // Nominatim requires user agent
            }
        });
        
        const results = await response.json();
        
        // Display suggestions
        if (results && results.length > 0) {
            suggestionsList.innerHTML = results.map(result => `
                <li class="autocomplete-item" 
                    data-lat="${result.lat}" 
                    data-lon="${result.lon}"
                    data-display="${result.display_name}">
                    <span class="autocomplete-item-name">${result.display_name.split(',')[0]}</span>
                    <span class="autocomplete-item-address">${result.display_name}</span>
                </li>
            `).join('');
            suggestionsList.classList.add('active');
        } else {
            suggestionsList.innerHTML = '<li class="autocomplete-item"><span class="autocomplete-item-name">Không tìm thấy kết quả</span></li>';
            suggestionsList.classList.add('active');
        }
    } catch (error) {
        console.error('Autocomplete error:', error);
        suggestionsList.innerHTML = '<li class="autocomplete-item"><span class="autocomplete-item-name">Lỗi tìm kiếm</span></li>';
        suggestionsList.classList.add('active');
    }
}

function selectSuggestion(lat, lon, displayName, type) {
    // Convert to numbers
    const latitude = parseFloat(lat);
    const longitude = parseFloat(lon);
    
    // Store coordinates in global variables
    if (type === 'start') {
        startCoords = [latitude, longitude];
        document.getElementById('start-suggestions').classList.remove('active');
        
        // Update state and map marker with display name
        setPoint({ lat: latitude, lng: longitude }, 'start', displayName);
    } else if (type === 'end') {
        endCoords = [latitude, longitude];
        document.getElementById('end-suggestions').classList.remove('active');
        
        // Update state and map marker with display name
        setPoint({ lat: latitude, lng: longitude }, 'end', displayName);
    }
}

function hideSuggestions(suggestionsListId) {
    setTimeout(() => {
        document.getElementById(suggestionsListId).classList.remove('active');
    }, 200);
}

function initAutocomplete() {
    const startInput = document.getElementById('start-input');
    const endInput = document.getElementById('end-input');
    const startSuggestions = document.getElementById('start-suggestions');
    const endSuggestions = document.getElementById('end-suggestions');
    
    // Debounced search functions (500ms delay)
    const debouncedStartSearch = debounce(() => searchLocation(startInput, 'start-suggestions'), 500);
    const debouncedEndSearch = debounce(() => searchLocation(endInput, 'end-suggestions'), 500);
    
    // Input event listeners
    startInput.addEventListener('input', debouncedStartSearch);
    endInput.addEventListener('input', debouncedEndSearch);
    
    // Click handlers for suggestions
    startSuggestions.addEventListener('click', (e) => {
        const item = e.target.closest('.autocomplete-item');
        if (item && item.dataset.lat) {
            selectSuggestion(item.dataset.lat, item.dataset.lon, item.dataset.display, 'start');
        }
    });
    
    endSuggestions.addEventListener('click', (e) => {
        const item = e.target.closest('.autocomplete-item');
        if (item && item.dataset.lat) {
            selectSuggestion(item.dataset.lat, item.dataset.lon, item.dataset.display, 'end');
        }
    });
    
    // Hide suggestions when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.autocomplete-container')) {
            startSuggestions.classList.remove('active');
            endSuggestions.classList.remove('active');
        }
    });
    
    // Hide suggestions on blur
    startInput.addEventListener('blur', () => hideSuggestions('start-suggestions'));
    endInput.addEventListener('blur', () => hideSuggestions('end-suggestions'));
}

// ============================================================================
// UI Interactions
// ============================================================================

// Geocoding Helper (Nominatim)
async function geocode(query) {
    if (!query) return null;
    // Check if query is "lat,lng"
    const coordMatch = query.match(/^(-?\d+(\.\d+)?),\s*(-?\d+(\.\d+)?)$/);
    if (coordMatch) {
        return { lat: parseFloat(coordMatch[1]), lng: parseFloat(coordMatch[3]) };
    }

    // Call Nominatim
    try {
        const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query + ', Ho Chi Minh City')}&limit=1`;
        const res = await fetch(url);
        const json = await res.json();
        if (json && json.length > 0) {
            return { lat: parseFloat(json[0].lat), lng: parseFloat(json[0].lon) };
        }
        return null;
    } catch (e) {
        console.error("Geocode error", e);
        return null;
    }
}

async function handleSearch(inputId, type) {
    const input = document.getElementById(inputId);
    const query = input.value;
    const coords = await geocode(query);

    if (coords) {
        setPoint(coords, type);
    } else {
        alert("Location not found. Try entering 'Lat,Lng' directly.");
    }
}

function setPoint(coords, type, displayName = null) {
    if (type === 'start') {
        state.startPoint = coords;
        // Display address if provided, otherwise show coordinates
        document.getElementById('start-input').value = displayName || `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`;
        if (state.startMarker) map.removeLayer(state.startMarker);
        state.startMarker = L.marker([coords.lat, coords.lng], { icon: startIcon, draggable: true }).addTo(map);
        state.startMarker.on('dragend', (e) => setPoint(e.target.getLatLng(), 'start'));
        map.panTo([coords.lat, coords.lng]);
    } else {
        state.endPoint = coords;
        // Display address if provided, otherwise show coordinates
        document.getElementById('end-input').value = displayName || `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`;
        if (state.endMarker) map.removeLayer(state.endMarker);
        state.endMarker = L.marker([coords.lat, coords.lng], { icon: endIcon, draggable: true }).addTo(map);
        state.endMarker.on('dragend', (e) => setPoint(e.target.getLatLng(), 'end'));
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    
    // Tab Switching
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabId = button.dataset.tab;
            
            // Update active states
            tabButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            
            // Show corresponding content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(`content-${tabId}`).classList.add('active');
            
            // Clear risk markers when switching to routing tab
            if (tabId === 'routing' && predictionState.riskMarkerLayer) {
                predictionState.riskMarkerLayer.clearLayers();
            }
        });
    });
    
    // Initialize autocomplete
    initAutocomplete();
    
    // Initial Load
    fetchFloodStatus();
    
    // Refresh flood status every 30s
    setInterval(fetchFloodStatus, 30000);

    // Toggles
    const toggleCam = document.getElementById('toggle-cameras');
    toggleCam.addEventListener('change', (e) => {
        if (e.target.checked) {
            map.addLayer(state.cameraLayer);
        } else {
            map.removeLayer(state.cameraLayer);
        }
    });

    const toggleFlood = document.getElementById('toggle-flood');
    toggleFlood.addEventListener('change', (e) => {
        if (e.target.checked) {
            map.addLayer(state.floodLayer);
        } else {
            map.removeLayer(state.floodLayer);
        }
    });

    // Traffic toggle is now just a visual indicator
    // Traffic is automatically shown on route when available
    const toggleTraffic = document.getElementById('toggle-traffic');
    // Keep toggle checked by default to indicate traffic is active
    toggleTraffic.checked = true;
    toggleTraffic.disabled = true; // Disable since it's always on for routes
    
    // Add tooltip/title to explain
    const trafficLabel = toggleTraffic.closest('.layer-item');
    if (trafficLabel) {
        trafficLabel.title = 'Giao thông tự động hiển thị trên route';
    }

    // Test Mode – enable/disable flood simulation + boost weather display
    const toggleTest = document.getElementById('toggle-test-mode');
    toggleTest.addEventListener('change', async (e) => {
        const isOn = e.target.checked;
        state.floodTestMode = isOn;

        // Show/hide the hint about clicking cameras for severity analysis
        const hint = document.getElementById('test-mode-hint');
        if (hint) hint.classList.toggle('hidden', !isOn);

        // 1. Tell backend to enable/disable flood simulation
        const endpoint = isOn ? `${BACKEND_URL}/test-flood/enable` : `${BACKEND_URL}/test-flood/disable`;
        await fetch(endpoint, { method: 'POST' }).catch(() => {});
        await fetchFloodStatus();

        // 2. Boost (or restore) weather widget values for demo effect
        applyWeatherBoost(isOn);
    });

    // Note: Input change handlers removed - now using autocomplete

    // Buttons
    document.getElementById('btn-find-route').addEventListener('click', findRoute);
    
    document.getElementById('btn-use-current').addEventListener('click', () => {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(pos => {
                setPoint({ lat: pos.coords.latitude, lng: pos.coords.longitude }, 'start');
            });
        } else {
            alert("Geolocation not supported");
        }
    });

    // Map Click Context
    // map.on('click', (e) => {
    //     // Simple logic: If start is empty, set start. If start exists, set end.
    //     if (!state.startPoint) {
    //         setPoint(e.latlng, 'start');
    //     } else if (!state.endPoint) {
    //         setPoint(e.latlng, 'end');
    //     }
    // });
    
    // Better: Right click menu or just let user type. 
    // Let's implement Right Click to set points for better UX
    map.on('contextmenu', (e) => {
        const popup = L.popup()
            .setLatLng(e.latlng)
            .setContent(`
                <button class="btn btn-sm btn-success mb-1" onclick="window.setStartPoint(${e.latlng.lat}, ${e.latlng.lng});">Set Start</button><br>
                <button class="btn btn-sm btn-danger" onclick="window.setEndPoint(${e.latlng.lat}, ${e.latlng.lng});">Set End</button>
            `)
            .openOn(map);
    });

    // Expose helpers for popup
    window.setStartPoint = (lat, lng) => {
        setPoint({lat, lng}, 'start');
        map.closePopup();
    };
    window.setEndPoint = (lat, lng) => {
        setPoint({lat, lng}, 'end');
        map.closePopup();
    };
    
    // Expose map globally for debugging if needed
    window.mapInstance = map;
});

// Utilities
function showLoading(show) {
    const el = document.getElementById('loading-overlay');
    if (show) el.classList.remove('hidden');
    else el.classList.add('hidden');
}

function updateStatus(msg, type='info') {
    const panel = document.getElementById('status-panel');
    const text = document.getElementById('status-text');
    panel.classList.remove('hidden');
    text.textContent = msg;
    // Status panel no longer auto-hides
}

// Persistent route info display (won't be overwritten by flood status updates)
let currentRouteInfo = null;

function updateRouteInfo(msg) {
    currentRouteInfo = msg;
    const panel = document.getElementById('status-panel');
    const text = document.getElementById('status-text');
    panel.classList.remove('hidden');
    text.textContent = msg;
}

function clearRouteInfo() {
    currentRouteInfo = null;
}

// ============================================================================
// Soi Ngập - Prediction Functionality
// ============================================================================

// Prediction state
const predictionState = {
    currentHour: 1,
    predictions: [],
    cacheTimestamp: null,
    riskMarkerLayer: null
};

// Initialize risk marker layer
predictionState.riskMarkerLayer = L.layerGroup();

// Fetch predictions for a specific hour
async function fetchPredictions(hour) {
    try {
        const response = await fetch(`${BACKEND_URL}/predictions/${hour}`);
        if (!response.ok) throw new Error('Failed to fetch predictions');
        
        const data = await response.json();
        predictionState.predictions = data.cameras;
        predictionState.cacheTimestamp = data.cache_timestamp;
        
        return data;
    } catch (error) {
        console.error('Error fetching predictions:', error);
        return null;
    }
}

// Update the prediction UI with fetched data
function updatePredictionUI(data) {
    if (!data) {
        document.getElementById('stat-high-risk').textContent = '--';
        document.getElementById('stat-medium-risk').textContent = '--';
        document.getElementById('stat-low-risk').textContent = '--';
        document.getElementById('cache-timestamp').textContent = 'Lỗi tải dữ liệu';
        return;
    }
    
    // Count risk levels - matching backend thresholds:
    // low: < 0.4, medium: 0.4-0.6, high: 0.6-0.8, very high: >= 0.8
    let veryHigh = 0, high = 0, medium = 0, low = 0;
    data.cameras.forEach(cam => {
        if (cam.risk >= 0.8) veryHigh++;
        else if (cam.risk >= 0.6) high++;
        else if (cam.risk >= 0.4) medium++;
        else low++;
    });
    
    // Update stats
    // Combine veryHigh + high as "Nguy hiểm" (danger)
    document.getElementById('stat-high-risk').textContent = veryHigh + high;
    document.getElementById('stat-medium-risk').textContent = medium;
    document.getElementById('stat-low-risk').textContent = low;
    
    // Update timestamp
    if (data.cache_timestamp) {
        const date = new Date(data.cache_timestamp);
        document.getElementById('cache-timestamp').textContent = 
            `Cập nhật: ${date.toLocaleString('vi-VN')}`;
    } else {
        document.getElementById('cache-timestamp').textContent = 'Dữ liệu thời gian thực';
    }
    
    // Update high risk camera list
    updateHighRiskCameraList(data.cameras);
    
    // Update map markers
    displayPredictionMarkers(data.cameras);
}

// Update the high risk camera list
function updateHighRiskCameraList(cameras) {
    const container = document.getElementById('high-risk-cameras');
    
    // Filter high risk cameras (risk >= 0.6 - medium and above)
    const highRiskCameras = cameras
        .filter(cam => cam.risk >= 0.6)
        .sort((a, b) => b.risk - a.risk)
        .slice(0, 10); // Top 10
    
    if (highRiskCameras.length === 0) {
        container.innerHTML = '<div class="camera-list-empty">Không có camera rủi ro cao</div>';
        return;
    }
    
    container.innerHTML = highRiskCameras.map(cam => {
        const riskPercent = (cam.risk * 100).toFixed(0);
        const badgeClass = cam.risk >= 0.8 ? 'very-high' : cam.risk >= 0.6 ? 'high' : 'medium';
        const badgeText = cam.risk >= 0.8 ? 'Rất cao' : cam.risk >= 0.6 ? 'Cao' : 'TB';
        
        return `
            <div class="camera-risk-item" data-lat="${cam.lat}" data-lng="${cam.lng}" data-id="${cam.camera_id}">
                <div class="camera-risk-indicator" style="background: ${cam.risk_color}"></div>
                <div class="camera-risk-info">
                    <div class="camera-risk-name">${cam.name || cam.camera_id}</div>
                    <div class="camera-risk-value">Rủi ro: ${riskPercent}%</div>
                </div>
                <span class="camera-risk-badge ${badgeClass}">${badgeText}</span>
            </div>
        `;
    }).join('');
    
    // Add click handlers to zoom to camera
    container.querySelectorAll('.camera-risk-item').forEach(item => {
        item.addEventListener('click', () => {
            const lat = parseFloat(item.dataset.lat);
            const lng = parseFloat(item.dataset.lng);
            map.setView([lat, lng], 16);
        });
    });
}

// Display prediction markers on the map
function displayPredictionMarkers(cameras) {
    // Clear existing markers
    predictionState.riskMarkerLayer.clearLayers();
    
    cameras.forEach(cam => {
        if (!cam.lat || !cam.lng) return;
        
        // Create circle marker with risk color
        const marker = L.circleMarker([cam.lat, cam.lng], {
            radius: 8,
            fillColor: cam.risk_color || '#22c55e',
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.8
        });
        
        // Add tooltip
        const riskPercent = (cam.risk * 100).toFixed(0);
        marker.bindTooltip(`
            <strong>${cam.name || cam.camera_id}</strong><br>
            Rủi ro: ${riskPercent}%<br>
            Mức: ${cam.risk_level}
        `, { 
            direction: 'top',
            offset: [0, -10]
        });
        
        predictionState.riskMarkerLayer.addLayer(marker);
    });
    
    // Add layer to map if not already added
    if (!map.hasLayer(predictionState.riskMarkerLayer)) {
        map.addLayer(predictionState.riskMarkerLayer);
    }
}

// Trigger manual risk job
async function triggerRiskJob() {
    try {
        showLoading(true);
        const response = await fetch(`${BACKEND_URL}/risk-job/trigger`, { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'success') {
            // Refresh predictions for current hour
            const predictions = await fetchPredictions(predictionState.currentHour);
            updatePredictionUI(predictions);
        }
    } catch (error) {
        console.error('Error triggering risk job:', error);
    } finally {
        showLoading(false);
    }
}

// Initialize prediction tab event listeners
function initPredictionTab() {
    const hourSlider = document.getElementById('hour-slider');
    const hourValue = document.getElementById('hour-value');
    const refreshBtn = document.getElementById('btn-refresh-predictions');
    
    // Hour slider change
    hourSlider.addEventListener('input', (e) => {
        const hour = parseInt(e.target.value);
        hourValue.textContent = hour;
        predictionState.currentHour = hour;
    });
    
    // Hour slider change (on release)
    hourSlider.addEventListener('change', async (e) => {
        const hour = parseInt(e.target.value);
        showLoading(true);
        const predictions = await fetchPredictions(hour);
        updatePredictionUI(predictions);
        // Also fetch weather forecast for this hour
        await fetchFutureWeather(hour);
        showLoading(false);
    });
    
    // Refresh button
    refreshBtn.addEventListener('click', triggerRiskJob);
    
    // Load initial predictions and weather when tab is shown
    const inspectionTab = document.getElementById('tab-inspection');
    inspectionTab.addEventListener('click', async () => {
        showLoading(true);
        // Always fetch weather forecast when tab is clicked
        await fetchFutureWeather(predictionState.currentHour);
        // Fetch predictions if not already loaded
        if (predictionState.predictions.length === 0) {
            const predictions = await fetchPredictions(predictionState.currentHour);
            updatePredictionUI(predictions);
        }
        showLoading(false);
    });
}

// ============================================================================
// Weather Functionality
// ============================================================================

// Weather state
const weatherState = {
    currentWeather: null,
    forecastWeather: null,
    lastFetch: null
};

// Get badge class based on rain level
function getRainBadgeClass(level) {
    const levelMap = {
        'Không mưa': '',
        'Mưa nhẹ': 'rain-light',
        'Mưa vừa': 'rain-moderate',
        'Mưa to': 'rain-heavy',
        'Mưa rất to': 'rain-very-heavy'
    };
    return levelMap[level] || '';
}

// Get badge class based on tide level
function getTideBadgeClass(level) {
    const levelMap = {
        'Thấp': 'tide-low',
        'Trung bình': 'tide-medium',
        'Cao': 'tide-high',
        'Rất cao': 'tide-very-high'
    };
    return levelMap[level] || 'tide-low';
}

// Fetch current weather
async function fetchCurrentWeather() {
    try {
        const response = await fetch(`${BACKEND_URL}/weather/current`);
        if (!response.ok) throw new Error('Failed to fetch current weather');
        
        const data = await response.json();
        weatherState.currentWeather = data;
        weatherState.lastFetch = new Date();
        
        updateCurrentWeatherUI(data);
        return data;
    } catch (error) {
        console.error('Error fetching current weather:', error);
        return null;
    }
}

// Fetch future weather for a specific hour
async function fetchFutureWeather(hour) {
    try {
        const response = await fetch(`${BACKEND_URL}/weather/${hour}`);
        if (!response.ok) throw new Error(`Failed to fetch weather for hour ${hour}`);
        
        const data = await response.json();
        weatherState.forecastWeather = data;
        
        updateForecastWeatherUI(data);
        return data;
    } catch (error) {
        console.error(`Error fetching weather for hour ${hour}:`, error);
        return null;
    }
}

// Update current weather UI (top right widget)
function updateCurrentWeatherUI(data) {
    if (!data || !data.weather) {
        document.getElementById('current-rain').textContent = '--';
        document.getElementById('current-tide').textContent = '--';
        document.getElementById('rain-badge').textContent = '--';
        document.getElementById('tide-badge').textContent = '--';
        return;
    }
    
    const weather = data.weather;
    
    // Update rain
    document.getElementById('current-rain').textContent = weather.rain_3h.toFixed(1);
    const rainBadge = document.getElementById('rain-badge');
    rainBadge.textContent = weather.rain_level;
    rainBadge.className = 'weather-badge ' + getRainBadgeClass(weather.rain_level);
    rainBadge.style.background = `${weather.rain_color}33`;  // 20% opacity
    rainBadge.style.color = weather.rain_color;
    
    // Update tide
    document.getElementById('current-tide').textContent = weather.tide.toFixed(2);
    const tideBadge = document.getElementById('tide-badge');
    tideBadge.textContent = weather.tide_level;
    tideBadge.className = 'weather-badge ' + getTideBadgeClass(weather.tide_level);
    tideBadge.style.background = `${weather.tide_color}33`;  // 20% opacity
    tideBadge.style.color = weather.tide_color;
}

// Update forecast weather UI (in inspection tab)
function updateForecastWeatherUI(data) {
    const forecastRain = document.getElementById('forecast-rain');
    const forecastTide = document.getElementById('forecast-tide');
    const forecastRainBadge = document.getElementById('forecast-rain-badge');
    const forecastTideBadge = document.getElementById('forecast-tide-badge');
    
    if (!data || !data.weather) {
        if (forecastRain) forecastRain.textContent = '--';
        if (forecastTide) forecastTide.textContent = '--';
        if (forecastRainBadge) forecastRainBadge.textContent = '--';
        if (forecastTideBadge) forecastTideBadge.textContent = '--';
        return;
    }
    
    const weather = data.weather;
    
    // Update rain forecast
    if (forecastRain) {
        forecastRain.textContent = weather.rain_3h.toFixed(1);
    }
    if (forecastRainBadge) {
        forecastRainBadge.textContent = weather.rain_level;
        forecastRainBadge.className = 'forecast-badge ' + getRainBadgeClass(weather.rain_level);
        forecastRainBadge.style.background = `${weather.rain_color}33`;
        forecastRainBadge.style.color = weather.rain_color;
    }
    
    // Update tide forecast
    if (forecastTide) {
        forecastTide.textContent = weather.tide.toFixed(2);
    }
    if (forecastTideBadge) {
        forecastTideBadge.textContent = weather.tide_level;
        forecastTideBadge.className = 'forecast-badge ' + getTideBadgeClass(weather.tide_level);
        forecastTideBadge.style.background = `${weather.tide_color}33`;
        forecastTideBadge.style.color = weather.tide_color;
    }
}

// Initialize weather
function initWeather() {
    // Fetch current weather on load
    fetchCurrentWeather();
    
    // Refresh current weather every 5 minutes
    setInterval(fetchCurrentWeather, 5 * 60 * 1000);
}

/**
 * In flood test mode, override the weather widget to show raised rain/tide
 * values for a more realistic demo. Restores real data when turned off.
 */
function applyWeatherBoost(isOn) {
    if (isOn) {
        // Simulated heavy-rain + high-tide scenario
        const fakeWeather = {
            rain_3h: 28.5,
            rain_level: 'Mưa rất to',
            rain_color: '#dc2626',
            tide: 1.52,
            tide_level: 'Rất cao',
            tide_color: '#7c3aed',
        };
        _applyWeatherToWidget(fakeWeather);
        _applyWeatherToForecast(fakeWeather);
    } else {
        // Restore real data if available
        if (weatherState.currentWeather) {
            updateCurrentWeatherUI(weatherState.currentWeather);
        }
        if (weatherState.forecastWeather) {
            updateForecastWeatherUI(weatherState.forecastWeather);
        }
    }
}

/** Shared helper: write weather values into the top-right weather widget. */
function _applyWeatherToWidget(w) {
    const rainEl = document.getElementById('current-rain');
    const tidEl  = document.getElementById('current-tide');
    const rainBdg = document.getElementById('rain-badge');
    const tideBdg = document.getElementById('tide-badge');
    if (rainEl) rainEl.textContent = w.rain_3h.toFixed(1);
    if (tidEl)  tidEl.textContent  = w.tide.toFixed(2);
    if (rainBdg) {
        rainBdg.textContent = w.rain_level;
        rainBdg.style.background = `${w.rain_color}33`;
        rainBdg.style.color = w.rain_color;
    }
    if (tideBdg) {
        tideBdg.textContent = w.tide_level;
        tideBdg.style.background = `${w.tide_color}33`;
        tideBdg.style.color = w.tide_color;
    }
}

/** Shared helper: write weather values into the inspection-tab forecast section. */
function _applyWeatherToForecast(w) {
    const rainEl  = document.getElementById('forecast-rain');
    const tideEl  = document.getElementById('forecast-tide');
    const rainBdg = document.getElementById('forecast-rain-badge');
    const tideBdg = document.getElementById('forecast-tide-badge');
    if (rainEl)  rainEl.textContent  = w.rain_3h.toFixed(1);
    if (tideEl)  tideEl.textContent  = w.tide.toFixed(2);
    if (rainBdg) {
        rainBdg.textContent = w.rain_level;
        rainBdg.style.background = `${w.rain_color}33`;
        rainBdg.style.color = w.rain_color;
    }
    if (tideBdg) {
        tideBdg.textContent = w.tide_level;
        tideBdg.style.background = `${w.tide_color}33`;
        tideBdg.style.color = w.tide_color;
    }
}


document.addEventListener('DOMContentLoaded', () => {
    initPredictionTab();
    initWeather();
});

socket.onopen = () => {
    console.log("WebSocket connection opened");
}
socket.onmessage = (event) => {
    try {
        const data = JSON.parse(event.data);
        if (data.type === 'set_route_and_find') {
            handleSetRouteAndFind(data);
        } else if (data.type === 'show_camera_image') {
            handleShowCameraImage(data);
        }
    } catch (e) {
        console.error('WebSocket message parse error:', e);
    }
}
socket.onclose = () => {
    console.log("WebSocket connection closed");
}
socket.onerror = (error) => {
    console.error("WebSocket error:", error);
}

function handleSetRouteAndFind(data) {
    // 1. Set Start Point
    if (data.start && data.start.lat && data.start.lng) {
        setPoint(data.start, 'start');
    }

    // 2. Set End Point
    if (data.end && data.end.lat && data.end.lng) {
        setPoint(data.end, 'end');
    }

    // 3. Trigger Find Route
    if (state.startPoint && state.endPoint) {
        console.log("Agent triggering findRoute...");
        setTimeout(() => {
            findRoute();
        }, 100);
    }
}

function handleShowCameraImage(data) {
    const cameraId = data.camera_id;
    const streetName = data.street_name || 'Camera';
    const imageUrl = `${BACKEND_URL}/camera/${cameraId}/image`;

    // Hiển thị ảnh camera trong chat như một message
    const container = document.getElementById('chat-messages');
    if (container) {
        const div = document.createElement('div');
        div.className = 'chat-message assistant';
        div.innerHTML = `
            <div class="chat-bubble" style="padding: 8px;">
                <div style="font-size: 12px; opacity: 0.7; margin-bottom: 6px;">📷 ${streetName}</div>
                <img src="${imageUrl}" alt="Camera ${streetName}"
                     style="width: 100%; border-radius: 8px; cursor: pointer;"
                     onerror="this.alt='Không tải được ảnh camera'; this.style.padding='20px';"
                     onclick="window.open('${imageUrl}', '_blank')">
            </div>`;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }
}

// ============================================================================
// Chat Widget — Agent Service Integration
// ============================================================================

const chatState = {
    isOpen: false,
    isStreaming: false,
    currentAssistantBubble: null,
    currentAssistantText: '',
};

function initChat() {
    const toggleBtn = document.getElementById('chat-toggle');
    const closeBtn = document.getElementById('chat-close');
    const resetBtn = document.getElementById('chat-reset');
    const sendBtn = document.getElementById('chat-send');
    const input = document.getElementById('chat-input');

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', toggleChat);
    resetBtn.addEventListener('click', resetChat);
    sendBtn.addEventListener('click', () => sendChatMessage());
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
}

function toggleChat() {
    const panel = document.getElementById('chat-panel');
    const btn = document.getElementById('chat-toggle');
    chatState.isOpen = !chatState.isOpen;

    if (chatState.isOpen) {
        panel.classList.remove('hidden');
        btn.classList.add('active');
        document.getElementById('chat-input').focus();
    } else {
        panel.classList.add('hidden');
        btn.classList.remove('active');
    }
}

function scrollChatToBottom() {
    const container = document.getElementById('chat-messages');
    container.scrollTop = container.scrollHeight;
}

function appendUserMessage(text) {
    const container = document.getElementById('chat-messages');
    // Remove welcome if present
    const welcome = container.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = 'chat-message user';
    div.innerHTML = `<div class="chat-bubble">${escapeHtml(text)}</div>`;
    container.appendChild(div);
    scrollChatToBottom();
}

function createAssistantBubble() {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-message assistant';
    div.innerHTML = `<div class="chat-bubble"></div>`;
    container.appendChild(div);
    chatState.currentAssistantBubble = div.querySelector('.chat-bubble');
    chatState.currentAssistantText = '';
    scrollChatToBottom();
    return div;
}

function appendToolIndicator(name) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-tool-indicator';
    div.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
        </svg>
        <span>Đang sử dụng <span class="chat-tool-name">${escapeHtml(name)}</span>...</span>
    `;
    container.appendChild(div);
    scrollChatToBottom();
}

function showTypingIndicator() {
    const container = document.getElementById('chat-messages');
    // Remove existing typing indicator
    const existing = container.querySelector('.chat-typing');
    if (existing) return;

    const div = document.createElement('div');
    div.className = 'chat-typing';
    div.innerHTML = `
        <div class="chat-typing-dot"></div>
        <div class="chat-typing-dot"></div>
        <div class="chat-typing-dot"></div>
    `;
    container.appendChild(div);
    scrollChatToBottom();
}

function removeTypingIndicator() {
    const container = document.getElementById('chat-messages');
    const typing = container.querySelector('.chat-typing');
    if (typing) typing.remove();
}

function appendErrorMessage(text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-message error';
    div.innerHTML = `<div class="chat-bubble">⚠️ ${escapeHtml(text)}</div>`;
    container.appendChild(div);
    scrollChatToBottom();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function setInputEnabled(enabled) {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    input.disabled = !enabled;
    sendBtn.disabled = !enabled;
    if (enabled) input.focus();
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || chatState.isStreaming) return;

    // Show user message
    appendUserMessage(text);
    input.value = '';
    chatState.isStreaming = true;
    setInputEnabled(false);

    // Show typing indicator
    showTypingIndicator();

    try {
        const response = await fetch(`${AGENT_URL}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let assistantDiv = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line in buffer

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6).trim();
                if (!jsonStr) continue;

                try {
                    const event = JSON.parse(jsonStr);

                    switch (event.type) {
                        case 'token':
                            removeTypingIndicator();
                            if (!chatState.currentAssistantBubble) {
                                assistantDiv = createAssistantBubble();
                            }
                            chatState.currentAssistantText += event.content;
                            chatState.currentAssistantBubble.textContent = chatState.currentAssistantText;
                            scrollChatToBottom();
                            break;

                        case 'tool_call':
                            removeTypingIndicator();
                            // Finalize current bubble if exists
                            if (chatState.currentAssistantBubble) {
                                chatState.currentAssistantBubble = null;
                            }
                            if (event.name) {
                                appendToolIndicator(event.name);
                            }
                            break;

                        case 'tool_result':
                            // After tool completes, show typing for the next response
                            showTypingIndicator();
                            break;

                        case 'done':
                            removeTypingIndicator();
                            // Remove spinning tool indicators
                            document.querySelectorAll('.chat-tool-indicator').forEach(el => {
                                el.querySelector('svg')?.style.setProperty('animation', 'none');
                            });
                            chatState.currentAssistantBubble = null;
                            break;

                        case 'error':
                            removeTypingIndicator();
                            chatState.currentAssistantBubble = null;
                            appendErrorMessage(event.content || 'Đã xảy ra lỗi.');
                            break;
                    }
                } catch (parseErr) {
                    console.warn('Chat SSE parse error:', parseErr, jsonStr);
                }
            }
        }
    } catch (err) {
        removeTypingIndicator();
        chatState.currentAssistantBubble = null;
        appendErrorMessage(`Không thể kết nối tới agent: ${err.message}`);
    } finally {
        chatState.isStreaming = false;
        chatState.currentAssistantBubble = null;
        setInputEnabled(true);
    }
}

async function resetChat() {
    try {
        await fetch(`${AGENT_URL}/reset`, { method: 'POST' });
    } catch (err) {
        console.warn('Failed to reset agent state:', err);
    }

    // Clear messages UI
    const container = document.getElementById('chat-messages');
    container.innerHTML = `
        <div class="chat-welcome">
            <div class="chat-welcome-icon">🤖</div>
            <p>Xin chào! Tôi là trợ lý Flood-AI.</p>
            <p class="chat-welcome-sub">Hỏi tôi về tình trạng ngập, thời tiết, hoặc tìm đường đi an toàn.</p>
        </div>
    `;
    chatState.currentAssistantBubble = null;
    chatState.currentAssistantText = '';
}

// Initialize chat on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initChat();
});
