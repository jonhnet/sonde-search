---
layout: page
title: "Sonde Email Notifier — Sign Up"
---

Enter your email address below. You will be emailed a link that
authorizes you to configure notifications for that address.

<div class="form-group">
  <form onsubmit="return send_email()">
    <label style="margin-top: 30px" for="email_input_box" required="required">Email address</label>
    <input type="email" name="email" required class="form-control" id="email_input_box" aria-describedby="emailHelp" placeholder="Enter email" style="width: 40em" autocomplete="email">
    <div id="form_result" style="visibility: hidden">Form not submitted</div>
    <button type="submit" id="submit_button" class="ladda-button" data-style="slide-right">Send Validation Email</button>
  </form>
</div>

<script>
    function send_email() {
        let button = $('#submit_button');
        var l = Ladda.create(button[0]);
        l.start();
        var email = $('#email_input_box').val();
        $.ajax({
            method: "POST",
            url: "https://api.sondesearch.lectrobox.com/api/v2/send_validation_email",
	    data: {
		'email': email,
		'url': window.location.href,
	    },
            success: function() {
                l.stop();
                button.css("visibility", "hidden");
                $('#form_result').text('Success! Check your email for a link.');
                $('#form_result').css("visibility", "visible");
            },
            error: function() {
                l.stop();
                button.css("visibility", "hidden");
                $('#form_result').text("We're sorry—there was an error trying to sign up. Please try again later.")
                $('#form_result').css("visibility", "visible");
            }
        });

        // return false to prevent form from navigating away to a new page
        return false;
    }

</script>
