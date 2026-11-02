const statusFilter = document.querySelector("#statusFilter");
const reportCards = [...document.querySelectorAll(".report-card")];
const emptyFilter = document.querySelector("#emptyFilter");

statusFilter?.addEventListener("change", () => {
  const selectedStatus = statusFilter.value;
  let visibleCount = 0;
  for (const card of reportCards) {
    const visible = selectedStatus === "all" || card.dataset.status === selectedStatus;
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  }
  emptyFilter.hidden = visibleCount > 0;
});

const mapConfigElement = document.querySelector("#map-config");
const latitudeInput = document.querySelector("#latitude");
const longitudeInput = document.querySelector("#longitude");
const mapNotice = document.querySelector("#mapNotice");
const locateButton = document.querySelector("#locateButton");
const reportForm = document.querySelector("#reportForm");
const mapConfig = mapConfigElement ? JSON.parse(mapConfigElement.textContent) : null;
const defaultCampusCenter = { lat: 15.0286, lng: 120.6898 };
let map;
let selectedMarker;

function setSelectedLocation(location) {
  latitudeInput.value = location.lat.toFixed(6);
  longitudeInput.value = location.lng.toFixed(6);
  if (selectedMarker) {
    selectedMarker.setLatLng(location);
  } else {
    selectedMarker = L.marker(location, {
      draggable: true,
      title: "Selected problem location",
    }).addTo(map);
    selectedMarker.on("dragend", () => {
      const markerLocation = selectedMarker.getLatLng();
      latitudeInput.value = markerLocation.lat.toFixed(6);
      longitudeInput.value = markerLocation.lng.toFixed(6);
    });
  }
}

function initializeMap() {
  const campusCenter = mapConfig.campusCenter || defaultCampusCenter;
  let center = campusCenter;
  let zoom = 16;
  if (mapConfig.reports.length && !mapConfig.campusCenter) {
    const firstReport = mapConfig.reports[0];
    center = { lat: firstReport.latitude, lng: firstReport.longitude };
    zoom = 15;
  }

  map = L.map("map").setView([center.lat, center.lng], zoom);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  map.on("click", (event) => setSelectedLocation(event.latlng));

  for (const report of mapConfig.reports) {
    L.marker([report.latitude, report.longitude], {
      title: `${report.title} — ${report.status}`,
    })
      .addTo(map)
      .bindPopup(
        `<strong>${escapeHtml(report.title)}</strong><br>${escapeHtml(report.category)} · ${escapeHtml(report.status)}`,
      );
  }

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!mapConfig.campusCenter && !mapConfig.reports.length) {
          map.setView(
            [position.coords.latitude, position.coords.longitude],
            16,
          );
        }
      },
      () => {},
      { maximumAge: 300000, timeout: 5000 },
    );
  }
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

if (mapConfig && window.L) {
  initializeMap();
} else if (mapConfigElement) {
  mapNotice.textContent = "The map could not load. Reload the page or try again later to select a location.";
  mapNotice.classList.add("map-notice-warning");
}

reportForm?.addEventListener("submit", (event) => {
  if (!latitudeInput.value || !longitudeInput.value) {
    event.preventDefault();
    mapNotice.textContent = "Select a location on the map before submitting your report.";
    mapNotice.classList.add("map-notice-warning");
  }
});

locateButton?.addEventListener("click", () => {
  if (!navigator.geolocation) {
    mapNotice.textContent = "Location services are not available in this browser.";
    return;
  }
  if (!map) {
    mapNotice.textContent = "The map is unavailable. Reload the page or try again later to select a location.";
    return;
  }
  locateButton.disabled = true;
  navigator.geolocation.getCurrentPosition(
    (position) => {
      const location = L.latLng(
        position.coords.latitude,
        position.coords.longitude,
      );
      map.setView(location, 18);
      setSelectedLocation(location);
      locateButton.disabled = false;
    },
    () => {
      mapNotice.textContent = "Could not access your location. Allow location access or click the map instead.";
      locateButton.disabled = false;
    },
    { enableHighAccuracy: true, timeout: 10000 },
  );
});

for (const input of [latitudeInput, longitudeInput]) {
  input?.addEventListener("change", () => {
    const latitude = Number(latitudeInput.value);
    const longitude = Number(longitudeInput.value);
    if (
      Number.isFinite(latitude)
      && Number.isFinite(longitude)
      && Math.abs(latitude) <= 90
      && Math.abs(longitude) <= 180
      && map
    ) {
      const location = L.latLng(latitude, longitude);
      map.setView(location, 18);
      setSelectedLocation(location);
    }
  });
}
