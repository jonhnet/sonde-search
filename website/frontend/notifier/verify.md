---
layout: default
---

<div id="verify_status" style="padding: 20px;">
    <p>Verifying your email...</p>
</div>

<script>
function OnLoadTrigger() {
    const searchParams = new URLSearchParams(window.location.search);
    const statusDiv = document.getElementById('verify_status');

    // Get email_token from URL (proves they received the email)
    if (!searchParams.has('email_token')) {
        window.location.href = window.location.origin + window.location.pathname + '../signup/';
        return;
    }
    const email_token = searchParams.get('email_token');

    // Get pending_token from cookie (proves same browser as signup)
{% if site.dev_mode == 1 %}
    const pending_token = Cookies.get('pending_verification') || '';
{% else %}
    const pending_token = Cookies.get('pending_verification', {domain: '.sondesearch.lectrobox.com'}) || '';
{% endif %}

    if (!pending_token) {
        statusDiv.innerHTML = `<p style="color: red;">Verification failed.</p>
            <p>This can happen if you opened the verification link in a different browser than the one you used to sign up.</p>
            <p><a href="../signup/">Please sign up again</a></p>`;
        return;
    }

    // Call the backend with both tokens to get the user_token
    SondeSearchAPI.post('verify_email', {
        'email_token': email_token,
        'pending_token': pending_token,
    }, {
        credentials: 'include',
    }).then(function(response) {
        if (response.success) {
            // Verification successful! Now set the auth cookie.
            // Clear any old cookies first.
            Cookies.remove('notifier_user_token');
            Cookies.remove('notifier_user_token_v2');
            Cookies.remove('notifier_user_token', {domain: '.sondesearch.lectrobox.com'});
            Cookies.remove('notifier_user_token_v2', {domain: '.sondesearch.lectrobox.com'});

            // Also clear the pending_verification cookie since it's been used
            Cookies.remove('pending_verification');
            Cookies.remove('pending_verification', {domain: '.sondesearch.lectrobox.com'});

            // Set the auth cookie
            Cookies.set('notifier_user_token_v2', response.user_token, {
                expires: 365,
                domain: '.sondesearch.lectrobox.com',
            });
{% if site.dev_mode == 1 %}
            Cookies.set('notifier_user_token_v2', response.user_token, {
                expires: 365,
            });
{% endif %}

            // Redirect to manage page
            window.location.href = window.location.origin + window.location.pathname + '../manage/';
        } else {
            statusDiv.innerHTML = `<p style="color: red;">Verification failed. Please try signing up again.</p>
                <p><a href="../signup/">Go to signup page</a></p>`;
        }
    }).catch(function(error) {
        console.error('Verification error:', error);
        statusDiv.innerHTML = `<p style="color: red;">Verification failed: ${error.message || 'Unknown error'}</p>
            <p>This can happen if you opened the verification link in a different browser than the one you used to sign up.</p>
            <p><a href="../signup/">Please sign up again</a></p>`;
    });
}
</script>