---
layout: page-fullwidth
title: "Sonde Email Notifier"
footer: true
---

[Sign up here](manage) for to receive email notifications when a sonde
lands near you!

Not many of of the radiosondes in my area (Seattle) land somewhere
accessible. Most end up in the Olympic forest the ocean. Only rarely
do they come far enough east to land in civilization. My habit was to
check [SondeHub](https://www.sondehub.org/") daily to see if any of
the day's flights landed nearby.  This was an annoying chore, so I set
up a system that would query SondeHub's API for me and send me an
email if a radiosonde landed nearby. This facility is now available to
anyone!

Notifications are configured with:

* The latitude and longitude of "home"
* The maximum distance from home for a landing to be interesting

My system checks in with SondeHub regularly. If any landings are
within the desired search area, it sends an email with a little table
showing the important statistics, like this:

<style>
table.sonde {
    background-color: #e0e0e0;
    margin: 0 auto;
}
table.sonde th {
    background-color:  #404040;
    color: white;
}
table.sonde tbody tr:nth-child(odd) {
    background-color:  #d0d0d0;
}
</style>
<table class="sonde">
    <tbody><tr>
        <td>Sonde ID</td>
        <td><a href="https://sondehub.org/#!mt=Mapnik&amp;mz=9&amp;qm=12h&amp;f=V1914106&amp;q=V1914106" target="_blank">V1914106</a></td>
    </tr>
    <tr>
        <th colspan="2">Last Reception
    </th></tr>
    <tr>
        <td>Heard</td>
        <td>2023-11-15 05:01:16 PST by KK6HMI-2</td>
    </tr>
    <tr>
        <td>Altitude</td>
        <td>3,794 ft</td>
    </tr>
    <tr>
        <td>Position</td>
        <td><a href="https://www.google.com/maps/search/?api=1&amp;query=47.8959,-123.07148" target="_blank">47.8959, -123.07148</a></td>
    </tr>

    <tr>
        <td>Address</td>
        <td>Clallam County<br>Clallam County, Washington, United States</td>
    </tr>

    <tr>
        <td>Distance</td>
        <td>39 <span class="il">miles</span> <span class="il">from</span> <span class="il">home</span></td>
    </tr>
    <tr>
        <td>Bearing</td>
        <td>297° <span class="il">from</span> <span class="il">home</span></td>
    </tr>
    <tr>
        <td>Descent Rate</td>
        <td>40 ft/s, moving laterally 5 ft/s,
        heading 324°</td>
    </tr>

    <tr>
        <th colspan="2">Landing Estimation</th>
    </tr>
    <tr>
        <td>Ground Elev</td>
        <td>3,481 ft</td>
    </tr>
    <tr>
        <td>Time to landing</td>
        <td>8 s</td>
    </tr>
    <tr>
        <td>Search <span class="il">Radius</span></td>
        <td>35 ft</td>
    </tr>

</tbody></table>

It also attaches a map showing where the sonde was last heard by a
tracking site. It plots the sonde's flight path (red), a line from
your configured home coordinates to the last reception (blue) and a
line from the last receiver site to the sonde (green).

{% include thumb-image.html image="notifier-example.webp" %}

The sonde's mapped location is usually not where it landed, but where
the sonde was last heard by a receiver.  The actual landing site might
be some distance away, depending on how low the sonde was when it was
last tracked. This depends largely on how many volunteer receive sites
are nearby and the terrain or other obstructions between the sonde and
nearby receivers. If you want better tracking, the best way is to [set
up your own receive
site](https://github.com/projecthorus/radiosonde_auto_rx/wiki)!

Check SondeHub (by clicking on the sonde's serial number) to see the
computer projection of where the sonde might have landed based on the
model of winds aloft.  The higher the last-heard report, the worse the
landing estimate is. The notifier takes an educated guess as to how
much error might be in the landing estimate by computing how far the
sonde was likely to have travelled laterally before reaching the
ground. For example, if the sonde is last heard at 1000' MSL above a
site where the terrain elevation is 200', while descending at 100 feet
per second, it's 8 seconds from landing. Multiplying 8 seconds by its
horizontal speed gives a rough upper bound on how far the actual
landing site is from the last-heard location.

Of course, this algorithm is fairly naive compared to the more
sophisticated terrain and wind model that SondeHub uses. However, it's
useful in the email to get a quick, rough estimate of the error as an
indicator of it if's worth the time to investigate further.

### Ground Receptions

Occasionally, if you're very lucky, a sonde is within earshot of a
receive site all the way to the ground! This is an exciting situation
because it means there's *no* error in the sonde's location at
all. Since we've gotten its GPS coordinates while it was sitting on
the ground, we know exactly where it is -- we can just go to those
coordinates and pick it up!

The notifier detects such situations by detecting that last data
points reported by a receive site indicate its vertical and horizontal
velocities are both close to zero. In this case, the notifier will
send an email whose subject excitedly proclaims "GROUND RECEPTION!".

### Signing Up for Notifications

[Sign up here](signup) to receive notifications!

The notification service is free. We won't spam you or send you
anything other than notifications. You can sign up for as many
notification locations as you'd like.
