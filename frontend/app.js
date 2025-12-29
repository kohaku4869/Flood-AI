// Configuration
const BACKEND_URL = 'http://localhost:5000';

// State
const state = {
    startPoint: null, // {lat, lng}
    endPoint: null,   // {lat, lng}
    cameras: [],      // Array of camera objects
    cameraLayer: null, // Leaflet LayerGroup
    floodLayer: null,  // Leaflet LayerGroup
    routeLayer: null,  // Leaflet Polyline
    startMarker: null,
    endMarker: null,
    blockRadius: 150,  // Block radius in meters (will be updated from backend)
    currentCameraPopup: null  // Currently open camera popup
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
state.cameraLayer = L.layerGroup(); // Not added by default based on prompt req? "Check to show"
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
        updateStatus(`Loaded ${data.total_cameras} cameras. ${data.flooded_count} flooded.`);
    } catch (error) {
        console.error('Error fetching flood status:', error);
        updateStatus('Error loading flood data', 'danger');
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

        // Draw Route
        if (state.routeLayer) map.removeLayer(state.routeLayer);
        
        // Backend returns path as array of {lat, lng} objects
        // Convert to Leaflet format: [[lat, lng], [lat, lng], ...]
        const pathCoords = routeData.path.map(coord => [coord.lat, coord.lng]);
        
        state.routeLayer = L.polyline(pathCoords, {
            color: '#00b14f',
            weight: 6,
            opacity: 0.8,
            lineCap: 'round'
        }).addTo(map);

        map.fitBounds(state.routeLayer.getBounds(), { padding: [50, 50] });
        
        // Update block radius if provided by backend
        if (routeData.block_radius_meters) {
            state.blockRadius = routeData.block_radius_meters;
            // Refresh flood visualization to use new radius
            updateMapMarkers();
        }
        
        updateStatus(`Route found! Length: ${routeData.path_length} nodes. Avoided ${routeData.flooded_count} floods (${state.blockRadius}m radius).`);

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
    
    // Build popup HTML
    const popupContent = `
        <div class="camera-popup">
            <div class="camera-popup-header">
                <h3 class="camera-popup-title">${cameraName}</h3>
                <span class="camera-popup-status ${statusClass}">${status}</span>
            </div>
            <div class="camera-popup-image-container">
                <img 
                    class="camera-popup-image" 
                    id="camera-img-${camera.camera_id}"
                    src="${BACKEND_URL}/camera/${camera.camera_id}/image?t=${Date.now()}"
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
    `;
    
    // Create and open popup
    const popup = L.popup({
        maxWidth: 400,
        className: 'custom-camera-popup'
    })
    .setLatLng([camera.coords.lat, camera.coords.lng])
    .setContent(popupContent)
    .openOn(map);
    
    // Store reference to current popup
    state.currentCameraPopup = popup;
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

    // Test Mode
    const toggleTest = document.getElementById('toggle-test-mode');
    toggleTest.addEventListener('change', async (e) => {
        const endpoint = e.target.checked ? `${BACKEND_URL}/test-flood/enable` : `${BACKEND_URL}/test-flood/disable`;
        await fetch(endpoint, { method: 'POST' });
        await fetchFloodStatus();
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
    
    // Auto hide after 5s
    setTimeout(() => {
        // panel.classList.add('d-none'); 
        // Don't auto hide status, good to see state
    }, 5000);
}
