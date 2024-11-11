---
layout: page
title: "Sonde Email Notifier — Unsubscribe"
---

<div id="loading" class="row t30 text-center">
    <img src="/images/loading.gif" />
</div>

<div id="failure_message" hidden>
    We're sorry. There was an error processing your unsubscription.
    You might want to try to <a href="../manage/">manage your
    subscriptions</a>.

    For additional help, please write to <tt>notifier</tt> at
    our domain (lectrobox.com).
</div>

<div id="unsubscribe_message" hidden>
    You have unsubscribed from the following notification:
    <p>
        <table style="margin-left: auto; margin-right: auto;">
            <tr>
                <td>Email</td>
                <td><tt><span id="unsub_email"></span></tt></td>
            </tr>
            <tr>
                <td>Latitude</td>
                <td><span id="unsub_lat"></span></td>
            </tr>
            <tr>
                <td>Longitude</td>
                <td><span id="unsub_lon"></span></td>
            </tr>
        </table>
    </p>

    <p>
       To manage your other notifications for this email address,
       <a href="../manage">click here</a>.
    </p>
</div>


<script>
let base_url = "https://api.sondesearch.lectrobox.com/api/v2/";

function process_failure() {
    $('#loading').attr('hidden', true);
    $('#failure_message').attr('hidden', false);
}

function process_success_result(result) {
    if (!result['success'] == true) {
        process_failure_result();
        return;
    }

    $('#unsub_email').html(result['email']);
    $('#unsub_lat').html(result['cancelled_sub_lat']);
    $('#unsub_lon').html(result['cancelled_sub_lon']);

    $('#loading').attr('hidden', true);
    $('#unsubscribe_message').attr('hidden', false);
}

function OnLoadTrigger() {
    // Get the subscription UUID from the URL arguments
    let searchParams = new URLSearchParams(window.location.search);
    var uuid = searchParams.get('uuid');

    $.ajax({
        method: 'POST',
        url: base_url + 'oneclick_unsubscribe',
        data: {
            'uuid': uuid,
        },
        success: function(result) {
            process_success_result(result);
        },
        error: function(jqXHR, textStatus, errorThrown) {
            process_failure();
        }
    });
}

</script>
