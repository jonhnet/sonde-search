---
layout: page-fullwidth
title: "Finding a Mystery Launch Site"
footer: true
---

*January 28, 2024*

Today we had a different sort of find---finding an unknown launch site!

Typically, the source of weather balloons is not a mystery. The government
agencies that launch balloons, such as the [National Weather
Service](https://www.weather.gov/upperair/factsheet), publish data about their
launch programs. Most launches near Seattle come from Quillayute, about 100
miles west.

But a few months ago, something curious started to happen: during times of bad
weather, such as atmospheric rivers, Seattle-area sonde monitors on
[SondeHub](https://www.sondehub.org) started to pick up *extra* balloons
launched up to 8 times per day, which Jon began to call "bonus sondes." They
appeared to originate near Tacoma, Washington, a couple dozen miles south of
Seattle. The nearest receive site would only begin to pick up the balloon's
signal once it had gained several thousand feet of altitude. This was good
enough to narrow the launches down to a few square miles, but the exact location
of the launches remained mysterious.

In the [Facebook discussion
group](https://www.facebook.com/groups/444260440607754) devoted to
sonde-hunting, there was much speculation as to the source of these launches. On
Sunday, Jon and I decided to try and solve the mystery!

My [email notifier](/notifier) told us that bonus sondes were being launched all
weekend. We started out looking at the projected flight path for Sunday
morning's 10AM (Pacific Time) sonde,
[V3140090](https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f=V3140090&q=V3140090).
It was first heard by N0NHJ's receiver in Tacoma at about 3,400
feet. SondeHub projected the takeoff location around Ridgecrest Elementary
School in Puyallup, one of the possible launch sites that folks on the
discussion group had considered ... maybe it's a school project? We drove to
Puyallup just before the anticipated 1PM launch. First we drove a lap around the
school, seeing no activity. Then, we set up our portable receiver---a Linux
laptop with mobile hotspot running
[radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx), an
[RTL SDR dongle](https://www.rtl-sdr.com/rtl-sdr-blog-v-3-dongles-user-guide/),
a
[filter+LNA](https://store.uputronics.com/index.php?route=product/product&product_id=54)
tuned for 403MHz, and a homemade monopole antenna with a [3D printed
frame](https://github.com/jonhnet/sonde-search/tree/main/3d-models/sma-antenna-mount)
that we put on the roof of the car.

{% include right-image.html
  image="mobile-sonde-receiver.webp"
  caption="Jon with our mobile sonde receiver"
%}

A couple of minutes later, sonde
[V3310159](https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f=V3310159&q=V3310159)
came over the horizon and started giving us good strong pings indicating a
position to our south! We first started picking it up at about 1,700'; by the
time it passed over us at the school it was climbing through 2,300'. We were a
little disappointed our initial guess at the launch site had been wrong, but
there was a clear next step. Because we'd started to hear the sonde at a much
lower altitude than the fixed receive sites had, SondeHub gave us a better
launch estimate: the north end of the nearby [McMillin
Reservoir](https://southhillhistory.com/Newsletters/Newsletter_archive/History%20On%20The%20Hill%202010-5%20Sp.pdf),
about a mile south of us.

We packed up, drove to the reservoir's front entrance, and discovered to our
disappointment that the entire facility is surrounded by high fences and razor
wire. The whole site says "go away." Near the entrance road there was a small
parking lot and customer service building. We parked and peered beyond the
fence, but didn't see anything that looked like a NOAA launch site, such as the
typical a domed building or hydrogen storage farm. We did, however, see a large
monopole antenna on top of a rusty 20-foot tower a few hundred feet away. Might
that be a sonde receiver? It might! It was hard to judge its size from so far
away but it did seem to be much larger than something tuned for 400 MHz.

{% include right-image.html
  image="reservoir-antenna.webp"
  caption="An antenna visible through the fence at McMillin Reservoir"
%}

We got back into the car and drove around the residential areas on the
reservoir's perimeter. After a couple of miles, this brought us to another
elementary school on the south edge of the reservoir. We walked into their back
yard and found a small berm that overlooked the site but again, everything was
too far away to see anything clearly.

As our circumnavigation continued, we made a fortuitous discovery: a public
hiking path on the east side of the reservoir, right along the fence line! We
walked a mile up the the trail, finally finding a good spot with a beautiful
view of most of the facility. We still saw nothing that looked like a launch
site, but we were willing to wait a couple hours for the 4PM sonde to be
launched. We drove to a nearby restaurant to get a late lunch; I pulled my
laptop out and looked at the history of the last dozen or so bonus sondes
launched from the area. To get the quickest possible reception, we didn't want
to lose the minute that it takes for auto_rx to cycle through the entire band
scanning for signals. The history showed that sondes in the area all use 405.3,
405.5, and 405.7 MHz so we reconfigured auto_rx to just scan those three
frequencies.

<br clear="right">
{% include right-image.html
  image="receiving-at-the-reservoir.webp"

  caption="Our mobile receive site set up at the reservoir, receiving packets
from the sonde while it's still on the ground!"
 %}

Finally, just before 4PM we returned to the hiking trail, set up the receiver,
and---boom! We instantly heard pings from sonde
[V3130545](https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f=V3130545&q=V3130545)
while it was still on the ground, giving us its exact position! It was coming
through loud and clear with an SNR of better than 40dB. The position reported
was on the west side of the reservoir (we were on the east side), south and west
of us. We quickly picked up our gear and moved south until we were due east of
it, looked west through the fence and across the water, and there we saw a man
in a shed inflating a giant balloon! Success!

We stayed to watch the launch, waited until the other Seattle-area stations
started to pick up the signal, then finally packed up and went home. Mystery
solved!

## Epilogue

When we told this story on one of the Facebook groups devoted to finding sondes,
Mark Jessop, the administrator of Sondehub, added the launch site to Sondehub's
map! Hopefully, the launch site will no longer be a mystery to future hunters.

Jon and I reached out to the reservoir administration and NOAA to learn who was
launching the sondes and why. We never heard back, but some Internet sleuthing
provided the answer when I learned about [FIRO](https://cw3e.ucsd.edu/firo/), a
research program for "Forecast Informed Reservoir Operations"---that is,
optimizing the management of reservoirs on the U.S. West Coast by improving
skill in forecasting rain and floods. They explain that "the key to accurately
predicting precipitation and flooding is linked to an understanding of the
dominant rainfall producing mechanism, atmospheric rivers," including a
[radiosonde sensing program](https://cw3e.ucsd.edu/cw3e_radiosondes/) that
launches sondes from 7 sites on the West Coast, including in Tacoma. "The
radiosondes are launched every three hours during storm conditions," they say,
matching our observations!

Delightfully, this research program makes [all their data
public](https://drive.google.com/drive/folders/0ByCzhY5jqBMDT2YwOERKZ045aEU?resourcekey=0-pGG7nMQK___q4oEE885dZQ).
Given the facts above, there seemed little doubt that this program was
responsible for the sondes we saw. But just to prove it absolutely, I downloaded
the research program's [data
log](https://drive.google.com/file/d/1cL7atN9J1f-vusyhdzT-Ywwz__DY8BpT/view?usp=drive_link)
from the same time as the launch we'd witnessed. I plotted the first couple
hundred lat/lon points from that log and, sure enough, [the map I
drew](images/USTAC_20240129_0000.txt.launch.png) showed the sonde starting from
exactly the spot we'd seen in the reservoir. Now the mystery has *really* been
solved!

<div class="lec-captioned-image">
<center>
  <video width="720" controls>
    <source src="images/reservoir-launch.webm" type="video/webm" />
  </video>
  <div class="caption">The launch, seen from through the reservoir's east fence, January 2024</div>
  </center>
</div>
