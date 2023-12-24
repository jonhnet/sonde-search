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

        <div class="row t10">
            <div class="large-6 columns">
                <label>Desired Units</label>
                <label for="unit_imperial">
                    <input type="radio" name="units" onclick="set_units('imperial')" id="unit_imperial">
                    Imperial (feet, miles)
                </label>
                <label for="unit_metric">
                    <input type="radio" name="units" onclick="set_units('metric')" id="unit_metric">
                    Metric (meters, km)
                </label>
            </div>
        </div>

        <div class="row">
            <div class="large-12 columns t10">
                <div>Enter latitude and longitude using decimal degrees, negative for South and West.</div>
            </div>
        </div>

        <div class="row t10">
            <div class="large-4 columns">
                <label>Home Latitude
                    <input type="number" required="true" min="-90" max="90" step="any" id="subscribe_lat" />
                </label>
            </div>
            <div class="large-4 columns">
                <label>Home Longitude
                    <input type="number" required="true" min="-180" max="180" step="any" id="subscribe_lon" />
                </label>
            </div>
            <div class="large-4 columns">
                <div class="row collapse">
                    <label>Maximum Distance</label>
                    <div class="small-9 columns">
                        <input type="number" required="true" min="0" max="5000" step="0.1" id="subscribe_maxdist"/>
                    </div>
                    <div class="small-3 columns">
                        <span class="postfix" id="maxdist_unit">miles</span>
                    </div>
                </div>
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

<script>
let base_url = "https://api.sondesearch.lectrobox.com/api/v1/";
var tzname = null;
var units = null;
var editing_uuid = null;

function km_to_mi(km) {
    return km / 1.60934;
}

function mi_to_km(mi) {
    return mi * 1.60934;
}

function m_to_mi(m) {
    return m / 1609.34;
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
    var prefs = config['prefs'] || {};
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
        let del_button = $('<button class="ladda-button trash" data-style="slide-right" data-size="xs">');
        //let del_button = $('<div data-size="xs">');
        del_button.append($('<img src="/images/trash.png" width="20" />'));
        let uuid = this['uuid'];
        del_button.click(function() { unsubscribe(del_button, uuid); });
        row.append($('<td class="text-center">').html(del_button));
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
        Cookies.set('notifier_user_token', searchParams.get('user_token'), { expires: 365 });
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
            config_error();
        }
    });
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

function get_history() {
    $.ajax({
        type: 'GET',
        url: base_url + 'get_notification_history',
        data: {
            'user_token': Cookies.get('notifier_user_token')
        },
        success: function(result) {
            process_history(result);
        },
        error: function(xhr, status, e) {
            console.log("Error getting history: " + status + ', ' + e);
        }
    });
}
function start_subscribe() {
    $('#subscribe_title').text('Add New Notification');
    $('#subscribe_button').html('Subscribe');
    $('#subscribe_lat').val(null);
    $('#subscribe_lon').val(null);
    $('#subscribe_maxdist').val(100);
    editing_uuid = null;
    $('#add-subscription').foundation('reveal', 'open');
}

function start_edit(sub) {
    $('#subscribe_title').text('Edit Notification');
    $('#subscribe_button').html('Update');
    $('#subscribe_lat').val(sub['lat']);
    $('#subscribe_lon').val(sub['lon']);
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
    let user_token = Cookies.get('notifier_user_token');
    var dist = $('#subscribe_maxdist').val();
    if (units == 'metric') {
        dist = km_to_mi(dist);
    }
    sub_data = {
        'user_token': user_token,
        'units': units,
        'tzname': tzname,
        'lat': $('#subscribe_lat').val(),
        'lon': $('#subscribe_lon').val(),
        'max_distance_mi': dist,
    }
    if (editing_uuid != null) {
        sub_data['replace_uuid'] = editing_uuid;
    }

    $.ajax({
        method: 'POST',
        url: base_url + 'subscribe',
        data: sub_data,
        success: function(result) {
            l.stop();
            process_config(result);
            cancel_subscribe();
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

function unsubscribe(del_icon, uuid) {
    var l = Ladda.create(del_icon[0]);
    l.start();
    let user_token = Cookies.get('notifier_user_token');

    $.ajax({
        method: 'POST',
        url: base_url + 'managed_unsubscribe',
        data: {
            'user_token': user_token,
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
    get_config();
    get_history();
}

</script>
