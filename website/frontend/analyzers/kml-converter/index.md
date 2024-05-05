---
layout: page-fullwidth
title: "Sonde Data KML Converter"
footer: true
---

This is a simple service that converts a sonde's flight data intl the
[KML](https://en.wikipedia.org/wiki/Keyhole_Markup_Language) format, allowing
you to visualize a flight using a tool like [Google
Earth](https://earth.google.com), as in the example screenshot.

Just type the serial number of a sonde into the form and click "Download".

<script>
  //let base_url = 'http://home.circlemud.org:8080/';
  let base_url = 'https://api.sondesearch.lectrobox.com/api/v1/';

  function download() {
    let serial = $('#serial_input_box').val();
    window.open(base_url + 'get_sonde_kml/' + serial);
    return false;
  }
</script>

<div class="form-group">
  <form onsubmit="return download()">
    <label style="margin-top: 30px" for="serial_input_box" required="required">Sonde Serial Number</label>
    <input type="text" required class="form-control" name="serial_input_box" id="serial_input_box" placeholder="Example: V1854526">
    <div id="form_result" style="visibility: hidden">Form not submitted</div>
    <button type="submit" id="download_button" class="ladda-button" data-style="slide-right">Download</button>
  </form>
</div>
