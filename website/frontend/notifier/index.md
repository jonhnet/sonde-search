---
layout: page-fullwidth
title: "Sonde Email Notifier"
footer: true
---

[Sign up here](manage) to receive email notifications when a sonde
lands near you!

Not many radiosondes land in my home of Seattle. The balloons launched
from Quillayute, about 100 miles (170km) west, usually land somewhere
inaccessible such as in the Olympic forest or the ocean. Only rarely
do they come far enough east to land in civilization. My habit was to
check [SondeHub](https://www.sondehub.org/") to see if the day's
flights landed nearby. This was an annoying chore, so I set up a
system that would query SondeHub's API for me and send an email if a
radiosonde landed less than a configured distance from home. This
facility is now available to anyone!

Notifications are configured with:

* The latitude and longitude of "home"
* The maximum distance from home for a landing to be interesting

My system checks SondeHub regularly. Any landings within the desired search area
are reported. You'll get email with a table showing the important
statistics, like this example:
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

The time of day will be reported in the time zone of the computer used
to sign up for notifications. The distance and altitude units can be
configured to be metric or imperial.

Notifications have a map attached showing where the sonde was last
heard by a receiver. It plots the sonde's flight path (red), a
line from your configured home coordinates to the last reception
(blue) and a line from the last receiver site to the sonde (green).

{% include thumb-image.html image="notifier-example.webp" %}

### Accuracy

A sonde's mapped location is usually not where it landed, but where
the sonde was last heard by a receiver. The actual landing site might
be some distance away. Click on the sonde's serial number at the top
of the table to see SondeHub's projected landing site based on a model
of winds aloft and terrain.

Sondes last heard at high altitudes depend more heavily on these
models, increasing the potential for error. The notifier guesses the
error of the landing estimate by estimating how far the sonde was
travelled laterally before reaching the ground from its last known
location. For example, if a sonde is last heard at 1000' MSL above
200' high terrain while descending at 100' per second, it's about 8
seconds from landing. Multiplying 8 seconds by its horizontal speed
gives a rough upper bound on how far the actual landing site is from
the last-heard location.

Of course, this algorithm is fairly naive compared to SondeHub's more
sophisticated terrain and wind model. However, the rough error
estimate helps you decide if it's worth the time to investigate the
flight further as a potential find.

The quality of the tracking depends largely on how many volunteer
receive sites are nearby and the terrain or other obstructions (e.g.,
buildings) between the sonde and nearby receivers. The more receivers
there are in strategic locations, the more likely it is that sondes
will get tracked to lower altitudes. If you want better tracking, the
best way is to [set up your own receive
site](https://github.com/projecthorus/radiosonde_auto_rx/wiki)!


### Ground Receptions

Occasionally, if you're very lucky, a sonde will be within earshot of
a receiver all the way to the ground! This is an exciting
situation because it means there's *no* error in the sonde's
location. Since we've gotten its GPS coordinates while it was sitting
on the ground, we know exactly where it is---we can just go pick it
up!

The notifier detects ground receptions when the last data points
reported by a receive site indicate the sonde's vertical and
horizontal velocities are both close to zero. In this case, the
notifier will send an email whose subject excitedly proclaims "GROUND
RECEPTION!".

### Signing Up for Notifications

[Sign up here](signup) to receive notifications!

The notification service is free. We won't spam you or send you anything other
than notifications. You can sign up for as many notification locations as you'd
like.
