---
layout: page-fullwidth
title: "Sonde Listener Analysis"
footer: true
---

This tool analyzes which sonde listening stations were able to hear a
particular radiosonde during its flight. This is useful for comparing
the efficacy of receivers in different locations. It provides statistics
including:

- Which listeners heard the sonde
- Frame ranges and coverage percentages for each listener
- First and last altitude and vertical velocity for each listener
- How many listeners heard each transmission point

To see the analysis, enter a sonde serial number and click "Analyze".

<script src="/assets/js/sondesearch-api.js"></script>
<script>

  function formatTable(stats) {
    if (!stats || stats.length === 0) {
      return '<p>No listener data available.</p>';
    }

    let html = '<table class="table table-striped"><thead><tr>';
    html += '<th>Listener</th>';
    html += '<th>First Frame</th>';
    html += '<th>Last Frame</th>';
    html += '<th>Count</th>';
    html += '<th>Coverage %</th>';
    html += '<th>First Time</th>';
    html += '<th>Last Time</th>';
    html += '<th>First Alt (m)</th>';
    html += '<th>Last Alt (m)</th>';
    html += '<th>First Vel V (m/s)</th>';
    html += '<th>Last Vel V (m/s)</th>';
    html += '</tr></thead><tbody>';

    for (let row of stats) {
      html += '<tr>';
      html += `<td><strong>${row.uploader_callsign}</strong></td>`;
      html += `<td>${row.frame_first}</td>`;
      html += `<td>${row.frame_last}</td>`;
      html += `<td>${row.frame_count}</td>`;
      html += `<td>${row['cov%']}</td>`;
      html += `<td>${row.time_first}</td>`;
      html += `<td>${row.time_last}</td>`;
      html += `<td>${row.alt_first}</td>`;
      html += `<td>${row.alt_last}</td>`;
      html += `<td>${row.vel_v_first}</td>`;
      html += `<td>${row.vel_v_last}</td>`;
      html += '</tr>';
    }

    html += '</tbody></table>';
    return html;
  }

  function formatCoverage(coverage) {
    if (!coverage || Object.keys(coverage).length === 0) {
      return '';
    }

    let html = '<h3>Number of Points Heard By:</h3>';
    html += '<table class="table table-sm"><thead><tr>';
    html += '<th>Listeners</th><th>Points</th>';
    html += '</tr></thead><tbody>';

    // Sort by count (descending)
    let entries = Object.entries(coverage).sort((a, b) => b[1] - a[1]);

    for (let [listeners, count] of entries) {
      html += '<tr>';
      html += `<td>${listeners}</td>`;
      html += `<td>${count}</td>`;
      html += '</tr>';
    }

    html += '</tbody></table>';
    return html;
  }

  function analyze() {
    let serial = $('#serial_input_box').val().trim();
    if (!serial) {
      $('#result_area').html('<div class="alert alert-warning">Please enter a sonde serial number.</div>');
      return false;
    }

    $('#result_area').html('<div class="text-center"><img src="/images/loading.gif" /></div>');

    SondeSearchAPI.get('get_sonde_listeners/' + serial)
      .then(function(data) {
        if (!data.success) {
          $('#result_area').html(`<div class="alert alert-danger">Error: ${data.error}</div>`);
          return;
        }

        let html = '';

        if (data.warning) {
          html += `<div class="alert alert-warning">${data.warning}</div>`;
        }

        html += '<h2>Listener Statistics</h2>';
        html += formatTable(data.stats);
        html += formatCoverage(data.coverage);

        $('#result_area').html(html);
      })
      .catch(function(error) {
        $('#result_area').html(`<div class="alert alert-danger">Request failed: ${error.message}</div>`);
      });

    return false;
  }
</script>

<div class="form-group" style="clear:both">
  <form onsubmit="return analyze()">
    <label style="margin-top: 30px" for="serial_input_box" required="required">Sonde Serial Number</label>
    <input type="text" required class="form-control" name="serial_input_box" id="serial_input_box" placeholder="Example: V1854526">
    <button type="submit" id="analyze_button" class="ladda-button" data-style="slide-right">Analyze</button>
  </form>
</div>

<div id="result_area" style="margin-top: 30px">
</div>
