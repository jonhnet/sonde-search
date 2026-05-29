# Buck Test Tools

Tools for characterizing fixed-output buck converter modules with a GW Instek
GPP4323 and, optionally, a Keysight 34465A DMM for input-current measurement.

## Capture

```bash
./buck_characterize.py data/buckN.csv
```

The characterizer records:

- no-load input current, Iq, over a Vin sweep
- efficiency over Vin and load-current sweeps

The output filename is required. By default, the DMM host is `dmm` and the DMM
aperture is 0.5 s.

## Plot

```bash
./buck_plot.py data/buckN.csv
```

The plotter writes PNGs named from the CSV basename:

- `data/buckN_iq.png`
- `data/buckN_efficiency.png`

Use `--iq-out` or `--eff-out` to override those names.

## Compare

```bash
./buck_compare.py data/buck1.csv data/buck2.csv
```

The comparator matches rows by test type, Vin setpoint, and load setpoint. It
prints percent-difference matrices using the CSV basenames as labels.
