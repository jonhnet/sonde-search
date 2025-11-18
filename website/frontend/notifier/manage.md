---
layout: page
title: "Sonde Email Notifier — Manage"
---
<style>
    table.subs .trash:not([data-loading]) {
        background-color: transparent;
    }
    table.subs .trash {
        margin: 0;
    }
    table.subs td {
        padding: 4px;
        vertical-align: middle;
    }
</style>
<div id="loading" class="row t30 text-center">
    <img src="/images/loading.gif" />
</div>

<div id="config_error" hidden>
    We're sorry, the notifier management service seems to be having a problem.
    Please try <a href="../signup/">signing up again</a>, or <a
    href="https://www.lectrobox.com/contact/">let us know</a> that it's broken.
</div>

<div id="management_state" hidden>
    <p>
    Managing notifications for
    <tt><span id="state_email">unknown</span></tt>
    <a href="../signup/">(Change)</a>
    </p>

    <p id="no_subs" hidden>
    You currently have no notifications configured. Click below to add one.
    </p>

    <div id="sub_table_div" class="text-center">
    </div>

    <button class="button" onclick="start_subscribe()">Add New Notification</button>
</div>

<div id="history" hidden>
    <h3> Recent Notifications </h3>

    <table id="history_table">
        <tr>
            <th>Sonde Last Heard</th>
            <th>Dist from Home</th>
            <th>Sonde ID</th>
            <th>Map</th>
        </tr>
    </table>
</div>

<!--- https://get.foundation/sites/docs-v5/components/forms.html --->
<div class="reveal-modal" id="add-subscription" data-reveal aria-labelledby="modalTitle" aria-hidden="true" role="dialog">
    <h2 id="subscribe_title"></h2>
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

        <div class="row t20 collapse">
            <label>
                Maximum Distance
            </label>

            <div class="small-6 columns">
                <input type="number" required="true" min="0" max="5000" step="0.1" id="subscribe_maxdist"/>
            </div>

            <div class="small-6 columns">
                <select id="subscribe_units">
                    <option value="imperial">Miles</option>
                    <option value="metric"  >Kilometers</option>
                </select>
            </div>
        </div>

        <div class="row collapse">
            <label>
                Home Latitude
            </label>

            <div class="small-6 columns">
                <input type="number" required="true" min="0" max="90" step="any" id="subscribe_lat" />
            </div>

            <div class="small-6 columns">
                <select id="subscribe_lat_sign">
                    <option value="north">North</option>
                    <option value="south">South</option>
                </select>
            </div>
        </div>

        <div class="row collapse">
            <label>
                Home Longitude
            </label>

            <div class="small-6 columns">
                <input type="number" required="true" min="0" max="180" step="any" id="subscribe_lon" />
            </div>

            <div class="small-6 columns">
                <select id="subscribe_lon_sign">
                    <option value="east">East</option>
                    <option value="west">West</option>
                </select>
            </div>
        </div>

        <div class="row">
            <div class="large-12 columns">
                <button class="button" type="button" data-style="slide-right"
                class="button" style="float: left"
                onclick="cancel_subscribe();">
                 Cancel
             </button>
             <button class="button" type="submit" data-style="slide-right"
                 id="subscribe_button" class="button success" style="float: right">
             </button>
            </div>
        </div>

        <div class="row">
            <div class="large-12 columns" id="subscribe_result" style="visibility: hidden">
            </div>
        </div>
    </form>
    <a class="close-reveal-modal" aria-label="Close">&#215;</a>
</div>

<script src="/assets/js/sondesearch-api.js"></script>
<script>

var tzname = null;
var units = null;
var editing_uuid = null;

const KM_PER_MILE = 1.609344;

function km_to_mi(km) {
    return km / KM_PER_MILE;
}

function mi_to_km(mi) {
    return mi * KM_PER_MILE;
}

function m_to_mi(m) {
    return km_to_mi(m / 1000);
}

function mi_to_m(mi) {
    return mi_to_km(mi) * 1000;
}

function miles_to_desired_units(dist_mi) {
    let dist = dist_mi;
    if (units == 'metric') {
        dist = mi_to_km(dist_mi);
    }
    return Math.round(10*dist)/10;
}

function render_distance_miles(dist_mi) {
    let dist = miles_to_desired_units(dist_mi);
    if (units == 'metric') {
        dist_unit = ' km';
    } else {
        dist_unit = ' mi';
    }
    return '' + dist + dist_unit;
}

function config_error() {
    $('#config_error').attr('hidden', false);
    $('#loading').attr('hidden', true);
}

function process_config(config) {
    email = config['email'];
    tzname = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const prefs = config['prefs'] || {};
    set_units(prefs['units'] || 'imperial');

    $('#state_email').html(email);
    $('#subscribe_email').html(email);
    $('#subscribe_tzname').html(tzname);

    // construct the table
    let table = $('<table class="subs">');
    let headers = $('<tr>');
    let num_subs = 0;
    headers.append($('<th>').text('Home Lat'));
    headers.append($('<th>').text('Home Lon'));
    headers.append($('<th>').text('Max Dist'));
    headers.append($('<th>').text('Edit'));
    headers.append($('<th>').text('Delete'));
    headers.append($('<th>').text('Map'));
    table.append(headers);

    $.each(config['subs'] || [], function() {
        num_subs += 1;
        let row = $('<tr>');
        row.append($('<td class="text-right">').text(this['lat']));
        row.append($('<td class="text-right">').text(this['lon']));
        row.append($('<td class="text-right">').text(render_distance_miles(this['max_distance_mi'])));

        // edit
        let edit_button = $('<button class="trash" style="padding: 0;">');
        edit_button.append($('<img src="/images/edit.png" width="20" />'));
        let sub = this;
        edit_button.click(function() { start_edit(sub); });
        row.append($('<td class="text-center">').html(edit_button));

        // delete
        let del_outer_button = $('<button class="ladda-button trash" data-style="slide-right" data-size="xs">');
        let del_inner_button = del_outer_button.append($('<img src="/images/trash.png" width="20" />'));
        let uuid = this['uuid'];
        del_inner_button.click(function() { unsubscribe(del_outer_button, uuid); });
        row.append($('<td class="text-center">').html(del_outer_button));

        // map
        let link = "../map/?lat=" + this['lat'];
        link += "&lon=" + this['lon'];
        link += "&r=" + mi_to_m(this['max_distance_mi']);
        let map_inner_button = $('<img src="/images/map-color.png" width="32" style="cursor: pointer"/>');
        map_inner_button.click(function() { window.open(link, 'Notification Area', 'width=600,height=600')})
        row.append($('<td class="text-center">').html(map_inner_button));

        table.append(row);
    });

    if (num_subs == 0) {
        $('#no_subs').attr('hidden', false);
        $('#sub_table_div').attr('hidden', true);
    } else {
        $('#no_subs').attr('hidden', true);
        $('#sub_table_div').html(table);
        $('#sub_table_div').attr('hidden', false);
    }
    $('#management_state').attr('hidden', false);
    $('#loading').attr('hidden', true);
}

function set_units(units_arg) {
    units = units_arg;
    $('#subscribe_units').val(units);
}

function convert_maxdist_field(from_units, to_units) {
    const maxdist_field = $('#subscribe_maxdist');
    const current_value = parseFloat(maxdist_field.val());

    // Only convert if there's a valid number in the field
    if (isNaN(current_value) || current_value === '') {
        return;
    }

    let new_value = current_value;
    if (from_units === 'imperial' && to_units === 'metric') {
        // Converting from miles to kilometers
        new_value = mi_to_km(current_value);
    } else if (from_units === 'metric' && to_units === 'imperial') {
        // Converting from kilometers to miles
        new_value = km_to_mi(current_value);
    }

    // Round to 1 decimal place and update field
    maxdist_field.val(Math.round(10 * new_value) / 10);
}

// Called when we've successfully retrieved the notification history
function process_history(history) {
    if (history == null || history.length == 0) {
        return;
    }

    // sort history by time of sonde landing, most recent first
    history.sort(function(a, b) { return b['sonde_last_heard'] - a['sonde_last_heard']});

    // add each history entry to the table
    $.each(history, function() {
        if (this['sonde_last_heard'] == null) {
            return;
        }
        let row = $('<tr>');
        let date = new Date(this['sonde_last_heard'] * 1000);
        row.append($('<td class="text-right">').text(date.toLocaleString()));
        let dist = render_distance_miles(m_to_mi(this['dist_from_home_m']));
        row.append($('<td class="text-right">').text(dist));
        let serial = this['serial'];
        let url = `https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f=${serial}&q=${serial}`;
        row.append($('<td class="text-right">').html($('<a>',{
            text: serial,
            href: url,
        })));
        row.append($('<td class="text-right">').html($('<a>',{
            text: 'Map',
            href: this['map_url'],
        })));
        $('#history_table').append(row);
    });

    $('#history').attr('hidden', false);
}

async function get_state() {
    // Backcompat for old links: send over to the verify page
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.has('user_token')) {
        window.location.href = window.location.origin + window.location.pathname + '../verify/' + window.location.search;
        return;
    }

    // If there's been no authorization, redirect to the signup page
{% if site.dev_mode == 1 %}
    const user_token = Cookies.get('notifier_user_token_v2');
{% else %}
    const user_token = Cookies.get('notifier_user_token_v2', {
        domain: '.sondesearch.lectrobox.com',
    });
{% endif %}

    if (user_token == null) {
        //$('#result').html('no auth');
        window.location.href = window.location + '../signup';
    }

    try {
        // Fetch both the config and the history in parallel
        let config_req = SondeSearchAPI.get('get_config', {
            credentials: 'include',
        })
        let history_req = SondeSearchAPI.get('get_notification_history', {
            credentials: 'include',
        })

        let config = await config_req;
        let history = await history_req;

        process_config(config);
        process_history(history);
    } catch (error) {
        config_error();
    }
}

function start_subscribe() {
    $('#subscribe_title').text('Add New Notification');
    $('#subscribe_button').html('Subscribe');
    $('#subscribe_lat').val(null);
    $('#subscribe_lon').val(null);
    $('#subscribe_lat_sign').val('north');
    $('#subscribe_lon_sign').val('west');
    $('#subscribe_maxdist').val(100);

    editing_uuid = null;
    $('#add-subscription').foundation('reveal', 'open');
}

function start_edit(sub) {
    $('#subscribe_title').text('Edit Notification');
    $('#subscribe_button').html('Update');

    let lat = sub['lat'];
    if (lat < 0) {
        $('#subscribe_lat').val(-lat);
        $('#subscribe_lat_sign').val('south');
    } else {
        $('#subscribe_lat').val(lat);
        $('#subscribe_lat_sign').val('north');
    }

    let lon = sub['lon'];
    if (lon < 0) {
        $('#subscribe_lon').val(-lon);
        $('#subscribe_lon_sign').val('west');
    } else {
        $('#subscribe_lon').val(lon);
        $('#subscribe_lon_sign').val('east');
    }

    $('#subscribe_maxdist').val(miles_to_desired_units(sub['max_distance_mi']));
    $('#add-subscription').foundation('reveal', 'open');
    editing_uuid = sub['uuid'];
}

function cancel_subscribe() {
    $('#add-subscription').foundation('reveal', 'close');
    return false;
}

function subscribe() {
    let button = $('#subscribe_button');
    var l = Ladda.create(button[0]);
    l.start();
    set_units($('#subscribe_units').val());
    var dist = $('#subscribe_maxdist').val();
    if (units == 'metric') {
        dist = km_to_mi(dist);
    }

    // get lat and lon with hemispheres
    let lat = $('#subscribe_lat').val();
    if ($('#subscribe_lat_sign').val() == 'south') {
        lat = -lat;
    }
    let lon = $('#subscribe_lon').val();
    if ($('#subscribe_lon_sign').val() == 'west') {
        lon = -lon;
    }

    sub_data = {
        'units': units,
        'tzname': tzname,
        'lat': lat,
        'lon': lon,
        'max_distance_mi': dist,
    }
    if (editing_uuid != null) {
        sub_data['replace_uuid'] = editing_uuid;
    }

    SondeSearchAPI.ajax({
        method: 'POST',
        endpoint: 'subscribe',
        xhrFields: {
            withCredentials: true,
        },
        data: sub_data,
        success: function(result) {
            l.stop();
            process_config(result);
            cancel_subscribe();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            l.stop();
            $('#subscribe_result').html("<p>We're sorry—there was an error trying to sign up. Please try again.</p><p>Error: <tt>" + jqXHR.responseText + "</tt></p>");
            $('#subscribe_result').css("visibility", "visible");
        }
    });

    // return false to prevent form from navigating away to a new page
    return false;
}

function unsubscribe(del_icon, uuid) {
    var l = Ladda.create(del_icon[0]);
    l.start();

    SondeSearchAPI.ajax({
        method: 'POST',
        endpoint: 'managed_unsubscribe',
        xhrFields: {
            withCredentials: true,
        },
        data: {
            'uuid': uuid,
        },
        success: function(result) {
            process_config(result);
        },
        error: function(jqXHR, textStatus, errorThrown) {
            l.stop();
            alert("Couldn't delete notification! Please try again later.");
        }
    });

    // return false to prevent form from navigating away to a new page
    return false;
}

function OnLoadTrigger() {
    // Set up event handler for unit conversion when dropdown changes
    $('#subscribe_units').on('change', function() {
        const old_units = units;
        const new_units = $(this).val();
        convert_maxdist_field(old_units, new_units);
        set_units(new_units);
    });

    get_state();
}

</script>
