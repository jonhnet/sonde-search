---
layout: page-fullwidth
title: "Radiosonde (Weather Balloon) Email Notifier"
footer: true
---

[Sign up here](manage) to receive email notifications when a radiosonde
lands near you!

Not many radiosondes land near my home town of Seattle. The weather balloons
launched from Quillayute, about 100 miles (170km) west, usually land somewhere
inaccessible such as in the Olympic forest or the ocean. Only rarely do they
come far enough east to land in civilization. My habit was to check
[SondeHub](https://www.sondehub.org/") to see if the day's flights landed
nearby. This was an annoying chore, so I set up a system that would query
SondeHub's API for me and send an email if a radiosonde landed less than a
configured distance from home. This facility is now available to anyone!

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
    margin-bottom: 20px;
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
traveled laterally before reaching the ground from its last known
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
situation because it means there's far less error in the sonde's
location. Since we've gotten its GPS coordinates while it was sitting
on the ground, we know almost exactly where it is---we can just go pick it
up!

The notifier detects ground receptions when the last data points
reported by a receive site indicate the sonde's vertical and
horizontal velocities are both close to zero. In this case, the
notifier will send an email whose subject excitedly proclaims "GROUND
RECEPTION!".

Sondes keep transmitting for many hours after they land.
If we're lucky enough to hear a sonde while it's on the ground,
we can estimate the its final resting position even more precisely
by averaging all the post-landing frames overheard.
The notifier does this automatically.
Ground reception emails tell you the number of ground-transmitted
frames received, the average lat/lon and elevation of those
frames, and the position's estimated error (standard deviation).
Here's an example from sonde <a href="https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f=X0933436&q=X0933436" target="_blank">X0933436</a>,
from which we heard over a thousand frames while it sitting on the ground:

<table class="sonde">
    <tbody>
    <tr>
        <th colspan="2">Ground Reception</th>
    </tr>
    <tr>
        <td>Ground Points</td>
        <td>1266 frames</td>
    </tr>
    <tr>
        <td>Avg Position</td>
        <td><a href="https://www.google.com/maps/search/?api=1&query=47.397525,-122.680011" target="_blank">47.397525, -122.680011</a> (±16')</td>
    </tr>
    <tr>
        <td>Avg Altitude</td>
        <td>311' (±9')</td>
    </tr>
    <tr>
        <td>Est. Height</td>
        <td>15' AGL</td>
    </tr>
</tbody></table>

The notification also includes a special map showing
all the GPS positions reported while on the ground.


{% include thumb-image.html image="ground-reception-example.webp" %}

### Notification History

The management page lists all of the notifications you've received in the past 30
days. For each sonde that landed nearby, you'll see the date and time of the
sonde's final reception, the sonde's serial number, a link to SondeHub's page,
and the map attached to the notification. Here's an example:

<table id="history_table"  style="margin: 0 auto;">
        <tbody><tr>
            <th>Sonde Last Heard</th>
            <th>Dist from Home</th>
            <th>Sonde ID</th>
            <th>Map</th>
        </tr>
        <tr><td class="text-right">12/23/2023, 4:57:08 PM</td><td class="text-right">94.2 mi</td><td class="text-right"><a href="https://sondehub.org/#!mt=Mapnik&amp;mz=9&amp;qm=12h&amp;f=V1750589&amp;q=V1750589">V1750589</a></td><td class="text-right"><a href="https://sondemaps.lectrobox.com/792dac8089004349a86f54940b3a7716/2023/12/24-0-47.88929--124.30961.jpg">Map</a></td></tr>
        <tr><td class="text-right">12/23/2023, 5:03:06 AM</td><td class="text-right">71 mi</td><td class="text-right"><a href="https://sondehub.org/#!mt=Mapnik&amp;mz=9&amp;qm=12h&amp;f=V1750579&amp;q=V1750579">V1750579</a></td><td class="text-right"><a href="https://sondemaps.lectrobox.com/792dac8089004349a86f54940b3a7716/2023/12/23-13-47.72163--123.84317.jpg">Map</a></td></tr>
        <tr><td class="text-right">12/22/2023, 5:29:15 AM</td><td class="text-right">152.6 mi</td><td class="text-right"><a href="https://sondehub.org/#!mt=Mapnik&amp;mz=9&amp;qm=12h&amp;f=V4030234&amp;q=V4030234">V4030234</a></td><td class="text-right"><a href="https://sondemaps.lectrobox.com/9feabde880ef4d2bb80c538070bf9426/2023/12/22-13-45.41774--122.69893.jpg">Map</a></td></tr>
        </tbody>
</table>

### Signing Up for Notifications

[Sign up here](signup) to receive notifications!

The notification service is free. We won't spam you or send you anything other
than notifications. You can sign up for as many notification locations as you'd
like.
