package com.sondehound.data

import kotlinx.coroutines.*
import kotlin.math.*

/**
 * Generates fake sonde telemetry for testing in the emulator where BLE is unavailable.
 *
 * Simulates a descending RS41 radiosonde drifting with the wind.
 */
object MockDataSource {

    private var job: Job? = null
    private var running = false

    // Simulated sonde starting position (Boulder, CO area)
    private var lat = 40.05
    private var lon = -105.25
    private var alt = 25000.0  // meters
    private var step = 0

    fun start() {
        if (running) return
        running = true

        // Reset state
        lat = 40.05
        lon = -105.25
        alt = 25000.0
        step = 0

        SondeRepository.setConnected(true)
        SondeRepository.updateConnectionStatus("Connected (mock)")
        SondeRepository.setMode(ReceiverMode.AUTO)

        job = CoroutineScope(Dispatchers.IO).launch {
            while (isActive && running && alt > 0) {
                step++

                // Simulate wind drift and descent
                val windSpeedMs = 8.0 + 3.0 * sin(step * 0.05)
                val windHeading = 240.0 + 20.0 * sin(step * 0.02) // roughly from WSW
                val descentRate = if (alt > 15000) -3.0 else -5.5  // faster descent below 15km

                val headingRad = Math.toRadians(windHeading)
                val dlat = windSpeedMs * cos(headingRad) / 111320.0
                val dlon = windSpeedMs * sin(headingRad) / (111320.0 * cos(Math.toRadians(lat)))

                lat += dlat
                lon += dlon
                alt += descentRate

                if (alt < 0) alt = 0.0

                val msg = AutoRxMessage(
                    type = "PAYLOAD_SUMMARY",
                    callsign = "S4310587",
                    model = "RS41-SG",
                    freq = "403.210 MHz",
                    latitude = lat,
                    longitude = lon,
                    altitude = alt,
                    velH = windSpeedMs,
                    heading = windHeading,
                    velV = descentRate,
                    time = "",
                    snr = 12.5 - (25000 - alt) / 5000.0
                )

                SondeRepository.handleAutoRxMessage(msg)
                delay(2000) // update every 2 seconds
            }
        }
    }

    fun stop() {
        running = false
        job?.cancel()
        job = null
        PredictionApi.stop()
        SondeRepository.setConnected(false)
        SondeRepository.updateConnectionStatus("Disconnected")
    }

    fun isRunning(): Boolean = running
}
