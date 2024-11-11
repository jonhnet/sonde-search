---
layout: default
---
<script>
function OnLoadTrigger() {
    // If an auth token was provided in the URL, convert it into a cookie
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.has('user_token')) {
        Cookies.set(
            'notifier_user_token',
            searchParams.get('user_token'),
            {
                expires: 365,
                domain: '.sondesearch.lectrobox.com',
            }
        );
        window.location.href = window.location.origin + window.location.pathname + '../manage/';
    } else {
        window.location.href = window.location.origin + window.location.pathname + '../signup/';
    }
}
</script>