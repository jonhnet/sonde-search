---
layout: page-fullwidth
title: "Sonde Email Notifier — Manage"
---

<div id='result'>
    Nothing here yet
</div>

<div class="reveal-modal" id="add-subscription" data-reveal aria-labelledby="modalTitle" aria-hidden="true" role="dialog">
  <h2> Configure New Notification </h2>
    <form onsubmit="return subscribe()">
     <div class="row t10">
       <div class="large-6 columns">
         <label>Notification address</label>
	 <tt><span id="subscribe_email">unknown</span></tt>
	 <a href="../signup/">(Change)</a>
       </div>
       <div class="large-6 columns">
         <label>Time Zone</label>
	 <tt><span id="subscribe_tzname">unknown</span></tt>
       </div>
    </div>

    <div class="row t10">
      <div class="large-6 columns">
	<label>Desired Units</label>
        <input type="radio" name="units" onclick="set_units('imperial')" id="unit_imperial"><label for="unit_imperial">Imperial (feet, miles)</label>
        <input type="radio" name="units" onclick="set_units('metric')" id="unit_metric"><label for="unit_metric">Metric (meters, km)</label>
      </div>
    </div>

    <div class="row">
      <div class="large-4 columns">
	<label>Home Latitude (Decimal Degrees)
        <input type="number" required="true" min="-90" max="90" step="any" id="subscribe_lat" />
	</label>
      </div>
      <div class="large-4 columns">
	<label>Home Longitude (Decimal Degrees)
        <input type="number" required="true" min="-180" max="180" step="any" id="subscribe_lon" />
	</label>
      </div>

      <div class="large-4 columns">
	<div class="row collapse">
	  <label>Maximum Distance</label>
	  <div class="small-9 columns">
	    <input type="number" required="true" value="100" min="0" max="5000" id="subscribe_maxdist"/>
	  </div>
	  <div class="small-3 columns">
	    <span class="postfix" id="maxdist_unit">miles</span>
	  </div>
	</div>
      </div>
    </div>

    <div class="row">
      <div class="large-12 columns">
	<button class="button" id="subscribe_button">Add</button>
      </div>
    </div>

    <div class="row">
      <div class="large-12 columns" id="subscribe_result" style="visibility: hidden">
      </div>
    </div>

  </form>
</div>

<button class="button" data-reveal-id="add-subscription">Add New Notification</button>


<script>
let base_url = "https://api.sondesearch.lectrobox.com/api/v1/";
var tzname = null;
var units = null;

function km_to_mi(km) {
    return km / 1.60934;
}

function mi_to_km(mi) {
    return mi * 1.60934;
}

function process_config(config) {
    email = config['email'];
    tzname = Intl.DateTimeFormat().resolvedOptions().timeZone;
    var prefs = {}
    if ('prefs' in config) {
	prefs = config['prefs'];
    }
    if ('units' in prefs) {
	set_units(prefs['units']);
    } else {
	set_units('imperial');
    }

    $('#subscribe_email').html(email);
    $('#subscribe_tzname').html(tzname);
}

function set_units(units_arg) {
    units = units_arg;
    if (units == 'metric') {
	$('#maxdist_unit').html('km');
	$('#unit_metric').prop('checked', true);
    } else {
	$('#maxdist_unit').html('miles');
	$('#unit_imperial').prop('checked', true);
    }
}

function get_config() {
    // If an auth token was provided in the URL, convert it into a cookie
    let searchParams = new URLSearchParams(window.location.search);
    if (searchParams.has('user_token')) {
        Cookies.set('notifier_user_token', searchParams.get('user_token'));
    }

    // If there's been no authorization, redirect to the signup page
    let user_token = Cookies.get('notifier_user_token');
    if (user_token == null) {
        //$('#result').html('no auth');
        window.location.href = window.location.origin + '/notifier/signup';
    }

    $.ajax({
        type: 'GET',
        url: base_url + 'get_config',
	data: {
	    'user_token': user_token,
	},
        success: function(result) {
            process_config(result);
        },
        error: function() {
        }
    });
}

function subscribe() {
    let button = $('#subscribe_button');
    var l = Ladda.create(button[0]);
    l.start();
    let user_token = Cookies.get('notifier_user_token');
    var dist = $('#subscribe_maxdist').val();
    if (units == 'metric') {
	dist = km_to_mi(dist);
    }

    $.ajax({
        method: 'POST',
        url: base_url + 'subscribe',
	data: {
	    'user_token': user_token,
	    'units': units,
	    'tzname': tzname,
	    'lat': $('#subscribe_lat').val(),
	    'lon': $('#subscribe_lon').val(),
	    'max_distance_mi': dist,
	},
        success: function(result) {
            l.stop();
            process_config(result);
        },
        error: function(jqXHR, textStatus, errorThrown) {
            l.stop();
            $('#subscribe_result').html("<p>We're sorry -- there was an error trying to sign up. Please try again.</p><p>Error: <tt>" + jqXHR.responseText + "</tt></p>");
            $('#subscribe_result').css("visibility", "visible");
        }
    });

    // return false to prevent form from navigating away to a new page
    return false;
}


function OnLoadTrigger() {
    get_config();
}

</script>
