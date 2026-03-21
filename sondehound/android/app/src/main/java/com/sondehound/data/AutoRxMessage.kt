package com.sondehound.data

import com.google.gson.annotations.SerializedName

/**
 * Represents the JSON telemetry message from radiosonde_auto_rx's UDP output.
 *
 * Actual auto_rx PAYLOAD_SUMMARY format:
 * {
 *   "type": "PAYLOAD_SUMMARY",
 *   "station": "N3UUO",
 *   "callsign": "X4412798",
 *   "latitude": 48.42107,
 *   "longitude": -122.93946,
 *   "altitude": 22115.13823,
 *   "speed": 33.436836,
 *   "heading": 134.15361,
 *   "time": "00:08:25",
 *   "model": "RS41-SG",
 *   "freq": "404.6020 MHz",
 *   "temp": -61.6,
 *   "humidity": 1.8,
 *   "vel_v": 6.90301,
 *   "vel_h": 9.28801,
 *   "snr": 9.3,
 *   "batt": 2.6,
 *   "sats": 10,
 *   "frame": 5364
 * }
 */
data class AutoRxMessage(
    val type: String = "",

    val callsign: String = "",

    val model: String = "",

    val freq: String = "",

    val latitude: Double = 0.0,

    val longitude: Double = 0.0,

    val altitude: Double = 0.0,

    @SerializedName("vel_h")
    val velH: Double = 0.0,

    val heading: Double = 0.0,

    @SerializedName("vel_v")
    val velV: Double = 0.0,

    val time: String = "",

    @SerializedName("time_epoch")
    val timeEpoch: Long = 0,

    val snr: Double = 0.0,

    val temp: Double = 0.0,

    val humidity: Double = 0.0,

    val batt: Double = 0.0,

    val sats: Int = 0
) {
    fun parseFrequencyMhz(): Double {
        return freq.replace(" MHz", "").toDoubleOrNull() ?: 0.0
    }

    fun toSondePosition(): SondePosition {
        // Use the GPS epoch timestamp from the Pi if available,
        // otherwise fall back to receive time
        val ts = if (timeEpoch > 0) timeEpoch else System.currentTimeMillis() / 1000
        return SondePosition(
            latitude = latitude,
            longitude = longitude,
            altitude = altitude,
            timestamp = ts,
            speed = velH,
            heading = heading,
            climbRate = velV
        )
    }
}
