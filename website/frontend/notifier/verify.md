---
layout: default
---
<script>
function OnLoadTrigger() {
    // If an auth token was provided in the URL, convert it into a cookie
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.has('user_token')) {
        Cookies.remove('notifier_user_token');
        Cookies.remove('notifier_user_token_v2');
        Cookies.remove(
            'notifier_user_token',
            {
                domain: '.sondesearch.lectrobox.com',
            }
        )
        Cookies.remove(
            'notifier_user_token_v2',
            {
                domain: '.sondesearch.lectrobox.com',
            }
        )

        Cookies.set(
            'notifier_user_token_v2',
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