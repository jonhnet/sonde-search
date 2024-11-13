---
layout: default
skip_nav: true
---

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>

<div id="map" style="width: auto; height: 600px;"></div>
<script>
    const searchParams = new URLSearchParams(window.location.search);
	const lat = parseFloat(searchParams.get('lat'));
	const lon = parseFloat(searchParams.get('lon'));
	const r = parseFloat(searchParams.get('r'));
	const map = L.map('map').setView([lat, lon]);
	var circle = L.circle([lat, lon], {
		color: 'red',
		radius: r,
		opacity: 0.4,
	}).addTo(map);
	map.fitBounds(circle.getBounds());
	const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
		maxZoom: 19,
		attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
	}).addTo(map);
</script>