---
layout: page-fullwidth
title: "Sonde Listener Analysis"
footer: true
comments: true
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

<style>
  /* UpSet.js has no option to disable the vertical lines that connect the
     matrix dots within a combination, so hide them by their generated class. */
  #coverage_plot [class^="upsetLine-"] {
    display: none;
  }
</style>

<script src="https://cdn.jsdelivr.net/npm/@upsetjs/bundle@1.11.0/dist/upsetjs.umd.production.min.js" integrity="sha512-P53bOndyDaFYKoYwZA6olCphZAMuLSpvoOd4IWqsLJmB9EOoitPiMixW4z8vjl1aMup5gD7V/oOb8j+4vhdtKg==" crossorigin="anonymous"></script>

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

  // Number of combination classes (bars) shown per page.
  let PAGE_SIZE = 40;

  // Remembered so we can re-render the plot at the new width on window resize.
  let lastCoverage = null;
  // Which page of combination classes is currently shown, plus the data needed
  // to redraw it when paging or resizing.
  let currentPage = 0;
  let pageState = null;

  function renderCoverage(coverage, container) {
    // Reset to the first page when a brand-new dataset is rendered (resize
    // re-renders pass the same coverage object, and should keep the page).
    if (coverage !== lastCoverage) {
      currentPage = 0;
    }
    lastCoverage = coverage;

    if (!coverage || Object.keys(coverage).length === 0) {
      container.innerHTML = '<p>No coverage data available.</p>';
      return;
    }

    // The backend gives us, for each exact combination of listeners, the
    // number of points (frames) that exactly that set of listeners heard.
    // Reconstruct synthetic "point" elements so UpSet.js can derive the sets
    // and their intersections.
    let elems = [];
    let id = 0;
    for (let [listeners, count] of Object.entries(coverage)) {
      let sets = listeners.split(',');
      for (let i = 0; i < count; i++) {
        elems.push({ name: 'p' + (id++), sets: sets });
      }
    }

    // Sort the combinations (x-axis) and the rows (listeners) by number of
    // points heard, descending.
    let extracted = UpSetJS.extractCombinations(elems, {
      combinationOrder: 'cardinality',
      setOrder: 'cardinality:asc',
    });

    // Give each listener its own color (tints its set bar and matrix dots).
    let palette = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f'];
    extracted.sets.forEach((s, i) => {
      s.color = palette[i % palette.length];
    });

    let width = container.clientWidth || 800;
    let height = Math.max(350, 250 + extracted.sets.length * 25);

    // Too many combination classes are unreadable in a single chart. Stash the
    // (sorted) combinations and render one page at a time, with next/prev
    // buttons to flip through the tail. All pages share the same sorted rows.
    pageState = {
      sets: extracted.sets,
      combos: extracted.combinations,
      container: container,
      width: width,
      height: height,
    };
    renderPage();
  }

  function renderPage() {
    if (!pageState) return;

    let combos = pageState.combos;
    let container = pageState.container;
    let totalPages = Math.max(1, Math.ceil(combos.length / PAGE_SIZE));
    if (currentPage < 0) currentPage = 0;
    if (currentPage > totalPages - 1) currentPage = totalPages - 1;

    container.innerHTML = '';

    let chart = document.createElement('div');
    container.appendChild(chart);

    // Paging controls below the plot, centered (only needed when there's more
    // than one page).
    if (totalPages > 1) {
      let nav = document.createElement('div');
      nav.style.margin = '10px 0';
      nav.style.textAlign = 'center';

      let prev = document.createElement('button');
      prev.type = 'button';
      prev.className = 'button tiny';
      prev.textContent = '← Prev';
      prev.disabled = currentPage === 0;
      prev.onclick = function () {
        currentPage--;
        renderPage();
      };

      let label = document.createElement('span');
      label.style.margin = '0 12px';
      label.textContent =
        'Combination classes page ' + (currentPage + 1) + ' of ' + totalPages;

      let next = document.createElement('button');
      next.type = 'button';
      next.className = 'button tiny';
      next.textContent = 'Next →';
      next.disabled = currentPage >= totalPages - 1;
      next.onclick = function () {
        currentPage++;
        renderPage();
      };

      nav.appendChild(prev);
      nav.appendChild(label);
      nav.appendChild(next);
      container.appendChild(nav);
    }

    let start = currentPage * PAGE_SIZE;
    UpSetJS.render(chart, {
      sets: pageState.sets,
      combinations: combos.slice(start, start + PAGE_SIZE),
      width: pageState.width,
      height: pageState.height,
      setName: 'Points heard',
      combinationName: 'Points heard by listeners',
      color: '#5a4fcf',
      selectionColor: '#e15759',
      hasSelectionOpacity: 0.4,
      // Shrink the set-size bar chart, but give the set labels enough room for
      // full callsigns.
      widthRatios: [0.1, 0.15],
    });

    // UpSet.js draws the per-bar count labels horizontally, so with many
    // combinations they overlap. Rotate them to vertical after render.
    requestAnimationFrame(function () {
      let labels = container.querySelectorAll('text[class^="cBarTextStyle-"]');
      labels.forEach(function (label) {
        let bb = label.getBBox();
        let cx = bb.x + bb.width / 2;
        let cy = bb.y + bb.height / 2;
        // Rotate to vertical, then shift up so the (now vertical) label sits
        // fully above the bar it labels instead of overlapping it.
        let lift = bb.width / 2 + 4;
        label.setAttribute(
          'transform',
          'translate(0,' + -lift + ') rotate(-90 ' + cx + ' ' + cy + ')'
        );
      });
    });
  }

  function analyze() {
    let serial = $('#serial_input_box').val().trim();
    if (!serial) {
      $('#result_area').html('<div class="alert alert-warning">Please enter a sonde serial number.</div>');
      return false;
    }

    var l = Ladda.create($('#analyze_button')[0]);
    l.start();
    $('#result_area').html('');

    SondeSearchAPI.get('get_sonde_listeners/' + serial)
      .then(function(data) {
        l.stop();

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
        html += '<h3>Number of Points Heard By:</h3>';
        html += '<div id="coverage_plot" style="margin-top: 15px;"></div>';

        $('#result_area').html(html);

        renderCoverage(data.coverage, document.getElementById('coverage_plot'));
      })
      .catch(function(error) {
        l.stop();
        $('#result_area').html(`<div class="alert alert-danger">Request failed: ${error.message}</div>`);
      });

    return false;
  }

  // UpSet.js renders at a fixed pixel width, so re-render it when the window
  // resizes (debounced).
  let resizeTimer = null;
  window.addEventListener('resize', function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      let container = document.getElementById('coverage_plot');
      if (container && lastCoverage) {
        renderCoverage(lastCoverage, container);
      }
    }, 150);
  });
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
