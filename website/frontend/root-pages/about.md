---
layout: page-fullwidth
title: "What is a radiosonde, and why search for one?"
permalink: "/about/"
footer: true
---

<div class="lec-right-image">
  <div class="lec-captioned-image">
    <video width="480" height="270" controls>
      <source src="/images/video/salem-launch-july-2021.webm" type="video/webm" />
    </video>
    <div class="caption">An automatic sonde launcher seen in Salem, Oregon, July 2021</div>
  </div>
</div>

A [radiosonde](https://www.noaa.gov/jetstream/upperair/radiosondes) is
the technical term for a weather balloon. It's a small wireless sensor
package used to gather data about the atmosphere such as temperature,
humidity, and the wind's speed and direction. These readings are a key
component of weather prediction and research. At over 1,300 sites
worldwide, sondes are launched twice a day, hoisted into the upper
atmosphere by large hydrogen-filled balloons. Over the course of
several hours, they climb up above 100,000 feet (30,000 meters).

When the balloon bursts, the sonde falls gently back to Earth under a
small parachute, often never to be seen again. The sondes are low-cost
and designed to be used only once. For the agencies that launch the
sondes, that's where the story ends. But for our hobby, that's where
it begins!

Sonde-hunting enthusiasts around the world collaborate to track the sondes and
find them after they land. Every second that they're aloft, the devices transmit
data back to their launch point. The transmissions include their current
GPS-derived position (latitude, longitude and altitude). The data is considered
public information and is not encrypted, so hobbyists have learned to receive
and decode the transmissions, typically with a cheap [software-defined
radio](https://www.rtl-sdr.com/about-rtl-sdr/). Volunteers have set up hundreds
of listening posts worldwide. The next step is to get out into the field and try
to find the sonde based on its tracking data. It's a great way to touch grass!

[SondeHub](https://www.sondehub.org) is the largest public repository of
radiosonde data collected by hobbyists. Over the past couple of years, I've
built tools that help track radiosondes based on the data from SondeHub. My site
makes all those tools available to the public. You can also find all [the source
code](https://github.com/jonhnet/sonde-search) on GitHub.

You may still be wondering: but *why* search for sondes?

Why not? It's fun. It's like a high-tech treasure hunt, similar to
[Geocaching](https://www.geocaching.com).

More information can be found at:

* [Upper Air
  Data](https://www.noaa.gov/jetstream/upperair/radiosondes)---explains
  the purpose of radiosonde launches from one of the agencies that
  launch them, the U.S. Government's [National Oceanic and Atmospheric
  Administration (NOAA)](https://www.noaa.gov/).

* [SondeHub](https://www.sondehub.org)---the largest repository of
  crowdsourced balloon tracking data. It includes live maps and an API
  for retrieving both live and historical data. People also report
  which balloons they've found here. The tools on this site use data
  from SondeHub.

* [RadioSondy](https://s1.radiosondy.info/)---another repository of
  volunteer-tracked balloon data.

* [Balloon Path Predictor](https://predict.sondehub.org/)---type in
  the launch time and location and the site will use a model of winds
  aloft and terrain to determine where the balloon is likely to land.

* [Radiosonde
  auto-rx](https://github.com/projecthorus/radiosonde_auto_rx) is
  software for Linux that can decode transmissions from many common
  models of radiosondes and upload the data in real-time to
  SondeHub. It is typically used with an
  [RTL-SDR](https://www.rtl-sdr.com/) radio.

* [Bryan Klofas' Radiosonde Antenna](https://www.klofas.com/blog/2022/quarter-wave-ground-plane-antenna/)---a nice example of how to build an antenna tuned to 404 MHz, the frequency of many radiosondes launched in the United States

* [MySondyGo](https://www.tindie.com/products/mayhemxlabs/radiosonde-tracker-mysondygo-with-404-mhz-antenna/)
  is a portable sonde tracker; a useful self-contained device for
  picking up transmissions from nearby balloons while in the field.

* [Radiosonde North
  America](https://www.facebook.com/groups/444260440607754)---an active,
  friendly Facebook group where U.S.-based sonde hunters post photos, stories
  from the hunt, and questions.
