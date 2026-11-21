"use strict";

const form = document.getElementById("route-form");
const submitButton = document.getElementById("submit-button");
const statusMessage = document.getElementById("status");
const results = document.getElementById("route-results");
const directionsList = document.getElementById("directions-list");
const speakButton = document.getElementById("speak-all");
const stopButton = document.getElementById("stop-speech");
let map;
let routeLayer;

function showStatus(message, type) {
  statusMessage.textContent = message;
  statusMessage.className = `status ${type}`;
  statusMessage.hidden = false;
}

function clearStatus() {
  statusMessage.textContent = "";
  statusMessage.hidden = true;
  statusMessage.className = "status";
}

function formatDuration(minutes) {
  if (minutes < 1) return "Less than 1 min";
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (remainingMinutes === 0) return `${hours} hr`;
  return `${hours} hr ${remainingMinutes} min`;
}

function initializeMap() {
  if (map || !window.L) return;
  map = L.map("map", { scrollWheelZoom: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
  }).addTo(map);
  map.fitBounds([[6, 68], [38, 98]], { padding: [14, 14] });
}

function renderRoute(route) {
  initializeMap();
  if (!map) {
    throw new Error("The map could not be loaded. Check your connection and try again.");
  }
  if (routeLayer) map.removeLayer(routeLayer);
  routeLayer = L.geoJSON(
    { type: "LineString", coordinates: route.geometry },
    { style: { color: "#187b5a", weight: 6, opacity: 0.9, lineCap: "round", lineJoin: "round" } },
  ).addTo(map);
  const points = [
    [route.origin.lat, route.origin.lon],
    [route.destination.lat, route.destination.lon],
  ];
  L.circleMarker(points[0], {
    radius: 7, color: "#ffffff", weight: 3, fillColor: "#187b5a", fillOpacity: 1,
  }).addTo(routeLayer).bindPopup("Starting point");
  L.circleMarker(points[1], {
    radius: 7, color: "#ffffff", weight: 3, fillColor: "#db8456", fillOpacity: 1,
  }).addTo(routeLayer).bindPopup("Destination");
  map.fitBounds(routeLayer.getBounds(), { padding: [28, 28] });
  window.setTimeout(() => map.invalidateSize(), 50);
}

function renderDirections(steps) {
  directionsList.replaceChildren();
  steps.forEach((step, index) => {
    const item = document.createElement("li");
    item.className = "direction-step";

    const number = document.createElement("span");
    number.className = "step-number";
    number.setAttribute("aria-hidden", "true");
    number.textContent = String(index + 1);

    const instruction = document.createElement("span");
    instruction.className = "step-copy";
    instruction.textContent = step.instruction;

    const distance = document.createElement("span");
    distance.className = "step-distance";
    distance.textContent = step.distance_km > 0
      ? `${step.distance_km.toFixed(2)} km`
      : "";

    item.append(number, instruction, distance);
    directionsList.append(item);
  });
}

function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  speakButton.disabled = false;
  speakButton.innerHTML = "<span aria-hidden=\"true\">▶</span> Listen to directions";
  stopButton.hidden = true;
}

function speakDirections() {
  if (!("speechSynthesis" in window)) {
    showStatus("Spoken directions are not supported by this browser. You can still read the steps below.", "error");
    return;
  }
  stopSpeaking();
  const directions = Array.from(directionsList.querySelectorAll(".step-copy"))
    .map((step, index) => `Step ${index + 1}. ${step.textContent}`);
  if (!directions.length) return;
  const utterance = new SpeechSynthesisUtterance(directions.join(". "));
  utterance.rate = 0.9;
  utterance.onstart = () => {
    speakButton.disabled = true;
    speakButton.textContent = "Speaking directions…";
    stopButton.hidden = false;
  };
  utterance.onend = stopSpeaking;
  utterance.onerror = () => {
    stopSpeaking();
    showStatus("Your browser could not play spoken directions. Please read the steps below.", "error");
  };
  window.speechSynthesis.speak(utterance);
}

function displayRoute(route) {
  renderRoute(route);
  document.getElementById("distance-value").textContent = `${route.distance_km.toFixed(2)} km`;
  document.getElementById("duration-value").textContent = formatDuration(route.duration_minutes);
  document.getElementById("destination-value").textContent = route.destination.label.split(",")[0];
  renderDirections(route.steps);
  results.hidden = false;
  document.getElementById("map-title").textContent = "Your walking route";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearStatus();
  results.hidden = true;
  stopSpeaking();
  if (routeLayer && map) {
    map.removeLayer(routeLayer);
    routeLayer = null;
  }
  document.getElementById("map-title").textContent = "A clear view ahead";
  submitButton.disabled = true;
  submitButton.querySelector("span:first-child").textContent = "Finding your route…";

  const formData = new FormData(form);
  const payload = {
    origin: formData.get("origin").trim(),
    destination: formData.get("destination").trim(),
    origin_state: formData.get("origin_state"),
    destination_state: formData.get("destination_state"),
    prefer_sidewalks: formData.has("prefer_sidewalks"),
    avoid_steep_hills: formData.has("avoid_steep_hills"),
  };

  try {
    const response = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "We could not find a route. Please try again.");
    displayRoute(result);
    clearStatus();
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showStatus(error.message || "Something went wrong. Please try again.", "error");
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span:first-child").textContent = "Find my walking route";
  }
});

speakButton.addEventListener("click", speakDirections);
stopButton.addEventListener("click", stopSpeaking);
initializeMap();
