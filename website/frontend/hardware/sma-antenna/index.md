---
layout: page-fullwidth
title: "Radiosonde Antenna with 3D Printed Frame"
footer: true
---

Home radiosonde receive sites need a good antenna. Most hobbyists build their
own. One of the simplest is a monopole antenna, which can be constructed from an
an antenna connector and a few pieces of copper wire cut to the proper length.
Bryan Klofas has [a nice example of building a quarter-wave monopole
antenna](https://www.klofas.com/blog/2022/quarter-wave-ground-plane-antenna/)
that Jon and I used as a basis for our own.

We iterated over a few designs and decided on one based on an SMA connector,
with stiff Romex wire used as the elements, cut to the proper length, tuned, and
then zip-tied into a 3D-printed frame for stability. Although it's harder to
solder onto an SMA connector than the big chassis-mount N connector Bryan used,
the SMA connector is more convenient to attach to modern SDR dongles that
typically also use SMA connectors.

### Step 1: Buy an SMA connector and wire

We used a through-hole, right-angle SMA connector. These are very common and can be purchased at

* [Amazon](https://www.amazon.com/Uxcell-a16011100ux0048-Female-Connector-Adapter/dp/B01DO06QYQ)
* [Digi-key](https://www.digikey.com/en/products/detail/te-connectivity-linx/CONREVSMA002/340145
)
* [Ali Express](https://www.aliexpress.us/item/2251832631544350.html)

Stiff wire works best. Jon had a reel of 14 AWG Romex cable (common for in-wall home wiring) so we used a few scraps from that.

### Step 2: Cut wire slightly too long and bend to shape

[This antenna calculator](https://m0ukd.com/calculators/quarter-wave-ground-plane-antenna-calculator/) is useful. We targeted 404.6 MHz giving us
a vertical element of about 18cm and ground radials of about 20cm each. We cut 3 lengths of wire: one for the vertical element, and two for each pair of ground radials. There's about a 1cm gap in between the radials where they meet the connector, plus a few cm "to spare" for a total of about 44cm each, bent into a V shape as shown below.

It's very important to start the elements a little bit *too long* so they can be trimmed during the tuning step. It's a lot easier to make wire shorter than longer!

<div class="lec-inline-images">
{% include thumb-image.html image="cut-wires.webp" %}
</div>

### Step 3: Solder the wire to the connector

Solder the vertical element to the SMA connector's center conductor. Solder each of the two ground-radial pairs to two of the through-hole contacts of the SMA connector.

<div class="lec-inline-images">
{% include thumb-image.html image="soldering.webp" %}
{% include thumb-image.html image="fully-soldered.webp" %}
</div>

### Step 4: Tune

If you have a vector network analyzer, attach it to the antenna to check the tuning. By making the wires a little bit too long, it'll be tuned for a frequency a little bit too low. Gradually trim pieces of the wire away with a pair of diagonal cutters until the antenna's peak performance moves up to your desired target frequency.

Antenna analyzers:

* The classic [NanoVNA](https://nanovna.com/) broke new ground as one of the
  first hobbyist antenna analyzers. It works decently at 400MHz and only [costs
  $60](https://www.amazon.com/s?k=NanoVNA&me=A3KC9Z86M9XWS3). It's remarkable
  because a similar instrument a decade or two earlier would set you back
  thousands of dollars.

* Inspired by the NanoVNA but developed by different people, the [NanoVNA
  v2](https://nanorfe.com/nanovna-v2.html) is a more accurate and reliable
  instrument and has a larger range of frequencies, but also [costs a lot
  more](https://www.tindie.com/stores/hcxqsgroup/?utm_source=sidebar), about $300.

<div class="lec-inline-images">
{% include thumb-image.html image="tuning-result.webp" %}
</div>

### Step 5: Add antenna frame

One disadvantage of a wire antenna is that it's fragile. It easily bends out of
shape, and the solder joint is a weak point. To solve this problem, Jon designed
a [3D-printable plastic antenna frame](https://github.com/jonhnet/sonde-search/blob/main/3d-models/freestanding-antenna-frame/freestanding-mount-mk2-single.stl). It has a small housing where the SMA
connector sits and 5 arms with wire-sized channels to support the 5 antenna
elements. The legs are at the proper angle for a monopole antenna. Each arm has
a little notch for attaching a zip-tie to hold the copper wire into the arm's
channel.

The easiest way to print it is to split it in half just below the SMA holder, as seen below. If you use a Prusa printer, you can use the pre-split version in [this PrusaSlicer project file](https://github.com/jonhnet/sonde-search/raw/main/3d-models/freestanding-antenna-frame/freestanding-mount-mk2-single.3mf).

<div class="lec-inline-images">
{% include thumb-image.html image="frame-printing.webp" %}
{% include thumb-image.html image="fully-assembled-frame.webp" %}
</div>

Another variation is a [simple windowsill
mount](https://github.com/jonhnet/sonde-search/blob/main/3d-models/windowsill-antenna-mount/windowsill-mount-revB-Body.stl).
This one isn't quite as sturdy because it doesn't give the arms support, and
isn't for portable use. But, it's worked well to keep an antenna permanently
mounted on my window sill.

<div class="lec-inline-images">
{% include thumb-image.html image="windowsill-mount.webp" %}
</div>