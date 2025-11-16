---
layout: page-fullwidth
title: "Sonde Data KML Converter"
footer: true
---

{% include right-image.html
   image="kml-example.webp"
   caption="An example screenshot of Google Earth showing sonde V1854526"
%}

This is a simple service that converts a sonde's flight data, as acquired by
SondeHub, into the [KML](https://en.wikipedia.org/wiki/Keyhole_Markup_Language)
format, allowing you to visualize a flight using a tool like [Google
Earth](https://earth.google.com), as in the example screenshot.

Just type the serial number of a sonde into the form and click "Download".
Flight data will be downloaded from SondeHub automatically and converted to a
KML file. Check your browser's "downloads" folder to see the KML file.

<script src="/assets/js/sondesearch-api.js"></script>
<script>
  function download() {
    let serial = $('#serial_input_box').val();
    window.open(SondeSearchAPI.buildUrl('get_sonde_kml/' + serial));
    return false;
  }
</script>

<div class="form-group" style="clear:both">
  <form onsubmit="return download()">
    <label style="margin-top: 30px" for="serial_input_box" required="required">Sonde Serial Number</label>
    <input type="text" required class="form-control" name="serial_input_box" id="serial_input_box" placeholder="Example: V1854526">
    <div id="form_result" style="visibility: hidden">Form not submitted</div>
    <button type="submit" id="download_button" class="ladda-button" data-style="slide-right">Download</button>
  </form>
</div>
