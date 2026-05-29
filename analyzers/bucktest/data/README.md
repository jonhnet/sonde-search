# MP1584EN 5 V Buck Module Notes

These notes summarize measurements from three samples of this Amazon module:

https://www.amazon.com/dp/B0B779ZYN1

The listing describes it as a fixed 5 V MP1584EN buck converter board sold in a
5-pack, with a nominal 5-30 V input range and up to 1.8 A output.

## Test Summary

Three boards from the same batch were tested from 6-18 V input. No-load input
current was measured with a Keysight 34465A DMM, and loaded efficiency was
measured from 10 mA to 1 A output load.

Iq is in the low hundreds of microamps. Across the three boards it was about
217-230 uA at 6 V, falling to about 78-142 uA by 18 V. The input current is
pulsed rather than perfectly steady; high-rate DMM captures showed narrow
peaks around 40 mA.

Efficiency is generally good for a tiny inexpensive module. Above 50 mA load,
the boards were usually in the high 80% range. Two of the three boards matched
closely, averaging about 88.7% efficiency over those points. The third board
was similar at lighter loads and lower input voltages, but was weaker at high
input voltage and heavier load, averaging about 87.4% over the same range.

Output voltage stayed near 5 V in normal use. At 1 A load, the measured output
voltage across all boards ranged from about 4.79 V to 5.20 V. One board ran
noticeably high at high input voltage, so there is some unit-to-unit variation.
