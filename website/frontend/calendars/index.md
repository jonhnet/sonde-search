---
layout: page-fullwidth
title: "Sonde Landing Calendars"
footer: true
---

<div class="lec-right-image">
  <div class="lec-captioned-image">
    <a href="https://sondesearch.lectrobox.com/vault/calendars/seattle-landings-by-month.webp">
       <img width="400" src="images/seattle-calendar-thumb.webp" />
    </a>
    <div class="caption">Seattle-area sonde landings tracked by SondeHub, plotted by month, 2021-2023</div>
  </div>
</div>

Weather patterns change with the seasons. As prevailing winds change, so do the
typical landing zones of radiosondes. To determine the best times of year for
finding sondes, I created a tool that would draw a "map calendar"---12 small
maps in a grid, one for each month of the year, showing the historical landing
locations of sondes during that month.

In my home town of Seattle, for example, sondes are hard to retrieve. The
nearest launch site is Quillayute, about 100 miles (170km) west, with the
Olympic forest in between. Sondes sometimes make it far enough east to be close
to civilization, but often land in the ocean or deep in inaccessible parts of
the Olympics.

The [Seattle-area
calendar](https://sondesearch.lectrobox.com/vault/calendars/seattle-landings-by-month.webp)
makes it clear that this effect is seasonal. From June to September, sondes
consistently land in the ocean or the forest. We can confidently plan not to
spend time sonde-hunting during the summer here! The best months seem to be
November to January.

You can view these other pre-generated example calendars:

* [Spokane, WA](https://sondesearch.lectrobox.com/vault/calendars/spokane-landings-by-month.webp)
* [Kitchener, Ontario](https://sondesearch.lectrobox.com/vault/calendars/kitchener-landings-by-month.webp)
* [Hilo, Hawaii](https://sondesearch.lectrobox.com/vault/calendars/hilo-landings-by-month.webp)
* [Madison, WI](https://sondesearch.lectrobox.com/vault/calendars/madison-landings-by-month.webp)

<br clear="all">

## Interactive Calendar Generator

Use the map below to pan and zoom to your area of interest, then click "Generate
Calendar" to create a custom landing calendar for any region in the world. If
you prefer to run the calendar-generator on your own computer, the code is
[here](https://github.com/jonhnet/sonde-search/blob/main/analyzers/landings-by-month.py).

<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>

<div style="margin-top: 30px; margin-bottom: 20px;">
  <button type="button" id="generate_button" class="ladda-button" data-style="slide-right" onclick="generateCalendar()">Generate Calendar</button>
  <span id="status_message" style="margin-left: 15px;"></span>
</div>

<div id="map" style="width: 100%; height: 600px; margin-bottom: 30px; position: relative; z-index: 1;"></div>

<div id="result_area"></div>

<script>
  // Initialize map centered on North America
  const map = L.map('map').setView([40, -100], 4);

  // Add OpenStreetMap tiles
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  function generateCalendar() {
    // Get current map bounds
    const bounds = map.getBounds();
    const southWest = bounds.getSouthWest();
    const northEast = bounds.getNorthEast();

    const bottom_lat = southWest.lat;
    const left_lon = southWest.lng;
    const top_lat = northEast.lat;
    const right_lon = northEast.lng;

    // Check if map area is too large
    const latDiff = Math.abs(top_lat - bottom_lat);
    const lonDiff = Math.abs(right_lon - left_lon);

    if (latDiff > 8 || lonDiff > 8) {
      $('#status_message').html('<span style="color: red;">Map area too large! Please zoom in. (Maximum 8 degrees of latitude or longitude)</span>');
      return;
    }

    // Start Ladda spinner on button
    let button = $('#generate_button');
    var l = Ladda.create(button[0]);
    l.start();

    // Hide map and clear previous results
    $('#map').hide();
    $('#status_message').html('');
    $('#result_area').html('');

    // Build API URL with parameters
    const url = SondeSearchAPI.buildUrl('generate_landing_calendar', {
      bottom_lat: bottom_lat,
      left_lon: left_lon,
      top_lat: top_lat,
      right_lon: right_lon
    });

    // Fetch the image
    fetch(url)
      .then(response => {
        if (!response.ok) {
          throw new Error('Failed to generate calendar: ' + response.statusText);
        }
        return response.blob();
      })
      .then(blob => {
        // Stop the spinner and hide the generate button
        l.stop();
        $('#generate_button').hide();

        // Create an object URL for the image
        const imageUrl = URL.createObjectURL(blob);

        // Display the image
        $('#result_area').html(`
          <h2>Your Custom Landing Calendar</h2>
          <p>Bounds: ${bottom_lat.toFixed(4)}, ${left_lon.toFixed(4)} to ${top_lat.toFixed(4)}, ${right_lon.toFixed(4)}</p>
          <p style="margin-bottom: 20px;">
            <a id="download_link" href="${imageUrl}" download="landing-calendar-${bottom_lat.toFixed(2)}-${left_lon.toFixed(2)}.png" class="button">Download Your Calendar Image</a>
            <button type="button" class="button" onclick="resetMap()">Generate Another Calendar</button>
          </p>
          <img src="${imageUrl}" style="width: 100%; height: auto;" alt="Landing Calendar" />
        `);

        $('#status_message').html('');
      })
      .catch(error => {
        // Stop the spinner
        l.stop();

        $('#map').show();
        $('#status_message').html('<span style="color: red;">Error: ' + error.message + '</span>');
        $('#result_area').html('');
      });
  }

  function resetMap() {
    $('#map').show();
    $('#generate_button').show();
    $('#result_area').html('');
    $('#status_message').html('');
  }
</script>
